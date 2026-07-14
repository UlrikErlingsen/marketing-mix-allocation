from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest
from scipy.optimize import OptimizeResult

import allocsignal.allocation as allocation_module
from allocsignal.allocation import (
    AllocationInfeasibleError,
    ChannelPlanError,
    evaluate_allocation,
    optimize_fixed_budget,
    optimize_profit,
    stress_test_allocation,
    validate_channel_plan,
)


@pytest.fixture
def channel_plan() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "channel": "Efficient search",
                "current_spend": 5.0,
                "min_spend": 0.0,
                "max_spend": 50.0,
                "floor_response": 0.0,
                "ceiling_response": 300.0,
                "half_saturation": 18.0,
                "shape": 1.2,
                "fixed": False,
            },
            {
                "channel": "Broad display",
                "current_spend": 25.0,
                "min_spend": 0.0,
                "max_spend": 50.0,
                "floor_response": 0.0,
                "ceiling_response": 100.0,
                "half_saturation": 80.0,
                "shape": 1.0,
                "fixed": False,
            },
            {
                "channel": "Contracted sponsorship",
                "current_spend": 10.0,
                "min_spend": 0.0,
                "max_spend": 30.0,
                "floor_response": 0.0,
                "ceiling_response": 70.0,
                "half_saturation": 30.0,
                "shape": 1.0,
                "fixed": True,
            },
        ]
    )


def test_baseline_uses_additive_response_and_profit_definition(channel_plan: pd.DataFrame) -> None:
    result = evaluate_allocation(channel_plan, margin=2.0, base_response=50.0)

    expected_channel_response = result.table["current_response"].sum()
    assert result.total_response == pytest.approx(50 + expected_channel_response)
    assert result.profit == pytest.approx(result.total_response * 2 - result.total_spend)
    assert result.incremental_profit_vs_baseline == pytest.approx(0)
    assert "independent" in " ".join(result.assumptions).lower()


def test_fixed_budget_respects_sum_bounds_and_fixed_channel(channel_plan: pd.DataFrame) -> None:
    baseline = evaluate_allocation(channel_plan, margin=2.0)
    result = optimize_fixed_budget(channel_plan, total_budget=40.0, margin=2.0)

    assert result.success
    assert result.total_spend == pytest.approx(40.0, abs=1e-6)
    assert result.profit >= baseline.profit - 1e-7
    fixed = result.table.set_index("channel").loc["Contracted sponsorship"]
    assert fixed["recommended_spend"] == pytest.approx(10.0)
    assert fixed["change"] == pytest.approx(0.0)
    assert (result.table["recommended_spend"] >= result.table["min_spend"] - 1e-7).all()
    assert (result.table["recommended_spend"] <= result.table["max_spend"] + 1e-7).all()


def test_fixed_budget_improves_deliberately_weak_baseline(channel_plan: pd.DataFrame) -> None:
    result = optimize_fixed_budget(channel_plan, total_budget=40.0, margin=2.0)

    allocations = result.table.set_index("channel")["recommended_spend"]
    assert allocations["Efficient search"] > 5
    assert allocations["Broad display"] < 25
    assert result.incremental_profit_vs_baseline > 0


def test_infeasible_budget_reports_feasible_range(channel_plan: pd.DataFrame) -> None:
    with pytest.raises(AllocationInfeasibleError, match="between"):
        optimize_fixed_budget(channel_plan, total_budget=500, margin=2)


def test_all_fixed_channels_require_exact_budget(channel_plan: pd.DataFrame) -> None:
    plan = channel_plan.copy()
    plan["fixed"] = True
    exact = optimize_fixed_budget(plan, total_budget=40, margin=2)
    assert exact.total_spend == pytest.approx(40)
    assert "no reallocation" in exact.message.lower()

    with pytest.raises(AllocationInfeasibleError):
        optimize_fixed_budget(plan, total_budget=41, margin=2)


