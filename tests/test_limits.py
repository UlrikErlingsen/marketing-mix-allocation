"""Data limits: none locally, demo caps only with SIGNAL_PUBLIC=1, large-table exports and the shared upload cap."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import zipfile

import pandas as pd
import pytest

import allocsignal.io as alloc_io
import allocsignal.panel as panel_module
from allocsignal import limits
from allocsignal.errors import DataProblem, friendly_message
from allocsignal.panel import PanelValidationError, analyze_panel
from allocsignal.validation import prepare_panel_data

ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_UPLOAD_MB = 10000  # Streamlit's transport cap only; the app adds no data limit locally
PREDICTORS = ["paid_search", "online_display", "traditional_media", "distribution", "price_index"]


def demo_panel():
    frame = pd.read_csv(ROOT / "examples" / "demo_marketing_panel.csv")
    return prepare_panel_data(frame, entity_column="region", time_column="period", outcome_column="sales",
                              numeric_predictors=PREDICTORS)


def test_local_mode_accepts_input_beyond_every_demo_cap(monkeypatch):
    monkeypatch.delenv("SIGNAL_PUBLIC", raising=False)
    rows = limits.DEMO_MAX_TABLE_ROWS + 1
    raw = ("channel,value\n" + "Search,1\n" * rows).encode()
    assert len(alloc_io.load_data(raw, name="long.csv").tables["data"]) == rows
    for name in ("max_upload_bytes", "max_json_bytes", "max_expanded_excel_bytes", "max_table_rows",
                 "max_total_cells", "max_panel_design_cells"):
        assert getattr(limits, name)() is None, name
    monkeypatch.setattr(limits, "DEMO_MAX_PANEL_DESIGN_CELLS", 10)
    prepared = demo_panel()
    analysis = analyze_panel(prepared.frame, entity_col="region", time_col="period", outcome_col="sales",
                             predictors=prepared.predictors, time_effects=True)
    assert analysis.diagnostics.n_observations == len(prepared.frame)


def test_public_demo_enforces_its_caps_with_a_demo_message(monkeypatch):
    monkeypatch.setenv("SIGNAL_PUBLIC", "1")
    raw = ("channel,value\n" + "Search,1\n" * 50).encode()
    monkeypatch.setattr(limits, "DEMO_MAX_TABLE_ROWS", 10)
    with pytest.raises(DataProblem, match="at most 10 rows.*downloadable Alloc Signal app has no built-in limit"):
        alloc_io.load_data(raw, name="long.csv")
    monkeypatch.setattr(limits, "DEMO_MAX_JSON_MB", 0)
    with pytest.raises(DataProblem, match="JSON files up to 0 MB.*public demo only"):
        alloc_io.load_data(b'[{"a": 1}]', name="data.json")
    monkeypatch.setattr(limits, "DEMO_MAX_UPLOAD_MB", 0)
    with pytest.raises(DataProblem, match="files up to 0 MB"):
        alloc_io.load_data(raw, name="long.csv")
    monkeypatch.setattr(limits, "DEMO_MAX_PANEL_DESIGN_CELLS", 100)
    prepared = demo_panel()
    with pytest.raises(PanelValidationError, match="at most 100 design cells.*public demo only"):
        analyze_panel(prepared.frame, entity_col="region", time_col="period", outcome_col="sales",
                      predictors=prepared.predictors)


def test_running_out_of_memory_is_reported_plainly(monkeypatch):
    def no_memory(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(alloc_io.pd, "read_csv", no_memory)
    with pytest.raises(DataProblem, match="not enough memory on this computer"):
        alloc_io.load_data(b"a,b\n1,2\n", name="x.csv")
    assert friendly_message(MemoryError()) == limits.MEMORY_MESSAGE


def test_wide_time_effect_models_use_a_recorded_entity_sample(monkeypatch):
    from allocsignal.ui.app import _panel_fitted_residuals

    prepared = demo_panel()
    monkeypatch.setattr(panel_module, "TIME_EFFECTS_APPROXIMATE_CELLS", 600)
    analysis = analyze_panel(prepared.frame, entity_col="region", time_col="period", outcome_col="sales",
                             predictors=prepared.predictors, time_effects=True)
    assert analysis.diagnostics.warnings[0].startswith("Approximation: time fixed effects")
    assert analysis.diagnostics.n_observations < len(prepared.frame)
    residuals = _panel_fitted_residuals(analysis, prepared)
    assert len(residuals) == analysis.diagnostics.n_observations
    # Without time effects every row is used, whatever the threshold.
    full = analyze_panel(prepared.frame, entity_col="region", time_col="period", outcome_col="sales",
                         predictors=prepared.predictors)
    assert full.diagnostics.n_observations == len(prepared.frame)


def test_long_tables_stay_complete_in_csv_and_json_and_are_listed_in_excel(monkeypatch):
    tables = {"Rows": pd.DataFrame({"x": range(30), "label": ["=bad", "ok", "+cmd"] * 10}),
              "Small": pd.DataFrame({"y": [1.5]})}
    monkeypatch.setattr(alloc_io, "EXCEL_MAX_TABLE_CELLS", 20)
    monkeypatch.setattr(alloc_io, "JSON_COMPACT_ROWS", 10)
    workbook = pd.read_excel(BytesIO(alloc_io.results_to_excel(tables)), sheet_name=None)
    assert "Rows" not in workbook and workbook["Read me large tables"].loc[0, "rows"] == 30
    payload = json.loads(alloc_io.results_to_json(tables, {"source": "test"}))
    assert len(payload["Rows"]) == 30 and payload["Small"] == [{"y": 1.5}]
    assert payload["analysis_metadata"] == {"source": "test"}
    with zipfile.ZipFile(BytesIO(alloc_io.tables_to_csv_zip(tables))) as archive:
        exported = pd.read_csv(BytesIO(archive.read("Rows.csv")))
    assert len(exported) == 30 and exported.loc[0, "label"] == "'=bad" and exported.loc[1, "label"] == "ok"


def test_launchers_docker_and_config_share_the_suite_upload_cap():
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    windows = (ROOT / "run_app.bat").read_text(encoding="utf-8")
    macos = (ROOT / "run_app.command").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cap = STREAMLIT_UPLOAD_MB
    assert f"maxUploadSize = {cap}" in config
    assert f'set "ALLOCSIGNAL_MAX_UPLOAD_MB={cap}"' in windows
    assert "--server.maxUploadSize=%ALLOCSIGNAL_MAX_UPLOAD_MB%" in windows
    assert f'MAX_UPLOAD_MB="${{ALLOCSIGNAL_MAX_UPLOAD_MB:-{cap}}}"' in macos
    assert f"STREAMLIT_SERVER_MAX_UPLOAD_SIZE={cap}" in dockerfile
    assert "--server.maxUploadSize" not in dockerfile
