# Dashboard and exchanger analysis cleanup

## Changes

- Removed the dashboard's exchanger, inspection, tube, result and plan metric strip.
- Dashboard population follows the exchanger list across registered production teams. VCM3/VCM4 remain excluded from this work. Annual inspection totals are grouped by the equipment's production team, with distinct exchanger counts per team/year.
- Exchanger links open analysis when the user has the remaining-life screen permission; existing authorization fallback remains.
- Three or more effective measurement dates: choose the larger positive regression or long-term rate. Two dates: choose the larger positive short-term or long-term rate. Preserve raw rates and detailed internal selection codes; display the short labels 추세, 단기, 장기.
- Kept equipment Summary visible alongside selected-tube thickness trends and inspection history. The right-hand panel scrolls independently on desktop.
- Merged sample-estimate results into equipment Summary and removed its separate results section and the separate top-five tube table.
- Moved prediction coverage into a closed calculation-basis disclosure. Section explanations and analysis guides are closed by default.
- Tube table starts at the ten highest wall-loss rows; View all expands it. Map selections outside those ten expand and reveal the selected row. Non-positive short-term rates display as a dash.
- Consolidated wall-loss colors at 40% and above on the analysis screen. Original report palettes elsewhere remain unchanged.
- Cumulative plugging chart scales to the actual forecast counts and prints the allowable count separately when outside the plotted range.

## Verification

Use the iris2-local virtual environment only:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_corrosion_rate_selection tests.test_life_dashboard tests.test_short_term_corrosion tests.test_ui_usability
.\.venv\Scripts\python.exe tools/verify_analysis_cleanup.py
node tools/verify_analysis_cleanup_browser.mjs
node tests/test_analysis_activation.cjs
```

The MariaDB verifier performs read-only queries and exports authenticated preview HTML into ignored local reports. It reconciled 900 registered exchangers and 118 INSPECTED exchangers with the list. E-111 Tube 18-13 selected its long-term rate, 0.00834923469161038 mm/year. Browser checks passed at 1440, 768 and 390px, including the top-ten expansion, linked selection, history placement, collapsed help and absence of page overflow.

Generated HTML, screenshots, validation JSON and logs stay local under `reports/analysis-cleanup-20261119`; they must not be committed. This source change does not deploy or restart the production application.

The focused 51 Python tests and the browser/touch checks passed. A broader discovery run executed 410 tests: one Text-to-SQL service test returned 503, three integration tests lacked a local test schema or its grants, and one relative-import test requires package-qualified invocation. These broader failures do not establish a fully passing suite; see the local full-tests log.

Package-qualified rerun passed all seven menu-cleanup and API 510 dashboard authorization checks. The Text-to-SQL fluid-grouping test still returned 503 independently of the discovery run.

## Request-by-request recheck

- Rechecked dashboard team totals and annual aggregates against independent read-only SQL. INSPECTED is VCM 108 plus PE 10, totaling 118. All 900 registered exchangers match the list population.
- Checked all 41 E-111 calculation rows: selected rates are at least each valid positive long-term rate and positive regression rate. Tube 18-13 remains 0.00834923469161038 mm/year, basis 장기.
- Browser checks verify removed metric tiles, PE dashboard inclusion, exchanger-code/name links to analysis, ten initial tube rows, expansion and linked selection, short-rate dashes, full short basis labels, and selected history next to the map.
- Found and corrected explanations generated after tube selection: thickness-trend notes, short-rate calculations, remaining-life scope notes, cumulative-chart notes, and the PDF section introduction now also start closed. Updated the analysis script version to refresh browser caches.
- Verified 39.99% uses the below-threshold color, and 40%, 70%, and 99% use the identical Plugging color through the actual map renderer with an isolated local HTML fixture.
- The E-111 cumulative chart uses a maximum of 4 while showing the 70-tube allowable limit separately. Nonzero bars have visible height.
- Focused 51 Python tests and browser checks at 1440, 768, and 390px passed again. Raw MariaDB data was not changed by the recheck.
- The optional existing-server comparison could not connect to localhost:4824. Source and authenticated Flask previews are verified; deployment and the currently served application's state are not verified. No server was started or restarted.

## Local running-server verification

At the user's request, retried outside the restricted execution context and bypassed system HTTP proxies for loopback requests. The existing `0.0.0.0:4824` server returned HTTP 200 with IRIS2/MariaDB health status `ok`, integrity `ok`, and zero foreign-key issues. The prior connection failure did not establish that the server was stopped.

Authenticated HTTP GETs to the actual server's dashboard, exchanger list and E-111 analysis returned 200. The served E-111 Tube 18-13 selected rate equals the source result, 0.00834923469161038 mm/year. The analysis response includes the latest `20261119-recheck-2` script and closed PDF explanation.

`tools/verify_analysis_cleanup.py --runtime-browser` passes an authenticated session to the browser over stdin only, without writing session credentials. Live HTTP browser checks at 1440, 768 and 390px confirmed all top-ten/view-all, selected summary/history/trend, non-positive short-rate dash, short basis labels, collapsed explanations, visible forecast bars, and no page-overflow assertions. The live dashboard contains all production teams including PE with the removed metric strip absent. Live exchanger-code and equipment-name links point to analysis. Screenshots and results are local ignored reports named `runtime-analysis-*.png` and `runtime-browser-validation.json`.

No application server or MariaDB restart was needed, and this check did not modify business data.

## Subsequent repeat check

On the subsequent repeat-check request, an elevated direct loopback health request returned Windows connection-refused error 10061 and no 4824 listener was found. Started only the IRIS2 web server with the local `.venv/Scripts/python.exe server.py --host 0.0.0.0 --port 4824 --no-browser`, in a hidden background process. MariaDB and other applications were not stopped. The web health endpoint then returned 200 with status and integrity `ok`. Repeated the authenticated live-server and browser verification using `--runtime-browser`; current local reports contain the refreshed evidence.
