<p align="center">
  <img src="assets/allocsignal-banner.svg" alt="AllocSignal — put the next budget where it works hardest" width="100%">
</p>

<p align="center">
  <a href="https://github.com/UlrikErlingsen/marketing-mix-allocation/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/UlrikErlingsen/marketing-mix-allocation/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-173C3A?logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/Streamlit-app-D95B40?logo=streamlit&logoColor=white">
  <a href="LICENSE"><img alt="License: AGPL-3.0-or-later" src="https://img.shields.io/badge/License-AGPL--3.0--or--later-36534E"></a>
</p>

<p align="center"><strong>Open marketing-response planning — diminishing-return curves and real constraints in, an auditable budget recommendation out.</strong></p>

**AllocSignal** helps a marketer decide how much to spend and how to divide a budget across channels. It draws saturating response curves, compares the current plan with optimized alternatives, reports marginal return and elasticity, and stress-tests the recommendation. A separate panel-evidence workspace compares pooled, fixed-effects, and random-effects models so advanced users can challenge what the historical data actually support.

The interface starts with the decision. The methods, assumptions, and diagnostics remain close enough for an analyst to audit. Everything runs locally with open-source Python packages; there is no account, telemetry, or external AI call.

## Read this first

> **An optimizer makes assumptions consistent; it does not make them true.** A numerically preferred allocation can still be strategically wrong when response curves are weakly calibrated, spend has little historical variation, channels interact, execution cannot move that quickly, or an estimated association is mistaken for causality.

AllocSignal therefore separates two jobs:

1. **Planning:** encode a defensible diminishing-return story for each channel, add business constraints, and compare allocations.
2. **Evidence checking:** use repeated unit-by-time observations to ask whether within-unit changes support the assumed direction and size of marketing effects.

A panel coefficient is not silently converted into a causal response curve. Connecting evidence to planning remains an explicit analyst judgment.

## Try it in two minutes

1. Start the app and load the fictional **channel plan** from the sidebar.
2. Review current, minimum, maximum, fixed-channel, saturation, half-saturation, and curve-shape assumptions.
3. Compare the current plan with an optimized fixed-budget allocation. Read the change in contribution and each channel's marginal contribution from one more currency unit.
4. Open the response curves and sensitivity view. Notice which recommendation changes when ceiling response or half-saturation is less favorable.
5. Load the fictional **regional panel**. Select `region` as the entity, `period` as time, and `sales` as the outcome; compare pooled OLS, fixed effects, and random effects.
6. Export the tables, assumptions, warnings, and model evidence needed to reproduce the discussion.

The demos are synthetic teaching data. They describe no real company, campaign, channel, or market.

## Planning data

Use one row per channel. CSV, Excel, and JSON are supported.

| channel | current_spend | min_spend | max_spend | floor_response | ceiling_response | half_saturation | shape | long_run_multiplier | fixed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Paid search | 120000 | 50000 | 220000 | 0 | 760000 | 115000 | 1.35 | 1.08 | false |
| Retail media | 90000 | 30000 | 180000 | 0 | 520000 | 95000 | 1.20 | 1.04 | false |

Monetary fields must use one consistent currency and time period. Response must be an economically meaningful quantity such as incremental sales revenue, units, or gross profit opportunity. AllocSignal applies one contribution margin to translate response into contribution:

`contribution(spend) = response(spend) × contribution margin − spend`

The built-in curve is the ADBUDG/Hill form:

`response(x) = b + (a − b) × x^c / (d + x^c)`

where `b` is the floor, `a` is the saturation ceiling, `c` controls shape, and `d = half_saturation^c`. At the half-saturation spend, the curve is halfway from its floor to its ceiling. This parameterization makes the scale easier to discuss than an opaque `d` value.

For fixed-budget allocation, AllocSignal retains the best known feasible starting plan, creates additional deterministic starts through dense global searches along two-channel budget exchanges, and then runs multi-start SLSQP. With exactly two movable channels, the pairwise search covers the complete feasible budget line. With more channels, repeated pairwise searches plus SLSQP are a stronger globalisation heuristic—not a universal guarantee of the joint global optimum. Always inspect binding bounds, solver notes, and sensitivity rather than treating `success` as proof of global optimality.

