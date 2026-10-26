"""Command-line entry point for governed ML checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .environment import MissingMLDependencies, require_ml_environment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IRIS governed ML utilities")
    parser.add_argument(
        "command",
        choices=(
            "check-environment",
            "run-pipeline",
            "run-anomaly-quality",
            "run-hotspot-patterns",
        ),
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--verified-tests", type=int, default=0)
    parser.add_argument("--review-database", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run-pipeline":
        if args.database is None or args.artifacts is None or args.verified_tests <= 0:
            parser.error("run-pipeline requires --database, --artifacts, and --verified-tests > 0")
        from .pipeline import run_governed_pipeline
        result = run_governed_pipeline(
            args.database, args.artifacts, verified_test_count=args.verified_tests,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"PASS", "PASS_WITH_NOTE"} else 3
    if args.command == "run-anomaly-quality":
        if args.database is None or args.artifacts is None or args.review_database is None:
            parser.error(
                "run-anomaly-quality requires --database, --artifacts, and --review-database"
            )
        from iris2.hx_configuration import (
            ML_CONTAMINATION,
            ML_ESTIMATORS,
            ML_RANDOM_STATE,
            ML_UNITS,
        )
        from .operations import run_anomaly_quality_operation
        result = run_anomaly_quality_operation(
            args.database,
            args.artifacts,
            args.review_database,
            units=ML_UNITS,
            contamination=ML_CONTAMINATION,
            estimators=ML_ESTIMATORS,
            random_state=ML_RANDOM_STATE,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"PASS", "PASS_WITH_NOTE"} else 3
    if args.command == "run-hotspot-patterns":
        if args.database is None or args.artifacts is None:
            parser.error("run-hotspot-patterns requires --database and --artifacts")
        from .workflow_operations import run_hotspot_pattern_operation
        result = run_hotspot_pattern_operation(args.database, args.artifacts)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"PASS", "PASS_WITH_NOTE"} else 3
    try:
        result = require_ml_environment()
    except MissingMLDependencies as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": "PASS", "command": args.command, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
