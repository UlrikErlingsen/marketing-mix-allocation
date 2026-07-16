# Methods and interpretation

AllocSignal combines two related but deliberately separate analytical tasks:

1. **response planning and constrained allocation**; and
2. **panel-data evidence checking**.

The first needs a response curve that can be evaluated outside the exact historical observations. The second estimates conditional associations from repeated observations. A panel estimate does not become an allocation curve without additional assumptions, calibration, and usually experimental evidence.

## 1. ADBUDG/Hill response curve

For channel spend `x ≥ 0`, AllocSignal uses the saturating curve

`R(x) = b + (a − b) × x^c / (h^c + x^c)`

where:

- `b` is floor response at zero spend;
- `a` is saturation response as spend becomes very large;
- `h` is half-saturation spend;
- `c > 0` is the shape parameter.

This is the ADBUDG/Hill form, with the original scale parameter `d = h^c`. The half-saturation parameterization is interpretable because `R(h) = b + (a − b)/2`.

For `c = 1`, the curve is concave from the origin. For `c > 1`, it is S-shaped: marginal response first rises and later falls. An S-shape can encode a threshold or activation effect, but it makes optimization non-concave and therefore more dependent on search coverage, starting values, and bounds. A numerical recommendation is never proof that the chosen curve shape is empirically correct.

### Marginal response

For `x > 0`, the analytic derivative is

`R′(x) = (a − b) × c × h^c × x^(c−1) / (h^c + x^c)^2`.

This slope is the modeled response from the next small unit of spend. It is different from average response `R(x)/x` and from historical average ROI.

At zero, the derivative is interpreted by its right-hand limit:

- zero when `c > 1`;
- `(a − b)/h` when `c = 1`; and
- unbounded when `0 < c < 1`, which is mathematically valid but can be operationally implausible.

The app should not use a tiny-spend singularity as a business recommendation. Minimum executable spend and calibrated bounds matter.

### Elasticity

Point elasticity is

`ε(x) = R′(x) × x / R(x)`

when `R(x) > 0`. It is the modeled percentage change in channel response associated with a one-percent spend change at that point. If `b` includes response that would occur without the channel, elasticity to total response will be lower than elasticity to incremental response; define the response unit before interpretation.

## 2. Contribution and economic optimum

For one common contribution margin `m`, total modeled contribution is

`Π(x) = m × [B + Σ R_j(x_j)] − Σ x_j`,

where `B` is any nonmarketing baseline response and `j` indexes channels. If response is already measured in contribution currency rather than revenue or units, set the effective margin to 1 and document that choice.

For an interior, unconstrained optimum of an independent channel,

`m × R′_j(x_j) − 1 = 0`.

Therefore the **marginal contribution per additional currency unit** is

`MC_j(x_j) = m × R′_j(x_j) − 1`.

An `MC` of 0.20 means the curve predicts about 0.20 additional contribution currency after paying for the next 1.00 of spend, locally. It is not a confidence interval or guaranteed realized return.

With a fixed total budget, an interior optimum tends to equalize `m × R′_j(x_j)` across movable channels. It does not require every channel's marginal contribution to equal zero because the budget itself is binding. A minimum, maximum, or fixed commitment can also prevent equal marginal returns.

## 3. Allocation scenarios

AllocSignal separates three comparisons.

### Current plan

Evaluate the uploaded or edited current spend without optimization. This is the baseline for all deltas.

### Flexible budget sizing

Spend may move independently inside each channel's minimum and maximum. The objective is to maximize modeled contribution. This answers “how large should the modeled budget be?” under the supplied curves and bounds. If a solution lands at many bounds, the economic result is driven by those bounds and should be described that way.

### Fixed-budget reallocation

Total spend is constrained to a declared budget while each channel respects its bounds and fixed status. This answers “how should this budget be divided?” A fixed channel's lower and upper bound are both set to its commitment for that run.

The fixed-budget search first builds deterministic feasible starts, including the current allocation, bound-oriented allocations, and pairwise grid-refined allocations. Each pairwise refinement searches the complete feasible exchange line for two channels on a dense grid, then refines the best neighborhood. SLSQP subsequently improves those starts, while the best feasible raw start is retained as a candidate. This protects against returning a result worse than a known feasible start and materially reduces local-basin failures from S-shaped curves.

