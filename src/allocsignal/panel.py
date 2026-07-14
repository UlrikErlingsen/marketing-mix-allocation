"""Panel-data estimators and diagnostics for AllocSignal.

The module deliberately separates evidence from allocation.  These estimators
describe conditional associations in observed panel data; none of the returned
objects labels a coefficient as a causal effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
import warnings as python_warnings

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor


class PanelValidationError(ValueError):
    """Raised when data do not form an estimable entity-by-time panel."""


@dataclass(frozen=True)
class PanelDiagnostics:
    """Structure, variation, and collinearity checks for a panel dataset."""

    n_observations: int
    n_entities: int
    n_periods: int
    min_periods_per_entity: int
    max_periods_per_entity: int
    balanced: bool
    variation: pd.DataFrame
    vif: pd.DataFrame
    condition_number: float
    warnings: tuple[str, ...] = ()

    @property
    def nobs(self) -> int:
        """Statsmodels-style alias used by compact UI metric components."""

        return self.n_observations

    def summary_frame(self) -> pd.DataFrame:
        """Return the headline panel structure as a display-ready table."""

        return pd.DataFrame(
            {
                "metric": [
                    "Observations",
                    "Entities",
                    "Distinct periods",
                    "Minimum observations per entity",
                    "Maximum observations per entity",
                    "Balanced panel",
                    "Standardized condition number",
                ],
                "value": [
                    self.n_observations,
                    self.n_entities,
                    self.n_periods,
                    self.min_periods_per_entity,
                    self.max_periods_per_entity,
                    self.balanced,
                    self.condition_number,
                ],
            }
        )


@dataclass(frozen=True)
class PanelModelResult:
    """A consistent, UI-friendly result from one panel estimator."""

    estimator: str
    coefficients: pd.DataFrame
    covariance: pd.DataFrame
    fitted_values: pd.Series
    residuals: pd.Series
    metrics: Mapping[str, float]
    nobs: int
    n_entities: int
    n_periods: int
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def coefficient(self, term: str) -> float:
        """Return one estimate by term name, with a useful missing-term error."""

        rows = self.coefficients.loc[self.coefficients["term"] == term, "estimate"]
        if rows.empty:
            available = ", ".join(self.coefficients["term"].astype(str))
            raise KeyError(f"{term!r} is not estimated by {self.estimator}. Available terms: {available}")
        return float(rows.iloc[0])


@dataclass(frozen=True)
class HausmanResult:
    """Classical FE-versus-RE coefficient-difference diagnostic."""

    statistic: float
    degrees_of_freedom: int
    p_value: float
    compared_terms: tuple[str, ...]
    covariance_difference_psd: bool
    conclusion: str
    covariance_basis: str = "Provided FE and RE covariance matrices"
    warnings: tuple[str, ...] = ()
    fixed_covariance: pd.DataFrame | None = None
    random_covariance: pd.DataFrame | None = None
    covariance_difference: pd.DataFrame | None = None

    @property
    def df(self) -> int:
        """Conventional short alias for degrees of freedom."""

        return self.degrees_of_freedom

    @property
    def valid(self) -> bool:
        """Whether the conventional quadratic-form interpretation is numerically sound."""

        return bool(
            self.degrees_of_freedom > 0
            and bool(self.compared_terms)
            and self.covariance_difference_psd
            and np.isfinite(self.statistic)
            and np.isfinite(self.p_value)
        )

    @property
    def note(self) -> str:
        """Short compatibility alias for the substantive conclusion."""

        return self.conclusion

    @property
    def details(self) -> pd.DataFrame:
        """Display-ready details for audit and export views."""

        return self.as_frame()

    def as_frame(self) -> pd.DataFrame:
        """Return a one-row representation for display or export."""

        return pd.DataFrame(
            {
                "statistic": [self.statistic],
                "degrees_of_freedom": [self.degrees_of_freedom],
                "p_value": [self.p_value],
                "compared_terms": [", ".join(self.compared_terms)],
                "covariance_difference_psd": [self.covariance_difference_psd],
                "covariance_basis": [self.covariance_basis],
                "valid": [self.valid],
                "conclusion": [self.conclusion],
            }
        )


@dataclass(frozen=True)
class PanelAnalysis:
    """Complete evidence bundle used by the Streamlit interface and exports."""

    diagnostics: PanelDiagnostics
    pooled: PanelModelResult
    fixed_effects: PanelModelResult
    random_effects: PanelModelResult
    hausman: HausmanResult
    within_between: pd.DataFrame

    def model_comparison(self) -> pd.DataFrame:
        """Put estimates from the three models side by side."""

        frames: list[pd.DataFrame] = []
        for label, result in (
            ("pooled_ols", self.pooled),
            ("fixed_effects", self.fixed_effects),
            ("random_effects", self.random_effects),
        ):
            frame = result.coefficients[["term", "estimate", "std_error", "p_value"]].copy()
            frame = frame.rename(
                columns={
                    "estimate": f"{label}_estimate",
                    "std_error": f"{label}_std_error",
                    "p_value": f"{label}_p_value",
                }
            )
            frames.append(frame)

        comparison = frames[0]
        for frame in frames[1:]:
            comparison = comparison.merge(frame, on="term", how="outer")
        return comparison


def prepare_panel(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    *,
    missing: str = "raise",
) -> pd.DataFrame:
    """Select and explicitly handle rows needed for panel estimation.

    ``missing='drop'`` is intentionally explicit: AllocSignal never silently
    drops incomplete rows.  Predictors must already be numeric (for example,
    categories should first be encoded as documented dummy variables).
    """

    if not isinstance(data, pd.DataFrame):
        raise PanelValidationError("Panel data must be supplied as a pandas DataFrame.")
    if missing not in {"raise", "drop"}:
        raise PanelValidationError("missing must be either 'raise' or 'drop'.")

    predictor_list = _normalise_predictors(predictors)
    role_columns = [entity_col, time_col, outcome_col, *predictor_list]
    if any(not isinstance(column, str) or not column for column in role_columns):
        raise PanelValidationError("Entity, time, outcome, and predictor column names must be non-empty strings.")
    if len(set(role_columns)) != len(role_columns):
        raise PanelValidationError("Entity, time, outcome, and predictor roles must use distinct columns.")

    absent = [column for column in role_columns if column not in data.columns]
    if absent:
        raise PanelValidationError(f"Missing required panel columns: {', '.join(absent)}.")

    prepared = data.loc[:, role_columns].copy()
    missing_counts = prepared.isna().sum()
    missing_counts = missing_counts.loc[missing_counts > 0]
    if not missing_counts.empty:
        detail = ", ".join(f"{column}={int(count)}" for column, count in missing_counts.items())
        if missing == "raise":
            raise PanelValidationError(
                "Missing values found in model columns "
                f"({detail}). Resolve them or call prepare_panel(..., missing='drop') explicitly."
            )
        prepared = prepared.dropna(subset=role_columns).copy()

    if prepared.empty:
        raise PanelValidationError("No observations remain after preparing the panel.")

    invalid_key_columns: list[str] = []
    for column in (entity_col, time_col):
        if pd.api.types.is_numeric_dtype(prepared[column]):
            try:
                if not np.isfinite(prepared[column].to_numpy(dtype=float)).all():
                    invalid_key_columns.append(column)
            except (TypeError, ValueError):
                invalid_key_columns.append(column)
    if invalid_key_columns:
        raise PanelValidationError(
            "Numeric entity/time keys must be finite; invalid values found in: "
            + ", ".join(invalid_key_columns)
            + "."
        )

    numeric_columns = [outcome_col, *predictor_list]
    non_numeric = [column for column in numeric_columns if not pd.api.types.is_numeric_dtype(prepared[column])]
    if non_numeric:
        raise PanelValidationError(
            "Outcome and predictors must be numeric. Encode categorical controls explicitly; "
            f"non-numeric columns: {', '.join(non_numeric)}."
        )

    prepared[numeric_columns] = prepared[numeric_columns].astype(float)
    finite_mask = np.isfinite(prepared[numeric_columns].to_numpy(dtype=float))
    if not finite_mask.all():
        invalid_columns = [
            column for column, valid in zip(numeric_columns, finite_mask.all(axis=0), strict=True) if not valid
        ]
        raise PanelValidationError(
            "Outcome and predictors must contain only finite values; invalid values found in: "
            f"{', '.join(invalid_columns)}."
        )
    return prepared


def validate_panel(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    *,
    missing: str = "raise",
) -> PanelDiagnostics:
    """Validate panel keys and return variation/collinearity diagnostics."""

    predictor_list = _normalise_predictors(predictors)
    prepared = prepare_panel(
        data,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        missing=missing,
    )
    return _diagnose_prepared(prepared, entity_col, time_col, outcome_col, predictor_list)


def fit_pooled_ols(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    *,
    confidence_level: float = 0.95,
    time_effects: bool = False,
    cluster_robust: bool = True,
) -> PanelModelResult:
    """Fit pooled OLS, optionally with period controls and entity clustering."""

    prepared, diagnostics, predictor_list = _validated_inputs(
        data, entity_col, time_col, outcome_col, predictors, confidence_level
    )
    return _fit_pooled_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        cluster_robust,
    )


def fit_fixed_effects(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    *,
    confidence_level: float = 0.95,
    time_effects: bool = False,
    cluster_robust: bool = True,
) -> PanelModelResult:
    """Fit an entity fixed-effects model using the within transformation."""

    prepared, diagnostics, predictor_list = _validated_inputs(
        data, entity_col, time_col, outcome_col, predictors, confidence_level
    )
    return _fit_fixed_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        cluster_robust,
    )


def fit_random_effects(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    *,
    confidence_level: float = 0.95,
    time_effects: bool = False,
    cluster_robust: bool = True,
) -> PanelModelResult:
    """Fit feasible random effects by method-of-moments quasi-demeaning.

    The variance-components estimator supports both balanced and unbalanced
    panels.  It clips a negative estimated entity variance at zero and reports
    that boundary case as a warning.
    """

    prepared, diagnostics, predictor_list = _validated_inputs(
        data, entity_col, time_col, outcome_col, predictors, confidence_level
    )
    return _fit_random_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        cluster_robust,
    )


def hausman_test(
    fixed_effects: PanelModelResult,
    random_effects: PanelModelResult,
    predictors: Sequence[str],
    *,
    alpha: float = 0.05,
    covariance_basis: str = "Provided FE and RE covariance matrices",
) -> HausmanResult:
    """Compare common FE and RE slopes with a generalized Hausman statistic.

    The classical chi-square interpretation expects compatible, conventional
    model-based FE and RE covariance matrices. ``analyze_panel`` supplies those
    from separate refits; callers using this lower-level helper must choose and
    label the covariance basis explicitly.
    """

    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1.")
    predictor_list = _normalise_predictors(predictors)
    fe_terms = set(fixed_effects.coefficients["term"])
    re_terms = set(random_effects.coefficients["term"])
    terms = tuple(term for term in predictor_list if term in fe_terms and term in re_terms)
    if not terms:
        message = (
            "No substantive predictor slope is estimable in both FE and RE, so a Hausman "
            "coefficient-difference test cannot be computed."
        )
        return HausmanResult(
            statistic=float("nan"),
            degrees_of_freedom=0,
            p_value=float("nan"),
            compared_terms=(),
            covariance_difference_psd=False,
            conclusion=message,
            covariance_basis=covariance_basis,
            warnings=(message,),
        )

    fe_estimates = fixed_effects.coefficients.set_index("term").loc[list(terms), "estimate"].to_numpy(dtype=float)
    re_estimates = random_effects.coefficients.set_index("term").loc[list(terms), "estimate"].to_numpy(dtype=float)
    difference = fe_estimates - re_estimates
    fixed_covariance = fixed_effects.covariance.loc[list(terms), list(terms)].copy()
    random_covariance = random_effects.covariance.loc[list(terms), list(terms)].copy()
    covariance_difference = (
        fixed_covariance.to_numpy(dtype=float)
        - random_covariance.to_numpy(dtype=float)
    )
    covariance_difference = (covariance_difference + covariance_difference.T) / 2.0
    covariance_difference_frame = pd.DataFrame(
        covariance_difference,
        index=list(terms),
        columns=list(terms),
    )

    # Rank and PSD checks must be relative to the covariance scale.  A fixed
    # absolute floor would misclassify perfectly informative coefficients that
    # happen to be measured in large units (and therefore have tiny variances).
    scale = max(float(np.max(np.abs(covariance_difference))), np.finfo(float).tiny)
    tolerance = scale * 1e-9
    eigenvalues = np.linalg.eigvalsh(covariance_difference)
    covariance_psd = bool(np.all(eigenvalues >= -tolerance))
    covariance_rank = int(np.linalg.matrix_rank(covariance_difference, tol=tolerance))
    degrees_of_freedom = covariance_rank

    if covariance_rank == 0:
        message = (
            "The FE-minus-RE covariance difference has rank zero, so the Hausman quadratic "
            "form has no estimable comparison direction."
        )
        return HausmanResult(
            statistic=float("nan"),
            degrees_of_freedom=0,
            p_value=float("nan"),
            compared_terms=terms,
            covariance_difference_psd=covariance_psd,
            conclusion=message,
            covariance_basis=covariance_basis,
            warnings=(message,),
            fixed_covariance=fixed_covariance,
            random_covariance=random_covariance,
            covariance_difference=covariance_difference_frame,
        )

    inverse = np.linalg.pinv(covariance_difference, rcond=1e-10)
    raw_statistic = float(difference.T @ inverse @ difference)
    warning_messages: list[str] = []
    if not covariance_psd:
        warning_messages.append(
            "The FE-minus-RE covariance difference is not positive semidefinite. "
            "The pseudoinverse result and p-value are indicative, not a textbook Hausman test."
        )
    if covariance_rank < len(terms):
        warning_messages.append(
            f"The covariance difference has rank {covariance_rank} for {len(terms)} compared slopes; "
            "the generalized test uses its estimable subspace."
        )
    if raw_statistic < 0:
        warning_messages.append(
            "The indefinite covariance difference produced a negative quadratic form; the displayed statistic is bounded at zero."
        )
    statistic = max(0.0, raw_statistic)
    p_value = float(stats.chi2.sf(statistic, degrees_of_freedom))

    if not covariance_psd:
        conclusion = (
            "The conventional Hausman assumptions are numerically unresolved here. Compare FE and RE estimates, "
            "inspect the panel design, and do not treat this p-value as a model-selection rule."
        )
    elif p_value < alpha:
        conclusion = (
            "FE and RE slopes differ more than expected from their estimated sampling variation. "
            "The RE orthogonality assumption is questionable; FE is safer for within-entity association."
        )
    else:
        conclusion = (
            "The diagnostic does not find a clear systematic FE–RE difference. "
            "This does not prove the RE orthogonality assumption or establish causality."
        )
    return HausmanResult(
        statistic=statistic,
        degrees_of_freedom=degrees_of_freedom,
        p_value=p_value,
        compared_terms=terms,
        covariance_difference_psd=covariance_psd,
        conclusion=conclusion,
        covariance_basis=covariance_basis,
        warnings=tuple(warning_messages),
        fixed_covariance=fixed_covariance,
        random_covariance=random_covariance,
        covariance_difference=covariance_difference_frame,
    )


def within_between_diagnostics(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
) -> pd.DataFrame:
    """Contrast unadjusted pooled, within, and between slopes one variable at a time.

    Direction reversals are useful Simpson-risk flags, not tests of bias and not
    causal evidence.  The multivariable estimators remain the primary results.
    """

    prepared, _, predictor_list = _validated_inputs(
        data, entity_col, time_col, outcome_col, predictors, confidence_level=0.95
    )
    grouped = prepared.groupby(entity_col, observed=True, sort=False)
    y = prepared[outcome_col].to_numpy(dtype=float)
    y_within = (prepared[outcome_col] - grouped[outcome_col].transform("mean")).to_numpy(dtype=float)
    means = grouped[[outcome_col, *predictor_list]].mean()

    rows: list[dict[str, object]] = []
    for predictor in predictor_list:
        x = prepared[predictor].to_numpy(dtype=float)
        x_within = (prepared[predictor] - grouped[predictor].transform("mean")).to_numpy(dtype=float)
        pooled_slope = _simple_slope(x, y)
        within_slope = _simple_slope(x_within, y_within, already_centered=True)
        between_slope = _simple_slope(
            means[predictor].to_numpy(dtype=float), means[outcome_col].to_numpy(dtype=float)
        )
        pooled_reversal = _opposite_direction(pooled_slope, within_slope)
        between_reversal = _opposite_direction(between_slope, within_slope)
        simpson_risk = pooled_reversal or between_reversal
        if simpson_risk:
            interpretation = (
                "Direction changes across aggregation levels. Stable entity differences may be masking the within-entity association."
            )
        elif not np.isfinite(within_slope):
            interpretation = "No usable within-entity variation; an entity fixed-effects slope is not identified."
        else:
            interpretation = (
                "Directions are not reversed, but pooled and within slopes can still differ because they answer different questions."
            )
        rows.append(
            {
                "predictor": predictor,
                "pooled_slope": pooled_slope,
                "within_slope": within_slope,
                "between_slope": between_slope,
                "pooled_within_reversal": pooled_reversal,
                "between_within_reversal": between_reversal,
                "simpson_risk": simpson_risk,
                "interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows)


def analyze_panel(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    *,
    confidence_level: float = 0.95,
    time_effects: bool = False,
    cluster_robust: bool = True,
) -> PanelAnalysis:
    """Run validation, three estimators, Hausman, and aggregation diagnostics."""

    prepared, diagnostics, predictor_list = _validated_inputs(
        data, entity_col, time_col, outcome_col, predictors, confidence_level
    )
    pooled = _fit_pooled_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        cluster_robust,
    )
    fixed = _fit_fixed_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        cluster_robust,
    )
    random = _fit_random_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        cluster_robust,
    )
    # A classical Hausman quadratic form relies on the model-based FE and RE
    # covariance relationship under the RE null.  Sandwich covariances used for
    # the displayed confidence intervals do not generally preserve that
    # relationship, even when their numerical difference happens to be PSD.
    # Refit only the covariance layer conventionally and label it explicitly.
    hausman_fixed = _fit_fixed_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        False,
        model_based_covariance=True,
    )
    hausman_random = _fit_random_prepared(
        prepared,
        diagnostics,
        entity_col,
        time_col,
        outcome_col,
        predictor_list,
        confidence_level,
        time_effects,
        False,
        model_based_covariance=True,
    )
    displayed_basis = "entity-clustered/robust" if cluster_robust else "HC1 robust"
    covariance_basis = (
        "Conventional model-based covariance from separate FE and RE refits; "
        f"displayed coefficient intervals use {displayed_basis} covariance."
    )
    hausman = hausman_test(
        hausman_fixed,
        hausman_random,
        predictor_list,
        covariance_basis=covariance_basis,
    )
    within_between = _within_between_prepared(prepared, entity_col, outcome_col, predictor_list)
    return PanelAnalysis(
        diagnostics=diagnostics,
        pooled=pooled,
        fixed_effects=fixed,
        random_effects=random,
        hausman=hausman,
        within_between=within_between,
    )


def _normalise_predictors(predictors: Sequence[str]) -> list[str]:
    if isinstance(predictors, str):
        raise PanelValidationError("predictors must be a sequence of column names, not one string.")
    predictor_list = list(predictors)
    if not predictor_list:
        raise PanelValidationError("Select at least one predictor.")
    if len(set(predictor_list)) != len(predictor_list):
        raise PanelValidationError("Predictor names must be unique.")
    return predictor_list


def _validated_inputs(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    confidence_level: float,
) -> tuple[pd.DataFrame, PanelDiagnostics, list[str]]:
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1.")
    predictor_list = _normalise_predictors(predictors)
    prepared = prepare_panel(data, entity_col, time_col, outcome_col, predictor_list)
    diagnostics = _diagnose_prepared(prepared, entity_col, time_col, outcome_col, predictor_list)
    return prepared, diagnostics, predictor_list


def _diagnose_prepared(
    data: pd.DataFrame,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
) -> PanelDiagnostics:
    duplicate_mask = data.duplicated([entity_col, time_col], keep=False)
    if duplicate_mask.any():
        examples = data.loc[duplicate_mask, [entity_col, time_col]].drop_duplicates().head(3)
        rendered = "; ".join(f"{row[entity_col]} × {row[time_col]}" for _, row in examples.iterrows())
        raise PanelValidationError(
            f"Entity × time keys must be unique; found {int(duplicate_mask.sum())} rows in duplicate keys"
            f" (for example: {rendered})."
        )

    entity_counts = data.groupby(entity_col, observed=True, sort=False).size()
    n_entities = int(entity_counts.size)
    n_periods = int(data[time_col].nunique(dropna=False))
    n_observations = int(len(data))
    if n_entities < 2:
        raise PanelValidationError("Panel analysis needs at least two entities.")
    if n_periods < 2:
        raise PanelValidationError("Panel analysis needs at least two distinct time periods.")
    if int(entity_counts.min()) < 2:
        singleton_count = int((entity_counts < 2).sum())
        raise PanelValidationError(
            f"Every entity needs repeated observations; {singleton_count} entities have fewer than two rows."
        )
    if n_observations <= n_entities + 1:
        raise PanelValidationError("Too few observations remain to estimate within-entity sampling variation.")

    warning_messages: list[str] = []
    variation_rows: list[dict[str, object]] = []
    for column in [outcome_col, *predictors]:
        values = data[column].to_numpy(dtype=float)
        overall_centered = values - values.mean()
        group_means = data.groupby(entity_col, observed=True, sort=False)[column].transform("mean").to_numpy(dtype=float)
        within_centered = values - group_means
        group_mean_table = data.groupby(entity_col, observed=True, sort=False)[column].mean()
        weighted_between = group_means - values.mean()
        overall_ss = float(overall_centered @ overall_centered)
        within_ss = float(within_centered @ within_centered)
        between_ss = float(weighted_between @ weighted_between)
        tolerance = _sum_squares_tolerance(values)

        if overall_ss <= tolerance:
            raise PanelValidationError(f"{column!r} has no usable overall variation.")
        within_identified = within_ss > tolerance
        between_identified = between_ss > tolerance
        changes = data.groupby(entity_col, observed=True, sort=False)[column].agg(lambda series: float(series.max() - series.min()))
        entity_scale = max(1.0, float(np.max(np.abs(values))))
        entities_with_change = float((changes > np.finfo(float).eps * entity_scale * 100).mean())

        if column == outcome_col and not within_identified:
            raise PanelValidationError(f"Outcome {outcome_col!r} has no usable within-entity variation.")
        if column != outcome_col and not within_identified:
            warning_messages.append(
                f"Predictor {column!r} has no within-entity variation and will be omitted from entity fixed effects."
            )
        if column != outcome_col and not between_identified:
            warning_messages.append(f"Predictor {column!r} has no between-entity variation.")

        variation_rows.append(
            {
                "variable": column,
                "role": "outcome" if column == outcome_col else "predictor",
                "overall_sd": float(np.sqrt(overall_ss / max(1, n_observations - 1))),
                "within_sd": float(np.sqrt(within_ss / max(1, n_observations - n_entities))),
                "between_sd": float(group_mean_table.std(ddof=1)),
                "within_share_of_total_ss": float(within_ss / overall_ss),
                "entities_with_change_share": entities_with_change,
                "within_identified": within_identified,
                "between_identified": between_identified,
            }
        )

    vif, condition_number = _collinearity_diagnostics(data, predictors)
    high_vif = vif.loc[np.isfinite(vif["vif"]) & (vif["vif"] >= 10), "term"].tolist()
    infinite_vif = vif.loc[~np.isfinite(vif["vif"]), "term"].tolist()
    if high_vif or infinite_vif:
        affected = high_vif + infinite_vif
        warning_messages.append(
            "Strong predictor collinearity is indicated for: " + ", ".join(dict.fromkeys(affected)) + "."
        )
    if condition_number >= 30:
        warning_messages.append(
            f"The standardized predictor condition number is {condition_number:.1f}; individual slopes may be unstable."
        )
    if n_entities < 10:
        warning_messages.append(
            f"Only {n_entities} entities are available; entity-clustered standard errors can be unstable in small samples."
        )

    return PanelDiagnostics(
        n_observations=n_observations,
        n_entities=n_entities,
        n_periods=n_periods,
        min_periods_per_entity=int(entity_counts.min()),
        max_periods_per_entity=int(entity_counts.max()),
        balanced=bool(entity_counts.nunique() == 1 and int(entity_counts.iloc[0]) == n_periods),
        variation=pd.DataFrame(variation_rows),
        vif=vif,
        condition_number=condition_number,
        warnings=tuple(warning_messages),
    )


def _collinearity_diagnostics(data: pd.DataFrame, predictors: Sequence[str]) -> tuple[pd.DataFrame, float]:
    matrix = data[list(predictors)].astype(float)
    standard_deviations = matrix.std(ddof=0)
    standardized = (matrix - matrix.mean()) / standard_deviations
    values = standardized.to_numpy(dtype=float)
    condition_number = float(np.linalg.cond(values))
    if len(predictors) == 1:
        return pd.DataFrame({"term": list(predictors), "vif": [1.0]}), condition_number

    design = sm.add_constant(standardized, has_constant="add").to_numpy(dtype=float)
    vif_values: list[float] = []
    with python_warnings.catch_warnings():
        python_warnings.simplefilter("ignore")
        for position in range(1, design.shape[1]):
            try:
                vif_values.append(float(variance_inflation_factor(design, position)))
            except (ValueError, np.linalg.LinAlgError):
                vif_values.append(float("inf"))
    return pd.DataFrame({"term": list(predictors), "vif": vif_values}), condition_number


def _design_matrix(
    data: pd.DataFrame,
    time_col: str,
    predictors: Sequence[str],
    time_effects: bool,
    *,
    include_intercept: bool,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    predictor_design = data[list(predictors)].astype(float).copy()
    if include_intercept and "const" in predictor_design.columns:
        raise PanelValidationError(
            "Predictor name 'const' is reserved for the model intercept. Rename that input column."
        )
    design = pd.DataFrame(index=data.index)
    time_terms: tuple[str, ...] = ()
    if time_effects:
        dummies = pd.get_dummies(
            data[time_col].astype("category"),
            prefix="__period",
            prefix_sep="=",
            drop_first=True,
            dtype=float,
        )
        duplicate_names = set(predictor_design.columns) & set(dummies.columns)
        if duplicate_names:
            raise PanelValidationError(f"Generated time-control names collide with predictors: {duplicate_names}.")
        # Period controls deliberately precede substantive predictors.  The
        # independent-column selector is order preserving, so a predictor that
        # is fully determined by period is omitted rather than silently
        # weakening the requested time fixed-effects basis.
        design = pd.concat([design, dummies], axis=1)
        time_terms = tuple(dummies.columns.astype(str))
    design = pd.concat([design, predictor_design], axis=1)
    if include_intercept:
        design.insert(0, "const", 1.0)
    return design, time_terms


def _select_independent_columns(
    design: pd.DataFrame,
    *,
    allow_empty: bool = False,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    selected: list[str] = []
    dropped: list[str] = []
    current_rank = 0
    for column in design.columns:
        values = design[column].to_numpy(dtype=float)
        absolute_scale = max(1.0, float(np.max(np.abs(design.to_numpy(dtype=float)))))
        zero_tolerance = np.finfo(float).eps * max(design.shape) * absolute_scale * 100
        if float(np.linalg.norm(values)) <= zero_tolerance:
            dropped.append(column)
            continue
        candidate_columns = [*selected, column]
        candidate = design[candidate_columns].to_numpy(dtype=float)
        candidate_rank = int(np.linalg.matrix_rank(candidate))
        if candidate_rank > current_rank:
            selected.append(column)
            current_rank = candidate_rank
        else:
            dropped.append(column)
    if not selected and not allow_empty:
        raise PanelValidationError("The model design has no estimable columns after removing absorbed terms.")
    return design[selected], tuple(dropped)


def _fit_with_covariance(
    outcome: pd.Series,
    design: pd.DataFrame,
    groups: pd.Series,
    cluster_robust: bool,
    *,
    model_based: bool = False,
) -> tuple[object, str, tuple[str, ...]]:
    if len(outcome) <= np.linalg.matrix_rank(design.to_numpy(dtype=float)):
        raise PanelValidationError("The model has no residual degrees of freedom; reduce controls or add observations.")
    model = sm.OLS(outcome.astype(float), design.astype(float), missing="raise")
    warning_messages: list[str] = []
    if model_based:
        return model.fit(use_t=True), "conventional model-based", ()
    n_groups = int(groups.nunique())
    if cluster_robust and n_groups >= 3:
        try:
            result = model.fit(
                cov_type="cluster",
                cov_kwds={
                    "groups": groups.to_numpy(),
                    "use_correction": True,
                    "df_correction": True,
                },
                use_t=True,
            )
            covariance_label = "entity-clustered"
            if n_groups < 10:
                warning_messages.append(
                    f"Cluster-robust inference uses only {n_groups} entity clusters and may be unstable."
                )
            return result, covariance_label, tuple(warning_messages)
        except (ValueError, np.linalg.LinAlgError, ZeroDivisionError) as error:
            warning_messages.append(
                f"Entity-clustered covariance failed ({type(error).__name__}); HC1 heteroskedasticity-robust inference is shown."
            )
    elif cluster_robust:
        warning_messages.append(
            f"Entity clustering needs at least three clusters in this implementation; HC1 is shown for {n_groups} entities."
        )

    try:
        result = model.fit(cov_type="HC1", use_t=True)
        return result, "HC1 heteroskedasticity-robust", tuple(warning_messages)
    except (ValueError, np.linalg.LinAlgError, ZeroDivisionError) as error:
        warning_messages.append(
            f"HC1 covariance failed ({type(error).__name__}); conventional OLS covariance is shown."
        )
        return model.fit(), "conventional OLS", tuple(warning_messages)


def _coefficient_frame(result: object, columns: Sequence[str], confidence_level: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    estimates = np.asarray(result.params, dtype=float)
    standard_errors = np.asarray(result.bse, dtype=float)
    statistics = np.asarray(result.tvalues, dtype=float)
    p_values = np.asarray(result.pvalues, dtype=float)
    intervals = np.asarray(result.conf_int(alpha=1.0 - confidence_level), dtype=float)
    coefficients = pd.DataFrame(
        {
            "term": list(columns),
            "estimate": estimates,
            "std_error": standard_errors,
            "ci_lower": intervals[:, 0],
            "ci_upper": intervals[:, 1],
            "statistic": statistics,
            "p_value": p_values,
        }
    )
    covariance = pd.DataFrame(np.asarray(result.cov_params(), dtype=float), index=columns, columns=columns)
    return coefficients, covariance


def _fit_pooled_prepared(
    data: pd.DataFrame,
    diagnostics: PanelDiagnostics,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    confidence_level: float,
    time_effects: bool,
    cluster_robust: bool,
) -> PanelModelResult:
    design, time_terms = _design_matrix(data, time_col, predictors, time_effects, include_intercept=True)
    design, dropped = _select_independent_columns(design)
    result, covariance_label, covariance_warnings = _fit_with_covariance(
        data[outcome_col], design, data[entity_col], cluster_robust
    )
    coefficients, covariance = _coefficient_frame(result, design.columns, confidence_level)
    fitted = pd.Series(design.to_numpy(dtype=float) @ np.asarray(result.params), index=data.index, name="fitted")
    residuals = pd.Series(data[outcome_col].to_numpy(dtype=float) - fitted.to_numpy(), index=data.index, name="residual")
    warning_messages = list(covariance_warnings)
    if dropped:
        warning_messages.append("Perfectly collinear terms were omitted from pooled OLS: " + ", ".join(dropped) + ".")
    notes = [
        "Pooled OLS combines within-entity changes and stable between-entity differences.",
        f"Coefficient inference uses {covariance_label} standard errors.",
        "Coefficients are conditional associations in the observed sample, not causal effects.",
    ]
    if time_terms:
        notes.append("Period indicators control for shocks shared by every entity in a period.")
    return PanelModelResult(
        estimator="Pooled OLS",
        coefficients=coefficients,
        covariance=covariance,
        fitted_values=fitted,
        residuals=residuals,
        metrics={
            "r_squared": float(result.rsquared),
            "adjusted_r_squared": float(result.rsquared_adj),
            "rmse": float(np.sqrt(np.mean(np.square(residuals.to_numpy(dtype=float))))),
            "residual_degrees_of_freedom": float(result.df_resid),
        },
        nobs=diagnostics.n_observations,
        n_entities=diagnostics.n_entities,
        n_periods=diagnostics.n_periods,
        notes=tuple(notes),
        warnings=tuple(warning_messages),
    )


def _fit_fixed_prepared(
    data: pd.DataFrame,
    diagnostics: PanelDiagnostics,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    confidence_level: float,
    time_effects: bool,
    cluster_robust: bool,
    *,
    model_based_covariance: bool = False,
) -> PanelModelResult:
    design, time_terms = _design_matrix(data, time_col, predictors, time_effects, include_intercept=False)
    entity = data[entity_col]
    within_design = design - design.groupby(entity, observed=True, sort=False).transform("mean")
    within_design, dropped = _select_independent_columns(within_design, allow_empty=True)
    outcome = data[outcome_col]
    within_outcome = outcome - outcome.groupby(entity, observed=True, sort=False).transform("mean")
    if float(np.square(within_outcome.to_numpy(dtype=float)).sum()) <= _sum_squares_tolerance(outcome.to_numpy()):
        raise PanelValidationError("The outcome has no estimable within-entity variation.")

    if within_design.empty:
        coefficient_columns = [
            "term",
            "estimate",
            "std_error",
            "ci_lower",
            "ci_upper",
            "statistic",
            "p_value",
        ]
        coefficients = pd.DataFrame(columns=coefficient_columns)
        covariance = pd.DataFrame(dtype=float)
        covariance_label = "not applicable (no estimable within slopes)"
        covariance_warnings: tuple[str, ...] = ()
        residual_values = within_outcome.to_numpy(dtype=float)
        metrics = {
            "r_squared": 0.0,
            "within_r_squared": 0.0,
            "adjusted_within_r_squared": float("nan"),
            "rmse": float(np.sqrt(np.mean(np.square(residual_values)))),
            "residual_degrees_of_freedom": float(
                diagnostics.n_observations - diagnostics.n_entities
            ),
        }
    else:
        result, covariance_label, covariance_warnings = _fit_with_covariance(
            within_outcome,
            within_design,
            entity,
            cluster_robust,
            model_based=model_based_covariance,
        )
        coefficients, covariance = _coefficient_frame(result, within_design.columns, confidence_level)
        within_fitted = within_design.to_numpy(dtype=float) @ np.asarray(result.params)
        residual_values = within_outcome.to_numpy(dtype=float) - within_fitted
        metrics = {
            "r_squared": float(result.rsquared),
            "within_r_squared": float(result.rsquared),
            "adjusted_within_r_squared": float(result.rsquared_adj),
            "rmse": float(np.sqrt(np.mean(np.square(residual_values)))),
            "residual_degrees_of_freedom": float(result.df_resid),
        }
    residuals = pd.Series(residual_values, index=data.index, name="residual")
    fitted = pd.Series(outcome.to_numpy(dtype=float) - residual_values, index=data.index, name="fitted")

    warning_messages = list(covariance_warnings)
    omitted_predictors = [term for term in dropped if term in predictors]
    omitted_time = [term for term in dropped if term in time_terms]
    if omitted_predictors:
        warning_messages.append(
            "Predictors absorbed or made collinear by the within transformation were omitted: "
            + ", ".join(omitted_predictors)
            + "."
        )
    if omitted_time:
        warning_messages.append("Collinear period indicators were omitted: " + ", ".join(omitted_time) + ".")
    if within_design.empty:
        warning_messages.append(
            "No predictor has an estimable within-entity slope; the FE result contains entity means only."
        )
    notes = [
        "Entity fixed effects remove every stable observed or unobserved entity attribute by within transformation.",
        "The intercept and entity-specific levels are absorbed and are not reported as coefficients.",
        f"Coefficient inference uses {covariance_label} standard errors.",
        "Slopes describe conditional within-entity associations; fixed effects alone do not establish causality.",
    ]
    if time_terms:
        notes.append("Period indicators control for shocks shared by every entity in a period.")
    return PanelModelResult(
        estimator="Entity fixed effects",
        coefficients=coefficients,
        covariance=covariance,
        fitted_values=fitted,
        residuals=residuals,
        metrics=metrics,
        nobs=diagnostics.n_observations,
        n_entities=diagnostics.n_entities,
        n_periods=diagnostics.n_periods,
        notes=tuple(notes),
        warnings=tuple(warning_messages),
    )


def _fit_random_prepared(
    data: pd.DataFrame,
    diagnostics: PanelDiagnostics,
    entity_col: str,
    time_col: str,
    outcome_col: str,
    predictors: Sequence[str],
    confidence_level: float,
    time_effects: bool,
    cluster_robust: bool,
    *,
    model_based_covariance: bool = False,
) -> PanelModelResult:
    entity = data[entity_col]
    outcome = data[outcome_col].astype(float)
    original_design, time_terms = _design_matrix(
        data, time_col, predictors, time_effects, include_intercept=True
    )
    original_design, original_dropped = _select_independent_columns(original_design)

    within_base = original_design.drop(columns=["const"], errors="ignore")
    within_design = within_base - within_base.groupby(entity, observed=True, sort=False).transform("mean")
    try:
        within_design, within_dropped = _select_independent_columns(within_design)
    except PanelValidationError:
        within_dropped = tuple(within_design.columns)
        within_design = pd.DataFrame(index=data.index)
    within_outcome = outcome - outcome.groupby(entity, observed=True, sort=False).transform("mean")
    within_rank = 0 if within_design.empty else int(np.linalg.matrix_rank(within_design.to_numpy(dtype=float)))
    sigma_e_df = diagnostics.n_observations - diagnostics.n_entities - within_rank
    if sigma_e_df <= 0:
        raise PanelValidationError("Too few residual degrees of freedom to estimate the random-effects variance components.")
    if within_design.empty:
        within_residuals = within_outcome.to_numpy(dtype=float)
    else:
        within_fit = sm.OLS(within_outcome, within_design, missing="raise").fit()
        within_residuals = np.asarray(within_fit.resid, dtype=float)
    sigma_e2 = float(np.square(within_residuals).sum() / sigma_e_df)

    pooled_fit = sm.OLS(outcome, original_design, missing="raise").fit()
    pooled_residuals = pd.Series(np.asarray(pooled_fit.resid, dtype=float), index=data.index)
    residual_means = pooled_residuals.groupby(entity, observed=True, sort=False).mean()
    entity_counts = data.groupby(entity_col, observed=True, sort=False).size().astype(float)
    between_residual_variance = float(residual_means.var(ddof=1))
    sampling_correction = float((sigma_e2 / entity_counts).mean())
    raw_sigma_u2 = between_residual_variance - sampling_correction
    sigma_u2 = max(0.0, raw_sigma_u2)

    denominator = sigma_e2 + entity_counts * sigma_u2
    if sigma_e2 <= np.finfo(float).eps and sigma_u2 <= np.finfo(float).eps:
        theta_by_entity = pd.Series(0.0, index=entity_counts.index)
    else:
        theta_by_entity = 1.0 - np.sqrt(sigma_e2 / denominator.clip(lower=np.finfo(float).eps))
    theta_rows = entity.map(theta_by_entity).astype(float)
    outcome_means = outcome.groupby(entity, observed=True, sort=False).transform("mean")
    quasi_outcome = outcome - theta_rows * outcome_means
    design_means = original_design.groupby(entity, observed=True, sort=False).transform("mean")
    quasi_design = original_design - design_means.mul(theta_rows, axis=0)
    quasi_design, quasi_dropped = _select_independent_columns(quasi_design)

    result, covariance_label, covariance_warnings = _fit_with_covariance(
        quasi_outcome,
        quasi_design,
        entity,
        cluster_robust,
        model_based=model_based_covariance,
    )
    coefficients, covariance = _coefficient_frame(result, quasi_design.columns, confidence_level)

    marginal_fitted_values = original_design[list(quasi_design.columns)].to_numpy(dtype=float) @ np.asarray(result.params)
    marginal_residuals = outcome.to_numpy(dtype=float) - marginal_fitted_values
    residual_mean_by_entity = pd.Series(marginal_residuals, index=data.index).groupby(
        entity, observed=True, sort=False
    ).mean()
    shrinkage = (entity_counts * sigma_u2) / (sigma_e2 + entity_counts * sigma_u2).clip(lower=np.finfo(float).eps)
    random_intercepts = residual_mean_by_entity * shrinkage
    conditional_fitted_values = marginal_fitted_values + entity.map(random_intercepts).to_numpy(dtype=float)
    residual_values = outcome.to_numpy(dtype=float) - conditional_fitted_values
    fitted = pd.Series(conditional_fitted_values, index=data.index, name="fitted")
    residuals = pd.Series(residual_values, index=data.index, name="residual")

    total_ss = float(np.square(outcome.to_numpy(dtype=float) - outcome.mean()).sum())
    marginal_r_squared = 1.0 - float(np.square(marginal_residuals).sum()) / total_ss
    conditional_r_squared = 1.0 - float(np.square(residual_values).sum()) / total_ss
    rho = sigma_u2 / (sigma_u2 + sigma_e2) if sigma_u2 + sigma_e2 > 0 else 0.0

    warning_messages = list(covariance_warnings)
    model_omitted_predictors = [
        term
        for term in dict.fromkeys([*original_dropped, *quasi_dropped])
        if term in predictors
    ]
    within_only_predictors = [
        term
        for term in within_dropped
        if term in predictors and term not in model_omitted_predictors
    ]
    if model_omitted_predictors:
        warning_messages.append(
            "Predictors collinear with protected model controls were omitted from random effects: "
            + ", ".join(model_omitted_predictors)
            + "."
        )
    if within_only_predictors:
        warning_messages.append(
            "Predictors without usable within-entity variation were omitted only from the idiosyncratic-variance step: "
            + ", ".join(within_only_predictors)
            + ". Their RE coefficients rely on between-entity variation."
        )
    if raw_sigma_u2 < 0:
        warning_messages.append(
            "The method-of-moments entity variance estimate was negative and was clipped to zero; RE therefore approaches pooled OLS."
        )
    elif sigma_u2 <= np.finfo(float).eps:
        warning_messages.append("Estimated entity-level variance is approximately zero; RE approaches pooled OLS.")
    notes = [
        "Random effects uses entity-size-specific quasi-demeaning, so it supports balanced and unbalanced panels.",
        "Idiosyncratic variance comes from within residuals; entity variance is a pooled-residual method-of-moments estimate.",
        "In-sample fitted values include shrunken entity intercepts; marginal and conditional R² are reported separately.",
        f"Coefficient inference uses {covariance_label} standard errors.",
        "RE requires stable entity effects to be uncorrelated with every included predictor; the Hausman diagnostic probes, but cannot prove, that assumption.",
        "Slopes are conditional associations and should not be presented as causal effects without a credible identification design.",
    ]
    if time_terms:
        notes.append("Period indicators control for shocks shared by every entity in a period.")
    return PanelModelResult(
        estimator="Random effects",
        coefficients=coefficients,
        covariance=covariance,
        fitted_values=fitted,
        residuals=residuals,
        metrics={
            "r_squared": float(conditional_r_squared),
            "marginal_r_squared": float(marginal_r_squared),
            "conditional_r_squared": float(conditional_r_squared),
            "rmse": float(np.sqrt(np.mean(np.square(residual_values)))),
            "sigma_idiosyncratic_squared": float(sigma_e2),
            "sigma_entity_squared": float(sigma_u2),
            "intraclass_correlation": float(rho),
            "theta_min": float(theta_by_entity.min()),
            "theta_mean": float(theta_by_entity.mean()),
            "theta_max": float(theta_by_entity.max()),
            "residual_degrees_of_freedom": float(result.df_resid),
        },
        nobs=diagnostics.n_observations,
        n_entities=diagnostics.n_entities,
        n_periods=diagnostics.n_periods,
        notes=tuple(notes),
        warnings=tuple(warning_messages),
    )


def _within_between_prepared(
    data: pd.DataFrame,
    entity_col: str,
    outcome_col: str,
    predictors: Sequence[str],
) -> pd.DataFrame:
    grouped = data.groupby(entity_col, observed=True, sort=False)
    y = data[outcome_col].to_numpy(dtype=float)
    y_within = (data[outcome_col] - grouped[outcome_col].transform("mean")).to_numpy(dtype=float)
    means = grouped[[outcome_col, *predictors]].mean()
    rows: list[dict[str, object]] = []
    for predictor in predictors:
        x = data[predictor].to_numpy(dtype=float)
        x_within = (data[predictor] - grouped[predictor].transform("mean")).to_numpy(dtype=float)
        pooled_slope = _simple_slope(x, y)
        within_slope = _simple_slope(x_within, y_within, already_centered=True)
        between_slope = _simple_slope(
            means[predictor].to_numpy(dtype=float), means[outcome_col].to_numpy(dtype=float)
        )
        pooled_reversal = _opposite_direction(pooled_slope, within_slope)
        between_reversal = _opposite_direction(between_slope, within_slope)
        simpson_risk = pooled_reversal or between_reversal
        if simpson_risk:
            interpretation = (
                "Direction changes across aggregation levels. Stable entity differences may be masking the within-entity association."
            )
        elif not np.isfinite(within_slope):
            interpretation = "No usable within-entity variation; an entity fixed-effects slope is not identified."
        else:
            interpretation = (
                "Directions are not reversed, but pooled and within slopes can still differ because they answer different questions."
            )
        rows.append(
            {
                "predictor": predictor,
                "pooled_slope": pooled_slope,
                "within_slope": within_slope,
                "between_slope": between_slope,
                "pooled_within_reversal": pooled_reversal,
                "between_within_reversal": between_reversal,
                "simpson_risk": simpson_risk,
                "interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows)


def _simple_slope(x: np.ndarray, y: np.ndarray, *, already_centered: bool = False) -> float:
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    if not already_centered:
        x_values = x_values - x_values.mean()
        y_values = y_values - y_values.mean()
    denominator = float(x_values @ x_values)
    if denominator <= _sum_squares_tolerance(x_values):
        return float("nan")
    return float((x_values @ y_values) / denominator)


def _opposite_direction(first: float, second: float) -> bool:
    if not np.isfinite(first) or not np.isfinite(second):
        return False
    scale = max(1.0, abs(first), abs(second))
    tolerance = np.finfo(float).eps * scale * 100
    return bool(abs(first) > tolerance and abs(second) > tolerance and np.sign(first) != np.sign(second))


def _sum_squares_tolerance(values: np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    scale = max(float(np.max(np.abs(array))), np.sqrt(np.finfo(float).tiny))
    return float(np.finfo(float).eps * max(1, array.size) * scale**2 * 100)
