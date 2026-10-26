"""Read-only screen, authorization, asset and VCM1/VCM2 regression inventory."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2.app import create_app
from iris2.database import get_engine
from sqlalchemy import text


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = set()
        self.forms = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.in_title |= tag == "title"
        self.forms += tag == "form"
        if tag in {"script", "img", "link"}:
            asset = attrs.get("src") if tag != "link" else attrs.get("href")
            if asset and asset.startswith("/") and not asset.startswith("//"):
                self.assets.add(asset)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def main():
    report_date = datetime.now(timezone(timedelta(hours=9))).date()
    output = ROOT / "reports/system_recheck" / report_date.strftime("%Y%m%d")
    output.mkdir(parents=True, exist_ok=True)
    app = create_app({"TESTING": True, "AUTH_DISABLED": False, "CSRF_ENABLED": True})
    engine = get_engine()
    with engine.connect() as conn:
        admin = conn.scalar(text("SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1"))
        units = {}
        for unit in ("VCM1", "VCM2"):
            row = conn.execute(text("SELECT h.heat_exchanger_id, MIN(i.iris_inspection_id) AS inspection_id FROM heat_exchanger h JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id JOIN iris_inspection i ON i.heat_exchanger_id=h.heat_exchanger_id WHERE u.unit_code=:unit GROUP BY h.heat_exchanger_id ORDER BY h.heat_exchanger_id LIMIT 1"), {"unit": unit}).mappings().one()
            units[unit] = dict(row)
        tube = conn.scalar(text("SELECT MIN(r.tube_id) FROM iris_tube_result r JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id WHERE i.heat_exchanger_id=:id"), {"id": units["VCM1"]["heat_exchanger_id"]})
        order = conn.scalar(text("SELECT MIN(work_order_id) FROM work_order_v2"))
        counts = {table: conn.scalar(text(f"SELECT COUNT(*) FROM {table}")) for table in ("heat_exchanger", "heat_exchanger_tube", "iris_inspection", "iris_tube_result", "tube_lifecycle_event")}
    client = app.test_client()
    anonymous = app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=admin, last_activity_at=time.time(), csrf_token="screen-check")
    results, assets, security, skipped = [], set(), [], []

    def check(url, expected=200, category="screen"):
        started = time.monotonic()
        try:
            response = client.get(url)
            entry = dict(url=url, category=category, status=response.status_code, expected=expected,
                         passed=response.status_code == expected, seconds=round(time.monotonic()-started, 3))
            if response.mimetype == "text/html":
                parser = Markup()
                parser.feed(response.get_data(as_text=True))
                assets.update(parser.assets)
                entry.update(title=parser.title, forms=parser.forms)
            if response.mimetype == "application/pdf":
                entry["passed"] &= response.data.startswith(b"%PDF-")
        except Exception as exc:
            entry = dict(url=url, category=category, passed=False, error=type(exc).__name__, detail=str(exc)[:350])
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=True), flush=True)

    replacements = {"<int:exchanger_id>": units["VCM1"]["heat_exchanger_id"], "<int:inspection_id>": units["VCM1"]["inspection_id"], "<int:tube_id>": tube, "<int:order_id>": order}
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint in {"static", "setup_admin", "pdf_report_view", "pdf_ocr_source"}:
            continue
        url = rule.rule
        for key, value in replacements.items():
            if value is not None:
                url = url.replace(key, str(value))
        if "<" in url:
            skipped.append(dict(endpoint=rule.endpoint, rule=rule.rule, reason="No existing fixture for parameter"))
            continue
        expected = 403 if rule.endpoint == "pdf_ocr_review_dashboard" else 301 if rule.endpoint == "hanwha_solution_logo_legacy" else 200
        check(url, expected)
        if rule.endpoint not in {"login", "api_health", "hanwha_solution_logo", "hanwha_solution_logo_legacy"}:
            response = anonymous.get(url)
            security.append(dict(url=url, status=response.status_code, passed=response.status_code == 302 and "/login" in response.location))
    for unit, row in units.items():
        hx = row["heat_exchanger_id"]
        for url in [f"/exchangers?unit={unit}", f"/exchangers/wall-loss-ranking?unit={unit}", f"/analysis?unit={unit}&exchanger_id={hx}", f"/remaining-life/tubes?unit_code={unit}&target_year=2030", f"/inspections/ml-review?unit_code={unit}", f"/inspections/ml-hotspots?unit_code={unit}", f"/inspections/ml-patterns?unit_code={unit}", f"/exchangers/{hx}", f"/exchangers/{hx}/edit", f"/exchangers/{hx}/tube-map", f"/api/exchangers/{hx}/tube-map", f"/exchangers/{hx}/report", f"/exchangers/{hx}/api510", f"/exchangers/{hx}/remaining-life-simulation?simulate=1&simulation_limit=20&corrosion_rate_percent=100", f"/inspections/{row['inspection_id']}", f"/inspections/{row['inspection_id']}/pdf", f"/inspections/tubes?exchanger_id={hx}&sort_dir=desc&page=2", f"/pdf-reports/2020/{unit}"]:
            check(url, category=unit)
    for url in ["/exchangers?search=NO_SUCH_EQUIPMENT_RECHECK", "/inspections?search=NO_SUCH_EQUIPMENT_RECHECK", "/inspections/ai-search?q=1104421", "/remaining-life/tubes?target_year=invalid", "/inspections/tubes?page=invalid"]:
        check(url, 302 if "target_year=invalid" in url else 200, "input")
    for url in ["/exchangers/2147483647", "/inspections/2147483647", "/tubes/2147483647", "/maintenance/work-orders/2147483647"]:
        check(url, 404, "not_found")
    for url in sorted(assets):
        check(url, category="asset")
    report = dict(date=report_date.isoformat(), units=units, counts=counts, checks=results, anonymous_security=security, skipped=skipped,
                  summary=dict(checks=len(results), failures=sum(not x["passed"] for x in results), security_checks=len(security), security_failures=sum(not x["passed"] for x in security)))
    (output / "screens.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
