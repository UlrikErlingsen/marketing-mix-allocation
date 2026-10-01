"""Signal Hub contract: importable UI entry point, Streamlit only under ui/, slug-namespaced state, packaged demos."""

import ast
from pathlib import Path
import re
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest

from allocsignal import __version__


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "allocsignal"
UI = PACKAGE / "ui"
UI_ONLY_LIBRARIES = {"streamlit", "plotly"}
PAGES = [
    "Welcome",
    "1 · Curves & assumptions",
    "2 · Allocate & stress-test",
    "3 · Panel evidence",
    "4 · Digital economics & attribution",
    "5 · Schedule & carryover",
    "6 · Decision & export",
    "Methods & limits",
]
PACKAGED_EXAMPLES = [
    "demo_channel_plan.csv",
    "demo_marketing_panel.csv",
    "demo_digital_economics.csv",
    "channel_plan_template.csv",
    "panel_template.csv",
]
RENDER_SCRIPT = """
from allocsignal.ui import render

render()
"""


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _button(buttons, label: str):
    return next(button for button in buttons if button.label == label)


def test_ui_entry_point_matches_the_hub_contract() -> None:
    from allocsignal.ui import APP_INFO, render

    assert callable(render)
    assert APP_INFO == {
        "product": "Alloc Signal",
        "version": __version__,
        "repo": "marketing-mix-allocation",
        "slug": "alloc",
    }


def test_only_the_ui_package_imports_streamlit_or_plotly() -> None:
    offenders = {
        str(path.relative_to(PACKAGE)): sorted(_imported_roots(path) & UI_ONLY_LIBRARIES)
        for path in PACKAGE.rglob("*.py")
        if UI not in path.parents and _imported_roots(path) & UI_ONLY_LIBRARIES
    }
    assert not offenders, offenders


def test_core_package_imports_without_streamlit_or_plotly() -> None:
    # A fresh interpreter, so modules already imported by other tests cannot hide a stray import.
    code = (
        f"import sys\nsys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "import allocsignal, allocsignal.allocation, allocsignal.digital, allocsignal.errors, allocsignal.io, "
        "allocsignal.panel, allocsignal.response, allocsignal.schedule, allocsignal.validation\n"
        "loaded = sorted(name for name in ('streamlit', 'plotly') if name in sys.modules)\n"
        "assert not loaded, loaded\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_render_never_sets_page_config_or_navigation() -> None:
    for path in UI.glob("*.py"):
        if path.name == "signal_theme.py":
            continue
        source = path.read_text(encoding="utf-8")
        for call in ("st.set_page_config(", "st.navigation(", "st.Page("):
            assert call not in source, (path.name, call)


def test_ui_reads_demo_files_from_the_package_not_the_repository_root() -> None:
    # Signal Hub installs the release as a normal package: only src/allocsignal/ (plus package data) exists there.
    from allocsignal.ui import app as ui_app

    assert ui_app.EXAMPLES.resolve().is_relative_to(UI.resolve())
    source = (UI / "app.py").read_text(encoding="utf-8")
    assert "parents[" not in source
    assert "ROOT" not in source
    used = set(re.findall(r'EXAMPLES / "([^"]+)"', source))
    assert used and used <= set(PACKAGED_EXAMPLES), used
    for name in PACKAGED_EXAMPLES:
        packaged = ui_app.EXAMPLES / name
        assert packaged.resolve().is_relative_to(UI.resolve())
        # The packaged copy must stay identical to the user-facing file in examples/ (scripts/generate_examples.py).
        expected = (ROOT / "examples" / name).read_bytes().replace(b"\r\n", b"\n")
        assert packaged.read_bytes().replace(b"\r\n", b"\n") == expected, name
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"allocsignal.ui" = ["assets/marks/*", "examples/*.csv"]' in pyproject


def test_render_runs_from_a_script_without_set_page_config() -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=120)
    app.run()

    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].key == "alloc:page"
    assert "alloc:planning_assumptions" in app.session_state
    assert "planning_assumptions" not in app.session_state
    body = "\n".join(str(item.value) for item in app.markdown)
    assert "MARKETING BUDGETS, WITHOUT FALSE PRECISION" in body
    assert f"Alloc Signal v{__version__}" in body

    _button(app.sidebar.button, "Demo · channel plan").click().run()
    assert not app.exception, [error.value for error in app.exception]
    assert app.sidebar.radio[0].value == "1 · Curves & assumptions"
    assert len(app.session_state["alloc:plan_raw"]) == 6


@pytest.mark.parametrize("page", PAGES)
def test_every_widget_key_is_namespaced(page: str) -> None:
    app = AppTest.from_string(RENDER_SCRIPT, default_timeout=120)
    app.run()
    # Load both demos so the data-dependent widgets render too.
    _button(app.sidebar.button, "Demo · channel plan").click().run()
    _button(app.sidebar.button, "Demo · regional panel").click().run()
    app.sidebar.radio[0].set_value(page).run()

    assert not app.exception, [error.value for error in app.exception]
    widgets = [
        *app.radio,
        *app.selectbox,
        *app.multiselect,
        *app.checkbox,
        *app.toggle,
        *app.button,
        *app.number_input,
        *app.slider,
    ]
    assert widgets
    unkeyed = [(type(widget).__name__, widget.label) for widget in widgets if widget.key is None]
    assert not unkeyed, unkeyed
    assert all(widget.key.startswith("alloc:") for widget in widgets)


def test_session_state_and_widget_keys_go_through_the_namespace_helper() -> None:
    source = (UI / "app.py").read_text(encoding="utf-8")
    state_keys = re.findall(r"session_state(?:\[|\.get\(|\.pop\(|\.setdefault\()\s*([^,\])]+)", source)
    widget_keys = re.findall(r"\bkey=([^,)\n]+)", source)
    assert state_keys and widget_keys
    assert all(key.startswith("k(") for key in state_keys), state_keys
    assert all(key.startswith("k(") for key in widget_keys), widget_keys
    assert "st.plotly_chart(" not in source  # every chart goes through sig.chart (template + theme=None)
    assert 'NS = "alloc"' in source
