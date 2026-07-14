from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from allocsignal.validation import prepare_channel_plan


ROOT = Path(__file__).parents[1]
APP = str(ROOT / "app.py")
PAGES = [
    "Welcome",
    "1 · Curves & assumptions",
    "2 · Allocate & stress-test",
    "3 · Panel evidence",
    "4 · Decision & export",
    "Methods & limits",
]


def _button(buttons, label: str):
    return next(button for button in buttons if button.label == label)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_without_data(page: str) -> None:
    app = AppTest.from_file(APP, default_timeout=45)
    app.run()
    app.sidebar.radio[0].set_value(page).run()

    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].value == page


def test_channel_demo_loads_and_navigates_to_curve_setup() -> None:
    app = AppTest.from_file(APP, default_timeout=45)
    app.run()
    _button(app.sidebar.button, "Demo · channel plan").click().run()

    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].value == "1 · Curves & assumptions"
    assert app.session_state["plan_source"] == "demo_channel_plan.csv"
    assert len(app.session_state["plan_raw"]) == 6


def test_panel_demo_loads_and_navigates_to_evidence_setup() -> None:
    app = AppTest.from_file(APP, default_timeout=45)
    app.run()
    _button(app.sidebar.button, "Demo · regional panel").click().run()

    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].value == "3 · Panel evidence"
    assert app.session_state["panel_source"] == "demo_marketing_panel.csv"
    frame = app.session_state["panel_tables"][app.session_state["panel_table"]]
    assert len(frame) == 144


def test_allocation_page_runs_three_decision_views_from_saved_plan() -> None:
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["channel_plan"] = prepare_channel_plan(pd.read_csv(ROOT / "examples" / "demo_channel_plan.csv"))
    app.session_state["planning_assumptions"] = {"margin": 0.42, "base_response": 500.0}
    app.session_state["nav_target"] = "2 · Allocate & stress-test"
    app.session_state["nav_epoch"] = 0
    app.run()
    _button(app.button, "Run baseline, reallocation, sizing & sensitivity").click().run()

    assert not app.exception, [error.value for error in app.exception]
    results = app.session_state["allocation_results"]
    assert results is not None
    assert set(results) >= {"baseline", "constrained", "sized", "scenarios"}
    assert abs(results["constrained"].table["recommended_spend"].sum() - 590_000) < 0.1
    assert len(app.get("plotly_chart")) >= 3


def test_anchor_calibration_updates_the_selected_channel_curve() -> None:
    plan = prepare_channel_plan(pd.read_csv(ROOT / "examples" / "demo_channel_plan.csv"))
    app = AppTest.from_file(APP, default_timeout=90)
    app.session_state["plan_raw"] = plan
    app.session_state["channel_plan"] = plan
    app.session_state["plan_source"] = "demo_channel_plan.csv"
    app.session_state["plan_fingerprint"] = "test-plan"
    app.session_state["planning_assumptions"] = {"margin": 0.42, "base_response": 500.0}
    app.session_state["nav_target"] = "1 · Curves & assumptions"
    app.session_state["nav_epoch"] = 0
    app.run()
    _button(app.button, "Fit these four anchors into the channel curve").click().run()

    assert not app.exception, [error.value for error in app.exception]
    calibration = app.session_state["calibration_results"]["Paid search"]
    assert calibration.success
    assert calibration.n_observations == 4
    assert calibration.rmse < 0.1
    updated = app.session_state["channel_plan"].set_index("channel").loc["Paid search"]
    assert updated["half_saturation"] == pytest.approx(calibration.curve.half_saturation)


def test_panel_demo_runs_pooled_fixed_and_random_effects() -> None:
    app = AppTest.from_file(APP, default_timeout=90)
    app.run()
    _button(app.sidebar.button, "Demo · regional panel").click().run()
    _button(app.button, "Validate panel & compare estimators").click().run()

    assert not app.exception, [error.value for error in app.exception]
    analysis = app.session_state["panel_analysis"]
    assert analysis is not None
    assert analysis.diagnostics.n_observations == 144
    assert analysis.diagnostics.n_entities == 12
    assert analysis.pooled.estimator == "Pooled OLS"
    assert analysis.fixed_effects.estimator == "Entity fixed effects"
    assert analysis.random_effects.estimator == "Random effects"
    assert len(app.get("plotly_chart")) == 1


def test_methods_page_exposes_both_methods_and_the_key_limits() -> None:
    app = AppTest.from_file(APP, default_timeout=45)
    app.run()
    app.sidebar.radio[0].set_value("Methods & limits").run()

    assert not app.exception, [error.value for error in app.exception]
    assert [tab.label for tab in app.tabs] == [
        "Plain-language method",
        "Response mathematics",
        "Panel estimators",
        "Limits & references",
    ]
    body = "\n".join(str(markdown.value) for markdown in app.markdown)
    assert "independently" in body
    assert "causal guarantee" in body
    assert len(app.latex) == 5
