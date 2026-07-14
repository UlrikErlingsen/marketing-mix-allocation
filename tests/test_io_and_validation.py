from io import BytesIO
import json
import zipfile

import pandas as pd
import pytest

from allocsignal.errors import DataProblem
from allocsignal.io import load_data, results_to_excel, results_to_json, safe_for_spreadsheet, tables_to_csv_zip
from allocsignal.validation import CHANNEL_COLUMNS, prepare_channel_plan, prepare_panel_data


def _valid_plan() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "channel": ["Search", "Video"],
            "current_spend": [100.0, 80.0],
            "min_spend": [20.0, 30.0],
            "max_spend": [220.0, 180.0],
            "floor_response": [0.0, 0.0],
            "ceiling_response": [600.0, 420.0],
            "half_saturation": [100.0, 90.0],
            "shape": [1.2, 1.6],
            "fixed": [False, "yes"],
            "long_run_multiplier": [1.1, 1.25],
        }
    )


def test_channel_plan_is_normalized_and_validated() -> None:
    plan = prepare_channel_plan(_valid_plan())

    assert list(plan.columns) == CHANNEL_COLUMNS
    assert plan["fixed"].tolist() == [False, True]
    assert plan["current_spend"].dtype.kind == "f"


def test_channel_plan_accepts_explanatory_aliases() -> None:
    aliased = _valid_plan().rename(
        columns={
            "min_spend": "minimum_spend",
            "max_spend": "maximum_spend",
            "ceiling_response": "saturation_response",
            "half_saturation": "half_saturation_spend",
        }
    )
    assert list(prepare_channel_plan(aliased).columns) == CHANNEL_COLUMNS


@pytest.mark.parametrize(
    "mutation",
    [
        lambda frame: frame.assign(channel=["Search", "Search"]),
        lambda frame: frame.assign(current_spend=[999.0, 80.0]),
        lambda frame: frame.assign(ceiling_response=[0.0, 420.0]),
        lambda frame: frame.assign(half_saturation=[0.0, 90.0]),
        lambda frame: frame.assign(shape=[-1.0, 1.6]),
    ],
)
def test_channel_plan_rejects_misleading_inputs(mutation) -> None:
    with pytest.raises(DataProblem):
        prepare_channel_plan(mutation(_valid_plan()))


def test_panel_preparation_encodes_selected_categories_and_preserves_keys() -> None:
    panel = pd.DataFrame(
        {
            "region": ["A", "A", "B", "B"],
            "period": [1, 2, 1, 2],
            "sales": [20.0, 24.0, 30.0, 29.0],
            "search": [2.0, 4.0, 7.0, 6.0],
            "season": ["low", "high", "low", "high"],
        }
    )
    prepared = prepare_panel_data(
        panel,
        entity_column="region",
        time_column="period",
        outcome_column="sales",
        numeric_predictors=["search"],
        categorical_predictors=["season"],
    )

    assert prepared.frame[["region", "period"]].equals(panel[["region", "period"]])
    assert prepared.predictors == ["search", "season_low"]
    assert prepared.encoded_from == {"season": ["season_low"]}


def test_panel_preparation_rejects_duplicate_keys_and_missing_selected_values() -> None:
    panel = pd.DataFrame(
        {
            "region": ["A", "A", "B", "B"],
            "period": [1, 1, 1, 2],
            "sales": [20.0, 24.0, 30.0, 29.0],
            "search": [2.0, 4.0, 7.0, 6.0],
        }
    )
    with pytest.raises(DataProblem, match="unique"):
        prepare_panel_data(panel, "region", "period", "sales", ["search"])
    panel.loc[1, "period"] = 2
    panel.loc[2, "search"] = None
    with pytest.raises(DataProblem, match="incomplete"):
        prepare_panel_data(panel, "region", "period", "sales", ["search"])


def test_panel_preparation_rejects_categorical_dummy_name_collisions() -> None:
    panel = pd.DataFrame(
        {
            "region": ["A", "A", "B", "B"],
            "period": [1, 2, 1, 2],
            "sales": [20.0, 24.0, 30.0, 29.0],
            "group_b": [1.0, 2.0, 3.0, 4.0],
            "group": ["a", "b", "a", "b"],
        }
    )

    with pytest.raises(DataProblem, match="overwrite existing predictor"):
        prepare_panel_data(
            panel,
            entity_column="region",
            time_column="period",
            outcome_column="sales",
            numeric_predictors=["group_b"],
            categorical_predictors=["group"],
        )


def test_panel_preparation_rejects_collisions_between_categorical_controls() -> None:
    panel = pd.DataFrame(
        {
            "region": ["A", "A", "B", "B"],
            "period": [1, 2, 1, 2],
            "sales": [20.0, 24.0, 30.0, 29.0],
            "group": ["a", "b", "a", "b"],
            "Group!": ["a", "b", "b", "a"],
        }
    )

    with pytest.raises(DataProblem, match="overwrite existing predictor"):
        prepare_panel_data(
            panel,
            entity_column="region",
            time_column="period",
            outcome_column="sales",
            numeric_predictors=[],
            categorical_predictors=["group", "Group!"],
        )


def test_csv_loading_and_all_export_formats_round_trip() -> None:
    raw = b"channel,value\nSearch,10\nVideo,20\n"
    loaded = load_data(raw, name="plan.csv")
    frame = loaded.tables["data"]
    tables = {"Plan": frame}

    assert loaded.source_name == "plan.csv"
    assert frame["value"].sum() == 30
    workbook = pd.read_excel(BytesIO(results_to_excel(tables)), sheet_name=None)
    assert workbook["Plan"].equals(frame)
    payload = json.loads(results_to_json(tables, {"source": "test"}))
    assert payload["Plan"][0]["channel"] == "Search"
    assert payload["analysis_metadata"]["source"] == "test"
    with zipfile.ZipFile(BytesIO(tables_to_csv_zip(tables))) as archive:
        assert archive.namelist() == ["Plan.csv"]


def test_spreadsheet_export_neutralizes_formula_like_strings() -> None:
    safe = safe_for_spreadsheet(pd.DataFrame({"label": ["=1+1", "+CMD", "normal"]}))
    assert safe["label"].tolist() == ["'=1+1", "'+CMD", "normal"]
