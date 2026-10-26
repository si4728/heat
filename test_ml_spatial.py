from __future__ import annotations

import unittest

from iris2.ml.spatial import score_spatial_hotspots, transform_point, validate_approved_rows


def spatial_row(tube_id, x, y, loss, year=2025):
    return {
        "layout_revision_id": 1, "bundle_id": 1, "tube_id": tube_id,
        "inspection_year": year, "canonical_x": x, "canonical_y": y,
        "wall_loss_percent": loss, "revision_status": "APPROVED",
        "verification_status": "VERIFIED", "mapping_status": "EXISTING_TUBE_MATCH",
        "tube_no": str(tube_id),
    }


class MLSpatialTest(unittest.TestCase):
    def test_rotation_flip_scale_and_offset_transform(self) -> None:
        x, y = transform_point(2, 1, rotation_degrees=90, flip_x=True, scale_x=2, scale_y=3, offset_x=10, offset_y=20)
        self.assertAlmostEqual(x, 7.0, places=7)
        self.assertAlmostEqual(y, 16.0, places=7)

    def test_unapproved_or_unverified_layout_is_rejected(self) -> None:
        for field, value in (("revision_status", "DRAFT"), ("verification_status", "PENDING"), ("mapping_status", "CONFLICT")):
            row = spatial_row(1, 0, 0, 10); row[field] = value
            with self.assertRaises(ValueError):
                validate_approved_rows([row])

    def test_high_tube_is_ranked_with_neighbor_evidence(self) -> None:
        rows = [spatial_row(1, 0, 0, 10), spatial_row(2, 1, 0, 11), spatial_row(3, 0, 1, 12), spatial_row(4, 1, 1, 60)]
        scored = score_spatial_hotspots(rows, neighbors=3)
        hotspot = next(row for row in scored if row["tube_id"] == 4)
        self.assertGreater(hotspot["hotspot_score"], 2.0)
        self.assertEqual(len(hotspot["evidence_tubes"]), 3)
        self.assertEqual(hotspot["change_state"], "NEW")

    def test_groups_never_use_other_year_as_neighbor(self) -> None:
        rows = [spatial_row(1, 0, 0, 10, 2023), spatial_row(2, 1, 0, 10, 2023), spatial_row(3, 0, 1, 10, 2023), spatial_row(1, 0, 0, 50, 2025), spatial_row(2, 1, 0, 10, 2025), spatial_row(3, 0, 1, 10, 2025)]
        scored = score_spatial_hotspots(rows, neighbors=2)
        target = next(row for row in scored if row["tube_id"] == 1 and row["inspection_year"] == 2025)
        self.assertEqual({item["tube_id"] for item in target["evidence_tubes"]}, {2, 3})


if __name__ == "__main__":
    unittest.main()
