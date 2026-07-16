# Decision guide

The output is useful only when it changes a real decision responsibly. This guide turns the model view into a meeting-ready recommendation.

## Start with one sentence

Complete this before opening the optimizer:

> We need to decide **[how much / how to split]** the **[currency and period]** marketing budget to improve **[response definition]**, subject to **[three most important constraints]**, and we will judge success using **[incremental measurement design]**.

If that sentence cannot be completed, more modeling is premature.

## Read the allocation in five passes

### 1. Feasibility

Confirm the proposed total, channel bounds, fixed commitments, and business capacity. A recommendation that cannot be executed is not a candidate plan.

### 2. Economic difference

Compare contribution with the current plan, not just response. More sales can destroy value when the incremental margin is smaller than the spend required to create them.

### 3. Marginal return

Look at the next currency unit, not the historical average. A channel can have the best past ROI and still be the wrong place for the next dollar because it is near saturation.

### 4. Sensitivity

Ask whether the channel ranking and direction of movement survive lower ceilings, slower response, different margin, and a plausible long-run view. A plan that flips under small changes should be described as a learning portfolio, not a confident optimum.

### 5. Evidence and extrapolation

Mark every proposed spend outside the historically observed range. Compare pooled and within-entity evidence. Write down which assumptions come from experiments, observational models, analogies, and judgment.

### Digital economics and attribution

Use CPM/CPC/CTR/CVR/CPA and contribution calculations to reconcile delivery and economics, not to infer causality. Check tracking coverage, view-through, cross-device, window, duplication, and long-term omissions before comparing rows. Treat retrospective attribution as descriptive credit assignment; require incremental evidence before moving budget because one channel received more attributed conversions.

## A practical recommendation format

Use four short sections:

1. **Move:** the spend changes that are stable enough to implement now.
2. **Hold:** commitments or channels with insufficient evidence to change.
3. **Test:** the uncertain shifts that should be staged with a holdout or matched comparison.
4. **Watch:** leading metrics, realized response, contribution, and assumptions that could invalidate the plan.

Avoid a long list of precise percentages when the curves are uncertain. Round implementation amounts to operationally meaningful increments.

## Why the constrained plan may beat the unconstrained story

An unconstrained run exposes the economics implied by the curves. A constrained run represents the decision the organization can actually make. Differences between them are useful: they identify the contracts, capacity limits, minimum presence, or risk rules carrying the largest opportunity cost.

Do not remove a constraint merely because the model dislikes it. Verify whether the constraint is a real fact, a negotiable policy, or stale folklore.

## Turn uncertainty into learning

For a contested channel shift:

- pre-register the primary outcome and window;
- keep a credible untreated or lower-spend comparison;
- randomize where feasible;
- protect against spillovers across geographies or audiences;
- measure actual delivery, not just booked budget;
- calculate incremental contribution, not only conversions; and
- update the curve using the result, including a null or negative result.

Small experiments can be more valuable than another decimal place in the optimizer.

## Common interpretation errors

| tempting statement | disciplined replacement |
|---|---|
| “Search has a 4× ROI, so fund it first.” | “Search's average historical ratio is high; the modeled marginal return at the proposed level determines the next allocation.” |
| “The optimizer says this is optimal.” | “This is the best feasible allocation under these curves, economics, and constraints.” |
| “Fixed effects prove marketing caused sales.” | “The estimate uses within-entity changes and removes persistent entity differences; time-varying confounding and reverse causality remain.” |
| “Hausman chose fixed effects.” | “The FE and RE slopes differ more than the comparison expects under the RE assumptions; we prefer the less demanding within interpretation.” |
| “Display is saturated.” | “The fitted curve is flat near current spend; that conclusion depends on support and calibration.” |
| “The long-run return is higher.” | “The long-run scenario assumes a multiplier; it is not an estimated carryover effect unless separately identified.” |

## Monitoring table

For each implemented channel change, record:

- planned and realized spend;
- target audience, geography, and dates;
- planned and realized reach or exposure;
- baseline and observed outcome;
- incremental-lift estimate and uncertainty;
- contribution margin actually realized;
- deviations from execution;
- competitor or market shocks; and
- the curve parameters to update.

Review the plan on the cadence appropriate to the response lag, not simply because a dashboard refreshes daily.
