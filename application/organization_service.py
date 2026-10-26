from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..hx_configuration import DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import Equipment, OrganizationCode, Plant, ProcessUnit

KINDS = {"PLANT": "공장", "TEAM": "생산팀", "PROCESS": "공정"}


def seed_organization_codes(session) -> None:
    """Add missing codes from existing masters without overwriting edited labels."""
    existing = {(r.parent_id, r.code): r for r in session.scalars(select(OrganizationCode))}

    def ensure(kind, code, parent_id, label):
        key = (parent_id, code)
        row = existing.get(key)
        if row is None:
            row = OrganizationCode(kind=kind, code=code, parent_id=parent_id, label=label)
            session.add(row)
            session.flush()
            existing[key] = row
        return row

    roots = {}
    for plant in session.scalars(select(Plant)):
        label = "울산공장" if plant.plant_code == "P1" else plant.plant_name
        root = ensure("PLANT", plant.plant_code, None, label)
        roots[plant.plant_id] = root
        plant.plant_name = root.label
    for equipment, unit in session.execute(
        select(Equipment, ProcessUnit).join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
    ):
        if not equipment.production_team_code:
            continue
        root = roots[unit.plant_id]
        team = ensure("TEAM", equipment.production_team_code, root.organization_code_id,
                      f"{equipment.production_team_code} 생산팀")
        if equipment.process_code:
            ensure("PROCESS", equipment.process_code, team.organization_code_id, equipment.process_code)


def organization_catalog() -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        nodes = list(session.scalars(select(OrganizationCode).order_by(OrganizationCode.code)))
        equipment_rows = session.execute(
            select(Equipment, ProcessUnit, Plant)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
        ).all()
        by_id = {n.organization_code_id: n for n in nodes}
        labels = {}
        entries = []
        for node in nodes:
            parent = by_id.get(node.parent_id)
            root = node if node.kind == "PLANT" else parent if node.kind == "TEAM" else by_id[parent.parent_id]
            team_code = parent.code if node.kind == "PROCESS" else ""
            labels[(node.kind, root.code, team_code, node.code)] = node.label
            count = sum(
                1 for e, u, p in equipment_rows if p.plant_code == root.code
                and (node.kind == "PLANT" or e.production_team_code == (node.code if node.kind == "TEAM" else team_code))
                and (node.kind != "PROCESS" or e.process_code == node.code)
            )
            path = root.label if node.kind == "TEAM" else f"{root.label} / {parent.label}" if parent else "-"
            entries.append({"node": node, "parent_label": path, "plant_code": root.code,
                            "team_code": team_code, "equipment_count": count})
        entries.sort(key=lambda r: (r["plant_code"], {"PLANT": 0, "TEAM": 1, "PROCESS": 2}[r["node"].kind], r["team_code"], r["node"].code))
        return {"entries": entries, "labels": labels, "kinds": KINDS,
                "parents": [e for e in entries if e["node"].kind != "PROCESS"]}


def save_organization_code(data: dict[str, Any], code_id: int | None = None) -> int:
    label = str(data.get("label") or "").strip()
    description = str(data.get("description") or "").strip()
    if not label or len(label) > 200:
        raise ValueError("Label(설명)은 1~200자로 입력해 주세요.")
    if len(description) > 2000:
        raise ValueError("상세 설명은 2,000자 이하로 입력해 주세요.")
    try:
        with session_scope(DB_PATH) as session:
            if code_id:
                node = session.get(OrganizationCode, code_id)
                if node is None:
                    raise ValueError("수정할 코드를 찾을 수 없습니다.")
                # Identity and parent are immutable; labels can be changed safely.
            else:
                kind = str(data.get("kind") or "")
                code = str(data.get("code") or "").strip()
                if kind not in KINDS or not code or len(code) > 100:
                    raise ValueError("구분과 코드(1~100자)를 확인해 주세요.")
                raw_parent = str(data.get("parent_id") or "").strip()
                if raw_parent and not raw_parent.isdigit():
                    raise ValueError("상위 코드를 선택해 주세요.")
                parent_id = int(raw_parent) if raw_parent else None
                if kind == "PLANT":
                    if parent_id is not None or not re.fullmatch(r"P[1-9][0-9]*", code):
                        raise ValueError("공장은 상위 코드 없이 P1, P2 형식으로 입력해 주세요.")
                else:
                    parent = session.get(OrganizationCode, parent_id) if parent_id else None
                    if not parent or parent.kind != {"TEAM": "PLANT", "PROCESS": "TEAM"}[kind]:
                        raise ValueError("생산팀은 공장, 공정은 생산팀을 상위 코드로 선택해 주세요.")
                conflict = session.scalar(select(OrganizationCode).where(
                    OrganizationCode.parent_id == parent_id, OrganizationCode.code == code))
                if conflict:
                    raise ValueError("동일 상위 조직에 이미 등록된 코드입니다.")
                node = OrganizationCode(kind=kind, code=code, parent_id=parent_id)
                session.add(node)
            node.label = label
            node.description = description or None
            if node.kind == "PLANT":
                plant = session.scalar(select(Plant).where(Plant.plant_code == node.code))
                if plant is None:
                    plant = Plant(plant_code=node.code, plant_name=label)
                    session.add(plant)
                plant.plant_name = label
            session.flush()
            return node.organization_code_id
    except IntegrityError as exc:
        raise ValueError("중복 코드 또는 유효하지 않은 상위 코드입니다.") from exc
