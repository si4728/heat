import re
import unittest
from . import test_ui_usability


class MenuCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_ui_usability.UiTemplateTests.setUpClass()
        cls.fixture=test_ui_usability.UiTemplateTests()
        cls.app=cls.fixture.app

    def dashboard_fixture(self,admin=False):
        return self.fixture.dashboard_fixture(admin=admin)

    def test_five_general_entries_match_customer_figure(self):
        html=self.dashboard_fixture(admin=True)
        nav=html.split('id="general-navigation">',1)[1].split('</nav>',1)[0]
        # Submenu entries are children of the single inspection-history entry.
        top=re.sub(r'<details.*?</details>','',nav,flags=re.S)
        self.assertEqual(len(re.findall(r'<a\b',top)),4)
        self.assertEqual(nav.count('<summary>검사 이력</summary>'),1)
        for text in ['대시보드','열교환기 목록','열교환기 분석','검사계획','연도별','공정별']:
            self.assertIn(text,nav)
        for text in ['JSON','사용자·권한','백업','Text-to-SQL','정비 관리','기본 설정','Excel']:
            self.assertNotIn(text,nav)

    def test_admin_settings_is_in_topbar_only_for_administrator(self):
        html=self.dashboard_fixture(admin=True)
        topbar=html.split('<header class="topbar">',1)[1].split('</header>',1)[0]
        for text in ['관리자 설정','JSON 로드','PDF·OCR 검토','사용자·권한 관리','백업 관리']:
            self.assertIn(text,topbar)
        ordinary=self.dashboard_fixture(admin=False)
        self.assertNotIn('id="administrator-settings"',ordinary)
        self.assertIn('/settings/preferences', ordinary)

    def test_partial_permissions_hide_general_entries(self):
        with self.app.test_request_context('/'):
            html=self.app.jinja_env.get_template('general_navigation.html').render(
                can_screen=lambda key,*args:key=='INSPECTIONS')
        self.assertNotIn('열교환기 목록',html)
        self.assertNotIn('열교환기 분석',html)
        self.assertIn('검사 이력',html)
        self.assertIn('검사계획',html)


if __name__=='__main__':
    unittest.main()
