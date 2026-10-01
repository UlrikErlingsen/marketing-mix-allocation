"""Signal brand: shared theme shell, README information architecture, and runtime scaffolding."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from allocsignal import __version__


ROOT = Path(__file__).parents[1]
APP = str(ROOT / "app.py")
UI = ROOT / "src" / "allocsignal" / "ui"


def test_shared_signal_shell_renders() -> None:
    app = AppTest.from_file(APP, default_timeout=120)
    app.run()

    assert not app.exception, [error.value for error in app.exception]
    body = "\n".join(str(item.value) for item in app.markdown)
    sidebar = "\n".join(str(item.value) for item in app.sidebar.markdown)
    assert "OPEN RESPONSE &amp; ALLOCATION" in body
    assert "MARKETING BUDGETS, WITHOUT FALSE PRECISION" in body
    assert f"Alloc Signal v{__version__}" in body
    assert "Decision support, not autopilot" in body
    assert "Part of the Signal suite" in body
    assert "AGPL-3.0-or-later" in body
    assert "sg-mast" in body  # the shared Signal masthead
    assert "sg-hero" in body  # the shared Signal hero
    assert "sg-foot" in body  # the shared Signal footer
    assert "Response curves in. A constrained, challengeable marketing budget out." in sidebar
    assert "sg-side" in sidebar  # the shared Signal sidebar lockup


def test_app_uses_shared_signal_theme_instead_of_pasted_styles() -> None:
    standalone = (ROOT / "app.py").read_text(encoding="utf-8")
    ui_source = (UI / "app.py").read_text(encoding="utf-8")
    theme = (UI / "signal_theme.py").read_text(encoding="utf-8")
    assert 'st.set_page_config(**sig.page_config("alloc"))' in standalone
    assert "sig.apply(NS)" in ui_source
    assert "st.plotly_chart(" not in ui_source  # charts go through sig.chart (template + theme=None)
    assert "<style>" not in standalone + ui_source
    assert "unsafe_allow_html" not in standalone + ui_source
    for old_colour in ("#173c3a", "#d95b40", "#83d2b4", "#f2c66d", "#17322e", "#102c2a", "#b9cbc5", "#b08d57"):
        assert old_colour not in (standalone + ui_source).lower()
    assert (UI / "assets" / "marks" / "allocsignal-mark-64.png").exists()
    assert ":focus-visible" in theme
    assert "@media (prefers-reduced-motion:reduce)" in theme
    assert "friendly_message" in ui_source


def test_every_chart_uses_the_alloc_template() -> None:
    source = (UI / "app.py").read_text(encoding="utf-8")
    figures = source.count("go.Figure()")
    assert figures >= 6
    assert source.count("template=sig.template(NS)") >= figures
    assert source.count("sig.chart(NS, ") >= figures


def test_readme_matches_suite_information_architecture() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # Signal README template order: readers find the same section in the same place in every repo.
    sections = [
        "## Read this first",
        "## Scope",
        "## Try the demo in three minutes",
        "## Data contract",
        "## Analysis contract",
        "## Methods",
        "## Decision statuses",
        "## Exports",
        "## Run locally",
        "## Privacy",
        "## No install? Give this file to an AI",
        "## Development",
        "## Where this fits in Signal",
        "## References",
        "## Originality and license",
    ]
    positions = [readme.find(f"\n{heading}\n") for heading in sections]
    assert all(position >= 0 for position in positions), dict(zip(sections, positions))
    assert positions == sorted(positions)
    assert readme.startswith('<p align="center">\n  <img src="assets/allocsignal-banner.png"')
    assert "assets/allocsignal-banner.svg" not in readme
    assert "Signal-Decide-4f80a2" in readme  # family badge in the Decide 600 colour
    assert "github.com/UlrikErlingsen/marketing-mix-allocation/actions" in readme  # tests badge
    assert "**Alloc Signal**" in readme
    assert "AllocSignal" not in readme
    assert '<img src="assets/allocsignal-mark-64.png"' in readme  # suite footer
    assert "Creator Signal" not in readme
    # Honesty statements that must survive any restructuring.
    assert "An optimizer makes assumptions consistent; it does not make them true." in readme
    assert "A panel coefficient is not silently converted into a causal response curve." in readme
    assert "never triggers automatic reallocation" in readme
    assert "not a universal guarantee of the joint global optimum" in readme
    for path in ("assets/allocsignal-banner.png", "assets/allocsignal-mark-64.png", "assets/allocsignal-social.png"):
        assert (ROOT / path).exists()
    assert not (ROOT / "assets" / "allocsignal-banner.svg").exists()


def test_runtime_scaffolding_is_private_and_health_checked() -> None:
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    launcher = (ROOT / "run_app.command").read_text(encoding="utf-8")

    assert "gatherUsageStats = false" in config
    assert 'base = "light"' in config
    assert 'primaryColor = "#4f80a2"' in config  # Signal Decide family, 600 step
    assert "\nUSER allocsignal" in dockerfile
    assert "allocsignal \\\nUSER" not in dockerfile  # a stray continuation would swallow the USER line
    assert "HEALTHCHECK" in dockerfile
    assert "8593" in dockerfile
    assert "ALLOCSIGNAL_PORT" in launcher
    assert "Alloc Signal" in launcher
