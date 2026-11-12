import sys
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from flask import Flask
from iris2.application.inspection_history import history_matrix, inspection_history_data
from iris2.application.inspection_recommendations import recommended_plans_data, save_recommended_plan
from iris2.domain.inspection_recommendation import recommendation, horizon_end
from iris2.web.security import register_security
from iris2.web.routes.inspections import register_routes


class HistoryMatrixTests(unittest.TestCase):
    def test_annual_maximum_links_its_source_report_not_the_latest_report(self):
        rows,years=history_matrix([{'heat_exchanger_id':1},{'heat_exchanger_id':2}],
            [dict(heat_exchanger_id=1,date=date(2023,1,1),loss_percent=50,inspection_id=10),
             dict(heat_exchanger_id=1,date=date(2023,12,1),loss_percent=20,inspection_id=11),
             dict(heat_exchanger_id=1,date=date(2025,1,1),loss_percent=55,inspection_id=12)])
        self.assertEqual(years,[2023,2025])
        self.assertEqual(rows[0]['cells'][2023]['inspection_id'],10)
        self.assertEqual(rows[0]['cells'][2023]['inspection_count'],2)
        self.assertEqual(rows[0]['change_percentage_points'],5)
        self.assertEqual(rows[1]['inspection_count'],0)
        self.assertEqual(rows[1]['cells'],{})

    def test_missing_values_and_real_zero_are_distinct(self):
        rows,_=history_matrix([{'heat_exchanger_id':1}],
            [dict(heat_exchanger_id=1,date=date(2023,1,1),loss_percent=None,inspection_id=1),
             dict(heat_exchanger_id=1,date=date(2023,2,1),loss_percent=0,inspection_id=2)])
        self.assertEqual(rows[0]['cells'][2023]['loss_percent'],0)
        self.assertEqual(rows[0]['cells'][2023]['inspection_id'],2)

    def test_empty_and_out_of_scope_inputs(self):
        self.assertEqual(history_matrix([],[]),([],[]))
        rows,years=history_matrix([{'heat_exchanger_id':1}],
            [dict(heat_exchanger_id=2,date=date(2023,1,1),loss_percent=50,inspection_id=1)])
        self.assertEqual(years,[])
        self.assertEqual(rows[0]['inspection_count'],0)

    def test_rejects_other_units_before_database_access(self):
        with self.assertRaises(ValueError):inspection_history_data(mode='process',unit='VCM3')
        with self.assertRaises(ValueError):recommended_plans_data(unit='VCM4')
        with self.assertRaises(ValueError):recommended_plans_data(horizon='-1')
        with self.assertRaises(ValueError):save_recommended_plan({},None)


