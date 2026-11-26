"""Advanced questions: actual HTTP and SELECT-only DB on an isolated copy."""
from datetime import datetime
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from customer_clone import customer_clone
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from iris2 import services
from iris2.app import create_app
from iris2.application.text_to_sql_help import ADVANCED_EXAMPLES
from iris2.iris_v2_models import (Equipment,HeatExchanger,ProcessUnit,HeatExchangerSpecRevision,
    TubeBundle,HeatExchangerTube,IrisInspection,IrisTubeResult,IrisInspectionSummaryHistory,TubePluggingEvent)


class AdvancedMariaDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=customer_clone(temporary_readers=True)
        cls.engine,cls.schema=cls.context.__enter__();cls.addClassCleanup(cls.context.__exit__,None,None,None)
        with Session(cls.engine) as s:
            unit=s.scalar(select(ProcessUnit).where(ProcessUnit.unit_code=='PE'))
            equipment=Equipment(unit_id=unit.unit_id,equipment_code='ADV-'+uuid4().hex[:10],equipment_tag='AUDIT-E-9001',
                equipment_name='Advanced isolated fixture',production_team_code='PE',install_date=datetime(2010,1,1))
            s.add(equipment);s.flush()
            hx=HeatExchanger(equipment_id=equipment.equipment_id,iris_applicability='REQUIRED')
            s.add(hx);s.flush();cls.identifier=hx.heat_exchanger_id
            s.add(HeatExchangerSpecRevision(heat_exchanger_id=hx.heat_exchanger_id,exchanger_code='E-9001',revision_no=1,
                revision_code='1',is_current=True,tube_count=20,tube_nominal_thickness_mm=2.77,tube_material='Cu-Ni'))
            bundle=TubeBundle(heat_exchanger_id=hx.heat_exchanger_id,bundle_code='AUDIT',expected_tube_count=20)
            s.add(bundle);s.flush()
            tubes=[HeatExchangerTube(bundle_id=bundle.bundle_id,tube_no=f'A-{n}',row_no=1,column_no=n,
                installed_at=datetime(2010,1,1),current_status='IN_SERVICE') for n in range(1,11)]
            s.add_all(tubes);s.flush()
            source=s.scalar(select(IrisInspection).limit(1))
            rounds=[]
            for index,year in enumerate((2020,2025)):
                inspection=IrisInspection(campaign_id=source.campaign_id,source_document_id=source.source_document_id,
                    heat_exchanger_id=hx.heat_exchanger_id,bundle_id=bundle.bundle_id,report_sequence=900001+index,
                    report_number=f'AUDIT-{year}',inspection_date=datetime(year,1,1),original_equipment_id='E-9001',
                    raw_report_json='{"isolated_fixture":true}')
                s.add(inspection);s.flush();rounds.append(inspection.iris_inspection_id)
                for number,tube in enumerate(tubes):
                    loss=(46 if index==0 else 51)+number
                    s.add(IrisTubeResult(iris_inspection_id=inspection.iris_inspection_id,tube_id=tube.tube_id,source_tube_id=tube.tube_no,
                        wall_loss_percent=loss,minimum_wall_thickness_mm=2.77*(1-loss/100),
                        wall_loss_depth_mm=2.77*loss/100,result_status='VALID',quality_status='INVALID' if number==0 else 'VALID',
                        raw_json='{"isolated_fixture":true}'))
                s.add(IrisInspectionSummaryHistory(iris_inspection_id=inspection.iris_inspection_id,
                    plugged_tube_count_before=0 if index==0 else 2,plugged_tube_count_after=2 if index==0 else 3))
            actual=HeatExchangerTube(bundle_id=bundle.bundle_id,tube_no='ACTUAL',current_status='PLUGGED',
                installed_at=datetime(2010,1,1),plugging_date=datetime(2022,1,1))
            s.add(actual);s.flush()
            s.add(TubePluggingEvent(heat_exchanger_id=hx.heat_exchanger_id,tube_id=actual.tube_id,operation='COMPLETE',
                effective_date=datetime(2022,1,1).date(),actor_id=1,actor_name='Isolated fixture',request_key=uuid4().hex,
                reason='isolated fixture',previous_status='IN_SERVICE'))
            s.commit();cls.rounds=rounds
        cls.app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
        with cls.engine.connect() as c:cls.uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))

    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as s:s.update(user_id=self.uid,auth_stamp=services.user_access_profile(self.uid)['auth_stamp'],last_activity_at=time.time(),csrf_token='advanced-db-test')
        return client

    def query(self,question):
        client=self.client();headers={'X-CSRF-Token':'advanced-db-test'}
        preview=client.post('/inspections/text-to-sql/generate',json=dict(question=question,result_unit='equipment',exchanger_ids=[self.identifier]),headers=headers)
        self.assertEqual(preview.status_code,200,preview.json)
        response=client.post('/inspections/text-to-sql/execute',json=dict(token=preview.json['token']),headers=headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotIn('heat_exchanger_id',response.json['result']['columns'])
        return response.json['result']

    def test_01_increase_and_rate_match_original_measurements_and_analysis(self):
        delta=self.query(ADVANCED_EXAMPLES[0])
        self.assertEqual(delta['rows'][0]['previous_maximum_loss'],55)
        self.assertEqual(delta['rows'][0]['latest_maximum_loss'],60)
        self.assertEqual(delta['rows'][0]['wall_loss_increase_percent_points'],5)
        result=self.query(ADVANCED_EXAMPLES[1])
        life=services.exchanger_detail(self.identifier)['remaining_life']
        expected=sum((r.get('corrosion_rate_mm_per_year') or 0)>=.1 for r in life['analysis_tube_rows'])
        self.assertEqual(result['rows'][0]['matching_tube_count'],expected)

    def test_02_team_and_sample_and_material(self):
        team=self.query(ADVANCED_EXAMPLES[2])
        self.assertEqual(team['result_unit'],'team')
        self.assertEqual(team['rows'][0]['exchanger_count'],1)
        self.assertEqual(team['matched_equipment_count'],1)
        sample=self.query(ADVANCED_EXAMPLES[3])
        self.assertEqual(sample['rows'][0]['sample_count'],9)
        self.assertEqual(sample['rows'][0]['total_tube_count'],20)
        material=self.query(ADVANCED_EXAMPLES[5])
        self.assertEqual(material['rows'][0]['tube_material'],'Cu-Ni')
        self.assertEqual(material['rows'][0]['maximum_loss'],60)

    def test_03_history_report_numbers_and_actual_completion_are_separate(self):
        result=self.query('E-9001의 검사 회차별 최대 감육률과 Plugging 수량 추이를 보여줘')
        self.assertEqual(result['result_unit'],'inspection')
        self.assertEqual(len(result['rows']),2)
        self.assertEqual([r['reported_plugging_after'] for r in result['rows']],[2,3])
        self.assertIsNone(result['rows'][0]['cumulative_actual_plugging_count'])
        self.assertEqual(result['rows'][1]['cumulative_actual_plugging_count'],1)
        self.assertNotIn('remaining_display',result['columns'])
        client=self.client()
        with patch('iris2.web.routes.text_to_sql.commentary.generate',return_value=dict(text='summary',status='generated',model='test')) as model:
            response=client.post('/inspections/text-to-sql/summarize',json=dict(token=result['summary_token']),headers={'X-CSRF-Token':'advanced-db-test'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertIn('검사 회차',model.call_args.args[0]['scope_label'])

    def test_04_missing_history_uses_inspection_dates_not_tube_sample(self):
        with Session(self.engine) as s:
            latest=s.get(IrisInspection,self.rounds[-1]);latest.superseded_by_inspection_id=self.rounds[0];s.commit()
        try:
            result=self.query(ADVANCED_EXAMPLES[4])
            self.assertEqual(result['rows'][0]['latest_inspection_date'],'2020-01-01')
            self.assertEqual(result['rows'][0]['iris_applicability'],'REQUIRED')
        finally:
            with Session(self.engine) as s:
                s.get(IrisInspection,self.rounds[-1]).superseded_by_inspection_id=None;s.commit()


if __name__=='__main__':unittest.main()
