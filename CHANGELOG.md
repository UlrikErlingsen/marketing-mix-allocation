# Changelog

All notable changes to Alloc Signal are documented here. The project follows [Semantic Versioning](https://semver.org/).

## 1.3.0 — 2026-10-03

Larger datasets for large marketing organisations. The optimizer, response curves, panel estimators, decision rules and export tables are unchanged; on the fictional demos every estimate is identical to 1.2.0.

### Larger datasets

- Larger datasets: run locally, Alloc Signal has no built-in limit on file size, rows, cells or panel size any more (it was 200 MB, or up to 500 MB via `ALLOCSIGNAL_MAX_UPLOAD_MB`, 30 MB for JSON, 250 MB unzipped workbooks, 500,000 rows and 8,000,000 cells); memory is the limit, and running out of memory is reported as a plain message. The public demo (`SIGNAL_PUBLIC=1`) keeps those values as demo limits, plus panel models of at most 10,000,000 design cells, all in the new `allocsignal/limits.py`; its messages say the downloaded app has none. `ALLOCSIGNAL_MAX_UPLOAD_MB` is no longer read in code; it only sets the launchers' Streamlit upload cap.
- CSV files are read with pandas' fast C parser after sniffing the delimiter from the header line (it used the slow Python parser in 25,000-row chunks), and uploaded tables are no longer copied after parsing. A 5,000,000-row, 330 MB panel reads in about 3 s.
- Panel estimators: the independent-column check and the rank checks run on the QR factor of the design (same tolerance as before) instead of re-decomposing every row for every column, and the per-entity change count is vectorized. A 200,000-row panel with 100 weekly time effects took 323 s and now takes about 33 s; 5,000,000 rows without time effects take about 45 s at about 4.8 GB peak memory.
- Time fixed effects add one dense indicator column per period. Above 12,000,000 design cells (rows × (predictors + periods)) the estimators are fitted on a seeded random sample of whole entities, a visible approximation stated first in the panel warnings and in every export; without time effects every row is used.
- On-screen digital-economics rows show at most 1,000 rows with a note. Exports hold every row: CSV and JSON always, while the Excel workbook lists tables above 2,000,000 cells on a "Read me" sheet (Excel stops at 1,048,576 rows per sheet). JSON tables above 100,000 rows are written as compact record arrays, and formula neutralisation runs once per distinct value. Above 100,000 exported rows the evidence files are prepared on request instead of on every page view.
- Column roles on the panel page are computed once per loaded table; reading, panel fitting and export preparation show a spinner.
- Streamlit's upload cap is 10,000 MB: `.streamlit/config.toml` (synced from Signal Hub), both launchers (`run_app.bat` now honors `ALLOCSIGNAL_MAX_UPLOAD_MB` like `run_app.command`, default 10000) and the Dockerfile (`STREAMLIT_SERVER_MAX_UPLOAD_SIZE=10000`).

### Suite

- Suite: Rival, Reach, Learn and Blueprint Signal added to the suite table.

## 1.2.0 — 2026-10-02

Signal brand refresh and Signal Hub entry point. The analysis, optimization, panel estimators, data contracts and export tables are unchanged (apart from the product label in the manifest).

### Brand

- Display name written **Alloc Signal** (with a space) in the app, README, docs, launchers and metadata; the evidence-pack manifest now reports `product: "Alloc Signal"`. Package, file, Docker and environment-variable names stay `allocsignal` / `ALLOCSIGNAL_*`.
- The app uses the shared `signal_theme` module (Organic Signal design, Decide family colour `#4f80a2`, Figtree): sidebar lockup, masthead, hero, cards, notes, footer, the per-app Plotly template (charts shown through `sig.chart`) and the mark as favicon replace the pasted styles. Chart series map to the Decide colorway and neutral tokens with the same meaning as before.
- New banner, social preview and marks in `assets/`; the old banner SVG is removed. `.streamlit/config.toml` uses the family colours.
- README follows the Signal template; bug-report and feature-request issue templates added.
- Embedded Figtree font, no Google Fonts request: the re-synced `signal_theme` loads Figtree from the new synced `signal_font` module, so the app makes no outbound font request; the colorway now uses a per-family contrast order.

### Signal Hub contract

- `allocsignal.ui` exposes `APP_INFO` and `render()`, so Signal Hub can embed the app; `app.py` is now a thin standalone entry point.
- Opens with the fictional demo preloaded: a new session starts with the fictional channel plan (already validated), regional panel and digital campaign loaded, so every page works without an upload. The demo buttons restore them, an upload replaces them, and the welcome page and README say so.
- All session-state and widget keys are namespaced `alloc:` (including the page selector).
- The fictional demos and templates ship as package data under `allocsignal/ui/examples/`, so they also work from a normal (non-editable) install; `examples/` keeps the user-facing copies.
- `streamlit` and `plotly` moved to a `ui` extra (also in `test`); the analysis core installs without them. `requirements.txt` still lists everything.
- New tests: no Streamlit/Plotly import outside `allocsignal.ui`, `render()` runs from a script without a page config, every widget key is namespaced, and the demo data is packaged.

### Fixed

- Dockerfile: a stray line continuation folded `USER allocsignal` into the `useradd` command.

## 1.1.1 — 2026-07-16

### Security

- Export sanitizer now also neutralizes formula-like column headers and strips control characters; Docker images keep application code root-owned; defusedxml hardens workbook XML parsing.

## [Unreleased]

## [1.1.0] - 2026-07-16

### Added

- Digital campaign economics for CPM, CPC, CTR, CVR, CPA, gross/net contribution, contribution ROAS, and break-even CPC/CPA.
- Search-keyword economics, identity/tracking coverage, and view-through/cross-device/window declarations.
- A retrospective attribution audit that preserves descriptive labels and never auto-reallocates budget from attributed conversions.
- A Schedule & carryover page for per-period media-plan arithmetic on declared assumptions: editable channels × periods spend table, geometric adstock with declared retention λ and half-life readout, declared-parameter reach/frequency (skipped visibly when audience or cost is not declared), bounded pairwise interaction scenarios (≤3 multipliers in 0.8–1.2) with a with/without comparison, effective-vs-planned and reach charts, and CSV export of all schedule tables.

## [1.0.0] - 2026-07-14

### Added

- Local-first Streamlit workflow for marketing-response planning and constrained resource allocation.
- ADBUDG/Hill response curves with analytic marginal response, elasticity, contribution, and current-plan diagnostics.
- Fixed-budget reallocation and flexible budget-sizing scenarios with channel minima, maxima, and fixed commitments.
- Short- and long-run views, parameter sensitivity, bound activity, and explicit independent-channel limitations.
- Separate panel-evidence workflow for pooled OLS, fixed effects, random effects, within/between variation, and Hausman comparison.
- Decision-focused exports preserving assumptions, constraints, diagnostics, warnings, and audit metadata.
- Fictional channel-plan and regional-panel demos, downloadable templates, method/data/decision documentation, and automated tests.
- Signal-family branding, local launchers, non-root Docker runtime, CI, security/privacy policies, citation metadata, and AGPL-3.0-or-later licensing.
