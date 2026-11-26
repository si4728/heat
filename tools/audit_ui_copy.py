"""Inventory potentially unfinished UI copy without modifying application data."""
from pathlib import Path
import argparse
from html.parser import HTMLParser
import json
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(
    r"미구현|미완성|준비\s?중|개발\s?중|개발 상태|구현 예정|추후|임시|개선|"
    r"점검용|검증용|순차적으로|호환성|TODO|not implemented|coming soon|"
    r"확인|점검|검토", re.I
)
UNFINISHED = re.compile(r'미구현|미완성|준비\s?중|개발\s?중|개발 상태|구현 예정|추후|임시|개선 예정|순차적으로|not implemented|coming soon', re.I)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def render_screens():
    sys.path.insert(0, str(ROOT.parent))
    from iris2 import services
    from iris2.app import create_app
    from iris2.database import get_engine
    from sqlalchemy import text
    app = create_app({'TESTING': True, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
    with get_engine().connect() as conn:
        admin = conn.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
        hx = conn.scalar(text("SELECT i.heat_exchanger_id FROM iris_inspection i JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id WHERE u.unit_code IN ('VCM1','VCM2') AND i.superseded_by_inspection_id IS NULL ORDER BY i.iris_inspection_id LIMIT 1"))
        inspection = conn.scalar(text('SELECT MIN(iris_inspection_id) FROM iris_inspection WHERE heat_exchanger_id=:hx'), {'hx': hx})
        tube = conn.scalar(text('SELECT MIN(t.tube_id) FROM heat_exchanger_tube t JOIN tube_bundle b ON b.bundle_id=t.bundle_id WHERE b.heat_exchanger_id=:hx'), {'hx': hx})
    if not all([admin, hx, inspection, tube]):
        raise RuntimeError('Active administrator and VCM1/VCM2 sample records are required')
    results = []
    client = app.test_client()
    excluded = {'static', 'setup_admin', 'logout', 'inspection_pdf_view', 'pdf_report_view',
                'pdf_ocr_source', 'export_heat_exchangers_tubes', 'text_to_sql_inspections',
                'inspection_recommendation_tubes'}
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods or rule.endpoint in excluded or rule.rule.startswith(('/api/', '/assets/')):
            continue
        url = rule.rule.replace('<int:exchanger_id>', str(hx)).replace('<int:inspection_id>', str(inspection)).replace('<int:tube_id>', str(tube))
        if '<' in url:
            results.append(dict(endpoint=rule.endpoint, status='NOT_RUN', reason='No sample identifier'))
            continue
        with client.session_transaction() as session:
            session.update(user_id=admin,auth_stamp=services.user_access_profile(admin)['auth_stamp'], last_activity_at=time.time())
        try:
            response = client.get(url)
            parser = VisibleText()
            parser.feed(response.get_data(as_text=True))
            matches = [part for part in parser.parts if UNFINISHED.search(part)]
            results.append(dict(endpoint=rule.endpoint, url=url, status=response.status_code, unfinished=matches))
        except Exception as exc:
            results.append(dict(endpoint=rule.endpoint, url=url, status=500, error=type(exc).__name__))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true', help='Also request authenticated GET screens; no forms submitted')
    args = parser.parse_args()
    files = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    findings, scanned = [], []
    for name in files:
        path = Path(name)
        if path.suffix not in {'.py', '.html', '.js'}:
            continue
        if name.startswith(('tests/', 'tools/', 'static/vendor/', '.agents/', 'legacy',
                            'test_', 'llm_integration/tests/')):
            continue
        scanned.append(name)
        for number, line in enumerate((ROOT / name).read_text(encoding='utf-8-sig').splitlines(), 1):
            if PATTERN.search(line):
                findings.append(dict(file=name, line=number, text=line.strip()))
    target = ROOT / 'tmp/ui-copy-audit.json'
    target.parent.mkdir(exist_ok=True)
    screens = render_screens() if args.render else []
    target.write_text(json.dumps(dict(scanned=scanned, findings=findings, screens=screens), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(files=len(scanned), matches=len(findings), screens=len(screens), output=str(target))))


if __name__ == '__main__':
    main()
