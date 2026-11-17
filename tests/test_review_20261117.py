import sys,unittest,json
from pathlib import Path
from datetime import date,datetime
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2 import services
from iris2.domain.measurement_eligibility import exclusion_reason
from iris2.application.equipment_summary import build_equipment_summary,prediction_label


class ReviewRulesTests(unittest.TestCase):
    def test_quality_approval_and_partial_scope_are_explicit(self):
        i=NS(heat_exchanger_id=100,original_equipment_id='E-111(TOPSOUTH)',inspection_date=date(2021,10,27),source_scope_code='TOPSOUTH')
        self.assertEqual(exclusion_reason(i),'PARTIAL_INSPECTION')
        i.heat_exchanger_id=101
        self.assertIsNone(exclusion_reason(i))
        self.assertIsNone(exclusion_reason(i,NS(result_status='VALID',quality_status='USER_APPROVED_211MM_BASIS')))
        self.assertEqual(exclusion_reason(i,NS(result_status='VALID',quality_status='USER_APPROVED_UNKNOWN')),'INVALID_QUALITY')
        self.assertEqual(exclusion_reason(i,as_of=date(2020,1,1)),'FUTURE_INSPECTION')

    def test_explicit_uninspected_and_unknown_ids_never_fall_back(self):
        ranking=dict(rows=[dict(heat_exchanger_id=1,iris_inspection_id=10),dict(heat_exchanger_id=2,iris_inspection_id=None)],units=['VCM1'])
        with patch.object(services,'exchanger_wall_loss_ranking',return_value=ranking),patch.object(services,'exchanger_detail') as detail:
            for identifier,status in [(2,'NO_INSPECTION'),(999,'NOT_AVAILABLE')]:
                result=services.precision_analysis_data(identifier)
                self.assertEqual(result['selected_exchanger_id'],identifier)
                self.assertEqual(result['selection_status'],status)
                self.assertIsNone(result['tube_map'])
            detail.assert_not_called()

    def life(self):
        return dict(status='LIMIT_NOT_REACHED',total_tube_count=100,remaining_life_years=None,
                    tube_projections=[],defect_rows=[],analysis_tube_rows=[])

    def test_sample_reached_overrides_count_without_fabricating_date(self):
        life=self.life();life['sample_wall_loss_estimate']=dict(status='ESTIMATED',sample_count=10,
            twenty_percent_threshold=dict(status='ESTIMATED_REACHED',date=None))
        result=build_equipment_summary(life,date(2026,11,17))
        self.assertEqual(result['remaining_life_years'],0)
        self.assertEqual(result['band'],'short')
        self.assertIsNone(result['target_date'])
        self.assertEqual(life['status'],'LIMIT_NOT_REACHED')
        self.assertEqual(result['target_display'],'검사일 기준 추정상 도달')

    def test_invalid_sample_falls_back_and_thirty_year_calendar_boundary(self):
        for status in ['SAMPLE_INSUFFICIENT','DEGENERATE_SAMPLE','AMBIGUOUS_INSPECTION']:
            life=self.life();life['sample_wall_loss_estimate']=dict(status=status)
            self.assertEqual(build_equipment_summary(life,date(2026,11,17))['basis'],'MEASURED_COUNT')
        self.assertEqual(prediction_label(dict(status='FORECAST',date='2056-11-17'),date(2026,11,17)),'2056년')
        self.assertEqual(prediction_label(dict(status='FORECAST',date='2056-11-18'),date(2026,11,17)),'30년 이상')
        life=self.life();life['sample_wall_loss_estimate']=dict(status='ESTIMATED',twenty_percent_threshold=dict(status='FORECAST',date='2056-11-17'))
        self.assertNotEqual(build_equipment_summary(life,date(2026,11,17))['remaining_display'],'30년 이상')

    def test_real_current_measurements_and_reasons(self):
        life=services.exchanger_detail(100)['remaining_life']
        row=next(r for r in life['analysis_tube_rows'] if r['tube_no']=='14-4')
        self.assertEqual(row['corrosion_measurement_count'],3)
        self.assertLess(row['corrosion_rate_mm_per_year'],.05)
        history=services.precision_tube_histories(100)[str(row['tube_id'])]
        self.assertTrue(any(r['exclusion_reason']=='PARTIAL_INSPECTION' for r in history))
        estimate=services.exchanger_detail(142)['remaining_life']['sample_wall_loss_estimate']
        self.assertEqual(estimate['sample_count'],20)
        self.assertEqual(estimate['status'],'ESTIMATED')
        zero=services.exchanger_detail(122)['remaining_life']
        self.assertEqual(zero['reason_counts']['INVALID_INSTALLATION_DATE'],0)
        self.assertGreater(zero['reason_counts']['NO_POSITIVE_CORROSION_RATE'],0)
        self.assertEqual(services.exchanger_detail(139)['remaining_life']['sample_wall_loss_estimate']['status'],'AMBIGUOUS_INSPECTION')


