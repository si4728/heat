import sys
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.app import create_app
from iris2.application.life_dashboard import group_life_rows, life_band
from iris2.domain.plugging_summary import plugging_counts


class PluggingCountTests(unittest.TestCase):
    def test_completed_threshold_future_and_unknown_states_are_distinct(self):
        tubes=[Obj(tube_id=i,current_status='PLUGGED' if i==1 else 'IN_SERVICE') for i in range(1,6)]
        latest={i:(Obj(wall_loss_percent=loss),None) for i,loss in [(1,60),(2,50),(3,10),(4,None)]}
        projections=[dict(tube_id=i,plugging_date=d) for i,d in [(1,'2025-01-01'),(2,'2026-11-10'),(3,'2030-01-01')]]
        counts=plugging_counts(tubes,latest,projections,40,date(2026,11,10),8)
        self.assertEqual(counts,dict(actual_plugged_count=1,threshold_reached_count=1,future_plugging_count=1,
            registered_in_service_count=4,uninspected_registered_count=1,unregistered_tube_count=3))

    def test_zero_completed_does_not_turn_threshold_targets_into_completed(self):
        tubes=[Obj(tube_id=i,current_status='IN_SERVICE') for i in range(5)]
        latest={i:(Obj(wall_loss_percent=50),None) for i in range(5)}
        counts=plugging_counts(tubes,latest,[],40,date(2026,11,10),None)
        self.assertEqual(counts['actual_plugged_count'],0)
        self.assertEqual(counts['threshold_reached_count'],5)
        self.assertIsNone(counts['unregistered_tube_count'])

    def test_missing_life_and_not_reached_have_separate_totals_and_filters(self):
        rows=[dict(unit_code='VCM1',band=life_band(dict(status='LIMIT_NOT_REACHED',total_tube_count=10))),
              dict(unit_code='VCM2',band=life_band(dict(status='INSUFFICIENT_DATA',total_tube_count=10)))]
        report=group_life_rows(rows,band='not_reached')
        self.assertEqual(report['totals']['not_reached'],1)
        self.assertEqual(report['totals']['unknown'],1)
        self.assertEqual(len(report['rows']),1)


class UiTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('iris2.services.initialize'):
            cls.app=create_app({'TESTING':True,'QR_UI_ENABLED':False})

    def render(self,name,endpoint='dashboard',**data):
        ctx=dict(can_screen=lambda *args:True,current_user=data.pop('current_user',dict(username='review',is_admin=True)),
            active_theme=dict(preset_key='DEFAULT',background_color='#f4f7f7',label_color='#52616a'),
            csrf_token='fixture',database_path='MariaDB / iris2',exchanger_display_code=lambda identifier:'E-131D',
            get_flashed_messages=lambda **kw:[],**data)
        with self.app.test_request_context('/'):
            from flask import request
            request.url_rule=next(rule for rule in self.app.url_map.iter_rules() if rule.endpoint==endpoint)
            return self.app.jinja_env.get_template(name).render(**ctx)

    def dashboard_fixture(self, admin=False):
        rows=[dict(unit_code='VCM1',band='short',heat_exchanger_id=1,exchanger_code='E-131D',equipment_name='VCM1 fixture',remaining_life_years=3,status='CALCULATED',latest_inspection_date='2026-01-01',projection_coverage_percent=80),
              dict(unit_code='VCM2',band='not_reached',heat_exchanger_id=2,exchanger_code='E-106',equipment_name='VCM2 fixture',remaining_life_years=None,status='LIMIT_NOT_REACHED',latest_inspection_date='2026-01-01',projection_coverage_percent=30)]
        return self.render('dashboard.html',current_user=dict(username='review',is_admin=admin),counts=defaultdict(int,exchangers=2),life_dashboard=dict(group_life_rows(rows),as_of_date='2026-11-10'),yearly_rows=[],recent=[],units=[],upcoming_plans=[])

    def precision_fixture(self):
        return self.render('precision_analysis.html','precision_analysis',selected_exchanger_id=1,selected_detail=None,tube_map=None,corrosion_rate_multiplier=1,units=['VCM1','VCM2'],unit_code='VCM1',search='',analysis_rows=[dict(heat_exchanger_id=1,exchanger_code='E-131D',unit_code='VCM1',equipment_name='Fixture exchanger',wall_loss_status='NORMAL',wall_loss_percent=20)])

    def loaded_precision_fixture(self):
        # A bounded fixture exercises the actual Map, selection and forecast JS.
        self.app.jinja_env.filters['plant_display']=lambda value:value
        self.app.jinja_env.filters['organization_label']=lambda value,*args:value
        row=dict(tube_id=1,tube_no='T-1',row_no=1,column_no=1,minimum_wall_thickness_mm=1,
            location_mm=100,corrosion_type='LOCAL',wall_loss_depth_mm=1,wall_loss_percent=50,
            plugging_complete=False,plugging_threshold_reached=True,plugging_year=2026,
            measurement_date='2020-10-24',report_number='Fixture',pdf_url=None,
            corrosion_rate_mm_per_year=.1)
        projection=dict(row,plugging_date='2026-11-10',projection_origin_date='2026-11-10',
            years_from_measurement=0,basis='CALCULATED',nominal_thickness_mm=2,current_wall_loss_mm=1)
        life=dict(defect_count=1,defect_rows=[row],tube_projections=[projection],tube_histories={},
            specified_tube_count=52,total_tube_count=52,managed_tube_count=5,projected_tube_count=5,chart_end_year=2050,
            as_of_date='2026-11-10',current_year=2026,limit_percent=20,allowable_plugging_count=20,
            actual_plugged_count=0,threshold_reached_count=1,future_plugging_count=0,unregistered_tube_count=47,
            equipment_summary=dict(latest_inspection_date='2020-10-24',inspected_tube_count=1,
                total_tube_count=100,shell_fluid='Water',tube_fluid='VCM',tube_material='Steel',
                representative_corrosion_rate_mm_per_year=.1))
        master=[dict(heat_exchanger_id=1),dict(process_code='',equipment_name='Fixture E-131D'),dict(unit_name='VCM1'),dict(plant_code='VCM1')]
        tube_map=dict(layout=dict(pdf_vector_display_applied=False,is_estimated=False),selected_campaign=None,
            tube_spec=dict(outer_diameter_mm=19,nominal_thickness_mm=2,length_mm=6000),
            tubes=[dict(tube_id=1,tube_no='T-1',x=1,y=1,row=1,column=1,category='CRITICAL',wall_loss_percent=50,current_status='IN_SERVICE')])
        return self.render('precision_analysis.html','precision_analysis',selected_exchanger_id=1,
            selected_detail=dict(master=master,remaining_life=life,analysis_pdf_reports=[],map_pdf_url=None),
            tube_map=tube_map,corrosion_rate_multiplier=1,units=['VCM1','VCM2'],unit_code='VCM1',search='',
            analysis_rows=[dict(heat_exchanger_id=1,exchanger_code='E-131D',unit_code='VCM1',equipment_name='Fixture exchanger',wall_loss_status='CRITICAL',wall_loss_percent=50)])

    def test_loaded_precision_contains_navigation_map_and_forecast_payload(self):
        html=self.loaded_precision_fixture()
        for text in ['id="app-sidebar"','id="precision-map-data"','id="precision-life-data"','id="remaining-life-analysis"','현재 메뉴: 정밀 분석','E-131D']:
            self.assertIn(text,html)

    def test_all_templates_parse(self):
        for path in (Path(__file__).resolve().parents[1]/'templates').glob('*.html'):
            with self.subTest(template=path.name):self.app.jinja_env.parse(path.read_text(encoding='utf-8-sig'))

    def test_dashboard_removes_missing_registration_and_qr_entries(self):
        html=self.dashboard_fixture()
        for absent in ['Tube 수량 미등록 열교환기','Tube 미등록 열교환기','missing-tube-count-panel','data-qr-scan-open','dashboard-qr-modal','Heat Exchanger Intelligence','IRIS<span>2']:
            self.assertNotIn(absent,html)
        for present in ['i-HMS','지능형 열교환기 관리 시스템','life-band-table','life-band-total','산정 불가','한도 미도달','안전 판정']:
            self.assertIn(present,html)

    def test_precision_keeps_system_navigation_and_separate_equipment_picker(self):
        html=self.precision_fixture()
        for present in ['id="app-sidebar"','sidebar-toggle','대시보드','열교환기 목록','검사 이력','검사계획','관리자 설정','열교환기 선택','E-131D','aria-current="true"']:
            self.assertIn(present,html)
        self.assertNotIn('app-shell analysis-fullscreen',html)

    def test_qr_dashboard_is_hidden_for_all_roles_when_disabled(self):
        for admin in (False,True):
            html=self.dashboard_fixture(admin=admin)
            for marker in ['data-qr-scan-open','id="dashboard-qr-modal"','dashboard-qr-scanner.js','vendor/jsqr/jsQR.js']:
                self.assertNotIn(marker,html)

    def test_qr_detail_action_is_visible_only_to_administrators(self):
        with self.app.test_request_context('/'):
            template=self.app.jinja_env.get_template('exchanger_detail.html')
            for profile,permission,expected in [(None,True,False),({'is_admin':False},True,False),({'is_admin':True},False,False),({'is_admin':True},True,False)]:
                context=template.new_context(dict(current_user=profile,can_screen=lambda *args:permission,hx=Obj(heat_exchanger_id=1)))
                html=''.join(template.blocks['actions'](context))
                self.assertEqual('QR 간편조회' in html,expected)

    def test_qr_enabled_is_still_admin_only(self):
        with patch.dict(self.app.config, {'QR_UI_ENABLED': True}):
            for admin in (False, True):
                html=self.dashboard_fixture(admin=admin)
                self.assertNotIn('data-qr-scan-open', html)
                self.assertNotIn('dashboard-qr-scanner.js', html)
            with self.app.test_request_context('/'):
                template=self.app.jinja_env.get_template('exchanger_detail.html')
                for admin, permission in [(False, True), (True, True), (True, False)]:
                    context=template.new_context(dict(current_user={'is_admin':admin},can_screen=lambda *args:permission,hx=Obj(heat_exchanger_id=1)))
                    html=''.join(template.blocks['actions'](context))
                    self.assertEqual('QR 간편조회' in html, admin and permission)

    def test_prediction_denominators_show_5_of_52_and_5_of_5(self):
        html=self.render('prediction_coverage.html',life=dict(total_tube_count=52,specified_tube_count=52,managed_tube_count=5,projected_tube_count=5,chart_end_year=2050,current_year=2026))
        for value in ['5/52개, 9.6%','5/5개, 100.0%','미등록·평가 제외: <strong>47개','그래프 표시 범위: 2026~2050년']:
            self.assertIn(value,html)
        precise=self.render('prediction_coverage.html',coverage_chart_end_year=2051,life=dict(total_tube_count=52,specified_tube_count=52,managed_tube_count=5,projected_tube_count=5,chart_end_year=2050,current_year=2026))
        self.assertIn('그래프 표시 범위: 2026~2051년',precise)

    def test_missing_specification_and_no_registered_tubes_do_not_show_100_percent(self):
        html=self.render('prediction_coverage.html',life=dict(specified_tube_count=None,managed_tube_count=0,projected_tube_count=0))
        self.assertIn('사양 미확인',html)
        self.assertIn('비율 산정 불가',html)
        self.assertNotIn('100.0%',html)

    def test_remaining_life_status_is_shared_and_not_displayed_as_dash_years(self):
        macros=self.app.jinja_env.get_template('life_display.html').module
        self.assertEqual(macros.remaining_label(dict(status='LIMIT_NOT_REACHED',remaining_life_years=None)),'가용 데이터에서 한도 미도달')
        self.assertEqual(macros.remaining_label(dict(status='INSUFFICIENT_DATA',remaining_life_years=None)),'산정 불가 (데이터 부족)')
        self.assertEqual(macros.remaining_label(dict(status='CALCULATED',remaining_life_years=0)),'0년')

    def test_observed_threshold_does_not_display_basis_date_as_actual_crossing(self):
        macros=self.app.jinja_env.get_template('life_display.html').module
        text=macros.projection_date(dict(basis='CALCULATED',plugging_threshold_reached=True,plugging_year=2026,plugging_date='2026-11-10'))
        self.assertEqual(text,'최근 검사에서 기준 도달 확인 — 실제 도달일 미상')
        self.assertNotIn('2026-11-10',text)
        self.assertIn('2030-01-01',macros.projection_date(dict(basis='CALCULATED',plugging_threshold_reached=False,plugging_year=2030,plugging_date='2030-01-01')))

    def forecast_fixture(self, name):
        self.app.jinja_env.filters['plant_display']=lambda value:value
        self.app.jinja_env.filters['organization_label']=lambda value,*args:value
        blank=lambda **kw:defaultdict(lambda:None,kw)
        life=blank(status='LIMIT_NOT_REACHED',remaining_life_years=None,life_reached_year=None,
            specified_tube_count=52,total_tube_count=52,managed_tube_count=5,projected_tube_count=5,
            projection_coverage_percent=100,unprojectable_tube_count=0,limit_percent=20,allowable_plugging_count=10,
            plugging_wall_loss_percent=40,corrosion_rate_multiplier=1,current_year=2026,base_year=2026,
            as_of_date='2026-11-10',chart_end_year=2050,chart_series=[],yearly=[],defect_rows=[],defect_count=0,
            actual_plugged_count=0,threshold_reached_count=5,future_plugging_count=0,registered_in_service_count=5,
            uninspected_registered_count=0,unregistered_tube_count=47,reason_counts=defaultdict(int),equipment_summary=blank(latest_inspection_date='2020-10-24'))
        life['tube_projections']=[dict(tube_id=i,tube_no=f'T-{i}',measurement_date='2026-01-01',
            nominal_thickness_mm=2,current_wall_loss_mm=1,corrosion_rate_mm_per_year=.1,basis='CALCULATED',
            plugging_threshold_reached=True,plugging_year=2026,plugging_date='2026-11-10') for i in range(1,6)]
        endpoint={'exchanger_detail.html':'exchanger_detail','qr_exchanger_lookup.html':'qr_exchanger_lookup','exchanger_report.html':'exchanger_report','remaining_life_simulation.html':'remaining_life_simulation'}[name]
        return self.render(name,endpoint=endpoint,master=[blank(heat_exchanger_id=1),blank(),blank(unit_name='VCM1'),blank(plant_code='VCM1')],
            remaining_life=life,remaining_life_simulation=None,spec=None,spec_summary=None,criteria=None,
            tube_length_resolution=blank(),inspections=[],bundles=[],scopes=[],tube_count=5,
            status_counts={'IN_SERVICE':5,'PLUGGED':0},inspection_priority=blank(enabled=False),
            ai_summary=blank(),pdf_reference=blank(),inspection_pdf_links={},approved_api510=[],
            generated_at=date(2026,11,10),maximum_wall_loss=50,calculation_method='LEGACY',
            simulation_requested=False,simulation_limit=20,corrosion_rate_percent=100,
            plugging_wall_loss_percent=40,forecast_end_year=2050,api510_values=None,api510_defaults=blank())

    def test_all_forecast_surfaces_use_common_denominators_and_status(self):
        for name in ['remaining_life_simulation.html','exchanger_detail.html','qr_exchanger_lookup.html','exchanger_report.html']:
            with self.subTest(name=name):
                html=self.forecast_fixture(name)
                self.assertIn('5/52개, 9.6%',html)
                self.assertIn('5/5개, 100.0%',html)
                self.assertIn('가용 데이터에서 한도 미도달',html)
                self.assertNotIn('예측기간 내 미도달',html)
                self.assertNotIn('>-년',html)
                self.assertIn('예측 가능한 등록 튜브 중 향후 추가 도달 대상 0개이며, 미등록 47개는 평가에서 제외됩니다.',html)
                self.assertIn('설비 최근 검사일: <strong>2020-10-24</strong>',html)
                self.assertIn('계산 기준일: <strong>2026-11-10</strong>',html)
                self.assertIn('실제 작업 완료나 계산 기준일의 재측정 결과를 뜻하지 않습니다.',html)
                if name in ['exchanger_detail.html','qr_exchanger_lookup.html']:
                    self.assertIn('개별 등록 튜브',html)
                    self.assertNotIn('물리 튜브',html)
                    self.assertNotIn('물리 Tube',html)
                if name=='exchanger_detail.html':
                    self.assertEqual(html.count('최근 검사에서 기준 도달 확인 — 실제 도달일 미상'),5)

    def test_shared_count_labels_do_not_call_predictions_completed(self):
        life=dict(actual_plugged_count=0,threshold_reached_count=5,future_plugging_count=2,registered_in_service_count=10,uninspected_registered_count=3,unregistered_tube_count=4,plugging_wall_loss_percent=40)
        html=self.render('plugging_counts.html',life=life)
        self.assertIn('실제 Plugging 완료 수량 <strong>0개',html)
        self.assertIn('Plugging 기준 도달 대상 수량 <strong>5개',html)
        self.assertIn('향후 Plugging 예상 수량 <strong>2개',html)

    def test_data_entry_retains_missing_tube_list(self):
        summary=defaultdict(int,groups=[],quality={},label='fixture',note='fixture',tube_count_unspecified_exchangers=1)
        coverage=dict(exchanger=summary,exchanger_groups=[],exchanger_management=summary,tube=summary,tube_groups=[],registered_tube=summary,registered_exchanger_count=1,open_issues=0,
            missing_tube_count_by_unit={'VCM1':1},missing_tube_count_exchangers=[dict(heat_exchanger_id=1,unit_code='VCM1',equipment_code='E131D',equipment_tag='E-131D',equipment_name='fixture',exchanger_type_code='FIXED')],
            tube_population=dict(total_count=10,registered_count=5,specified_exchanger_count=0,unspecified_exchanger_count=1))
        html=self.render('data_entry_status.html',endpoint='data_entry_status',data_entry_coverage=coverage)
        self.assertIn('Tube 수량 미등록 열교환기',html)
        self.assertIn('E131D',html)
        self.assertIn('missing-tube-count-search',html)

    def test_tube_management_excludes_unregistered_from_in_service(self):
        html=self.render('tube_management.html',endpoint='tube_management',master=[Obj(heat_exchanger_id=1),Obj()],specified_tube_count=100,registered_tube_count=5,registered_status_counts={'IN_SERVICE':5,'PLUGGED':0},status_counts={'IN_SERVICE':100,'PLUGGED':0},default_in_service_count=95,search='',status_filter='',tube_statuses={},tubes=[],latest={})
        self.assertIn('<span>사용 중</span><strong>5</strong>',html)
        self.assertIn('<span>등록되지 않은 튜브</span><strong>95</strong>',html)


if __name__=='__main__':unittest.main()
