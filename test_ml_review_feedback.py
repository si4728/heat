from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iris2.ml.review_feedback import (
    evaluate_expert_feedback,
    latest_review_feedback,
    save_review_feedback,
)


def _rows(count: int = 30) -> list[dict]:
    return [
        {"iris_tube_result_id": index, "review_priority_rank": index}
        for index in range(1, count + 1)
    ]


class MLReviewFeedbackTest(unittest.TestCase):
    def test_feedback_is_append_only_and_latest_label_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database = Path(name) / "feedback.db"
            common = {
                "run_id": "run-1", "model_version": "model-1",
                "iris_tube_result_id": 1, "iris_inspection_id": 2, "tube_id": 3,
                "reviewer_user_id": 4, "reviewer_name": "expert",
            }
            first_id = save_review_feedback(
                database, **common, label="INSUFFICIENT_EVIDENCE", note="원본 확인 전"
            )
            second_id = save_review_feedback(
                database, **common, label="CONFIRMED_SOURCE_ERROR", note="원본 보고서와 불일치"
            )
            latest = latest_review_feedback(database, "run-1")
            self.assertGreater(second_id, first_id)
            self.assertEqual(latest[1]["label"], "CONFIRMED_SOURCE_ERROR")
            self.assertEqual(latest[1]["note"], "원본 보고서와 불일치")

    def test_feedback_requires_a_reason(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(ValueError, "판단 근거"):
                save_review_feedback(
                    Path(name) / "feedback.db", run_id="run-1", model_version="model-1",
                    iris_tube_result_id=1, iris_inspection_id=2, tube_id=3,
                    label="RECHECK_REQUIRED", note="", reviewer_name="expert",
                )

    def test_evaluation_collects_until_all_top_30_are_reviewed(self) -> None:
        feedback = {
            index: {"label": "CONFIRMED_SOURCE_ERROR"}
            for index in range(1, 30)
        }
        result = evaluate_expert_feedback(_rows(), feedback)
        self.assertEqual(result["status"], "COLLECTING")
        self.assertEqual(result["reviewed_top30_count"], 29)

    def test_evaluation_passes_at_sixty_percent_without_hard_gate_omission(self) -> None:
        feedback = {
            index: {"label": "CONFIRMED_SOURCE_ERROR" if index <= 18 else "VALID_EXTREME_VALUE"}
            for index in range(1, 31)
        }
        result = evaluate_expert_feedback(_rows(), feedback)
        self.assertEqual(result["status"], "PASS")
        self.assertAlmostEqual(result["precision_at_30_reviewed"], 0.6)
        self.assertFalse(result["automatic_decision_enabled"])

    def test_evaluation_holds_when_hard_gate_has_critical_omission(self) -> None:
        feedback = {
            index: {"label": "CONFIRMED_SOURCE_ERROR"}
            for index in range(1, 31)
        }
        result = evaluate_expert_feedback(_rows(), feedback, hard_gate_critical_omissions=1)
        self.assertEqual(result["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
