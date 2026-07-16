# Changelog

All notable changes to AllocSignal are documented here. The project follows [Semantic Versioning](https://semver.org/).

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
