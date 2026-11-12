"""Read-only real-model / MariaDB acceptance checks for the pilot."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import dbapi
from iris2.hx_configuration import DB_PATH
from iris2.llm_integration.local_llm import LocalLlmClient
from iris2.llm_integration.model_config import load_local_runtime_config
from iris2.llm_integration.text_to_sql import generate_proposal, validate_proposal, execute_proposal, QueryRejected


def main():
    connection = dbapi.connect(DB_PATH, readonly=True, readonly_profile='text_to_sql')
    try:
        sample = connection.execute("""SELECT i.heat_exchanger_id, i.iris_inspection_id,
            COUNT(*) AS result_count FROM iris_inspection i
            JOIN iris_tube_result r ON r.iris_inspection_id=i.iris_inspection_id
            JOIN heat_exchanger hx ON hx.heat_exchanger_id=i.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=hx.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code IN ('VCM1','VCM2') AND i.superseded_by_inspection_id IS NULL
            GROUP BY i.heat_exchanger_id, i.iris_inspection_id
            ORDER BY result_count DESC, i.iris_inspection_id DESC LIMIT 1""").fetchone()
        if not sample:
            raise RuntimeError('No inspected VCM1/VCM2 sample')
        exchanger_id, inspection_id = sample['heat_exchanger_id'], sample['iris_inspection_id']
        summary = dict(connection.execute("""SELECT COUNT(*) AS inspected_tubes,
            COUNT(wall_loss_percent) AS valid_loss_tubes,
            MIN(minimum_wall_thickness_mm) AS minimum_mm,
            MAX(wall_loss_percent) AS maximum_loss,
            AVG(wall_loss_percent) AS average_loss FROM iris_tube_result
            WHERE iris_inspection_id=?""", (inspection_id,)).fetchone())
        top = [dict(r) for r in connection.execute("""SELECT tube_id, source_tube_id,
            minimum_wall_thickness_mm, wall_loss_percent, location_mm,
            iris_tube_result_id, source_page FROM iris_tube_result
            WHERE iris_inspection_id=? AND wall_loss_percent IS NOT NULL
            ORDER BY wall_loss_percent DESC, tube_id ASC LIMIT 5""", (inspection_id,)).fetchall()]
        threshold = [r[0] for r in connection.execute("""SELECT tube_id FROM iris_tube_result
            WHERE iris_inspection_id=? AND wall_loss_percent >= ?
            ORDER BY wall_loss_percent DESC, tube_id ASC LIMIT 100""", (inspection_id, 30)).fetchall()]
    finally:
        connection.rollback()
        connection.close()
    client = LocalLlmClient(load_local_runtime_config(ROOT/'llm_integration/models.local.json'))
    cases = [
        ('summary', '선택한 설비의 선택한 IRIS 검사 결과를 요약해 줘.'),
        ('top5', '선택한 설비에서 감육이 가장 심한 Tube 5개를 알려줘.'),
        ('threshold', '선택한 설비에서 감육률 30% 이상인 Tube를 보여줘.'),
        ('unsupported', '선택한 설비의 잔여수명을 계산해 줘.'),
    ]
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'sample': dict(sample), 'cases': []}
    try:
        for kind, question in cases:
            started = time.monotonic()
            item = {'kind': kind, 'question': question}
            try:
                proposal = generate_proposal(question, client)
                item['proposal'] = proposal
                validate_proposal(proposal)
                result = execute_proposal(proposal, exchanger_id=exchanger_id,
                    inspection_id=inspection_id, authorized_exchanger_ids={exchanger_id})
                item['result'] = result
                rows = result['rows']
                if kind == 'summary':
                    item['passed'] = rows == [summary]
                elif kind == 'top5':
                    # Detail results include server-attached equipment identity.
                    item['passed'] = (
                        [{key: row.get(key) for key in expected} for row, expected in zip(rows, top)] == top
                        and len(rows) == len(top)
                        and all(row.get('heat_exchanger_id') == exchanger_id
                                and row.get('equipment_code') for row in rows)
                    )
                elif kind == 'threshold':
                    item['passed'] = [r.get('tube_id') for r in rows] == threshold
                else:
                    item['passed'] = False
            except QueryRejected as exc:
                item['rejected'] = str(exc)
                item['passed'] = kind == 'unsupported' and '범위를 벗어' in str(exc)
            item['seconds'] = round(time.monotonic()-started, 2)
            report['cases'].append(item)
            print(json.dumps({k: item[k] for k in ('kind','passed','seconds')}, ensure_ascii=False), flush=True)
    finally:
        client.close()
        output = ROOT/'reports/text_to_sql/live_validation.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return 0 if all(c['passed'] for c in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
