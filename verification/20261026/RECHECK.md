# IRIS2 implementation and screen recheck - 2026-10-26

Scope: iris2 only; VCM1 and VCM2. Existing registered MariaDB routes reviewed. No application source changes.

## Results

- Official MariaDB integration and calculation regression suite: 90 passed; 0 failures/errors/skips.
- Authenticated screen/API/input/PDF/asset checks: 139 passed.
- Anonymous access checks: 46 passed.
- Additional checks: 44 templates compiled; setup redirect, designated PDF reviewer screen and 11 source PDFs passed.
- JavaScript behavior: precision selection and organization choices passed.
- Syntax: all 16 first-party static JavaScript files passed node --check.

## Implemented areas

Authentication and user permissions; dashboard; organization/plant/line masters; exchanger list, detail and revision forms; inspection history/plans; tube detail/management/layout revisions; 2D/3D Tube Map routes; precision analysis; remaining-life prediction and simulation; API 510; maintenance/work orders; imports and quality issues; PDF/OCR review; ML review/hotspots/patterns; AI query/report review; Excel/PDF exports; database monitor, backup and appearance settings.

## Limits and observations

- Dedicated MariaDB was stopped at the beginning. Started the existing iris2 instance using start_mariadb.ps1; left it running.
- Normal sandbox could not read private DB configuration. Checks ran with approved elevated access without printing credentials.
- Operational work-order detail had no fixture; successful work-order detail rendering and workflow were covered by the isolated integration test database.
- Existing legacy test_app.py references sibling iris assets. It was excluded rather than accessing iris. The official supported validation runner was used.
- Browser visual layout, real clicks, WebGL/GPU, QR camera and external LLM inference were not verified. HTTP/template tests do not establish those results.
- Field UAT and engineering/model approval remain separate.
- Tests that create/update data ran in the existing transition test schema; operational screen checks used GET requests.

## Screen and endpoint evidence