def test_profit_sizing_finds_economic_optimum() -> None:
    plan = pd.DataFrame(
        [
            {
                "channel": "A",
                "current_spend": 10.0,
                "min_spend": 0.0,
                "max_spend": 100.0,
                "floor_response": 0.0,
                "ceiling_response": 100.0,
                "half_saturation": 10.0,
                "shape": 1.0,
                "fixed": False,
            }
        ]
    )
    # Y=100x/(10+x), so dY/dx=1000/(10+x)^2.  With margin=1,
    # marginal contribution equals marginal cost at sqrt(1000)-10.
    economic_optimum = np.sqrt(1000) - 10

    result = optimize_profit(plan, margin=1.0)

    row = result.table.iloc[0]
    assert row["recommended_spend"] == pytest.approx(economic_optimum, rel=2e-5)
    assert row["marginal_profit"] == pytest.approx(0, abs=2e-5)
    assert result.incremental_profit_vs_baseline > 0


def test_zero_margin_sizes_flexible_channels_to_minimum(channel_plan: pd.DataFrame) -> None:
    result = optimize_profit(channel_plan, margin=0)
    table = result.table.set_index("channel")

    assert table.loc["Efficient search", "recommended_spend"] == pytest.approx(0)
    assert table.loc["Broad display", "recommended_spend"] == pytest.approx(0)
    assert table.loc["Contracted sponsorship", "recommended_spend"] == pytest.approx(10)


def test_zero_margin_reports_negative_one_marginal_profit_at_singular_origin() -> None:
    plan = pd.DataFrame(
        [
            {
                "channel": "Concave channel",
                "current_spend": 0.0,
                "min_spend": 0.0,
                "max_spend": 100.0,
                "floor_response": 0.0,
                "ceiling_response": 100.0,
                "half_saturation": 20.0,
                "shape": 0.4,
                "fixed": False,
            }
        ]
    )

    result = optimize_profit(plan, margin=0.0)

    row = result.table.iloc[0]
    assert row["recommended_spend"] == pytest.approx(0.0)
    assert row["marginal_response"] == np.inf
    assert row["marginal_profit"] == pytest.approx(-1.0)


def test_fixed_budget_global_seed_crosses_s_curve_activation_basins() -> None:
    """Regression for a two-channel case where corner/midpoint SLSQP lost 37%."""

    plan = pd.DataFrame(
        [
            {
                "channel": "Slow activation",
                "current_spend": 50.0,
                "min_spend": 0.0,
                "max_spend": 100.0,
                "floor_response": 0.0,
                "ceiling_response": 1582.7103497462056,
                "half_saturation": 80.27049256160824,
                "shape": 9.032226278337728,
                "fixed": False,
            },
            {
                "channel": "Fast activation",
                "current_spend": 50.0,
                "min_spend": 0.0,
                "max_spend": 100.0,
                "floor_response": 0.0,
                "ceiling_response": 1034.8850963821876,
                "half_saturation": 6.994726704583898,
                "shape": 8.998212761774722,
                "fixed": False,
            },
        ]
    )

    result = optimize_fixed_budget(plan, total_budget=100.0, margin=1.0)

    np.testing.assert_allclose(
        result.table["recommended_spend"],
        [89.882578, 10.117422],
        atol=2e-4,
    )
    assert result.profit == pytest.approx(2062.550928, abs=2e-5)


def test_fixed_budget_projection_never_leaks_tiny_negative_solver_values() -> None:
    """Regression for a feasible SLSQP result just below a zero lower bound."""

    plan = pd.DataFrame(
        {
            "channel": ["C0", "C1", "C2"],
            "current_spend": [100 / 3] * 3,
            "min_spend": [0.0] * 3,
            "max_spend": [100.0] * 3,
            "floor_response": [0.0] * 3,
            "ceiling_response": [701.8611356805951, 1718.454891243505, 1079.2659014666235],
            "half_saturation": [3.0010068564038312, 69.88159491887053, 70.17855044732855],
            "shape": [7.145896997782093, 2.010496869996351, 4.495466328969207],
            "fixed": [False] * 3,
        }
    )

    result = optimize_fixed_budget(plan, total_budget=100.0, margin=1.0)

    assert result.total_spend == pytest.approx(100.0, abs=1e-8)
    assert (result.table["recommended_spend"] >= 0.0).all()