See the [data guide](docs/data_guide.md) for units, anchors, constraints, validation, historical variation, and templates.

## Panel-evidence data

Use one row per entity-period pair. An entity can be a region, store, account, product, or another stable unit observed repeatedly.

| region | period | sales | paid_search | online_display | distribution | price_index |
|---|---|---:|---:|---:|---:|---:|
| North | 2025-Q1 | 831000 | 94000 | 56000 | 0.76 | 1.03 |
| North | 2025-Q2 | 865000 | 101000 | 59000 | 0.78 | 1.02 |
| South | 2025-Q1 | 692000 | 72000 | 43000 | 0.67 | 0.98 |

Every selected entity-period pair must be unique. A credible panel needs repeated observations, within-entity variation in the predictors, and enough entities for uncertainty estimates. Pooled OLS mixes within- and between-entity relationships. Fixed effects use deviations from each entity's own mean. Random effects add a stronger assumption: persistent unit differences must be uncorrelated with the included predictors.

AllocSignal's Hausman comparison is an assumption diagnostic, not a truth machine. Displayed FE and RE intervals may use entity-clustered or HC1-robust uncertainty, while the classical Hausman statistic is calculated from separate conventional model-based FE and RE covariance refits. The covariance basis is labeled with the result. If the models have no common estimable substantive slope, or the covariance difference has rank zero, the statistic and p-value are suppressed and the result is marked invalid. A small valid p-value is evidence against the random-effects orthogonality assumption under the test's conditions; a large valid p-value does not prove that assumption or establish causality.

## What the app is designed to show

- **Current plan:** spend, modeled response, contribution, elasticity, and marginal contribution by channel.
- **Budget reallocation:** a fixed-total-budget recommendation respecting channel minima, maxima, and fixed commitments.
- **Budget sizing:** a profit-oriented scenario when total spend may change within declared bounds.
- **Diminishing returns:** response curves and their analytic slopes, not constant average ROI extrapolation.
- **Economic logic:** at an unconstrained interior optimum, marginal response × margin approaches the marginal cost of spend; constraints can prevent equality.
- **Short and long run:** an explicitly labeled multiplier for delayed outcomes, not an unidentified dynamic model.
- **Sensitivity:** low/base/high cases showing whether the decision survives plausible parameter changes.
- **Panel structure:** pooled, fixed-effects, and random-effects estimates, uncertainty, within variation, and Hausman comparison.
- **Decision evidence:** portable tables and an audit trail containing inputs, assumptions, constraints, diagnostics, and warnings.

## What it deliberately does not claim

- Response-curve inputs are not causal merely because they are precise.
- Historical regression association is not incremental lift without a defensible identification design.
- Average ROI is not the return to the next currency unit; marginal return drives allocation.
- Deterministic pairwise searches and multi-start SLSQP reduce local-solution risk but do not prove the joint global optimum when more than two channels can move.
- An optimized plan is not implementable until minimum commitments, capacity, contracts, learning periods, and organizational constraints are represented.
- Independent channel curves do not capture synergy, substitution, shared reach, auction feedback, competitor response, or a changing market baseline.
- The long-run multiplier is a scenario device, not evidence of carryover. Use lagged or adstock models only when timing, variation, and assumptions support them.

## Run locally

You need Python 3.10 or newer and a local copy of this project folder.

**macOS:** double-click `run_app.command`.

**Windows:** double-click `run_app.bat`.

The first launch creates a private `.venv` and downloads the open-source dependencies. Later launches reuse it. Or use a terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### Docker

```bash
docker build -t allocsignal .
docker run --rm -p 8593:8593 allocsignal
```

Then open `http://127.0.0.1:8593`. The container runs the app as a non-root user. This repository does not promise a hosted public instance.

## No install? Give this file to an AI

Don't want to install anything? [AI_ANALYST.md](AI_ANALYST.md) is a single copy-paste file that turns a capable AI assistant (Claude, ChatGPT, Gemini, …) into this analysis. Copy the file into a chat, add your data, and the AI follows the same published methods and honesty rules as the app. The app is still the more private option: local mode keeps your data on your computer, while a cloud AI sees whatever you paste.

