"""Run the Stage 3 Hotspot and degradation-pattern review operation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from iris2.hx_configuration import DB_PATH, ML_ARTIFACT_ROOT  # noqa: E402
from iris2.ml.workflow_operations import run_hotspot_pattern_operation  # noqa: E402


def main() -> int:
    result = run_hotspot_pattern_operation(DB_PATH, ML_ARTIFACT_ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "PASS_WITH_NOTE"} else 3


if __name__ == "__main__":
    raise SystemExit(main())

