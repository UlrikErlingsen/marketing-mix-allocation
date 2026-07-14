from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from allocsignal.panel import (
    PanelModelResult,
    PanelValidationError,
    analyze_panel,
    fit_fixed_effects,
    fit_pooled_ols,
    fit_random_effects,
    hausman_test,
    prepare_panel,
    validate_panel,
    within_between_diagnostics,
)


def simulated_panel(seed: int = 47, entities: int = 60, periods: int = 12) -> pd.DataFrame:
    """Panel with predictor/entity correlation and known within slopes."""

    rng = np.random.default_rng(seed)
    rows: list[dict[str, float | int | str]] = []
    entity_effects = rng.normal(0.0, 2.0, size=entities)
    for entity_index, entity_effect in enumerate(entity_effects):
        stable_exposure = 0.9 * entity_effect + rng.normal(0.0, 0.25)
        for period in range(periods):
            shared_period_shock = 0.12 * period
            search = stable_exposure + rng.normal(0.0, 1.0)
            distribution = rng.normal(0.0, 1.0) + 0.15 * np.sin(period)
            sales = (
                6.0
                + entity_effect
                + shared_period_shock
                + 2.0 * search
                - 0.75 * distribution
                + rng.normal(0.0, 0.45)
            )
            rows.append(
                {
                    "region": f"R{entity_index:03d}",
                    "month": period,
                    "sales": sales,
                    "search": search,
                    "distribution": distribution,
                }
            )
    return pd.DataFrame(rows)


def test_fixed_effects_recovers_known_within_slopes() -> None:
    data = simulated_panel()
    result = fit_fixed_effects(
        data,
        "region",
        "month",
        "sales",
        ["search", "distribution"],
        time_effects=True,
    )

    assert result.coefficient("search") == pytest.approx(2.0, abs=0.08)
    assert result.coefficient("distribution") == pytest.approx(-0.75, abs=0.08)
    assert result.metrics["within_r_squared"] > 0.85
    assert result.n_entities == 60
    assert any("not establish causality" in note for note in result.notes)


def test_full_analysis_returns_three_models_and_stable_hausman_result() -> None:
    data = simulated_panel()
    analysis = analyze_panel(
        data,
        "region",
        "month",
        "sales",
        ["search", "distribution"],
        time_effects=True,
    )

    assert analysis.pooled.estimator == "Pooled OLS"
    assert analysis.fixed_effects.estimator == "Entity fixed effects"
    assert analysis.random_effects.estimator == "Random effects"
    assert set(analysis.hausman.compared_terms) == {"search", "distribution"}
    assert np.isfinite(analysis.hausman.statistic)
    assert 0.0 <= analysis.hausman.p_value <= 1.0
    assert analysis.random_effects.metrics["sigma_entity_squared"] >= 0.0
    assert analysis.random_effects.metrics["theta_min"] <= analysis.random_effects.metrics["theta_max"]
    comparison = analysis.model_comparison()
    assert {"pooled_ols_estimate", "fixed_effects_estimate", "random_effects_estimate"} <= set(
        comparison.columns
    )


def test_unbalanced_panel_is_supported_by_all_estimators() -> None:
    data = simulated_panel(entities=30, periods=9)
    unbalanced = data.loc[~((data["region"].isin(["R001", "R004", "R007"])) & (data["month"] >= 6))].copy()
    diagnostics = validate_panel(unbalanced, "region", "month", "sales", ["search", "distribution"])
    pooled = fit_pooled_ols(unbalanced, "region", "month", "sales", ["search", "distribution"])
    random = fit_random_effects(unbalanced, "region", "month", "sales", ["search", "distribution"])

    assert diagnostics.balanced is False
    assert diagnostics.min_periods_per_entity == 6
    assert diagnostics.max_periods_per_entity == 9
    assert pooled.nobs == len(unbalanced)
    assert np.isfinite(random.coefficient("search"))
    assert random.metrics["theta_min"] < random.metrics["theta_max"]


