from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import threading
import unittest
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from customer_clone import customer_clone
from iris2 import services
from iris2.application import plugging_operations as plugging
from iris2.application.customer_corrections_20261124 import correct
from iris2.hx_configuration import PDF_REPORT_DIR
from iris2.iris_v2_models import HeatExchangerTube, TubePluggingEvent, CustomerCorrectionEvent, HeatExchangerSpecRevision
from iris2.migration.plugging_operations import apply_migration


class CustomerCompletionMariaDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=customer_clone()
        cls.engine,cls.schema=cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__,None,None,None)
        apply_migration(cls.engine);apply_migration(cls.engine)

    def payload(self,ids,**changes):
        return dict(operation='COMPLETE',tube_ids=ids,date=date.today().isoformat(),reason='isolated test',
                    versions=plugging.state(100)['versions'],request_key=uuid4().hex,**changes)

    def test_01_source_correction_replay_preserves_history_and_evidence(self):
        plan=correct(self.engine,PDF_REPORT_DIR)
        changes=correct(self.engine,PDF_REPORT_DIR,apply=True)
        self.assertEqual(len(plan),len(changes))
        self.assertEqual(correct(self.engine,PDF_REPORT_DIR,apply=True),[])
        with self.engine.connect() as c:
            self.assertEqual(c.scalar(text('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=375 AND minimum_wall_thickness_mm=2.77')),10)
            self.assertEqual(c.scalar(text('SELECT tube_count FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=235 AND is_current=1')),179)
            self.assertGreaterEqual(c.scalar(text('SELECT COUNT(*) FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=235 AND tube_count=328 AND is_current=0')),1)
            self.assertEqual(c.scalar(text('SELECT MIN(total_tube_count_reported) FROM iris_inspection WHERE heat_exchanger_id=235 AND YEAR(inspection_date)=2022')),328)
            self.assertEqual(c.scalar(text('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=350 AND minimum_wall_thickness_mm IS NULL')),10)
        with self.assertRaises(DBAPIError),self.engine.begin() as c:
            c.exec_driver_sql('DELETE FROM customer_correction_event')

    def test_02_complete_cancel_counts_and_immutable_history(self):
        before=services.exchanger_detail(100)['remaining_life']
        state=plugging.state(100)
        ids=[int(k) for k,v in state['versions'].items() if v['status'] in ('ACTIVE','IN_SERVICE','UNUSED')][:2]
        data=self.payload(ids)
        self.assertEqual(plugging.apply(100,data,dict(user_id=1,username='test actor'))['changed'],2)
        self.assertTrue(plugging.apply(100,data,dict(user_id=1,username='test actor'))['replayed'])
        after=services.exchanger_detail(100)['remaining_life']
        self.assertEqual(after['actual_plugged_count'],before['actual_plugged_count']+2)
        projections=[p for p in after['tube_projections'] if p['tube_id'] in ids]
        self.assertTrue(all(p['basis']=='ALREADY_PLUGGED' for p in projections))
        self.assertEqual(len(projections),2)
        with Session(self.engine) as session:
            tubes=session.scalars(select(HeatExchangerTube).where(HeatExchangerTube.tube_id.in_(ids))).all()
            historical=plugging.tubes_as_of(session,100,tubes,date.today()-timedelta(days=1))
            self.assertTrue(all(t.current_status!='PLUGGED' for t in historical))
            self.assertTrue(all(t.current_status=='PLUGGED' for t in tubes))
        registered=plugging.state(100)
        events=[e['event_id'] for e in registered['history'] if e['tube_id'] in ids and e['can_cancel']]
        cancel=dict(operation='CANCEL',event_ids=events,reason='wrong entry',versions=registered['versions'],request_key=uuid4().hex)
        self.assertEqual(plugging.apply(100,cancel,dict(user_id=1,username='test actor'))['changed'],2)
        self.assertEqual(services.exchanger_detail(100)['remaining_life']['actual_plugged_count'],before['actual_plugged_count'])
        self.assertTrue(all(not e['can_cancel'] for e in plugging.state(100)['history'] if e['event_id'] in events))
        with self.assertRaises(DBAPIError),self.engine.begin() as c:
            c.exec_driver_sql('UPDATE tube_plugging_event SET reason=%s',('tamper',))

    def test_03_reject_invalid_dates_cross_equipment_and_stale_state(self):
        state=plugging.state(100);identifier=int(next(iter(state['versions'])))
        for overrides in [dict(date=(date.today()+timedelta(days=1)).isoformat()),dict(date='1900-01-01'),dict(tube_ids=[99999999]),dict(versions={})]:
            data=self.payload([identifier]);data.update(overrides)
            with self.subTest(overrides=overrides),self.assertRaises((ValueError,plugging.StateConflict)):
                plugging.apply(100,data,dict(user_id=1,username='test actor'))

    def test_04_concurrent_complete_only_one_wins(self):
        state=plugging.state(100);identifier=next(int(k) for k,v in state['versions'].items() if v['status']!='PLUGGED')
        payload=self.payload([identifier]);barrier=threading.Barrier(2);results=[]
        def run():
            data=dict(payload,request_key=uuid4().hex)
            barrier.wait()
            try:plugging.apply(100,data,dict(user_id=1,username='test actor'));results.append('ok')
            except plugging.StateConflict:results.append('conflict')
        threads=[threading.Thread(target=run) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(10)
        self.assertEqual(sorted(results),['conflict','ok'])

    def test_05_pe_dates_thresholds_classification_and_e222_analysis(self):
        overview=services.dashboard_remaining_life()
        self.assertIn('uninspected',overview['bands']);self.assertNotIn('not_reached',overview['bands'])
        self.assertEqual(sum(overview['totals'].values()),overview['total'])
        for row in overview['rows']:
            if row['band']=='unknown':self.assertTrue(row['uncalculable_reason'])
            self.assertNotIn('2321',row['target_display'])
        self.assertEqual(services.precision_analysis_data(235)['selection_status'],'READY')
        pe=[row for row in overview['rows'] if row['unit_code']=='PE' and row['band']!='uninspected']
        self.assertEqual(len(pe),10)
        for row in pe:
            detail=services.exchanger_detail(row['heat_exchanger_id'])['remaining_life']
            self.assertTrue(detail['equipment_overview']['measurement_date'])
            self.assertGreater(detail['sample_wall_loss_estimate']['sample_count'],0)
            self.assertIsNotNone(detail['equipment_overview']['measured_max'])
        for code in ('E-131D','E-331B','E-331C','E-341A','E-341C','E-241B-1'):
            self.assertGreater(next(r for r in pe if r['exchanger_code']==code)['threshold_reached_count'],0)


if __name__=='__main__':unittest.main()
