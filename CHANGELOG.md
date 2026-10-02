# Changelog

All notable changes to Alloc Signal are documented here. The project follows [Semantic Versioning](https://semver.org/).

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