class RecommendationTests(unittest.TestCase):
    def life(self,status='ESTIMATED',date_value='2026-01-01',prediction_status='FORECAST'):
        return {'sample_wall_loss_estimate':dict(status=status,measurement_date='2020-01-01',
            first_threshold=dict(status=prediction_status,date=date_value))}

    def measured(self):
        return dict(status='FORECAST',measurement_date='2020-01-01',date='2030-01-01',tube_no='1-2')

    def test_basis_selection_and_half_interval(self):
        r=recommendation(self.life(),self.measured())
        self.assertEqual(r['source'],'통계 추정')
        self.assertEqual(r['first_date'],date(2026,1,1))
        self.assertEqual(r['due_date'],date(2020,1,1)+(date(2026,1,1)-date(2020,1,1))//2)
        self.assertEqual(recommendation(self.life(),self.measured(),basis='measured')['source'],'실측 튜브')
        self.assertEqual(recommendation(self.life(),self.measured(),basis='estimated')['source'],'통계 추정')

    def test_sample_shortfall_falls_back_to_measured_only_when_allowed(self):
        r=recommendation(self.life(status='SAMPLE_INSUFFICIENT'),self.measured())
        self.assertEqual(r['source'],'실측 튜브')
        self.assertIsNone(recommendation(self.life(status='SAMPLE_INSUFFICIENT'),self.measured(),basis='estimated'))
        self.assertIsNone(recommendation({},None))

    def test_reached_status_does_not_invent_first_crossing_date(self):
        r=recommendation(self.life(date_value=None,prediction_status='ESTIMATED_REACHED'),None)
        self.assertTrue(r['threshold_reached'])
        self.assertIsNone(r['first_date'])
        self.assertEqual(r['due_date'],date(2020,1,1))

    def test_horizon_calendar_boundary_and_invalid_inputs(self):
        self.assertEqual(horizon_end(date(2024,2,29),'1'),date(2025,2,28))
        self.assertEqual(horizon_end(date(2026,11,12),'2'),date(2028,11,12))
        self.assertEqual(horizon_end(date(2026,11,12),'all'),date.max)
        with self.assertRaises(ValueError):recommendation({},None,basis='unknown')


class InspectionWorkspaceWebTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.config.update(SECRET_KEY='test-only',AUTH_DISABLED=False,CSRF_ENABLED=True,
            SESSION_IDLE_TIMEOUT_SECONDS=1800,TESTING=True)
        register_security(self.app)
        self.app.register_error_handler(403,lambda exc:('Forbidden',403))
        register_routes(self.app)
        self.profile=dict(user_id=1,username='reader',is_active=True,is_admin=False,
            permissions={'INSPECTIONS':dict(can_view=True,can_edit=False)})
        self.patch('iris2.services.user_count',return_value=1)
        self.patch('iris2.services.user_access_profile',side_effect=lambda uid:self.profile if uid else None)
        self.render=self.patch('iris2.web.routes.inspections.render_template',return_value='rendered')
        self.history=self.patch('iris2.web.routes.inspections.inspection_history_data',return_value={})
        self.recommendations=self.patch('iris2.web.routes.inspections.recommended_plans_data',return_value={})
        self.tubes=self.patch('iris2.web.routes.inspections.available_tubes',return_value=[{'tube_id':1,'tube_no':'1-2'}])
        self.save=self.patch('iris2.web.routes.inspections.save_recommended_plan',return_value=9)
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user_id=1,last_activity_at=time.time(),csrf_token='csrf')

    def patch(self,*args,**kwargs):
        p=patch(*args,**kwargs);self.addCleanup(p.stop);return p.start()

    def test_new_gets_use_inspection_read_permission(self):
        for url in ['/inspections/yearly','/inspections/process','/inspection-plans']:
            self.assertEqual(self.client.get(url).status_code,200)
        response=self.client.get('/inspection-plans/recommended/1/tubes')
        self.assertEqual(response.json['tubes'][0]['tube_no'],'1-2')
        self.assertEqual(self.client.get('/inspections/process?unit=VCM2&process=EDC').status_code,200)
        self.assertEqual(self.history.call_args.kwargs['unit'],'VCM2')

    def test_anonymous_and_missing_permissions_never_reach_queries(self):
        self.assertEqual(self.app.test_client().get('/inspections/yearly').status_code,302)
        self.profile['permissions']={}
        for url in ['/inspections/yearly','/inspections/process','/inspection-plans/recommended/1/tubes']:
            self.assertEqual(self.client.get(url).status_code,403)
        self.history.assert_not_called();self.tubes.assert_not_called()

    def test_registration_requires_edit_permission_and_csrf(self):
        payload=dict(registration_source='recommendation',heat_exchanger_id='1',tube_ids='1',
                     planned_date='2027-01-01',csrf_token='csrf')
        self.assertEqual(self.client.post('/inspection-plans',data=payload).status_code,403)
        self.profile['permissions']['INSPECTIONS']['can_edit']=True
        payload.pop('csrf_token')
        self.assertEqual(self.client.post('/inspection-plans',data=payload).status_code,400)
        self.save.assert_not_called()
        payload['csrf_token']='csrf'
        self.assertEqual(self.client.post('/inspection-plans',data=payload).status_code,302)
        self.assertEqual(self.save.call_args.args[1],1)
        self.assertEqual(self.save.call_args.args[0]['tube_ids'],['1'])

    def test_invalid_filters_return_bad_request(self):
        self.history.side_effect=ValueError('조회 기준 확인')
        self.assertEqual(self.client.get('/inspections/yearly').status_code,400)

    def test_recommendation_basis_is_fixed_to_measured(self):
        self.assertEqual(self.client.get('/inspection-plans?basis=earliest').status_code,200)
        self.assertEqual(self.recommendations.call_args.kwargs['basis'],'measured')

    def test_stale_registration_basis_rejected_before_database_access(self):
        from iris2.application.inspection_recommendations import save_recommended_plan
        with self.assertRaisesRegex(ValueError,'実測|실측'):
            save_recommended_plan(dict(heat_exchanger_id='1', recommendation_basis='earliest'),1)
