from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = APP_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from iris2.pdf_tube_sheet_geometry import (  # noqa: E402
    analysis_rows,
    analyze_all_pdfs,
    persist_analyses,
    summarize_analyses,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze all IRIS PDF Tube Maps and persist versioned geometry evidence."
    )
    parser.add_argument("--database", type=Path, default=APP_DIR / "data" / "heat_exchanger_db3.db")
    parser.add_argument("--data-dir", type=Path, default=APP_DIR / "data")
    parser.add_argument("--pdf-dir", type=Path, default=APP_DIR / "iris_test_report")
    parser.add_argument(
        "--output-dir", type=Path,
        default=APP_DIR / "outputs" / "pdf_tube_sheet_geometry_audit",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    analyses = analyze_all_pdfs(args.data_dir.resolve(), args.pdf_dir.resolve())
    summary = summarize_analyses(analyses)
    summary["database"] = str(args.database.resolve())
    summary["database_write"] = not args.dry_run
    if not args.dry_run:
        summary["persistence"] = persist_analyses(args.database.resolve(), analyses)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = analysis_rows(analyses)
    csv_path = args.output_dir / "tube_sheet_geometry_results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
