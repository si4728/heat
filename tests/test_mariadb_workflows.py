import os,re,sys,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
from iris2 import database,dbapi,services
from iris2.app import create_app

class MariaDBWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config=load_database_config(admin=True)
        settings=load_database_config()
        cls.schema=os.environ.get('IRIS2_TEST_SCHEMA','iris2_test_transition')
        if not re.fullmatch(r'iris2_test_[a-z0-9_]+',cls.schema) or cls.schema==settings['name']:
            raise RuntimeError('Writable workflow tests require a separate iris2_test_* schema')
        from iris2.migration.migrate_all import engine_for
        with engine_for(config,'mysql').begin() as conn:
            if not conn.exec_driver_sql('SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s',(cls.schema,)).scalar():
                raise unittest.SkipTest('Prepare an isolated MariaDB snapshot before writable workflow tests')
            for host in ['localhost','127.0.0.1']:
                conn.exec_driver_sql(f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{cls.schema}`.* TO %s@%s",(settings['user'],host))
        settings['name']=cls.schema
        cls.patch=patch('iris2.database.load_database_config',return_value=settings);cls.patch.start()
        def isolated_config(*,admin=False,path=None):
            value=load_database_config(admin=admin,path=path)
            if not admin:value['name']=cls.schema
            return value
        cls.dbapi_patch=patch('iris2.dbapi.load_database_config',side_effect=isolated_config);cls.dbapi_patch.start()
        suffix=cls.schema[len('iris2'):]
        cls.schema_patch=patch('iris2.dbapi.load_database_config_schemas',return_value={
            selector:canonical+suffix for selector,canonical in dbapi.SCHEMAS.items()})
        cls.schema_patch.start()
        database.get_engine.cache_clear()
        cls.app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
        cls.engine=database.get_engine()
        with cls.engine.connect() as conn:
            cls.admin=conn.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
            cls.unit=conn.scalar(text("SELECT MIN(unit_id) FROM process_unit WHERE unit_code='VCM1'"))
    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose();database.get_engine.cache_clear();cls.schema_patch.stop();cls.dbapi_patch.stop();cls.patch.stop()
    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session['user_id']=self.admin;session['last_activity_at']=time.time();session['csrf_token']='test-csrf'
        return client
    def test_unauthed_and_csrf_and_api_write_protection(self):
        self.assertEqual(self.app.test_client().get('/exchangers').status_code,302)
        self.assertEqual(self.client().post('/tubes/1/status',data={'current_status':'PLUGGED','reason':'test'}).status_code,400)
        self.assertIn(self.app.test_client().post('/api/v1/exchangers',json={}).status_code,[401,503])

    def test_monitor_and_report_use_current_database_and_explicit_tube_counts(self):
        client=self.client()
        html=client.get('/settings/database-monitor').get_data(as_text=True)
        self.assertIn('MariaDB · 127.0.0.1:3307 / '+self.schema,html)
        self.assertNotIn('database is locked',html)
        self.assertNotIn('heat_exchanger_db3.db</dd>',html)
        with self.engine.connect() as conn:
            identifier=conn.scalar(text('SELECT MIN(heat_exchanger_id) FROM heat_exchanger'))
        response=client.get(f'/exchangers/{identifier}/report')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('<dt>등록 튜브</dt>',html)
        self.assertIn('<dt>설계/예상 튜브</dt>',html)
        self.assertNotIn('<dt>전체 튜브</dt>',html)

    def test_unconnected_organization_choices_remain_available_for_explicit_use(self):
        from iris2.application.organization_service import save_organization_code
        import re
        with self.engine.connect() as conn:
            root=conn.scalar(text("SELECT organization_code_id FROM organization_code WHERE kind='PLANT' AND code='P1'"))
        code='UNCONNECTED-'+uuid.uuid4().hex[:8]
        team=save_organization_code({'kind':'TEAM','parent_id':root,'code':code,'label':code})
        process=save_organization_code({'kind':'PROCESS','parent_id':team,'code':code+'-PROCESS','label':code+'-PROCESS'})
        client=self.client()
        self.assertNotIn(code,client.get('/exchangers').get_data(as_text=True))
        self.assertIn(code,client.get('/master-data/organization-codes').get_data(as_text=True))
        selected=client.get('/exchangers',query_string={'team':code}).get_data(as_text=True)
        self.assertIn(code,selected)
        form=client.get('/exchangers/new').get_data(as_text=True)
        option=re.search(r'<option\b[^>]*value="'+str(process)+r'"[^>]*>',form).group()
        self.assertIn('data-unconnected="true"',option)
        self.assertIn('hidden disabled',option)
        self.assertIn('show-unconnected-processes',form)
    def test_current_tube_total_is_used_for_display_and_allowance(self):
        with self.engine.connect() as conn:
            row=conn.execute(text('''SELECT i.heat_exchanger_id,s.iris_inspection_id,s.summary_total_tubes,r.tube_count
                FROM iris_inspection_spec_snapshot s JOIN iris_inspection i ON i.iris_inspection_id=s.iris_inspection_id
                JOIN heat_exchanger_spec_revision r ON r.heat_exchanger_id=i.heat_exchanger_id AND r.is_current=1
                JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id
                JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
                WHERE r.tube_count>0 AND u.unit_code IN ('VCM1','VCM2') ORDER BY i.inspection_date DESC LIMIT 1''')).first()
        self.assertIsNotNone(row)
        try:
            with self.engine.begin() as conn:
                conn.execute(text('UPDATE iris_inspection_spec_snapshot SET summary_total_tubes=9999 WHERE iris_inspection_id=:id'),{'id':row[1]})
            life=services.exchanger_detail(row[0])['remaining_life']
            self.assertEqual(life['total_tube_count'],row[3])
            self.assertEqual(life['equipment_summary']['total_tube_count'],row[3])
        finally:
            with self.engine.begin() as conn:
                conn.execute(text('UPDATE iris_inspection_spec_snapshot SET summary_total_tubes=:n WHERE iris_inspection_id=:id'),{'id':row[1],'n':row[2]})

    def test_master_creation_revision_and_duplicate_protection(self):
        code='MIGTEST-'+uuid.uuid4().hex[:10]
        data={'unit_id':self.unit,'equipment_code':code,'equipment_name':'MariaDB integration test','exchanger_type_code':'ST','tube_count':10,'tube_nominal_thickness_mm':2.11}
        created=services.save_exchanger(data)
        identifier=created['heat_exchanger_id']
        with self.assertRaises(ValueError):services.save_exchanger(data)
        data['tube_nominal_thickness_mm']=2.2
        services.save_exchanger(data,identifier)
        with self.engine.connect() as conn:
            revisions=conn.execute(text('SELECT is_current,tube_nominal_thickness_mm FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=:id ORDER BY revision_no'),{'id':identifier}).fetchall()
            self.assertEqual(len(revisions),2)
            self.assertEqual(sum(bool(row[0]) for row in revisions),1)
        self.assertEqual(self.client().get(f'/exchangers/{identifier}').status_code,200)
    def test_tube_status_and_work_order_workflows(self):
        from iris2.application.maintenance_service import save_work_order,update_work_order,add_maintenance_record
        with self.engine.connect() as conn:
            tube=conn.execute(text('SELECT t.tube_id,b.heat_exchanger_id,t.current_status FROM heat_exchanger_tube t JOIN tube_bundle b ON b.bundle_id=t.bundle_id LIMIT 1')).first()
        status='PLUGGED' if tube[2]=='IN_SERVICE' else 'IN_SERVICE'
        result=services.update_tube_status(tube[0],status,'MariaDB integration test')
        self.assertTrue(result['changed'])
        order=save_work_order({'heat_exchanger_id':tube[1],'title':'Migration test','work_order_code':'MIG-'+uuid.uuid4().hex[:10]})
        self.assertEqual(self.client().get(f'/maintenance/work-orders/{order}').status_code,200)
        self.assertTrue(update_work_order(order,{'status':'IN_PROGRESS'}))
        record=add_maintenance_record(order,{'tube_id':tube[0],'action_type':'MAINTENANCE','new_status':tube[2],'details':'Migration test completion'})
        self.assertGreater(record,0)
    def test_rollback_is_atomic_and_revision_counter_transactional(self):
        with self.engine.connect() as conn:
            before=conn.exec_driver_sql('SELECT SUM(revision) FROM iris2_database_revision').scalar()
            original=conn.exec_driver_sql('SELECT equipment_name FROM equipment WHERE equipment_id=1').scalar()
            conn.exec_driver_sql("UPDATE equipment SET equipment_name='ROLLBACK_TEST' WHERE equipment_id=1")
            conn.rollback()
            self.assertEqual(conn.exec_driver_sql('SELECT equipment_name FROM equipment WHERE equipment_id=1').scalar(),original)
            self.assertEqual(conn.exec_driver_sql('SELECT SUM(revision) FROM iris2_database_revision').scalar(),before)

    def test_plan_approval_and_calculation_storage(self):
        from iris2.application.api510_service import save_pressure_boundary_component,create_api510_calculation
        with self.engine.connect() as conn:
            tube=conn.execute(text("SELECT t.tube_id,b.heat_exchanger_id FROM heat_exchanger_tube t JOIN tube_bundle b ON b.bundle_id=t.bundle_id WHERE t.current_status='IN_SERVICE' LIMIT 1")).first()
        plan=services.save_inspection_plan({'heat_exchanger_id':tube[1],'planned_date':'2026-12-01','tube_ids':[tube[0]]},self.admin)
        self.assertTrue(services.update_inspection_plan_status(plan,'APPROVED',actor_user_id=self.admin,actor_is_admin=True))
        self.assertTrue(services.update_inspection_plan_status(plan,'IN_PROGRESS',actor_user_id=self.admin,actor_is_admin=True))
        with self.assertRaises(ValueError):services.update_inspection_plan_status(plan,'COMPLETED',actor_user_id=self.admin,actor_is_admin=True)
        component=save_pressure_boundary_component(tube[1],{'component_code':'MIG-'+uuid.uuid4().hex[:10],'component_type':'CYLINDRICAL_SHELL','design_basis_source':'Integration test','inside_diameter_mm':1000,'design_pressure_mpa':1,'allowable_stress_mpa':120,'joint_efficiency':1,'actual_thickness_mm':10,'actual_thickness_date':'2026-10-01','thickness_source':'Test measurement'})
        calculation=create_api510_calculation(component,{'selected_corrosion_rate_mm_per_year':0.1,'corrosion_rate_selection_basis':'Test rate'})
        self.assertGreater(calculation,0)

    def test_api510_review_queue_and_concurrent_final_decisions(self):
        from iris2.application.api510_service import (save_pressure_boundary_component,
            create_api510_calculation,transition_api510_calculation,pending_api510_reviews)
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        with self.engine.connect() as conn:
            hx=conn.scalar(text("""SELECT h.heat_exchanger_id FROM heat_exchanger h
                JOIN equipment e ON e.equipment_id=h.equipment_id
                JOIN process_unit u ON u.unit_id=e.unit_id WHERE u.unit_code='VCM1' LIMIT 1"""))
        before=pending_api510_reviews()['count']
        component=save_pressure_boundary_component(hx,dict(component_code='AUDIT-'+uuid.uuid4().hex[:8],
            component_type='CYLINDRICAL_SHELL',design_basis_source='Isolated validation fixture',
            inside_diameter_mm=1000,design_pressure_mpa=1,allowable_stress_mpa=120,joint_efficiency=1,
            actual_thickness_mm=10,actual_thickness_date='2025-10-01',thickness_source='Test measurement'))
        calculation=create_api510_calculation(component,dict(selected_corrosion_rate_mm_per_year=.1,
            corrosion_rate_selection_basis='Test rate'),actor='audit-creator')
        self.assertEqual(pending_api510_reviews()['count'],before)
        transition_api510_calculation(calculation,'SUBMITTED','audit-reviewer')
        self.assertEqual(pending_api510_reviews()['count'],before+1)
        barrier=Barrier(2)
        def decide(status):
            barrier.wait(timeout=10)
            try:
                transition_api510_calculation(calculation,status,'audit-reviewer')
                return 'CHANGED'
            except ValueError:return 'REJECTED_CONFLICT'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(decide,['APPROVED','REJECTED']))
        self.assertEqual(sorted(outcomes),['CHANGED','REJECTED_CONFLICT'])
        self.assertEqual(pending_api510_reviews()['count'],before)
        with self.engine.connect() as conn:
            row=conn.execute(text('SELECT status,reviewed_by,reviewed_at FROM api510_calculation WHERE api510_calculation_id=:id'),{'id':calculation}).first()
        self.assertIn(row[0],('APPROVED','REJECTED'));self.assertEqual(row[1],'audit-reviewer');self.assertIsNotNone(row[2])

    def test_feedback_append_only_store_uses_isolated_auxiliary_schema(self):
        from iris2.ml.review_feedback import save_review_feedback,latest_review_feedback
        from iris2.hx_configuration import ML_REVIEW_DB_PATH
        run='AUDIT-'+uuid.uuid4().hex
        common=dict(run_id=run,model_version='audit',iris_tube_result_id=1,
            iris_inspection_id=1,tube_id=1,reviewer_name='isolated-audit',note='Validation fixture')
        first=save_review_feedback(ML_REVIEW_DB_PATH,**common,label='INSUFFICIENT_EVIDENCE')
        second=save_review_feedback(ML_REVIEW_DB_PATH,**common,label='CONFIRMED_SOURCE_ERROR')
        self.assertGreater(second,first)
        latest=latest_review_feedback(ML_REVIEW_DB_PATH,run)
        self.assertEqual(latest[1]['label'],'CONFIRMED_SOURCE_ERROR')
        connection=dbapi.connect(ML_REVIEW_DB_PATH,readonly=True)
        try:
            self.assertEqual(connection.schema,'iris2_ml'+self.schema[len('iris2'):])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM ml_review_feedback WHERE run_id=?',(run,)).fetchone()[0],2)
        finally:connection.close()
    def test_stale_edit_is_rejected(self):
        with self.engine.connect() as conn:
            code=conn.exec_driver_sql('SELECT equipment_code FROM equipment WHERE equipment_id=1').scalar()
            unit=conn.exec_driver_sql('SELECT unit_id FROM equipment WHERE equipment_id=1').scalar()
            identifier=conn.exec_driver_sql('SELECT heat_exchanger_id FROM heat_exchanger WHERE equipment_id=1').scalar()
        with self.assertRaises(ValueError):
            services.save_exchanger({'equipment_code':code,'unit_id':unit,'expected_updated_at':'2000-01-01T00:00:00'},identifier)
    def test_import_existing_document_is_not_duplicated(self):
        from iris2.iris_v2_importer import import_file
        path=Path(__file__).resolve().parents[1]/'data/source_json/2020VCM1_IRIS_all_tube_results.json'
        with self.engine.connect() as conn:before=conn.exec_driver_sql('SELECT COUNT(*) FROM iris_inspection').scalar()
        result=import_file(path,plant_code='P1',unit_code='VCM1',allow_errors=True)
        self.assertEqual(result['status'],'SKIPPED_DUPLICATE')
        with self.engine.connect() as conn:self.assertEqual(conn.exec_driver_sql('SELECT COUNT(*) FROM iris_inspection').scalar(),before)

    def test_overlapping_revisions_rejected_after_old_snapshot(self):
        from sqlalchemy.orm import Session
        from sqlalchemy.exc import DBAPIError
        from iris2.iris_v2_models import HeatExchangerSpecRevision
        from datetime import datetime
        data={'unit_id':self.unit,'equipment_code':'CONCUR-'+uuid.uuid4().hex[:10],'equipment_name':'Concurrency test'}
        identifier=services.save_exchanger(data)['heat_exchanger_id']
        first=Session(self.engine);second=Session(self.engine)
        try:
            first.execute(text('SELECT COUNT(*) FROM heat_exchanger_spec_revision')).scalar()
            second.add(HeatExchangerSpecRevision(heat_exchanger_id=identifier,revision_no=100,revision_code='100',effective_from=datetime(2020,1,1),effective_to=datetime(2021,1,1),is_current=False))
            second.commit()
            first.add(HeatExchangerSpecRevision(heat_exchanger_id=identifier,revision_no=101,revision_code='101',effective_from=datetime(2020,6,1),effective_to=datetime(2021,6,1),is_current=False))
            with self.assertRaises(DBAPIError):first.commit()
            first.rollback()
        finally:first.close();second.close()
    def test_two_simultaneous_revision_writers_cannot_overlap(self):
        from sqlalchemy.orm import Session
        from sqlalchemy.exc import DBAPIError
        from iris2.iris_v2_models import HeatExchangerSpecRevision
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        identifier=services.save_exchanger({'unit_id':self.unit,'equipment_code':'PAR-'+uuid.uuid4().hex[:10]})['heat_exchanger_id']
        barrier=Barrier(2)
        def write(number):
            with Session(self.engine) as session:
                session.execute(text('SELECT COUNT(*) FROM heat_exchanger_spec_revision')).scalar()
                barrier.wait(timeout=10)
                session.add(HeatExchangerSpecRevision(heat_exchanger_id=identifier,revision_no=number,revision_code=str(number),effective_from=datetime(2010,1,1),effective_to=datetime(2011,1,1),is_current=False))
                try:session.commit();return 'COMMITTED'
                except DBAPIError:session.rollback();return 'REJECTED'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,[100,101]))
        self.assertEqual(sorted(results),['COMMITTED','REJECTED'])
    def test_login_and_view_only_permissions(self):
        from iris2.application.auth_service import save_user
        username='migrtest'+uuid.uuid4().hex[:8]+'@example.test'
        user=save_user({'username':username,'display_name':'View only test','password':'Test-Password-735!','password_confirm':'Test-Password-735!','is_active':'1','permission_EXCHANGERS_view':'1'})
        client=self.app.test_client()
        client.get('/login')
        with client.session_transaction() as session:token=session['csrf_token']
        response=client.post('/login',data={'username':username,'password':'Test-Password-735!','csrf_token':token})
        self.assertEqual(response.status_code,302)
        self.assertEqual(client.get('/exchangers').status_code,200)
        self.assertEqual(client.get('/settings/users').status_code,403)
        with client.session_transaction() as session:token=session['csrf_token']
        self.assertEqual(client.post('/tubes/1/status',data={'current_status':'PLUGGED','reason':'permission test','csrf_token':token}).status_code,403)

    def test_committed_external_sql_invalidates_export_cache(self):
        from iris2.excel_export import get_heat_exchanger_export,clear_heat_exchanger_export_cache
        from io import BytesIO
        clear_heat_exchanger_export_cache()
        with patch('iris2.excel_export._generate_export_workbook',side_effect=[BytesIO(b'first'),BytesIO(b'second')]) as generate:
            first=get_heat_exchanger_export(Path(__file__).resolve().parents[1]/'data/heat_exchanger_db3.db')
            with self.engine.begin() as conn:
                conn.exec_driver_sql('UPDATE equipment SET equipment_name=equipment_name WHERE equipment_id=1')
            second=get_heat_exchanger_export(Path(__file__).resolve().parents[1]/'data/heat_exchanger_db3.db')
            self.assertEqual(generate.call_count,2)
            self.assertNotEqual(first.getvalue(),second.getvalue())
        clear_heat_exchanger_export_cache()
