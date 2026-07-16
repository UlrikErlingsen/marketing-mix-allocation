from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from allocsignal.errors import DataProblem
from allocsignal.schedule import (
    adstock_half_life,
    adstock_schedule,
    apply_interactions,
    geometric_adstock,
    prepare_schedule,
    reach_frequency,
)


def schedule_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "channel": ["TV", "Search"],
            "P01": [100.0, 40.0],
            "P02": [0.0, 40.0],
            "P03": [50.0, 40.0],
            "P04": [0.0, 40.0],
        }
    )


def test_prepare_schedule_returns_channel_indexed_numeric_periods() -> None:
    prepared = prepare_schedule(schedule_frame())
    assert list(prepared.index) == ["TV", "Search"]
    assert list(prepared.columns) == ["P01", "P02", "P03", "P04"]
    assert prepared.loc["TV", "P03"] == pytest.approx(50.0)
    assert prepared.dtypes.eq(float).all()


def test_prepare_schedule_refuses_too_few_periods_negative_and_incomplete_spend() -> None:
    with pytest.raises(DataProblem, match="between 4 and 52"):
        prepare_schedule(schedule_frame().drop(columns=["P04"]))
    negative = schedule_frame()
    negative.loc[0, "P01"] = -1.0
    with pytest.raises(DataProblem, match="cannot be negative"):
        prepare_schedule(negative)
    incomplete = schedule_frame()
    incomplete.loc[1, "P02"] = np.nan
    with pytest.raises(DataProblem, match="complete numeric"):
        prepare_schedule(incomplete)
    duplicated = schedule_frame()
    duplicated.loc[1, "channel"] = "TV"
    with pytest.raises(DataProblem, match="unique"):
        prepare_schedule(duplicated)


def test_geometric_adstock_matches_hand_computed_recursion() -> None:
    # A_1 = 100; A_2 = 0 + 0.5·100 = 50; A_3 = 50 + 0.5·50 = 75; A_4 = 0 + 0.5·75 = 37.5
    result = geometric_adstock([100.0, 0.0, 50.0, 0.0], retention=0.5)
    assert result == pytest.approx([100.0, 50.0, 75.0, 37.5])
    assert geometric_adstock([10.0, 20.0, 30.0, 40.0], retention=0.0) == pytest.approx([10.0, 20.0, 30.0, 40.0])


def test_geometric_adstock_refuses_out_of_range_retention_and_bad_spend() -> None:
    for retention in (-0.1, 0.951, 1.2, float("nan")):
        with pytest.raises(DataProblem, match="between 0 and 0.95"):
            geometric_adstock([1.0, 1.0, 1.0, 1.0], retention=retention)
    with pytest.raises(DataProblem, match="finite and non-negative"):
        geometric_adstock([1.0, -1.0, 1.0, 1.0], retention=0.5)


def test_adstock_half_life_hand_checked() -> None:
    assert adstock_half_life(0.5) == pytest.approx(1.0)
    assert adstock_half_life(0.7) == pytest.approx(np.log(0.5) / np.log(0.7))
    assert adstock_half_life(0.0) == 0.0
    with pytest.raises(DataProblem, match="between 0 and 0.95"):
        adstock_half_life(0.99)


def test_adstock_schedule_applies_declared_retention_per_channel() -> None:
    prepared = prepare_schedule(schedule_frame())
    adstocked = adstock_schedule(prepared, {"TV": 0.5, "Search": 0.0})
    assert adstocked.loc["TV"].to_numpy() == pytest.approx([100.0, 50.0, 75.0, 37.5])
    assert adstocked.loc["Search"].to_numpy() == pytest.approx([40.0, 40.0, 40.0, 40.0])
    with pytest.raises(DataProblem, match="Missing: Search"):
        adstock_schedule(prepared, {"TV": 0.5})


def test_reach_matches_hand_computed_exponential() -> None:
    # I = 200 / 0.02 = 10 000; reach = 20 000·(1 − e^{−0.5}); frequency = I / reach
    table = reach_frequency([200.0], audience_size=20_000.0, cost_per_impression=0.02)
    assert table["impressions"].iloc[0] == pytest.approx(10_000.0)
    assert table["reach"].iloc[0] == pytest.approx(20_000.0 * (1.0 - np.exp(-0.5)))
    assert table["frequency"].iloc[0] == pytest.approx(10_000.0 / (20_000.0 * (1.0 - np.exp(-0.5))))
    assert table["reach"].iloc[0] < 20_000.0
    assert table["reach"].iloc[0] <= table["impressions"].iloc[0]


def test_frequency_is_zero_without_pressure_and_grows_with_it() -> None:
    table = reach_frequency([0.0, 100.0, 400.0], audience_size=5_000.0, cost_per_impression=0.05)
    assert table["impressions"].iloc[0] == 0.0
    assert table["reach"].iloc[0] == 0.0
    assert table["frequency"].iloc[0] == 0.0
    assert table["frequency"].iloc[2] > table["frequency"].iloc[1] > 1.0


def test_reach_refuses_degenerate_cost_and_audience() -> None:
    for cost in (0.0, -0.01):
        with pytest.raises(DataProblem, match="Cost per impression-equivalent"):
            reach_frequency([1.0], audience_size=1_000.0, cost_per_impression=cost)
    for audience in (0.0, -5.0):
        with pytest.raises(DataProblem, match="Audience size"):
            reach_frequency([1.0], audience_size=audience, cost_per_impression=0.01)


def test_apply_interactions_scales_only_overlapping_periods() -> None:
    adstocked = pd.DataFrame(
        {"P01": [100.0, 40.0], "P02": [50.0, 0.0], "P03": [0.0, 40.0], "P04": [25.0, 40.0]},
        index=pd.Index(["TV", "Search"], name="channel"),
    )
    adjusted = apply_interactions(adstocked, [("TV", "Search", 1.2)])
    assert adjusted.loc["TV"].to_numpy() == pytest.approx([120.0, 50.0, 0.0, 30.0])
    assert adjusted.loc["Search"].to_numpy() == pytest.approx([48.0, 0.0, 40.0, 48.0])
    assert adstocked.loc["TV", "P01"] == pytest.approx(100.0)  # input is not mutated


def test_apply_interactions_refuses_out_of_range_unknown_self_and_excess() -> None:
    adstocked = pd.DataFrame(
        {"P01": [1.0, 1.0, 1.0], "P02": [1.0, 1.0, 1.0]},
        index=pd.Index(["A", "B", "C"], name="channel"),
    )
    for kappa in (0.79, 1.21):
        with pytest.raises(DataProblem, match="between 0.8 and 1.2"):
            apply_interactions(adstocked, [("A", "B", kappa)])
    with pytest.raises(DataProblem, match="not in the schedule"):
        apply_interactions(adstocked, [("A", "Radio", 1.1)])
    with pytest.raises(DataProblem, match="cannot pair with itself"):
        apply_interactions(adstocked, [("A", "A", 1.1)])
    with pytest.raises(DataProblem, match="declared more than once"):
        apply_interactions(adstocked, [("A", "B", 1.1), ("B", "A", 0.9)])
    with pytest.raises(DataProblem, match="at most 3"):
        apply_interactions(
            adstocked,
            [("A", "B", 1.1), ("A", "C", 1.1), ("B", "C", 1.1), ("A", "B", 0.9)],
        )
