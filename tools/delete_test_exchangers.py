"""Remove only the two explicitly identified test exchangers, with row backup."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from sqlalchemy import MetaData, select, or_, and_, func
from iris2.database import get_engine

CODES = ('E-LINE-A-001', 'E-TEST-V21')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    metadata = MetaData()
    engine = get_engine()
    metadata.reflect(bind=engine)
    equipment = metadata.tables['equipment']
    hx = metadata.tables['heat_exchanger']
    with engine.begin() as connection:
        roots = [dict(row) for row in connection.execute(select(equipment).where(equipment.c.equipment_code.in_(CODES)).with_for_update()).mappings()]
        if not roots:
            print('No target test equipment remains.')
            return
        if len(roots) != 2 or {row['equipment_code'] for row in roots} != set(CODES):
            raise RuntimeError('Unexpected target set; no deletion performed')
        total_before = connection.scalar(select(func.count()).select_from(hx))
        selected = {'equipment': roots}
        predicates = {}
        for _ in range(len(metadata.tables) + 1):
            changed = False
            for table in metadata.sorted_tables:
                if table.name == 'equipment':
                    continue
                conditions = []
                for constraint in table.foreign_key_constraints:
                    if len(constraint.elements) != 1:
                        raise RuntimeError('Composite foreign key requires explicit review')
                    fk = next(iter(constraint.elements))
                    parents = selected.get(fk.column.table.name, [])
                    values = {row[fk.column.name] for row in parents if row[fk.column.name] is not None}
                    if values:
                        conditions.append(fk.parent.in_(values))
                if not conditions:
                    continue
                predicate = or_(*conditions)
                rows = [dict(row) for row in connection.execute(select(table).where(predicate).with_for_update()).mappings()]
                if len(rows) != len(selected.get(table.name, [])):
                    selected[table.name] = rows
                    predicates[table.name] = predicate
                    changed = True
            if not changed:
                break
        else:
            raise RuntimeError('Dependency traversal did not converge')
        # These records were confirmed to have no real inspection/tube history.
        if selected.get('iris_inspection') or selected.get('heat_exchanger_tube'):
            raise RuntimeError('Inspection/tube history appeared; no deletion performed')
        counts = {name: len(rows) for name, rows in selected.items() if rows}
        if args.apply:
            folder = ROOT / 'reports' / 'deleted_test_exchangers'
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = folder / f'{stamp}_before.json'
            backup.write_text(json.dumps(selected, default=str, ensure_ascii=False, indent=2), encoding='utf-8')
            for table in reversed(metadata.sorted_tables):
                if table.name != 'equipment' and table.name in predicates:
                    connection.execute(table.delete().where(predicates[table.name]))
            connection.execute(equipment.delete().where(equipment.c.equipment_id.in_([row['equipment_id'] for row in roots])))
            total_after = connection.scalar(select(func.count()).select_from(hx))
            if total_after != total_before - 2:
                raise RuntimeError('Unexpected exchanger count after deletion; rolling back')
            for table in metadata.sorted_tables:
                if table.name in predicates and connection.scalar(select(func.count()).select_from(table).where(predicates[table.name])):
                    raise RuntimeError('Target-dependent rows remain; rolling back')
            print(json.dumps({'deleted': counts, 'exchangers_before': total_before, 'exchangers_after': total_after,
                              'backup': str(backup.relative_to(ROOT)), 'verified': True}))
        else:
            print(json.dumps({'targets': [{'code': row['equipment_code'], 'id': row['equipment_id']} for row in roots],
                              'dependent_rows': counts, 'exchangers_before': total_before}))


if __name__ == '__main__':
    main()
