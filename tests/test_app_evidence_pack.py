import json
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from allocsignal.validation import prepare_channel_plan


ROOT = Path(__file__).parents[1]
APP = str(ROOT / "app.py")


def _button(buttons, label: str):
    return next(button for button in buttons if button.label == label)


def test_changed_chosen_budget_is_not_labelled_pure_reallocation_and_exports() -> None:
    app = AppTest.from_file(APP, default_timeout=120)
    app.session_state["channel_plan"] = prepare_channel_plan(
        pd.read_csv(ROOT / "examples" / "demo_channel_plan.csv")
    )
    app.session_state["planning_assumptions"] = {"margin": 0.42, "base_response": 500.0}
    app.session_state["nav_target"] = "2 · Allocate & stress-test"
    app.session_state["nav_epoch"] = 0
    app.run()

    budget = next(
        item for item in app.number_input if item.label == "Total budget for the constrained plan"
    )
    budget.set_value(650_000.0).run()
    _button(app.button, "Run baseline, reallocation, sizing & sensitivity").click().run()

    assert not app.exception, [error.value for error in app.exception]
    assert app.tabs[0].label == "Chosen-budget plan"
    body = "\n".join(str(item.value) for item in [*app.markdown, *app.info])
    assert "budget-size change" in body

    app.sidebar.radio[0].set_value("5 · Decision & export").run()
    assert not app.exception, [error.value for error in app.exception]
    decision_body = "\n".join(str(item.value) for item in [*app.markdown, *app.info])
    assert "reallocation alone" in decision_body
    assert len(app.get("download_button")) == 3


def test_time_controls_stay_in_model_tables_but_not_public_coefficient_chart() -> None:
    app = AppTest.from_file(APP, default_timeout=120)
    app.run()
    _button(app.sidebar.button, "Demo · regional panel").click().run()
    next(toggle for toggle in app.toggle if toggle.label == "Include time fixed effects").set_value(True).run()
    _button(app.button, "Validate panel & compare estimators").click().run()

    assert not app.exception, [error.value for error in app.exception]
    analysis = app.session_state["panel_analysis"]
    assert "Conventional model-based covariance" in analysis.hausman.covariance_basis
    assert analysis.hausman.fixed_covariance is not None
    period_terms = {
        str(term)
        for term in analysis.fixed_effects.coefficients["term"]
        if str(term).startswith("__period=")
    }
    assert period_terms
    spec = json.loads(app.get("plotly_chart")[0].proto.spec)
    chart_terms = {str(value) for trace in spec["data"] for value in trace.get("y", [])}
    assert chart_terms.isdisjoint(period_terms)

    app.sidebar.radio[0].set_value("5 · Decision & export").run()
    assert not app.exception, [error.value for error in app.exception]
    assert len(app.get("download_button")) == 3
