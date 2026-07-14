# Data guide

AllocSignal accepts two separate table types:

1. a **channel plan** for response curves and allocation; or
2. an **entity-period panel** for historical evidence.

CSV, `.xlsx`, `.xls`, `.xlsm`, and JSON tables are supported. Keep a simple rectangular table with one header row, unique column names, and no merged cells or subtotal rows.

## Channel-plan schema

Use one row per channel.

| column | meaning | rules |
|---|---|---|
| `channel` | unique channel label | nonblank; one row per channel |
| `current_spend` | current spend for the chosen period | finite; zero or positive |
| `min_spend` | lowest executable or committed spend | finite; zero or positive; no greater than current maximum |
| `max_spend` | highest feasible spend | finite; at least the minimum |
| `floor_response` | modeled response at zero spend | finite; usually zero for incremental response |
| `ceiling_response` | modeled saturation response | finite; greater than the floor |
| `half_saturation` | spend producing half the floor-to-ceiling response | finite and strictly positive |
| `shape` | ADBUDG/Hill curvature | finite and strictly positive |
| `long_run_multiplier` | scenario multiplier for delayed response | finite and strictly positive; 1 means no difference |
| `fixed` | whether the channel cannot move in a constrained run | `true` or `false` |

The committed example uses the same headers in `demo_channel_plan.csv` and `channel_plan_template.csv`.

### Keep units consistent

Choose one currency, response unit, and planning period for the entire table. Do not mix monthly paid-search spend with annual television spend, or sales revenue with units sold, unless values are converted first.

Examples of valid response definitions:

- incremental sales revenue per quarter;
- incremental gross-profit opportunity per year;
- incremental orders per month; or
- modeled conversions per campaign window.

If response is sales revenue, multiply by contribution margin before subtracting spend. If it is units, the margin input must be contribution per unit rather than a percentage. If response is already contribution currency, use a margin of 1. Record the interpretation in the exported decision note.

### Floor response and double counting

For an incremental channel curve, `floor_response` is normally zero. A nonzero floor belongs only when it is genuinely part of that channel's curve. Do not repeat the same organic baseline in every channel row: summing those floors will double count it. Put shared base demand in a separate baseline input where available.

### Curve anchors

The easiest parameters to discuss are:

- response at zero spend (`floor_response`);
- the asymptotic response ceiling (`ceiling_response`);
- spend at half the floor-to-ceiling lift (`half_saturation`); and
- whether response starts immediately or needs activation (`shape`).

Check the implied response at current spend and at a realistic increased-spend point. If those values conflict with experiment or history, revise the curve rather than trusting the optimizer.

### Bounds and fixed channels

Bounds are business facts, not statistical decorations. Examples include:

- contractual commitments;
- inventory or call-center capacity;
- minimum viable media weight;
- addressable-audience saturation;
- sales-force headcount;
- brand-protection floors; and
- implementation limits on quarter-to-quarter change.

A fixed channel usually remains at `current_spend`. If the current value is outside the entered minimum/maximum range, fix the data first. For a fixed-total budget, the sum of channel minima must not exceed the budget and the sum of maxima must not fall below it after fixed commitments are accounted for.

### Historical support

Keep a separate record of the historical spend range used to calibrate each curve. The template does not treat `max_spend` as empirical support: a channel may be operationally capable of spending 500,000 even though historical evidence stops at 150,000. Proposed spend outside observed support is extrapolation.

## Panel-data schema

Use one row per entity-period pair.

| region | period | sales | paid_search | online_display | distribution | price_index |
|---|---|---:|---:|---:|---:|---:|
| North | 2025-Q1 | 831000 | 94000 | 56000 | 0.76 | 1.03 |
| North | 2025-Q2 | 865000 | 101000 | 59000 | 0.78 | 1.02 |

The app should let you assign:

- one entity column;
- one time column;
- one numeric outcome; and
- one or more numeric predictors.

Controls can include price, distribution, competitor activity, macro conditions, or other pre-specified confounders. A control should have a defensible role; adding post-treatment variables can remove part of the marketing effect or introduce bias.

### Panel key

Every selected entity-period pair must be unique. Duplicate keys mean the grain is finer than declared—for example, product rows within a region-month. Aggregate deliberately or add the missing key dimension before analysis. Never let the regression silently treat duplicates as independent repeated measurements.

### Repeated observations

Each entity needs at least two periods for within transformation, but two observations rarely provide useful evidence. More entities improve cluster-based uncertainty; more time periods improve within variation and dynamic diagnostics. An unbalanced panel can be valid when the missingness process is understood, but inspect entity counts and gaps.

### Numeric fields

Outcome and predictors must be finite numeric values after exclusions. Parse currency signs, spaces, decimal separators, and percentage strings before upload. Use raw zero only when it means a real zero; do not encode missing values as `0`, `-99`, or `999999`.

Marketing fields must match the hypothesized exposure window. A campaign launched at the end of March should not be treated as if it generated the whole of March's outcome.

### Within versus between variation

For each numeric variable, compare:

- overall spread;
- variation in entity means (between); and
- variation around each entity mean (within).

A large between spread with almost no within variation may look compelling in pooled OLS while leaving a fixed-effects coefficient unidentified or extremely noisy. This is a data limitation, not a reason to prefer the larger pooled estimate.

### Time, lags, and carryover

Sort periods correctly before creating lags. Labels such as `M1`, `M10`, `M2` sort lexically rather than chronologically. Prefer ISO dates, integer period indexes, or sortable values.

Lag and adstock variables should be created from a declared timing assumption before analysis. Leading missing values are structural and must be reported. Trying many lags and retaining only the best-fitting one inflates false confidence.

### Categorical controls

Entity labels are handled by the panel structure, not entered as ordinary numeric codes. Other categorical controls need explicit dummy variables with one reference category omitted. An arbitrary encoding such as `urban=1`, `suburban=2`, `rural=3` imposes a false linear spacing unless that ordering is genuinely intended.

## Templates and examples

The `examples` folder contains:

- `demo_channel_plan.csv` — six fictional channels with visibly different curve shapes and constraints;
- `channel_plan_template.csv` — starter rows to replace with real channel assumptions;
- `demo_marketing_panel.csv` — a synthetic region-by-quarter panel with marketing and business controls; and
- `panel_template.csv` — a minimal entity-period starter table.

All names and numbers are fictional. The panel is designed for teaching and software checks, not to establish benchmark effect sizes.

## Privacy and security

Channel plans can reveal confidential strategy even without personal data. Panel entity labels may identify small stores, territories, customers, or employees. Use pseudonymous keys where possible and remove names, email addresses, phone numbers, customer IDs, precise addresses, free text, and unused columns.

Excel files may contain hidden sheets, formulas, macros, links, and metadata. The app reads table values; it does not need macros. Save a clean values-only workbook for analysis.

## Preflight checklist

### Channel plan

- One unique row per channel.
- One currency, response unit, and planning period.
- Nonnegative spend and valid minimum/maximum bounds.
- Ceiling above floor; positive half-saturation and shape.
- Response definition and contribution margin written down.
- Parameter evidence source recorded.
- Historical support distinguished from operational maximum.
- Fixed commitments and feasible total budget checked.

### Panel evidence

- One unique row per entity-period pair.
- Repeated observations per entity.
- Chronological time field.
- Numeric outcome and predictors with units documented.
- Missing codes converted to actual blanks.
- Within variation inspected.
- Marketing timing aligned with outcome timing.
- Direct identifiers and unused sensitive columns removed.
- Causal claims matched to a real identification design.