| Category | URL | Status | Result |
|---|---|---:|---|
| screen | `/login` | 200 | PASS |
| screen | `/settings/preferences` | 200 | PASS |
| screen | `/settings/users` | 200 | PASS |
| screen | `/` | 200 | PASS |
| screen | `/master-data/organization-codes` | 200 | PASS |
| screen | `/exchangers` | 200 | PASS |
| screen | `/exchangers/wall-loss-ranking` | 200 | PASS |
| screen | `/analysis` | 200 | PASS |
| screen | `/master-data/plants-lines` | 200 | PASS |
| screen | `/settings/wall-loss-colors` | 200 | PASS |
| screen | `/settings/system-theme` | 200 | PASS |
| screen | `/exchangers/new` | 200 | PASS |
| screen | `/exchangers/67/edit` | 200 | PASS |
| screen | `/exchangers/67` | 200 | PASS |
| screen | `/q/exchangers/67` | 200 | PASS |
| screen | `/remaining-life/tubes` | 200 | PASS |
| screen | `/exchangers/67/remaining-life-simulation` | 200 | PASS |
| screen | `/exchangers/67/api510` | 200 | PASS |
| screen | `/inspections/15/pdf` | 200 | PASS |
| screen | `/inspections/15` | 200 | PASS |
| screen | `/inspections` | 200 | PASS |
| screen | `/inspections/tubes` | 200 | PASS |
| screen | `/inspections/ml-review` | 200 | PASS |
| screen | `/inspections/ml-hotspots` | 200 | PASS |
| screen | `/inspections/ml-patterns` | 200 | PASS |
| screen | `/inspection-plans` | 200 | PASS |
| screen | `/tubes/176` | 200 | PASS |
| screen | `/exchangers/67/tubes/manage` | 200 | PASS |
| screen | `/exchangers/67/report` | 200 | PASS |
| screen | `/maintenance` | 200 | PASS |
| screen | `/maintenance/work-orders/new` | 200 | PASS |
| screen | `/exchangers/67/tube-map` | 200 | PASS |
| screen | `/api/exchangers/67/tube-map` | 200 | PASS |
| screen | `/assets/three.min.js` | 200 | PASS |
| screen | `/assets/OrbitControls.js` | 200 | PASS |
| screen | `/assets/TransformControls.js` | 200 | PASS |
| screen | `/assets/hanhwa_solution2.jpg` | 200 | PASS |
| screen | `/assets/hanwha_solution.png` | 301 | PASS |
| screen | `/quality-issues` | 200 | PASS |
| screen | `/imports` | 200 | PASS |
| screen | `/imports/pdf-review` | 403 | PASS |
| screen | `/settings/database-monitor` | 200 | PASS |
| screen | `/settings/backups` | 200 | PASS |
| screen | `/settings/tube-layout-revisions` | 200 | PASS |
| screen | `/reports/ai-review` | 200 | PASS |
| screen | `/inspections/ai-search` | 200 | PASS |
| screen | `/api/health` | 200 | PASS |
| screen | `/api/v1/exchangers` | 200 | PASS |
| screen | `/api/v1/exchangers/67/history` | 200 | PASS |
| screen | `/exports/heat-exchangers-tubes.xlsx` | 200 | PASS |
| VCM1 | `/exchangers?unit=VCM1` | 200 | PASS |
| VCM1 | `/exchangers/wall-loss-ranking?unit=VCM1` | 200 | PASS |
| VCM1 | `/analysis?unit=VCM1&exchanger_id=67` | 200 | PASS |
| VCM1 | `/remaining-life/tubes?unit_code=VCM1&target_year=2030` | 200 | PASS |
| VCM1 | `/inspections/ml-review?unit_code=VCM1` | 200 | PASS |
| VCM1 | `/inspections/ml-hotspots?unit_code=VCM1` | 200 | PASS |
| VCM1 | `/inspections/ml-patterns?unit_code=VCM1` | 200 | PASS |
| VCM1 | `/exchangers/67` | 200 | PASS |
| VCM1 | `/exchangers/67/edit` | 200 | PASS |
| VCM1 | `/exchangers/67/tube-map` | 200 | PASS |
| VCM1 | `/api/exchangers/67/tube-map` | 200 | PASS |
| VCM1 | `/exchangers/67/report` | 200 | PASS |
| VCM1 | `/exchangers/67/api510` | 200 | PASS |
| VCM1 | `/exchangers/67/remaining-life-simulation?simulate=1&simulation_limit=20&corrosion_rate_percent=100` | 200 | PASS |
| VCM1 | `/inspections/15` | 200 | PASS |
| VCM1 | `/inspections/15/pdf` | 200 | PASS |
| VCM1 | `/inspections/tubes?exchanger_id=67&sort_dir=desc&page=2` | 200 | PASS |
| VCM1 | `/pdf-reports/2020/VCM1` | 200 | PASS |
| VCM2 | `/exchangers?unit=VCM2` | 200 | PASS |
| VCM2 | `/exchangers/wall-loss-ranking?unit=VCM2` | 200 | PASS |
| VCM2 | `/analysis?unit=VCM2&exchanger_id=139` | 200 | PASS |
| VCM2 | `/remaining-life/tubes?unit_code=VCM2&target_year=2030` | 200 | PASS |
| VCM2 | `/inspections/ml-review?unit_code=VCM2` | 200 | PASS |
| VCM2 | `/inspections/ml-hotspots?unit_code=VCM2` | 200 | PASS |
| VCM2 | `/inspections/ml-patterns?unit_code=VCM2` | 200 | PASS |
| VCM2 | `/exchangers/139` | 200 | PASS |
| VCM2 | `/exchangers/139/edit` | 200 | PASS |
| VCM2 | `/exchangers/139/tube-map` | 200 | PASS |
| VCM2 | `/api/exchangers/139/tube-map` | 200 | PASS |
| VCM2 | `/exchangers/139/report` | 200 | PASS |
| VCM2 | `/exchangers/139/api510` | 200 | PASS |
| VCM2 | `/exchangers/139/remaining-life-simulation?simulate=1&simulation_limit=20&corrosion_rate_percent=100` | 200 | PASS |
| VCM2 | `/inspections/157` | 200 | PASS |
| VCM2 | `/inspections/157/pdf` | 200 | PASS |
| VCM2 | `/inspections/tubes?exchanger_id=139&sort_dir=desc&page=2` | 200 | PASS |
| VCM2 | `/pdf-reports/2020/VCM2` | 200 | PASS |
| input | `/exchangers?search=NO_SUCH_EQUIPMENT_RECHECK` | 200 | PASS |
| input | `/inspections?search=NO_SUCH_EQUIPMENT_RECHECK` | 200 | PASS |
| input | `/inspections/ai-search?q=1104421` | 200 | PASS |
| input | `/remaining-life/tubes?target_year=invalid` | 302 | PASS |
| input | `/inspections/tubes?page=invalid` | 200 | PASS |
| not_found | `/exchangers/2147483647` | 404 | PASS |
| not_found | `/inspections/2147483647` | 404 | PASS |
| not_found | `/tubes/2147483647` | 404 | PASS |
| not_found | `/maintenance/work-orders/2147483647` | 404 | PASS |
| asset | `/assets/OrbitControls.js` | 200 | PASS |
| asset | `/assets/TransformControls.js` | 200 | PASS |
| asset | `/assets/hanhwa_solution2.jpg` | 200 | PASS |
| asset | `/assets/three.min.js` | 200 | PASS |
| asset | `/static/app.css` | 200 | PASS |
| asset | `/static/auth.css` | 200 | PASS |
| asset | `/static/branding.css` | 200 | PASS |
| asset | `/static/calculation-method.css` | 200 | PASS |
| asset | `/static/calculation-method.js` | 200 | PASS |
| asset | `/static/color-settings.css` | 200 | PASS |
| asset | `/static/dashboard-metrics.css` | 200 | PASS |
| asset | `/static/dashboard-metrics.js` | 200 | PASS |
| asset | `/static/dashboard-qr-scanner.js` | 200 | PASS |
| asset | `/static/dashboard-tube-count-search.js` | 200 | PASS |
| asset | `/static/dashboard.css` | 200 | PASS |
| asset | `/static/exchanger-form.js` | 200 | PASS |
| asset | `/static/hx-v6-theme.css` | 200 | PASS |
| asset | `/static/import-location.js` | 200 | PASS |
| asset | `/static/inspection-detail.css` | 200 | PASS |
| asset | `/static/legacy-theme.css` | 200 | PASS |
| asset | `/static/life-prediction.css` | 200 | PASS |
| asset | `/static/life-prediction.js` | 200 | PASS |
| asset | `/static/life-simulation.js` | 200 | PASS |
| asset | `/static/maintenance-record.css` | 200 | PASS |
| asset | `/static/master-form.css` | 200 | PASS |
| asset | `/static/ml-review.css` | 200 | PASS |
| asset | `/static/modal.css` | 200 | PASS |
| asset | `/static/orange-theme.css` | 200 | PASS |
| asset | `/static/pattern-help.js` | 200 | PASS |
| asset | `/static/plant-line-master.css` | 200 | PASS |
| asset | `/static/plugging-limit-range.js` | 200 | PASS |
| asset | `/static/precision-analysis.css?v=20261023-3d-link` | 200 | PASS |
| asset | `/static/precision-analysis.js?v=20261023-3d-link` | 200 | PASS |
| asset | `/static/qr-exchanger-lookup.css` | 200 | PASS |
| asset | `/static/responsive-scroll.css` | 200 | PASS |
| asset | `/static/sidebar.js` | 200 | PASS |
| asset | `/static/system-theme-settings.css` | 200 | PASS |
| asset | `/static/tube-map-interaction.css` | 200 | PASS |
| asset | `/static/tube-map.css` | 200 | PASS |
| asset | `/static/tube-map.js?v=20261023-3d-link` | 200 | PASS |
| asset | `/static/tube-status.css` | 200 | PASS |
| asset | `/static/vendor/jsqr/jsQR.js` | 200 | PASS |
| asset | `/static/wall-loss-color-sync.js?v=20261023` | 200 | PASS |
| asset | `/static/workflow.css` | 200 | PASS |
