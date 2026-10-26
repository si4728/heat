"""Apply equipment installation dates to every VCM1/VCM2 tube lifecycle."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from sqlalchemy import text
from iris2.database import get_engine

QUERY = """
SELECT t.tube_id, t.installed_at, e.install_date, e.equipment_code, u.unit_code
FROM heat_exchanger_tube t
JOIN tube_bundle b ON b.bundle_id=t.bundle_id
JOIN heat_exchanger h ON h.heat_exchanger_id=b.heat_exchanger_id
JOIN equipment e ON e.equipment_id=h.equipment_id
JOIN process_unit u ON u.unit_id=e.unit_id
WHERE u.unit_code IN ('VCM1','VCM2')
ORDER BY t.tube_id
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with get_engine().begin() as connection:
        rows = [dict(row) for row in connection.execute(text(QUERY + (' FOR UPDATE' if args.apply else ''))).mappings()]
        changes = [r for r in rows if r['install_date'] is not None and r['installed_at'] != r['install_date']]
        summary = dict(scope=['VCM1', 'VCM2'], tubes=len(rows), changes=len(changes),
                       missing_equipment_date=sum(r['install_date'] is None for r in rows),
                       overwritten_existing_dates=sum(r['installed_at'] is not None for r in changes))
        if args.apply and changes:
            report_dir = ROOT / 'reports' / 'tube_installation_dates'
            report_dir.mkdir(parents=True, exist_ok=True)
            backup = report_dir / f'{stamp}_before.json'
            backup.write_text(json.dumps({'summary': summary, 'rows': rows}, default=str, ensure_ascii=False, indent=2), encoding='utf-8')
            connection.execute(text('UPDATE heat_exchanger_tube SET installed_at=:install_date WHERE tube_id=:tube_id'),
                               [{'tube_id': r['tube_id'], 'install_date': r['install_date']} for r in changes])
            verified = [dict(r) for r in connection.execute(text(QUERY)).mappings()]
            if len(verified) != len(rows) or any(r['installed_at'] != r['install_date'] for r in verified if r['install_date'] is not None):
                raise RuntimeError('Verification failed; transaction rolled back')
            summary['backup'] = str(backup.relative_to(ROOT))
            summary['verified'] = True
        summary['applied'] = args.apply
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
