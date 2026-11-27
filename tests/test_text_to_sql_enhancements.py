from io import BytesIO
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from openpyxl import load_workbook
from iris2.application import text_to_sql_equipment as query
from iris2.application.text_to_sql_export import ExportStore, workbook
from iris2.llm_integration.text_to_sql import QueryRejected
from iris2.tests.test_text_to_sql_web import TextToSqlWebTests


class CompoundTests(unittest.TestCase):
    def test_three_conditions_and_scope_are_preserved(self):
        settings=query.options('VCM1에서 Tube 재질이 Cu-Ni이고 최대 감육률 30% 이상이며 잔여수명 5년 이하인 열교환기 목록')
        self.assertEqual(settings['mode'],'material')
        self.assertEqual(settings['conditions'],[['remaining_life_years','이하',5.0],['maximum_loss','이상',30.0]])
        self.assertIn('잔여수명 5.0년 이하',query.describe(settings))
        for text in ['Tube 재질 Cu-Ni 감육률 30% 이상 또는 잔여수명 5년 이하 열교환기',
                     'Tube 재질 Cu-Ni 감육률 30% 이상 잔여수명 5 열교환기',
                     'Tube 재질 Cu-Ni 평균 감육률 열교환기']:
            with self.subTest(text=text),self.assertRaises(QueryRejected):query.options(text)

    def test_execution_intersects_material_loss_and_life(self):
        class Cursor:
            def __init__(self,rows):self.rows=rows
            def fetchall(self):return self.rows
        class Connection:
            def execute(self,sql,args=()):
                return Cursor([('GRANT SELECT ON iris2.* TO reader',)]) if sql=='SHOW GRANTS' else Cursor([dict(heat_exchanger_id=i) for i in range(1,5)])
            def rollback(self):pass
            def close(self):pass
        def detail(i):
            return dict(spec=SimpleNamespace(tube_material='Cu-Ni' if i!=4 else 'SS'),remaining_life=dict(
                equipment_summary={},analysis_tube_rows=[dict(wall_loss_percent=20 if i==3 else 30)],
                equipment_overview=dict(remaining_life_years=6 if i==2 else 5,remaining_display='5년',source='test',recommendation_date=None)))
        ids=[1,2,3,4]
        with patch.object(query.dbapi,'connect',return_value=Connection()),patch.object(query.services,'exchanger_detail',side_effect=detail),patch('iris2.services.remaining_life_as_of_date',return_value=date(2026,11,27)):
            result=query.execute(ids,query.options('Tube 재질 Cu-Ni 최대 감육률 30% 이상 잔여수명 5년 이하 열교환기'),query.proposal(ids),set(ids))
        self.assertEqual([r['heat_exchanger_id'] for r in result['rows']],[1])


class ExportTests(unittest.TestCase):
    def test_snapshot_owner_expiry_eviction_and_formula_safety(self):
        store=ExportStore()
        result=dict(columns=['equipment_tag','maximum_loss'],rows=[dict(equipment_tag='=HYPERLINK("bad")',maximum_loss=0)],result_count=1)
        key=store.save(1,dict(question='질문'),result)
        result['rows'][0]['maximum_loss']=99
        with self.assertRaises(QueryRejected):store.get(key,2)
        book=load_workbook(workbook(store.get(key,1)))
        sheet=book.active
        self.assertEqual(sheet.cell(10,1).data_type,'s')
        self.assertEqual(sheet.cell(10,2).value,0)
        with patch('iris2.application.text_to_sql_export.monotonic',return_value=10**12):
            with self.assertRaises(QueryRejected):store.get(key,1)
        for i in range(34):store.save(1,{},result)
        self.assertEqual(len(store.entries),32)


class ExportWebTests(TextToSqlWebTests):
    def test_equipment_export_rechecks_remaining_life_permission(self):
        for key in ('EXCHANGERS','REMAINING_LIFE'):
            self.profile['permissions'][key]=dict(can_view=True,can_edit=False)
        preview=self.post('generate',dict(question='열교환기 잔여수명 목록',result_unit='equipment'))
        with patch.object(query,'execute',return_value=dict(columns=['remaining_display'],rows=[],result_count=0)):
            executed=self.post('execute',dict(token=preview.json['token']))
        key=executed.json['result']['export_key']
        self.assertEqual(self.post('export',dict(key=key)).status_code,200)
        self.profile['permissions'].pop('REMAINING_LIFE')
        self.assertEqual(self.post('export',dict(key=key)).status_code,403)

    def test_export_is_snapshot_and_rechecks_owner_scope_csrf_and_permission(self):
        preview=self.generate()
        result=self.post('execute',dict(token=preview.json['token'])).json['result']
        key=result['export_key']
        response=self.post('export',dict(key=key,rows=[{'inspected_tubes':999}]))
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response.headers['Cache-Control'])
        sheet=load_workbook(BytesIO(response.data)).active
        self.assertEqual(sheet.cell(10,1).value,82)
        self.assertEqual(self.post('export',dict(key=key),self.make_client(2)).status_code,400)
        self.assertEqual(self.client.post('/inspections/text-to-sql/export',json=dict(key=key)).status_code,400)
        self.catalog.return_value=[]
        self.assertEqual(self.post('export',dict(key=key)).status_code,403)
        self.catalog.return_value=[self.equipment]
        self.profile['permissions'].pop('TEXT_TO_SQL')
        self.assertEqual(self.post('export',dict(key=key)).status_code,403)
