from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path, PureWindowsPath


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_sources(value: str) -> list[str]:
    return [item.strip() for item in value.split(" | ") if item.strip()]


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    result = json.loads((review_dir / "rollout_draft_apply_result.json").read_text(encoding="utf-8"))
    revision_ids = [int(value) for value in result["staged_revision_ids"]]
    source_root = Path(r"C:\access\hanhwa\IRIS2_DATA")

    classifications = read_csv(review_dir / "rollout_candidate_classification.csv")
    selected = [row for row in classifications if row["classification"] == "AUTO_APPROVAL_CANDIDATE"]
    revision_manifest = {row["source_path"]: row for row in read_csv(review_dir / "layout_revisions.csv")}
    point_manifest = read_csv(review_dir / "tube_layout_candidates.csv")

    connection = sqlite3.connect(
        (workspace / "data" / "heat_exchanger_db3.db").resolve().as_uri() + "?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    errors: list[str] = []
    try:
        placeholders = ",".join("?" for _ in revision_ids)
        db_revisions = connection.execute(
            f"SELECT * FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders})",
            revision_ids,
        ).fetchall()
        if len(db_revisions) != 52:
            errors.append(f"revision count: {len(db_revisions)} != 52")
        selected_paths = {row["source_path"] for row in selected}
        if {row["source_path"] for row in db_revisions} != selected_paths:
            errors.append("database revision paths differ from the approved candidate manifest")

        expected_by_bundle = {
            int(item["bundle_id"]): {
                (int(point["row"]), int(point["column"])): point
                for point in point_manifest
                if int(point["bundle_id"]) == int(item["bundle_id"])
            }
            for item in selected
        }
        checked_points = 0
        for db_revision in db_revisions:
            source_path = str(db_revision["source_path"])
            manifest = revision_manifest[source_path]
            if db_revision["revision_status"] != "DRAFT":
                errors.append(f"{source_path}: status is not DRAFT")
            if db_revision["rotation_degrees"] is not None:
                errors.append(f"{source_path}: rotation was set before operational approval")
            physical = source_root.joinpath(*PureWindowsPath(source_path).parts)
            if not physical.is_file() or sha256(physical) != db_revision["source_checksum"]:
                errors.append(f"{source_path}: source checksum mismatch")

            points = connection.execute(
                "SELECT * FROM tube_layout_point WHERE layout_revision_id=?",
                (db_revision["layout_revision_id"],),
            ).fetchall()
            expected = expected_by_bundle[int(db_revision["bundle_id"])]
            if len(points) != len(expected) or len(points) != int(manifest["source_tube_count"]):
                errors.append(f"{source_path}: point count mismatch")
            for point in points:
                checked_points += 1
                key = (int(point["source_row"]), int(point["source_column"]))
                candidate = expected.get(key)
                if candidate is None:
                    errors.append(f"{source_path}: unexpected point {key}")
                    continue
                expected_tube_id = int(candidate["existing_tube_id"]) if candidate["existing_tube_id"] else None
                actual = (
                    float(point["source_x"]), float(point["source_y"]), point["tube_id"],
                    point["mapping_status"], point["verification_status"],
                    point["canonical_x"], point["canonical_y"],
                )
                wanted = (
                    float(candidate["source_x"]), float(candidate["source_y"]), expected_tube_id,
                    candidate["mapping_status"], "PENDING", None, None,
                )
                if actual != wanted:
                    errors.append(f"{source_path}: point mismatch {key}")

        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        approved_count = connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
        ).fetchone()[0]
        tube_count = connection.execute("SELECT count(*) FROM heat_exchanger_tube").fetchone()[0]
        tube_xy_count = connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL AND position_y IS NOT NULL"
        ).fetchone()[0]
    finally:
        connection.close()

    verification = {
        "status": "PASS" if not errors else "FAIL",
        "checked_revision_count": len(revision_ids),
        "checked_point_count": checked_points,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "approved_revision_count": approved_count,
        "tube_count": tube_count,
        "tube_xy_count": tube_xy_count,
        "errors": errors[:100],
        "database_mode": "READ_ONLY",
        "database_changes": 0,
    }
    if quick_check != "ok" or foreign_key_issues or approved_count != 3 or tube_count != 2253 or tube_xy_count != 0:
        verification["status"] = "FAIL"
    output = review_dir / "rollout_draft_verification.json"
    output.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    return 0 if verification["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
