# Contributing to AllocSignal

Contributions that make AllocSignal clearer, safer, statistically sounder, or easier for marketers are welcome.

## Development setup

Python 3.10 or newer is required. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e ".[test]"
python -m pytest
python -m ruff check .
python -m streamlit run app.py
```

## Project structure

```text
app.py                    Streamlit workflow and presentation
src/allocsignal/            Response, allocation, panel, validation, and export logic
tests/                    Statistical, constraint, validation, and app tests
docs/                     Data contract, method, and decision guidance
examples/                 Synthetic demos and starter templates
```

Computation under `src/allocsignal/` must remain importable without Streamlit, session state, or UI side effects.

## Method and data rules

- Keep planning curves separate from panel estimates; never turn a regression coefficient into an allocation curve silently.
- Preserve the ADBUDG/Hill parameter definition and test the analytic derivative independently.
- Distinguish average response, marginal response, elasticity, marginal revenue, and marginal contribution.
- Recompute objective values outside the optimizer and verify every bound, fixed channel, and total-budget constraint.
- Treat S-shaped curves as potentially non-concave and test multiple starting allocations where relevant.
- Label the additive independent-channel assumption and document every interaction extension.
- Keep short- and long-run scenarios distinct from estimated carryover.
- Validate unique entity-period keys and show within as well as between variation.
- Do not claim pooled, fixed-effects, random-effects, or Hausman output establishes causality.
- Use entity-aware uncertainty for repeated panel observations when the model supports it; warn when cluster counts are small.
- Disclose singular or indefinite Hausman covariance differences instead of forcing a valid-looking p-value.
- Add an analytically derived or independently generated synthetic reference test for every statistical behavior change.
- Update `docs/methods.md` and cite primary literature when changing a method or convention.

## Product and safety rules

- Start with the business decision and plain-language answer; keep expert diagnostics available nearby.
- Do not describe an optimizer result as truth, guaranteed lift, or implementable strategy.
- Keep assumptions, constraints, sensitivity, observed support, and warnings in exports.
- Preserve spreadsheet-formula neutralization and source/audit metadata across export formats.
- Never add telemetry, external AI calls, or persistent upload storage without an explicit public design discussion.
- Use only synthetic, public, or properly anonymized data in tests, examples, issues, and screenshots.

## Pull requests

Keep pull requests focused. Explain the user decision, methodological effect, validation, assumptions, limitations, and visible UI changes. Run the full test and lint commands before requesting review. Security and privacy concerns belong in the private channels described in [SECURITY.md](SECURITY.md), never in a public issue with real data.