def test_duplicate_entity_time_keys_are_rejected() -> None:
    data = simulated_panel(entities=5, periods=4)
    duplicated = pd.concat([data, data.iloc[[0]]], ignore_index=True)

    with pytest.raises(PanelValidationError, match="unique"):
        validate_panel(duplicated, "region", "month", "sales", ["search"])


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            pd.DataFrame(
                {
                    "entity": ["A", "A", "A"],
                    "time": [1, 2, 3],
                    "y": [1.0, 2.0, 3.0],
                    "x": [0.0, 1.0, 2.0],
                }
            ),
            "at least two entities",
        ),
        (
            pd.DataFrame(
                {
                    "entity": ["A", "B", "C"],
                    "time": [1, 1, 1],
                    "y": [1.0, 2.0, 3.0],
                    "x": [0.0, 1.0, 2.0],
                }
            ),
            "at least two distinct time periods",
        ),
        (
            pd.DataFrame(
                {
                    "entity": ["A", "A", "B"],
                    "time": [1, 2, 1],
                    "y": [1.0, 2.0, 3.0],
                    "x": [0.0, 1.0, 2.0],
                }
            ),
            "repeated observations",
        ),
    ],
)
def test_insufficient_panel_structures_are_rejected(data: pd.DataFrame, message: str) -> None:
    with pytest.raises(PanelValidationError, match=message):
        validate_panel(data, "entity", "time", "y", ["x"])


def test_missing_values_require_an_explicit_preparation_choice() -> None:
    data = simulated_panel(entities=5, periods=5)
    data.loc[0, "search"] = np.nan

    with pytest.raises(PanelValidationError, match="missing='drop'"):
        prepare_panel(data, "region", "month", "sales", ["search", "distribution"])

    prepared = prepare_panel(
        data,
        "region",
        "month",
        "sales",
        ["search", "distribution"],
        missing="drop",
    )
    assert len(prepared) == len(data) - 1
    assert not prepared.isna().any().any()


def test_within_between_diagnostic_flags_a_direction_reversal() -> None:
    rows: list[dict[str, float | int | str]] = []
    for entity in range(10):
        for period in range(8):
            within_signal = period - 3.5
            x = 4.0 * entity + within_signal
            y = -7.0 * entity + 1.5 * within_signal
            rows.append({"entity": f"E{entity}", "period": period, "outcome": y, "spend": x})
    data = pd.DataFrame(rows)

    diagnostic = within_between_diagnostics(data, "entity", "period", "outcome", ["spend"])
    row = diagnostic.iloc[0]
    assert row["pooled_slope"] < 0
    assert row["within_slope"] == pytest.approx(1.5)
    assert bool(row["simpson_risk"]) is True
    assert "masking" in row["interpretation"]


def test_time_invariant_predictor_is_reported_and_absorbed_by_fixed_effects() -> None:
    data = simulated_panel(entities=15, periods=6)
    data["market_size"] = data["region"].str.extract(r"(\d+)", expand=False).astype(float)
    diagnostics = validate_panel(
        data,
        "region",
        "month",
        "sales",
        ["search", "market_size"],
    )
    result = fit_fixed_effects(
        data,
        "region",
        "month",
        "sales",
        ["search", "market_size"],
    )

    assert diagnostics.variation.set_index("variable").loc["market_size", "within_identified"] == np.False_
    assert "market_size" not in set(result.coefficients["term"])
    assert any("market_size" in warning for warning in result.warnings)


def test_random_effects_can_estimate_a_between_only_predictor() -> None:
    data = simulated_panel(entities=25, periods=7)
    data["market_size"] = data["region"].str.extract(r"(\d+)", expand=False).astype(float)

    result = fit_random_effects(
        data,
        "region",
        "month",
        "sales",
        ["market_size"],
    )

    assert np.isfinite(result.coefficient("market_size"))
    assert any("between-entity variation" in warning for warning in result.warnings)


def test_equal_row_counts_with_different_period_sets_are_not_balanced() -> None:
    data = simulated_panel(entities=6, periods=5)
    data.loc[data["region"] == "R000", "month"] += 1

    diagnostics = validate_panel(data, "region", "month", "sales", ["search"])

    assert diagnostics.min_periods_per_entity == diagnostics.max_periods_per_entity == 5
    assert diagnostics.n_periods == 6
    assert diagnostics.balanced is False


