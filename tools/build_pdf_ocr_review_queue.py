from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(APP_DIR.parent))

from iris2.pdf_ocr_review import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PDF_DIR,
    REVIEW_DB_PATH,
    build_review_queue,
)
from iris2.hx_configuration import DB_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="5단계 PDF/OCR 검토 큐 생성")
    parser.add_argument("--database", type=Path, default=DB_PATH)
    parser.add_argument("--review-database", type=Path, default=REVIEW_DB_PATH)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    summary = build_review_queue(
        operational_db=args.database,
        review_db=args.review_database,
        pdf_dir=args.pdf_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "documents"}, ensure_ascii=False, indent=2))
    return 0 if summary["ocr_required_page_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