That procedure is a global search only along each two-channel exchange. With three or more movable channels, repeated pairwise searches plus multi-start SLSQP remain a globalisation heuristic, not a universal proof of the joint global optimum. Feasibility, recomputed objective values, bound activity, retained-start comparisons, and sensitivity analysis remain more informative than a solver success flag alone.

## 4. The independent-channel assumption

The base planning model adds channel responses:

`R_total = B + R_1(x_1) + … + R_J(x_J)`.

This assumes the response attributed to one channel does not change with another channel's spend. Real marketing often violates this because of shared reach, sequence effects, brand/search feedback, auction competition, retailer response, or substitution. A correlated history can also credit several channels for the same demand.

Until interaction terms or a joint-response model are supported by data, treat independence as a declared simplification. Stress-test allocations and avoid large shifts justified by tiny modeled advantages.

## 5. Calibration evidence

A response curve can be informed by:

- randomized geo, audience, or time experiments;
- quasi-experimental variation with a defensible identification design;
- historical marketing-mix or panel models;
- published analogies; or
- managerial judgment expressed as explicit anchors.

Useful judgmental anchors include response at zero, response at current spend, response after a credible increase, and a saturation ceiling. The four curve parameters should be treated as assumptions when those anchors are not statistically estimated.

Historical support is local. If paid-search spend only varied between 90 and 110 in the observed sample, the data cannot identify response at 300 without strong functional-form extrapolation. Record the observed range and flag proposed allocations beyond it.

Calibration uncertainty is usually larger than numerical-optimization error. A sensitivity analysis that moves the ceiling, half-saturation, margin, and long-run multiplier is therefore essential.

## 6. Short- and long-run scenarios

AllocSignal can apply a declared long-run response multiplier to the channel curve. This is a scenario, not a dynamic estimate. It can represent a hypothesized carryover, awareness, retention, or delayed conversion effect, but it does not identify when that response arrives.

A proper dynamic model needs dated observations, a defensible lag or adstock transformation, enough time variation, and diagnostics for autocorrelation and seasonality. Do not describe a scenario multiplier as empirically estimated carryover unless it actually came from such a model.

## 7. Panel-data evidence

Let `i` denote an entity and `t` a period:

`y_it = α + x_it′β + u_i + ε_it`.

Here `u_i` is a persistent entity-specific component and `ε_it` is the remaining time-varying disturbance.

### Pooled OLS

Pooled OLS treats every row as one regression sample and does not model `u_i`. Its coefficient combines:

- **between-entity information**: entities that spend more on average versus those that spend less; and
- **within-entity information**: periods when the same entity spends more or less than its own average.

Those relationships can differ in direction. A pooled scatterplot can therefore tell a Simpson's-paradox story that disappears or reverses after entity means are removed.

### Fixed effects

The fixed-effects or within estimator subtracts each entity's mean:

`y_it − ȳ_i = (x_it − x̄_i)′β + (ε_it − ε̄_i)`.

Time-invariant entity differences are removed, including unobserved ones. Coefficients are identified only from within-entity variation. A predictor that does not vary within entities cannot be estimated. Fixed effects do not remove time-varying omitted variables, reverse causality, measurement error, anticipation, or common shocks.

### Random effects

Random effects uses a quasi-demeaning transformation and can be more efficient when its key orthogonality assumption holds:

`E[u_i | x_i1, …, x_iT] = 0`.

In marketing, persistent market potential, sales-force quality, distribution, or management attention often affects both outcome and spend, making that assumption demanding.

### Hausman comparison

The classic statistic compares common FE and RE slopes:

`H = (β_FE − β_RE)′ [V_FE − V_RE]^−1 (β_FE − β_RE)`.

Under its regularity conditions, `H` is compared with a chi-squared distribution. A small p-value indicates systematic coefficient differences inconsistent with the RE orthogonality assumption. A large p-value can also reflect low power, noisy estimates, or an unstable covariance difference; it does not prove random effects.

AllocSignal computes this classical diagnostic from separate FE and RE refits using conventional model-based covariance matrices. The coefficient tables can still show entity-clustered or HC1-robust intervals; those robust matrices are not substituted into the classical `V_FE − V_RE` formula because their difference does not generally retain the covariance relationship the test requires. The reported covariance basis therefore travels with the Hausman result.