## Tests and development checks

```bash
python -m pip install -e ".[test]"
python -m pytest
python -m ruff check .
```

Statistical changes should be checked against analytically derived values or independently generated synthetic data. Optimization tests must verify feasibility as well as objective improvement. See [CONTRIBUTING.md](CONTRIBUTING.md).

## A disciplined workflow

1. Write the decision, planning horizon, currency, outcome unit, and contribution margin before tuning curves.
2. Calibrate each curve from experiments, quasi-experiments, historical evidence, or clearly labeled judgmental anchors.
3. Inspect historical spend range. An observed narrow range cannot identify a distant saturation point.
4. Declare minima, maxima, fixed commitments, and total-budget rules.
5. Run current, unconstrained, and constrained cases; explain which constraints bind.
6. Stress-test curve ceiling, half-saturation, margin, and delayed response.
7. Translate the result into an implementable change, preferably with holdouts or staged tests.
8. Monitor realized spend, reach, response, contribution, and model error; recalibrate rather than treating the first optimum as permanent.

## Privacy and responsible use

Local mode reads uploads into the Python process on that computer. AllocSignal adds no accounts, advertising, telemetry, external AI calls, or built-in data storage. Exports are created only when requested and source files are never modified.

Panel data can still be confidential or personal when an entity identifies a person, small account, or location. Use pseudonymous keys, aggregate where possible, and remove names, emails, free text, customer identifiers, and unnecessary columns. A hosted deployment changes the trust boundary; read [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md).

## Relationship to the Signal tools

These apps share a visual language but answer different questions:

- **[WorthSignal](https://github.com/UlrikErlingsen/customer-value-analytics)** asks what customers and customer relationships are worth.
- **[SegmentSignal](https://github.com/UlrikErlingsen/customer-segmentation)** asks whether customers form stable, useful groups.
- **[ChoiceSignal](https://github.com/UlrikErlingsen/conjoint-analysis)** asks how product attributes drive choice.
- **[AdoptSignal](https://github.com/UlrikErlingsen/adoption-forecasting)** asks when a new product gets adopted.
- **[PositionSignal](https://github.com/UlrikErlingsen/brand-positioning)** asks where brands sit relative to competitors.
- **[DriverSignal](https://github.com/UlrikErlingsen/survey-driver-analysis)** asks which measured experiences move with satisfaction or recommendation scores.
- **AllocSignal** asks where the next marketing budget should go, given response assumptions, economics, and constraints.

AllocSignal uses a contribution margin, but it is not a customer-lifetime-value model. WorthSignal can supply better unit economics; AllocSignal then applies them to a channel-allocation decision.

## Method references

- Little, J. D. C. (1970). Models and managers: The concept of a decision calculus. *Management Science, 16*(8), B-466–B-485. [https://doi.org/10.1287/mnsc.16.8.B466](https://doi.org/10.1287/mnsc.16.8.B466)
- Hanssens, D. M., Parsons, L. J., & Schultz, R. L. (2001). *Market Response Models: Econometric and Time Series Analysis* (2nd ed.). Kluwer Academic Publishers.
- Wooldridge, J. M. (2010). *Econometric Analysis of Cross Section and Panel Data* (2nd ed.). MIT Press.
- Hausman, J. A. (1978). Specification tests in econometrics. *Econometrica, 46*(6), 1251–1271. [https://doi.org/10.2307/1913827](https://doi.org/10.2307/1913827)

If AllocSignal supports research or teaching, cite the software metadata in [CITATION.cff](CITATION.cff) and the primary source appropriate to the selected method.

## License

AllocSignal is free software under **AGPL-3.0-or-later**. Commercial use is allowed; distribution and modified network services carry the source-sharing obligations in [LICENSE](LICENSE). The license covers this project's code and documentation, not ownership of the published methods it implements.

This application was developed with AI coding assistance and checked through source review and automated tests. Verify material decisions independently; no warranty is provided.
