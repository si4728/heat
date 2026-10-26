from __future__ import annotations

import unittest

from iris2.ml.anomaly import evaluate_priorities, rank_review_priorities, summarize_quality_detection


def row(result_id, score, loss, flags=()):
    return {"iris_tube_result_id": result_id, "ml_anomaly_score": score, "wall_loss_percent": loss, "review_flags": list(flags)}


class MLAnomalyPriorityTest(unittest.TestCase):
    def test_hard_gate_cannot_be_lowered_by_ml_score(self) -> None:
        ranked = rank_review_priorities([row(1, 999.0, 5), row(2, 0.0, 5, ("FORMULA_RESIDUAL_GT_1PP",))])
        self.assertEqual(ranked[0]["iris_tube_result_id"], 2)
        self.assertTrue(ranked[0]["hard_gate"])

    def test_same_input_produces_stable_ranking(self) -> None:
        rows = [row(2, 0.2, 20), row(1, 0.2, 20), row(3, 0.1, 40)]
        first = [item["iris_tube_result_id"] for item in rank_review_priorities(rows)]
        second = [item["iris_tube_result_id"] for item in rank_review_priorities(rows)]
        self.assertEqual(first, second)

    def test_missing_labels_forces_report_only_pass_with_note(self) -> None:
        ranked = rank_review_priorities([row(1, 0.1, 10)])
        result = evaluate_priorities(ranked)
        self.assertEqual(result["status"], "PASS_WITH_NOTE")
        self.assertFalse(result["automatic_decision_enabled"])

    def test_precision_gate_uses_supported_engineer_labels(self) -> None:
        ranked = rank_review_priorities([row(1, 0.2, 30), row(2, 0.1, 20)])
        result = evaluate_priorities(ranked, {1: "CONFIRMED_SOURCE_ERROR", 2: "VALID_EXTREME_VALUE"})
        self.assertEqual(result["precision_at_30"], 0.5)
        self.assertEqual(result["status"], "HOLD")

    def test_quality_detection_summary_counts_flags_by_unit(self) -> None:
        ranked = rank_review_priorities([
            {**row(1, 0.2, 45), "unit_code": "VCM1", "quality_status": "VALID", "ml_anomaly": True},
            {**row(2, 0.1, 5, ("FORMULA_RESIDUAL_GT_1PP",)), "unit_code": "VCM2", "quality_status": "REVIEW", "ml_anomaly": False},
        ])
        summary = summarize_quality_detection(ranked)
        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(summary["hard_gate_row_count"], 2)
        self.assertEqual(summary["ml_anomaly_row_count"], 1)
        self.assertEqual(summary["unit_counts"]["VCM2"]["hard_gate_rows"], 1)
        self.assertFalse(summary["automatic_engineering_decision_enabled"])


if __name__ == "__main__":
    unittest.main()