def test_profit_sizing_adaptive_seed_finds_narrow_s_curve_peak() -> None:
    plan = pd.DataFrame(
        [
            {
                "channel": "Narrow activation",
                "current_spend": 92.04224607347123,
                "min_spend": 0.0,
                "max_spend": 100.0,
                "floor_response": 0.0,
                "ceiling_response": 15.501296909434595,
                "half_saturation": 0.0005502894666705834,
                "shape": 8.280601185383034,
                "fixed": False,
            }
        ]
    )

    result = optimize_profit(plan, margin=0.022865893136625272)

    assert result.total_spend == pytest.approx(0.00138720, abs=2e-8)
    assert result.profit > 0.35
    assert result.table.iloc[0]["marginal_profit"] == pytest.approx(0.0, abs=2e-5)


def test_feasible_raw_starts_survive_solver_failure(
    channel_plan: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = evaluate_allocation(channel_plan, margin=2.0)

    def forced_failure(_objective, start, *args, **kwargs) -> OptimizeResult:
        del _objective, args, kwargs
        return OptimizeResult(
            x=np.asarray(start, dtype=float),
            fun=np.inf,
            success=False,
            status=8,
            nit=1,
            message="forced test failure",
        )

    monkeypatch.setattr(allocation_module, "minimize", forced_failure)
    result = optimize_fixed_budget(channel_plan, total_budget=40.0, margin=2.0)

    assert result.success
    assert result.total_spend == pytest.approx(40.0)
    assert result.profit >= baseline.profit
    assert result.solver_iterations == 0


def test_optimizers_reject_extreme_or_nonfinite_economic_scales(
    channel_plan: pd.DataFrame,
) -> None:
    with pytest.raises(ChannelPlanError, match="too large"):
        optimize_fixed_budget(channel_plan, total_budget=40.0, margin=1e16)
    with pytest.raises(ChannelPlanError, match="too large"):
        optimize_profit(channel_plan, margin=2.0, base_response=1e16)
    with pytest.raises(ChannelPlanError, match="finite"):
        optimize_fixed_budget(channel_plan, total_budget=40.0, margin=np.inf)
    with pytest.raises(ChannelPlanError, match="finite"):
        optimize_profit(channel_plan, margin=np.nan)


def test_optimizers_are_deterministic(channel_plan: pd.DataFrame) -> None:
    first = optimize_fixed_budget(channel_plan, 40, 2)
    second = optimize_fixed_budget(channel_plan, 40, 2)

    np.testing.assert_allclose(
        first.table["recommended_spend"], second.table["recommended_spend"], atol=1e-8
    )
    assert first.profit == pytest.approx(second.profit, abs=1e-8)


def test_stress_scenarios_are_deterministic_and_streamlit_ready(channel_plan: pd.DataFrame) -> None:
    first = stress_test_allocation(channel_plan, 2, total_budget=40)
    second = stress_test_allocation(channel_plan, 2, total_budget=40)

    assert first.summary["scenario"].tolist() == ["Downside", "Base", "Upside"]
    assert set(first.allocations["scenario"]) == {"Downside", "Base", "Upside"}
    pdt.assert_frame_equal(first.summary, second.summary)
    pdt.assert_frame_equal(first.allocations, second.allocations)


def test_validation_rejects_duplicate_channels_and_invalid_bounds(channel_plan: pd.DataFrame) -> None:
    duplicate = channel_plan.copy()
    duplicate.loc[1, "channel"] = duplicate.loc[0, "channel"]
    with pytest.raises(ChannelPlanError, match="unique"):
        validate_channel_plan(duplicate)

    bad_bounds = channel_plan.copy()
    bad_bounds.loc[0, "min_spend"] = 60
    with pytest.raises(ChannelPlanError, match="min_spend"):
        validate_channel_plan(bad_bounds)


def test_fixed_values_accept_friendly_csv_strings(channel_plan: pd.DataFrame) -> None:
    plan = channel_plan.copy()
    plan["fixed"] = ["no", "flexible", "yes"]

    validated = validate_channel_plan(plan)

    assert validated["fixed"].tolist() == [False, False, True]
