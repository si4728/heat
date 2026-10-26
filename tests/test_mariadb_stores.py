import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2 import dbapi
from iris2.hx_configuration import DB_PATH,ML_REVIEW_DB_PATH
from iris2.ml.readonly_db import readonly_connection
from iris2.ml.datasets import load_cohort_a
from iris2.llm_integration.report_workflow import list_drafts,collect_evidence
from iris2.llm_integration.natural_query import natural_language_search
from iris2.pdf_ocr_review import dashboard_data
from iris2.ml.review_feedback import latest_labels_by_result

class MariaDBStoreTests(unittest.TestCase):
    def test_analysis_account_rejects_writes(self):
        with readonly_connection(DB_PATH) as connection:
            self.assertTrue(connection.readonly)
            with self.assertRaises(dbapi.Error):
                connection.execute("UPDATE equipment SET equipment_name=equipment_name WHERE equipment_id=1")
            connection.rollback()
    def test_operational_dataset_is_complete(self):
        self.assertEqual(len(load_cohort_a(DB_PATH)),6084)
    def test_auxiliary_schemas_are_visible(self):
        self.assertEqual(len(list_drafts()['rows']),5)
        self.assertEqual(len(dashboard_data()['documents']),11)
        self.assertIsInstance(latest_labels_by_result(ML_REVIEW_DB_PATH),dict)
    def test_natural_query_and_evidence(self):
        self.assertGreater(natural_language_search('1104421')['result_count'],0)
        json.dumps(collect_evidence(14),ensure_ascii=False)
    def test_parameter_binding_and_rows(self):
        with dbapi.connect(DB_PATH,readonly=True) as connection:
            row=connection.execute("SELECT ? AS value, '?' AS literal, '100%' AS percent",("x' OR 1=1",)).fetchone()
            self.assertEqual(row[0],"x' OR 1=1")
            self.assertEqual(dict(row)['literal'],'?')
            self.assertEqual(row['percent'],'100%')
    def test_unknown_or_external_selector_rejected(self):
        for selector in ['C:/access/heat/iris/data/heat_exchanger_db3.db',str(Path(DB_PATH).parent/'unknown.db')]:
            with self.assertRaises(ValueError):dbapi.schema_for(selector)
