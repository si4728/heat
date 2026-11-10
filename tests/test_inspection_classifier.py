"""Leakage, identity and evaluation-boundary regressions for offline classifier."""
import tempfile
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from iris2.ml.inspection_classifier import (
    FEATURES, EXCLUDED, asset_key, parse_install_date, service_role,
    family_group, unit_from_master_tag, matrix, make_model, predict_records, grouped_splits, collect,
)

class FakeSheet:
    title='master'; max_column=9
    def __init__(self, rows):self.rows=rows
    def iter_rows(self, **kwargs):return iter(self.rows)

class FakeBook:
    sheetnames=['master']
    def __init__(self, rows):self.active=FakeSheet(rows)
    def close(self):pass

class InspectionClassifierTest(unittest.TestCase):
    def test_feature_contract_and_post_inspection_exclusion(self):
        self.assertEqual(FEATURES,('installation_year','unit_code','process_code','service_role'))
        self.assertIn('tube_nominal_thickness_mm',EXCLUDED)
        self.assertIn('tube_material',EXCLUDED)
        self.assertNotIn('inspection_count',FEATURES)

    def test_normalization_dates_role_and_sibling_group(self):
        self.assertEqual(asset_key(110044.0),'110044')
        self.assertEqual(parse_install_date('1990-10-03'),date(1990,10,3))
        with self.assertRaises(ValueError):parse_install_date('unknown')
        self.assertEqual(service_role('T-100 REBOILER'),'REBOILER')
        self.assertEqual(service_role('E-320'),'OTHER')
        self.assertEqual(family_group('VCM2','E-201A'),family_group('VCM2','E-201B(Spare)'))
        self.assertNotEqual(family_group('VCM1','E-201A'),family_group('VCM2','E-201A'))
        self.assertEqual(unit_from_master_tag('US-VC-E-103'),'VCM1')
        self.assertEqual(unit_from_master_tag('US-EV-E-106'),'VCM2')
        with self.assertRaises(ValueError):unit_from_master_tag('UNKNOWN-E-103')

    def test_features_use_excel_not_conflicting_db_or_json_values(self):
        header=['No.','상태','설비코드','생산팀','공정','설비Tag','Item No.','설비내역','설치일']
        source=[header,header,[1,None,100,'VCM','VCM(VCM1)','US-VC-E-201A','E-201A','COOLER','1990-10-03']]
        db=[{'heat_exchanger_id':1,'equipment_code':'100','unit_code':'VCM2','inspection_count':1,
             'install_date':'2025-01-01','process_code':'JSON_PROCESS','tube_nominal_thickness_mm':999}]
        with patch('openpyxl.load_workbook',return_value=FakeBook(source)):
            rows,_,audit=collect('unused',db,date(2026,10,30))
        self.assertEqual(rows[0]['unit_code'],'VCM1')
        self.assertEqual(rows[0]['installation_year'],1990)
        self.assertEqual(rows[0]['process_code'],'VCM(VCM1)')
        self.assertEqual(audit[5]['decision'],'DERIVE_UNIT_ONLY')
        source[2][5]='UNKNOWN'
        with patch('openpyxl.load_workbook',return_value=FakeBook(source)):
            rows,rejected,_=collect('unused',db,date(2026,10,30))
        self.assertEqual(rows,[])
        self.assertEqual(rejected[0]['reason'],'MASTER_TAG_UNIT_UNMAPPED')

    def test_source_matching_invalid_future_and_duplicate_keys(self):
        header=['No.','상태','설비코드','생산팀','공정','설비Tag','Item No.','설비내역','설치일']
        source=[header,header,[1,None,100,'VCM','VCM(VCM1)','US-VC-E-201A','E-201A','COOLER','1990-10-03'],
                [2,None,101,'VCM','EDC','US-EV-E-202','E-202','HEATER','2030-01-01']]
        db=[{'heat_exchanger_id':1,'equipment_code':'100','unit_code':'VCM1','inspection_count':1,'install_date':'1990-10-03'},
            {'heat_exchanger_id':2,'equipment_code':'101','unit_code':'VCM2','inspection_count':0,'install_date':'2030-01-01'}]
        with patch('openpyxl.load_workbook',return_value=FakeBook(source)):
            rows,rejected,audit=collect('unused',db,date(2026,10,29))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['source_row'],3)
        self.assertEqual(rejected[0]['reason'],'INSTALL_DATE_OUT_OF_RANGE')
        self.assertEqual(audit[8]['decision'],'INCLUDE_YEAR_ONLY')
        with patch('openpyxl.load_workbook',return_value=FakeBook(source+[source[2]])):
            rows,rejected,_=collect('unused',db[:1],date(2026,10,29))
        self.assertEqual(rows,[]);self.assertEqual(rejected[0]['reason'],'SOURCE_KEY_MISSING_OR_DUPLICATED')

    def test_grouped_folds_no_family_or_record_leakage(self):
        rows=[]
        for i in range(40):
            for j in range(2):
                rows.append({'installation_year':1970+i,'unit_code':'VCM1','process_code':'VCM1',
                             'service_role':'COOLER','family_group':f'family-{i}','inspected':(i+j)%2})
        splits=grouped_splits(rows,42);tested=[]
        for train,test in splits:
            self.assertFalse({rows[i]['family_group'] for i in train}&{rows[i]['family_group'] for i in test})
            tested.extend(test)
        self.assertEqual(sorted(tested),list(range(len(rows))))

    def test_model_ignores_thickness_and_target_fields_and_accepts_new_category(self):
        import numpy as np
        rows=[{'installation_year':1990+i,'unit_code':'VCM1','process_code':'EDC',
               'service_role':'COOLER' if i%2 else 'HEATER','inspected':i%2} for i in range(12)]
        model=make_model('logistic');model.fit(matrix(rows),np.array([r['inspected'] for r in rows]))
        bundle={'features':list(FEATURES),'model':model}
        changed=[{**r,'tube_nominal_thickness_mm':999,'wall_loss_percent':100,'inspected':1-r['inspected']} for r in rows]
        np.testing.assert_array_equal(predict_records(bundle,rows),predict_records(bundle,changed))
        unknown=[{**rows[0],'process_code':'NEW_PROCESS','service_role':'NEW_ROLE'}]
        self.assertTrue(0<=predict_records(bundle,unknown)[0]<=1)
        with self.assertRaises(ValueError):predict_records({'features':['wall_loss_percent'],'model':model},rows)

if __name__=='__main__':unittest.main()
