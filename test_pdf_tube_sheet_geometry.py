from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from iris2.pdf_tube_sheet_geometry import _classify_shape, convex_hull, polygon_area
from iris2.iris_v2_database import create_v2_engine, init_v2_db
from iris2.services import _estimated_circular_layout


class PdfTubeSheetGeometryTest(unittest.TestCase):
    def test_convex_hull_and_area(self):
        points = [(0, 0), (2, 0), (2, 1), (0, 1), (1, 0.5)]
        hull = convex_hull(points)
        self.assertEqual(len(hull), 4)
        self.assertAlmostEqual(polygon_area(hull), 2.0)

    def test_classifies_rectangular_grid(self):
        points = [(float(x), float(y)) for x in range(8) for y in range(5)]
        result = _classify_shape(points)
        self.assertEqual(result["shape_code"], "RECTANGULAR")
        self.assertGreater(result["confidence"], 0.8)

    def test_classifies_circular_population(self):
        points = [
            (float(x), float(y))
            for x in range(-5, 6)
            for y in range(-5, 6)
            if x * x + y * y <= 25
        ]
        result = _classify_shape(points)
        self.assertEqual(result["shape_code"], "CIRCULAR")
        self.assertGreater(result["confidence"], 0.8)

    def test_database_initialization_creates_geometry_revision_table(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "geometry.db"
            init_v2_db(database)
            engine = create_v2_engine(database)
            try:
                self.assertIn("tube_sheet_geometry_revision", inspect(engine).get_table_names())
                columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("tube_sheet_geometry_revision")
                }
                self.assertTrue({
                    "shape_code", "boundary_geometry_json", "source_pdf_sha256",
                    "consensus_shape_code", "cross_year_consistent",
                } <= columns)
            finally:
                engine.dispose()

    def test_estimated_layout_uses_registered_shape(self):
        rectangular = _estimated_circular_layout([], 25, shape_code="RECTANGULAR")
        elliptical = _estimated_circular_layout(
            [], 25, shape_code="ELLIPTICAL", width_height_ratio=2.0
        )
        self.assertEqual(len(rectangular), 25)
        self.assertEqual(len({row["x"] for row in rectangular}), 5)
        self.assertEqual(len({row["y"] for row in rectangular}), 5)
        ellipse_width = max(row["x"] for row in elliptical) - min(row["x"] for row in elliptical)
        ellipse_height = max(row["y"] for row in elliptical) - min(row["y"] for row in elliptical)
        self.assertGreater(ellipse_width, ellipse_height)


if __name__ == "__main__":
    unittest.main()
