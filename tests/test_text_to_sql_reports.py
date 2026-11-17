import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_reports as reports
from iris2.llm_integration.text_to_sql import QueryRejected


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.add_url_rule('/inspections/<int:inspection_id>/pdf', 'inspection_pdf_view', lambda inspection_id: '')
        self.context = self.app.test_request_context('/')
        self.context.push(); self.addCleanup(self.context.pop)
        equipment = [dict(heat_exchanger_id=1, equipment_tag='E-111', equipment_code='E111', unit_code='VCM1'),
                     dict(heat_exchanger_id=2, equipment_tag='E-111A', equipment_code='E111A', unit_code='VCM2')]
        rounds = [dict(iris_inspection_id=10, effective_date='2025-10-01', report_number='NEW'),
                  dict(iris_inspection_id=11, effective_date='2023-10-01', report_number='OLD')]
        for target, value in [('analysis.catalog', equipment), ('analysis.inspections', rounds),
                              ('services.find_inspection_pdf', dict(page=44))]:
            p = patch.object(getattr(reports, target.split('.')[0]), target.split('.')[1], return_value=value)
            p.start(); self.addCleanup(p.stop)

    def test_year_and_exact_tag_do_not_match_suffix_equipment(self):
        result = reports.response('E111 2025년 검사 보고서 PDF', {})
        self.assertEqual(len(result['reports']), 1)
        self.assertEqual(result['reports'][0]['url'], '/inspections/10/pdf#page=44')
        self.assertEqual(result['reports'][0]['unit_code'], 'VCM1')

    def test_default_all_history_and_latest(self):
        self.assertEqual(len(reports.response('E-111 보고서', {})['reports']), 2)
        self.assertEqual(len(reports.response('E-111 최근 보고서', {})['reports']), 1)

    def test_prefixed_tag_and_numeric_equipment_code(self):
        with patch.object(reports.analysis, 'catalog', return_value=[dict(heat_exchanger_id=1, equipment_tag='US-VC-E-111', equipment_code='1102116', unit_code='VCM1')]):
            for question in ['E-111 검사 보고서', 'US-VC-E-111 검사 보고서', '1102116 검사 보고서']:
                self.assertEqual(len(reports.response(question, {})['reports']), 2)

    def test_selected_round_belongs_to_equipment(self):
        self.assertEqual(reports.response('검사 보고서', dict(exchanger_ids=[1], inspection_id=11))['reports'][0]['url'], '/inspections/11/pdf#page=44')
        with self.assertRaises(QueryRejected):
            reports.response('검사 보고서', dict(exchanger_ids=[1], inspection_id=999))

    def test_missing_pdf_and_unmapped_page(self):
        with patch.object(reports.services, 'find_inspection_pdf', return_value=None):
            result = reports.response('E-111 최근 보고서', {})
            self.assertEqual(result['reports'], [])
            self.assertEqual(result['missing_count'], 1)
        with patch.object(reports.services, 'find_inspection_pdf', return_value=dict(page=None)):
            result = reports.response('E-111 최근 보고서', {})
            self.assertEqual(result['reports'][0]['url'], '/inspections/10/pdf')

    def test_unsupported_or_conflicting_scope_and_invalid_ids(self):
        for question, data in [('VCM3 보고서', {}), ('E-999 보고서', {}),
                               ('E-111 보고서', dict(exchanger_ids=[2])),
                               ('검사 보고서', {}), ('검사 보고서', dict(exchanger_ids=[True])),
                               ('E-111 보고서', dict(unit_codes=['VCM2']))]:
            with self.subTest(question=question, data=data), self.assertRaises(QueryRejected):
                reports.response(question, data)
        with self.assertRaises(PermissionError):
            reports.response('검사 보고서', dict(exchanger_ids=[999]))

    def test_pdf_requests_do_not_capture_analytic_questions(self):
        self.assertTrue(reports.matches('E-111 IRIS 검사 보고서 보여줘'))
        self.assertFalse(reports.matches('2025년 검사 보고서 감육률 요약'))


if __name__ == '__main__':
    unittest.main()