def test_time_effects_take_precedence_over_a_period_determined_predictor() -> None:
    data = simulated_panel(entities=30, periods=8)
    data["linear_trend"] = data["month"].astype(float)

    analysis = analyze_panel(
        data,
        "region",
        "month",
        "sales",
        ["linear_trend", "search"],
        time_effects=True,
        cluster_robust=True,
    )

    for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
        terms = set(result.coefficients["term"])
        assert "linear_trend" not in terms
        assert "search" in terms
        assert sum(str(term).startswith("__period=") for term in terms) == 7
        assert any("linear_trend" in warning for warning in result.warnings)

    assert analysis.hausman.compared_terms == ("search",)
    assert "Conventional model-based covariance" in analysis.hausman.covariance_basis
    assert "displayed coefficient intervals use entity-clustered/robust" in analysis.hausman.covariance_basis
    assert "covariance_basis" in analysis.hausman.as_frame().columns
    assert analysis.hausman.fixed_covariance is not None
    assert list(analysis.hausman.fixed_covariance.index) == ["search"]
    assert analysis.hausman.random_covariance is not None
    assert analysis.hausman.covariance_difference is not None


def test_all_substantive_predictors_omitted_returns_an_invalid_hausman_result() -> None:
    data = simulated_panel(entities=25, periods=7)
    data["period_only"] = data["month"].astype(float)

    analysis = analyze_panel(
        data,
        "region",
        "month",
        "sales",
        ["period_only"],
        time_effects=True,
    )

    for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
        assert "period_only" not in set(result.coefficients["term"])
    assert analysis.hausman.compared_terms == ()
    assert analysis.hausman.degrees_of_freedom == 0
    assert np.isnan(analysis.hausman.statistic)
    assert np.isnan(analysis.hausman.p_value)
    assert analysis.hausman.valid is False
    assert "cannot be computed" in analysis.hausman.conclusion


def test_entity_invariant_only_predictor_returns_entity_means_fe_and_invalid_hausman() -> None:
    data = simulated_panel(entities=20, periods=6)
    data["market_size"] = data["region"].str.extract(r"(\d+)", expand=False).astype(float)

    analysis = analyze_panel(
        data,
        "region",
        "month",
        "sales",
        ["market_size"],
    )

    assert analysis.fixed_effects.coefficients.empty
    assert analysis.fixed_effects.metrics["within_r_squared"] == 0.0
    assert any("entity means only" in warning for warning in analysis.fixed_effects.warnings)
    assert analysis.hausman.degrees_of_freedom == 0
    assert analysis.hausman.valid is False


def test_rank_zero_hausman_covariance_is_invalid_instead_of_df_one() -> None:
    coefficients = pd.DataFrame(
        {
            "term": ["x"],
            "estimate": [1.0],
            "std_error": [0.0],
            "ci_lower": [1.0],
            "ci_upper": [1.0],
            "statistic": [np.nan],
            "p_value": [np.nan],
        }
    )
    model = PanelModelResult(
        estimator="Synthetic",
        coefficients=coefficients,
        covariance=pd.DataFrame([[0.0]], index=["x"], columns=["x"]),
        fitted_values=pd.Series([1.0]),
        residuals=pd.Series([0.0]),
        metrics={},
        nobs=1,
        n_entities=1,
        n_periods=1,
    )

    result = hausman_test(model, model, ["x"], covariance_basis="Synthetic conventional covariance")

    assert result.compared_terms == ("x",)
    assert result.degrees_of_freedom == 0
    assert np.isnan(result.statistic)
    assert np.isnan(result.p_value)
    assert result.valid is False
    assert "rank zero" in result.conclusion
    assert result.covariance_basis == "Synthetic conventional covariance"


def test_reserved_intercept_predictor_name_gets_a_clear_error() -> None:
    data = simulated_panel(entities=8, periods=5).rename(columns={"search": "const"})

    with pytest.raises(PanelValidationError, match="reserved for the model intercept"):
        analyze_panel(data, "region", "month", "sales", ["const"])
