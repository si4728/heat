import unittest
from unittest.mock import patch
import test_text_to_sql_web as existing
from iris2.application.text_to_sql_equipment_history import HistoryNotReady


class AdvancedWebTests(unittest.TestCase):
    setUp=existing.TextToSqlWebTests.setUp
    start_patch=existing.TextToSqlWebTests.start_patch
    make_client=existing.TextToSqlWebTests.make_client
    post=existing.TextToSqlWebTests.post

    def permit(self):
        for key in ('EXCHANGERS','REMAINING_LIFE'):
            self.profile['permissions'][key]=dict(can_view=True,can_edit=False)

    def test_advanced_question_uses_equipment_path_even_with_legacy_selector(self):
        self.permit()
        preview=self.post('generate',dict(question='감육속도 0.1 mm/년 이상인 열교환기',result_unit='legacy'))
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(preview.json['query_kind'],'equipment_analysis')
        self.assertEqual(preview.json['settings']['mode'],'rate')
        self.worker.assert_not_called()
        with patch.object(existing.routes.equipment_query,'execute',return_value=dict(rows=[],columns=[],result_count=0)):
            self.assertEqual(self.post('execute',dict(token=preview.json['token']),self.make_client(2)).status_code,403)

    def test_advanced_queries_require_existing_analysis_permissions(self):
        self.assertEqual(self.post('generate',dict(question='감육속도 0.1 mm/년 이상인 열교환기')).status_code,403)
        self.worker.assert_not_called()

    def test_missing_history_permission_has_actionable_safe_503(self):
        self.permit()
        preview=self.post('generate',dict(question='E-106 검사 회차별 감육률과 Plugging 추이',result_unit='equipment'))
        self.assertEqual(preview.status_code,200,preview.json)
        with patch.object(existing.routes.equipment_query,'execute',side_effect=HistoryNotReady('고급 검사 이력 조회 준비가 필요합니다. 관리자에게 문의하세요.')):
            response=self.post('execute',dict(token=preview.json['token']))
        self.assertEqual(response.status_code,503)
        self.assertIn('관리자',response.json['error'])
        self.assertNotIn('GRANT',response.json['error'])


if __name__=='__main__':unittest.main()
