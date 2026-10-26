"""Run the Stage 2 anomaly-quality operation with project configuration."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from iris2.hx_configuration import (  # noqa: E402
    DB_PATH,
    ML_ARTIFACT_ROOT,
    ML_CONTAMINATION,
    ML_ESTIMATORS,
    ML_RANDOM_STATE,
    ML_REVIEW_DB_PATH,
    ML_UNITS,
)
from iris2.ml.operations import run_anomaly_quality_operation  # noqa: E402


def main() -> int:
    result = run_anomaly_quality_operation(
        DB_PATH,
        ML_ARTIFACT_ROOT,
        ML_REVIEW_DB_PATH,
        units=ML_UNITS,
        contamination=ML_CONTAMINATION,
        estimators=ML_ESTIMATORS,
        random_state=ML_RANDOM_STATE,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "PASS_WITH_NOTE"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