class UTubeCorrectionTests(unittest.TestCase):
    def test_mismatched_input_aborts_before_any_revision_is_changed(self):
        from iris2.db_config import load_database_config
        from iris2.migration.migrate_all import engine_for
        from iris2.application.utube_correction import correct_counts
        from iris2.iris_v2_models import HeatExchangerSpecRevision as Spec, TubeBundle
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        engine=engine_for(load_database_config(admin=True),'iris2_test_audit_20261113')
        with engine.connect() as connection:
            outer=connection.begin()
            with Session(bind=connection,join_transaction_mode='create_savepoint') as session:
                first=session.scalar(select(Spec).where(Spec.heat_exchanger_id==80,Spec.is_current.is_(True)))
                bad=session.scalar(select(TubeBundle).where(TubeBundle.heat_exchanger_id==103,TubeBundle.retired_at.is_(None)))
                bad.expected_tube_count=999;session.flush()
                with self.assertRaises(ValueError):correct_counts(session,apply=True)
                self.assertTrue(first.is_current)
                self.assertEqual(first.tube_count,18)
            outer.rollback()
        engine.dispose()

    def test_isolated_revision_preservation_idempotence_and_rollback(self):
        from iris2.db_config import load_database_config
        from iris2.migration.migrate_all import engine_for
        from iris2.application.utube_correction import correct_counts,TARGETS
        from iris2.iris_v2_models import HeatExchangerSpecRevision as Spec
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        schema='iris2_test_audit_20261113'
        engine=engine_for(load_database_config(admin=True),schema)
        with engine.connect() as connection:
            outer=connection.begin()
            with Session(bind=connection,join_transaction_mode='create_savepoint') as session:
                before={i:session.scalar(select(Spec).where(Spec.heat_exchanger_id==i,Spec.is_current.is_(True))) for i,*_ in TARGETS}
                original={i:r.tube_count for i,r in before.items()}
                result=correct_counts(session,apply=True)
                session.flush()
                self.assertEqual([r['new_count'] for r in result],[9,46,80])
                for i,old in before.items():
                    current=session.scalar(select(Spec).where(Spec.heat_exchanger_id==i,Spec.is_current.is_(True)))
                    self.assertEqual(old.tube_count,original[i])
                    self.assertFalse(old.is_current)
                    self.assertEqual(len(current.side_specs),len(old.side_specs))
                    for new_side,old_side in zip(sorted(current.side_specs,key=lambda x:x.side_code),sorted(old.side_specs,key=lambda x:x.side_code)):
                        self.assertEqual(new_side.material,old_side.material)
                        self.assertEqual(len(new_side.capacities),len(old_side.capacities))
                self.assertFalse(any(r['changed'] for r in correct_counts(session,apply=True)))
            outer.rollback()
        with Session(engine) as session:
            self.assertEqual({i:session.scalar(select(Spec.tube_count).where(Spec.heat_exchanger_id==i,Spec.is_current.is_(True))) for i,*_ in TARGETS},original)
        engine.dispose()


if __name__=='__main__':unittest.main()