The model-based covariance difference can still be singular or indefinite in finite samples. If no substantive slope is estimable in both models, or the covariance difference has rank zero, AllocSignal suppresses the statistic and p-value, reports zero test degrees of freedom, and marks the result invalid. An indefinite covariance difference is also marked invalid even when a pseudoinverse value can be calculated. These cases require direct comparison of estimates and assumptions rather than a model-selection p-value.

### Uncertainty and diagnostics

Repeated observations within one entity are not independent. Entity-clustered uncertainty is generally more defensible than ordinary iid standard errors when there are enough clusters. With few entities, conventional cluster-robust standard errors can still be unreliable and small-sample methods or randomization inference may be needed.

At minimum, inspect:

- number of entities and periods per entity;
- unique entity-period keys;
- missing and nonfinite values;
- within and between standard deviations;
- predictor correlation and condition number;
- residual patterns, influential entities, and serial dependence;
- outcome and spend time trends; and
- whether a proposed allocation lies inside observed support.

Time fixed effects can absorb shocks common to all entities, but they do not automatically solve endogeneity. Lagging spend changes timing, not identification.

## 8. Digital economics and attribution audit

For each campaign, platform, source, or search keyword, AllocSignal derives `CTR = clicks/impressions`, `CVR = conversions/clicks`, `CPM = 1000 × spend/impressions`, `CPC = spend/clicks`, and `CPA = spend/conversions` when denominators are positive. Gross contribution is `conversions × contribution per conversion`; net contribution subtracts spend. Contribution ROAS is gross contribution divided by spend. Break-even CPA equals contribution per conversion, and break-even CPC equals contribution per conversion multiplied by CVR.

These are arithmetic planning identities, not causal estimates. Tracking coverage reports the observed share linked to the declared identity or conversion mechanism and cannot recover unobserved conversions. Keyword, source, platform, and campaign comparisons inherit selection, auction, targeting, seasonality, and measurement differences.

The attribution audit records lookback window, view-through inclusion, cross-device handling, identity coverage, long-term-effect coverage, and any Markov/removal-effect assumptions. Every result is labeled retrospective and descriptive. Attributed conversions must not be treated as incrementality or passed directly into budget reallocation without a defensible experiment or other causal identification design.

## 9. Association is not causality

A regression coefficient estimates a causal incremental effect only under assumptions about assignment, omitted variables, interference, timing, functional form, and measurement. Marketing spend is often chosen in response to expected demand, so a positive association can reflect targeting rather than lift; a negative association can reflect reactive spending in weak markets.

For consequential reallocation, prefer randomized holdouts, geo experiments, credible instruments, regression discontinuities, or other designs matched to the business process. Use the panel workspace as structured evidence checking, not a causality badge.

## 10. Reproducible decision record

An analysis should preserve:

- source fingerprint and extraction date;
- response, currency, time-period, and margin definitions;
- curve values and their evidence source;
- current, minimum, maximum, and fixed spend;
- optimization mode, budget, solver status, and constraint checks;
- current and proposed channel metrics;
- sensitivity cases;
- panel role assignments, exclusions, model settings, estimates, uncertainty, and Hausman output; and
- plain-language limitations and the chosen implementation test.

The strategic decision belongs to the analyst and decision owner, not the optimizer.

## Primary references

- Little, J. D. C. (1970). Models and managers: The concept of a decision calculus. *Management Science, 16*(8), B-466–B-485. [https://doi.org/10.1287/mnsc.16.8.B466](https://doi.org/10.1287/mnsc.16.8.B466)
- Hanssens, D. M., Parsons, L. J., & Schultz, R. L. (2001). *Market Response Models: Econometric and Time Series Analysis* (2nd ed.). Kluwer Academic Publishers.
- Hausman, J. A. (1978). Specification tests in econometrics. *Econometrica, 46*(6), 1251–1271. [https://doi.org/10.2307/1913827](https://doi.org/10.2307/1913827)
- Wooldridge, J. M. (2010). *Econometric Analysis of Cross Section and Panel Data* (2nd ed.). MIT Press.
