import datetime,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import Column,DateTime,Float,String
from iris2.migration.migrate_all import digest,normalized

class MigrationValueTests(unittest.TestCase):
    def test_timezone_conversion_preserves_instant_and_microseconds(self):
        column=Column('time',DateTime())
        self.assertEqual(normalized('2026-10-17 09:10:11.123456+09:00',column),'2026-10-17 00:10:11.123456')
    def test_comparison_ignores_row_order_preserves_duplicates_and_nulls(self):
        columns=[Column('value',String())]
        self.assertEqual(digest([(None,),('a',)],columns),digest([('a',),(None,)],columns))
        self.assertNotEqual(digest([(None,)],columns),digest([('',)],columns))
        self.assertNotEqual(digest([('a',)],columns),digest([('a',),('a',)],columns))
    def test_double_comparison_retains_small_differences(self):
        columns=[Column('value',Float())]
        self.assertNotEqual(digest([(1.0000000001,)],columns),digest([(1.0000000002,)],columns))
