from __future__ import annotations

import pandas as pd
import pytest

from allocsignal.digital import AttributionConfig, DigitalRoles, audit_attribution, evaluate_digital_economics
from allocsignal.errors import DataProblem


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "channel": ["Search", "Social"],
            "keyword": ["brand", "prospecting"],
            "impressions": [100_000, 200_000],
            "clicks": [5_000, 4_000],
            "conversions": [500, 200],
            "platform": [550, 300],
            "spend": [5_000, 6_000],
            "margin": [20, 40],
        }
    )


def test_digital_economics_reconciles_funnel_and_contribution() -> None:
    result = evaluate_digital_economics(
        frame(),
        DigitalRoles(
            label="channel",
            keyword="keyword",
            impressions="impressions",
            clicks="clicks",
            conversions="conversions",
            platform_conversions="platform",
            spend="spend",
            contribution_margin="margin",
        ),
    )
    search = result.rows.set_index("label").loc["Search"]
    assert search["ctr"] == pytest.approx(0.05)
    assert search["cvr"] == pytest.approx(0.10)
    assert search["cpc"] == pytest.approx(1.0)
    assert search["cpa"] == pytest.approx(10.0)
    assert search["net_contribution"] == pytest.approx(5_000)
    assert search["break_even_cpc"] == pytest.approx(2.0)
    assert result.totals.iloc[0]["net_contribution"] == pytest.approx(7_000)


def test_funnel_rejects_impossible_clicks_and_unapproved_view_through() -> None:
    invalid = frame()
    invalid.loc[0, "clicks"] = 200_000
    with pytest.raises(DataProblem, match="Clicks cannot exceed"):
        evaluate_digital_economics(
            invalid,
            DigitalRoles("channel", "impressions", "clicks", "conversions", "spend", default_margin=20),
        )
    view = frame()
    view.loc[0, "conversions"] = 6_000
    with pytest.raises(DataProblem, match="view-through"):
        evaluate_digital_economics(
            view,
            DigitalRoles("channel", "impressions", "clicks", "conversions", "spend", default_margin=20),
        )


def test_attribution_audit_never_calls_retrospective_credit_incremental() -> None:
    audit = audit_attribution(
        AttributionConfig(
            method="Markov removal",
            identity_coverage=0.65,
            lookback_days=30,
            includes_view_through=True,
            cross_device_linked=False,
            experiment_calibrated=False,
            long_term_effects_included=False,
            removal_redistributes_traffic=None,
        )
    )
    assert audit.loc[audit["audit_area"] == "Incrementality", "status"].iloc[0] == "DESCRIPTIVE ONLY"
    assert "Removal assumption" in set(audit["audit_area"])
    assert "NO AUTOMATIC REALLOCATION" in set(audit["status"])
