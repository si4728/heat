"""Read-only regression checks for administrator completeness screen."""
import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.app import create_app
from iris2.database import get_engine
from iris2 import services

class DataEntryStatusAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app({'TESTING':True,'AUTH_DISABLED':False})
        with get_engine().connect() as c:
            cls.uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
        assert cls.uid, 'Active administrator required'
        cls.profile=services.user_access_profile(cls.uid)

    def client(self):
        c=self.app.test_client()
        with c.session_transaction() as s:
            s.update(user_id=self.uid,last_activity_at=time.time())
        return c

    def test_admin_screen_and_dashboard_separation(self):
        c=self.client()
        r=c.get('/master-data/data-entry-status')
        self.assertEqual(r.status_code,200)
        html=r.get_data(as_text=True)
        for label in ['열교환기 주요 데이터 입력률','Tube 주요 데이터 입력률','사양 수량 대비 개별 Tube 등록 현황','dashboard-metric-modal','열린 품질 이슈','status=OPEN']:
            self.assertIn(label,html)
        dashboard=c.get('/').get_data(as_text=True)
        self.assertNotIn('열교환기 주요 데이터 입력률',dashboard)
        self.assertNotIn('Tube 주요 데이터 입력률',dashboard)
        self.assertNotIn('열린 품질 이슈',dashboard)
        self.assertIn('/master-data/data-entry-status',dashboard)

    def test_non_admin_direct_access_and_menu_hidden(self):
        profile=dict(self.profile,is_admin=False)
        with patch('iris2.services.user_access_profile',return_value=profile):
            c=self.client()
            self.assertEqual(c.get('/master-data/data-entry-status').status_code,403)
            with self.app.test_request_context('/'):
                from flask import g,render_template
                g.current_user=profile
                html=render_template('base.html')
                self.assertNotIn('/master-data/data-entry-status',html)

    def test_pdf_review_is_admin_only_under_settings(self):
        c=self.client()
        r=c.get('/imports/pdf-review')
        self.assertEqual(r.status_code,200)
        html=r.get_data(as_text=True)
        settings=html.split('id="administrator-settings"',1)[1].split('</details>',1)[0]
        management=html.split('id="general-navigation"',1)[1].split('</nav>',1)[0]
        self.assertIn('href="/imports/pdf-review"',settings)
        self.assertNotIn('href="/imports/pdf-review"',management)
        profile=dict(self.profile,is_admin=False)
        with patch('iris2.services.user_access_profile',return_value=profile):
            c=self.client()
            self.assertEqual(c.get('/imports/pdf-review').status_code,403)
            self.assertEqual(c.get('/imports/pdf-review/1/source').status_code,403)
            with c.session_transaction() as session:
                session['csrf_token']='test-csrf'
            self.assertEqual(c.post('/imports/pdf-review/1/approve',data={'csrf_token':'test-csrf'}).status_code,403)
            with self.app.test_request_context('/'):
                from flask import g,render_template
                g.current_user=profile
                self.assertNotIn('href="/imports/pdf-review"',render_template('base.html'))
        self.assertEqual(self.app.test_client().get('/imports/pdf-review').status_code,302)

    def test_precision_pdf_evidence_links(self):
        data=services.precision_analysis_data(157)
        detail=data['selected_detail']
        reports={r['inspection_id']:r['pdf_url'] for r in detail['analysis_pdf_reports']}
        self.assertTrue(any(reports.values()))
        for history in detail['remaining_life']['tube_histories'].values():
            for item in history:
                self.assertEqual(item['pdf_url'],reports.get(item['inspection_id']))
        for row in detail['remaining_life']['defect_rows']:
            self.assertEqual(row['pdf_url'],reports.get(row['inspection_id']))
        c=self.client()
        response=c.get('/analysis?exchanger_id=157')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('analysis-pdf-reports',html)
        self.assertIn('설비 검사 이력 · 원본 PDF',html)
        self.assertIn('감육속도·잔여수명·누적 예측',html)
        self.assertIn('data-pdf-reports-open',html)
        url=next(value for value in reports.values() if value)
        pdf=c.get(url.split('#')[0])
        self.assertEqual(pdf.status_code,200)
        self.assertEqual(pdf.mimetype,'application/pdf')
        pdf.close()
        self.assertEqual(self.app.test_client().get(url.split('#')[0]).status_code,302)

    def test_json_import_is_admin_only_under_settings(self):
        c=self.client()
        r=c.get('/imports')
        self.assertEqual(r.status_code,200)
        html=r.get_data(as_text=True)
        settings=html.split('id="administrator-settings"',1)[1].split('</details>',1)[0]
        management=html.split('id="general-navigation"',1)[1].split('</nav>',1)[0]
        self.assertIn('href="/imports"',settings)
        self.assertNotIn('href="/imports"',management)
        self.assertIn('id="administrator-settings"',html)
        profile=dict(self.profile,is_admin=False)
        with patch('iris2.services.user_access_profile',return_value=profile),patch('iris2.services.load_json') as load:
            c=self.client()
            self.assertEqual(c.get('/imports').status_code,403)
            with c.session_transaction() as session:session['csrf_token']='test-csrf'
            self.assertEqual(c.post('/imports',data={'csrf_token':'test-csrf'}).status_code,403)
            load.assert_not_called()
            self.assertFalse(services.user_can(profile,'JSON_IMPORT',edit=True))
            with self.app.test_request_context('/'):
                from flask import g,render_template
                g.current_user=profile
                self.assertNotIn('href="/imports"',render_template('base.html'))
        self.assertEqual(self.app.test_client().get('/imports').status_code,302)

    def test_exchanger_navigation_uses_code_instead_of_asset(self):
        import re
        c=self.client()
        detail=services.exchanger_detail(157)
        asset=detail['master'][1].equipment_code
        code=services.exchanger_display_code(157)
        self.assertNotEqual(asset,code)
        for url in ['/exchangers/157','/exchangers/157/api510','/exchangers/157/report','/exchangers/157/tubes/manage','/exchangers/157/tube-map','/exchangers/157/edit','/exchangers/157/remaining-life-simulation','/q/exchangers/157']:
            with self.subTest(url=url):
                r=c.get(url)
                self.assertEqual(r.status_code,200)
                html=r.get_data(as_text=True)
                headings=re.findall(r'<(?:h1|title)[^>]*>(.*?)</(?:h1|title)>',html,re.S)
                self.assertTrue(any(code in heading for heading in headings))
                self.assertTrue(all(asset not in heading for heading in headings))
        html=c.get('/exchangers/157/edit').get_data(as_text=True)
        self.assertIn('type="hidden" name="equipment_code"',html)
        self.assertIn(asset,html)
        with patch('iris2.services.exchanger_display_code',return_value='열교환기 코드 미등록'):
            html=c.get('/exchangers/157').get_data(as_text=True)
            self.assertIn('<h1>열교환기 코드 미등록</h1>',html)

    def test_no_plugging_information_defaults_to_in_service(self):
        from iris2.domain.tube_status import normalize_tube_status
        self.assertEqual(normalize_tube_status('  '),'IN_SERVICE')
        self.assertEqual(normalize_tube_status(None),'IN_SERVICE')
        self.assertEqual(normalize_tube_status('PLUGGED'),'PLUGGED')
        registered={'tube_id':1,'tube_no':'1','x':0,'y':0,'current_status':'PLUGGED','operational_status':'PLUGGED','category':'PLUGGED'}
        items=services._estimated_circular_layout([registered],4)
        self.assertEqual(next(x for x in items if x.get('tube_id')==1)['operational_status'],'PLUGGED')
        for item in items:
            if item.get('tube_id') is None:
                self.assertEqual(item['operational_status'],'IN_SERVICE')
                self.assertEqual(item['inspection_status'],'NOT_INSPECTED')
                self.assertIsNone(item['minimum_wall_thickness_mm'])
                self.assertFalse(item['managed'])
        payload=self.client().get('/api/exchangers/157/tube-map').get_json()
        self.assertTrue(all(x['operational_status'] in ('IN_SERVICE','PLUGGED') for x in payload['tubes']))
        actual={state:sum(x['operational_status']==state for x in payload['tubes']) for state in ('IN_SERVICE','PLUGGED')}
        self.assertEqual(payload['summary']['operational'],actual)

    def test_api510_settings_selection_and_menu_move(self):
        c=self.client()
        response=c.get('/settings/api510?search=E-104B')
        self.assertEqual(response.status_code,200)
        html=response.get_data(as_text=True)
        self.assertIn('계산 대상 열교환기 선택',html)
        self.assertIn('/exchangers/157/api510',html)
        settings=html.split('id="administrator-settings"',1)[1].split('</details>',1)[0]
        self.assertIn('href="/settings/api510"',settings)
        detail=c.get('/exchangers/157').get_data(as_text=True)
        actions=detail.split('class="exchanger-actions"',1)[1].split('</nav>',1)[0]
        self.assertNotIn('/api510',actions)
        self.assertEqual(self.app.test_client().get('/settings/api510').status_code,302)
        profile=dict(self.profile,is_admin=False,permissions={})
        with patch('iris2.services.user_access_profile',return_value=profile):
            self.assertEqual(self.client().get('/settings/api510').status_code,403)

    def test_pdf_map_241b_matches_source_rows_and_pdf_link(self):
        from collections import Counter
        from iris2.application.pdf_map_display import pdf_vector_display
        data=services.precision_analysis_data(777)
        m=data['tube_map']
        self.assertTrue(m['layout']['pdf_vector_display_applied'])
        self.assertFalse(m['layout']['approved_layout_applied'])
        self.assertEqual([v for _,v in sorted(Counter(x['row'] for x in m['tubes']).items())],[8,11,12,13,12,13,13,12,13,12,11,8])
        self.assertEqual(len(m['tubes']),138)
        measured=[x for x in m['tubes'] if x.get('tube_id')]
        self.assertEqual(len(measured),10)
        self.assertAlmostEqual(next(x['wall_loss_percent'] for x in measured if (x['row'],x['column'])==(6,4)),61.73)
        ys={row:next(t['y'] for t in m['tubes'] if t['row']==row) for row in [5,6,7]}
        self.assertAlmostEqual(ys[7]-ys[6],2*(ys[6]-ys[5]),places=1)
        self.assertEqual(data['selected_detail']['map_pdf_url'],'/inspections/2/pdf#page=20')
        c=self.client()
        r=c.get('/analysis?exchanger_id=777')
        self.assertEqual(r.status_code,200)
        self.assertIn('href="/inspections/2/pdf#page=20"',r.get_data(as_text=True))
        r=c.get('/inspections/2/pdf');self.assertEqual(r.status_code,200);self.assertEqual(r.mimetype,'application/pdf');r.close()
        self.assertIsNone(pdf_vector_display(services.find_inspection_pdf(2)['path'],20,138,'incorrect-hash',measured))

    def test_anonymous_redirected_to_login(self):
        r=self.app.test_client().get('/master-data/data-entry-status')
        self.assertEqual(r.status_code,302)
        self.assertIn('/login',r.location)

if __name__=='__main__': unittest.main()
