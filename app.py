from __future__ import annotations

import os

# Keep Streamlit/Arrow serialization stable on macOS. This must be set early.
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

import base64
import hashlib
import inspect
import json
import platform
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import statsmodels
import streamlit as st


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from allocsignal import __version__
from allocsignal.allocation import evaluate_allocation, optimize_fixed_budget, optimize_profit
from allocsignal.errors import DataProblem, friendly_message
from allocsignal.io import load_data, results_to_excel, results_to_json, tables_to_csv_zip
from allocsignal.panel import analyze_panel
from allocsignal.response import adbudg_response, calibrate_from_anchors
from allocsignal.validation import (
    infer_column,
    numeric_candidates,
    prepare_channel_plan,
    prepare_panel_data,
)


PAGES = [
    "Welcome",
    "1 · Curves & assumptions",
    "2 · Allocate & stress-test",
    "3 · Panel evidence",
    "4 · Decision & export",
    "Methods & limits",
]
COLORS = {
    "ink": "#17322E",
    "deep": "#102C2A",
    "teal": "#173C3A",
    "coral": "#D95B40",
    "mint": "#83D2B4",
    "gold": "#F2C66D",
    "paper": "#F8F5ED",
    "muted": "#59716C",
}
CAUTION = (
    "**Treat the recommendation as a disciplined scenario, not an automatic budget.** Response curves, margin, "
    "constraints, competitive conditions, and cross-channel effects are assumptions until they are validated."
)
INDEPENDENCE_NOTE = (
    "This release adds channel responses independently. It does not estimate synergy, cannibalization, or "
    "cross-channel effects. When those matter, test them experimentally or model them explicitly before acting."
)
mark_path = ROOT / "assets" / "allocsignal-mark.svg"
MARK_URI = (
    "data:image/svg+xml;base64," + base64.b64encode(mark_path.read_bytes()).decode("ascii")
    if mark_path.exists()
    else ""
)


def full_width(widget, *args, **kwargs):
    """Use Streamlit's current width API while retaining older compatibility."""
    try:
        parameters = inspect.signature(widget).parameters
    except (TypeError, ValueError):
        parameters = {}
    width_parameter = parameters.get("width")
    if width_parameter is not None and isinstance(width_parameter.default, str):
        kwargs["width"] = "stretch"
    elif "use_container_width" in parameters:
        kwargs["use_container_width"] = True
    return widget(*args, **kwargs)


st.set_page_config(page_title="AllocSignal | Marketing response & allocation", page_icon="◒", layout="wide")
st.markdown(
    """
    <style>
    :root {
        --ms-ink:#17322e; --ms-deep:#102c2a; --ms-teal:#173c3a;
        --ms-coral:#d95b40; --ms-mint:#83d2b4; --ms-gold:#f2c66d;
        --ms-paper:#f8f5ed; --ms-line:rgba(23,50,46,.14);
    }
    [data-testid="stAppViewContainer"] {
        background:radial-gradient(circle at 94% 2%,rgba(242,198,109,.18),transparent 27rem),
                   radial-gradient(circle at 2% 92%,rgba(131,210,180,.13),transparent 25rem),
                   linear-gradient(180deg,#fbf9f3 0%,var(--ms-paper) 100%);
    }
    [data-testid="stHeader"] { background:rgba(248,245,237,.78); }
    [data-testid="stSidebar"] { background:linear-gradient(165deg,#173c3a 0%,#102c2a 65%,#0c2422 100%); }
    [data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] p,[data-testid="stSidebar"] label,[data-testid="stSidebar"] span { color:#f8f5ed; }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color:#b9cbc5; }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background:rgba(255,255,255,.06); border-color:rgba(131,210,180,.32);
    }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small span { color:#b9cbc5 !important; }
    [data-testid="stSidebar"] [data-testid="stButton"] button {
        background:rgba(255,255,255,.08); color:#f8f5ed !important; border-color:rgba(255,255,255,.23);
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button:hover {
        background:rgba(131,210,180,.16); border-color:rgba(131,210,180,.48);
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button * { color:#f8f5ed !important; }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        background:#f8f5ed; color:#17322e !important;
    }
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button * { color:#17322e !important; }
    .block-container { max-width:1240px; padding-top:4.4rem; padding-bottom:4rem; }
    h1,h2,h3 { color:var(--ms-ink); letter-spacing:-.025em; }
    a { color:#9b3e2b; }
    [data-testid="stMetric"] {
        background:rgba(255,255,255,.75); border:1px solid var(--ms-line); border-radius:16px;
        padding:1rem 1.05rem; box-shadow:0 8px 28px rgba(23,50,46,.045);
    }
    [data-testid="stMetricValue"] { color:var(--ms-ink); font-size:clamp(1.45rem,2.3vw,1.95rem); }
    .stButton > button[kind="primary"] {
        background:linear-gradient(135deg,#e26748,#c94c34); color:white; border:0;
        box-shadow:0 8px 20px rgba(217,91,64,.22); font-weight:750;
    }
    .stButton > button[kind="primary"]:hover { background:linear-gradient(135deg,#c94c34,#b63f2b); color:white; }
    button:focus-visible,a:focus-visible,input:focus-visible { outline:3px solid #f2c66d !important; outline-offset:2px; }
    [data-testid="stExpander"],[data-testid="stAlert"],[data-testid="stVerticalBlockBorderWrapper"] { border-radius:14px; }
    .ms-brand { padding:.25rem 0 1.1rem; }
    .ms-lockup { display:flex; align-items:center; gap:.65rem; }
    .ms-mark { width:38px; height:38px; }
    .ms-name { color:white; font-size:1.28rem; line-height:1; font-weight:850; letter-spacing:-.04em; }
    .ms-name span { color:#f2c66d !important; }
    .ms-tag { margin:.55rem 0 0 !important; color:#b9cbc5 !important; font-size:.77rem; line-height:1.4; }
    .ms-masthead {
        display:flex; justify-content:space-between; align-items:center; gap:1rem; padding:.72rem 1rem .72rem .78rem;
        margin-bottom:1.35rem; background:rgba(255,255,255,.65); border:1px solid var(--ms-line);
        border-radius:18px; box-shadow:0 10px 36px rgba(23,50,46,.05);
    }
    .ms-masthead .ms-mark { width:48px; height:48px; }
    .ms-wordmark { color:var(--ms-ink); font-weight:850; letter-spacing:-.045em; font-size:1.55rem; line-height:1; }
    .ms-wordmark span { color:var(--ms-coral); }
    .ms-kicker { margin-top:.32rem; color:#59716c; font-size:.67rem; font-weight:800; letter-spacing:.13em; }
    .ms-promise { color:#47645e; font-size:.78rem; font-weight:700; white-space:nowrap; }
    .ms-promise span { color:var(--ms-coral); padding:0 .3rem; }
    .ms-hero {
        position:relative; overflow:hidden; padding:clamp(1.7rem,4vw,3.4rem); margin-bottom:1.3rem;
        background:linear-gradient(135deg,#173c3a 0%,#102c2a 75%); border-radius:26px;
        box-shadow:0 18px 50px rgba(23,50,46,.17);
    }
    .ms-hero:after {
        content:""; position:absolute; width:320px; height:320px; right:-104px; top:-142px;
        border-radius:50%; border:58px solid rgba(242,198,109,.12);
    }
    .ms-eyebrow { color:#83d2b4; font-size:.72rem; font-weight:850; letter-spacing:.16em; }
    .ms-hero h1 { color:white; font-size:clamp(2.25rem,5vw,4.7rem); line-height:.97; margin:.75rem 0 1rem; max-width:940px; }
    .ms-hero h1 em { color:#f2c66d; font-style:normal; }
    .ms-hero p { color:#d7e3df; font-size:1.06rem; line-height:1.6; max-width:800px; }
    .ms-pills { display:flex; flex-wrap:wrap; gap:.55rem; margin-top:1.15rem; }
    .ms-pill {
        padding:.4rem .72rem; border:1px solid rgba(255,255,255,.16); border-radius:999px;
        color:#f8f5ed; font-size:.78rem; font-weight:700; background:rgba(255,255,255,.055);
    }
    .ms-step,.ms-insight {
        height:100%; padding:1.2rem 1.2rem 1rem; background:rgba(255,255,255,.66);
        border:1px solid var(--ms-line); border-radius:18px;
    }
    .ms-action-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; }
    .ms-step b,.ms-insight b { color:var(--ms-coral); font-size:.72rem; letter-spacing:.12em; }
    .ms-step h3,.ms-insight h3 { margin:.4rem 0 .5rem; overflow-wrap:normal; word-break:normal; hyphens:none; }
    .ms-step p,.ms-insight p { color:#59716c; font-size:.9rem; line-height:1.55; }
    .ms-note {
        padding:1rem 1.1rem; margin:.75rem 0 1rem; border-left:4px solid var(--ms-mint);
        background:rgba(255,255,255,.62); border-radius:0 14px 14px 0; color:#47645e;
    }
    .ms-callout {
        padding:1.1rem 1.25rem; margin:1rem 0; background:linear-gradient(135deg,rgba(242,198,109,.20),rgba(255,255,255,.66));
        border:1px solid rgba(217,91,64,.18); border-radius:16px; color:#36534e;
    }
    .ms-footer { margin-top:3.2rem; padding-top:1rem; border-top:1px solid var(--ms-line); color:#617670; font-size:.76rem; text-align:center; }
    .ms-footer span { color:var(--ms-coral); padding:0 .38rem; }
    @media (max-width:1150px) { .ms-action-grid{grid-template-columns:1fr} }
    @media (max-width:760px) { .ms-promise{display:none}.ms-hero{border-radius:20px}.block-container{padding-top:3.5rem} }
    @media (prefers-reduced-motion:reduce) { * { scroll-behavior:auto !important; transition:none !important; } }
    </style>
    """,
    unsafe_allow_html=True,
)


def show_error(exc: Exception) -> None:
    st.error(friendly_message(exc))
    if not isinstance(exc, (DataProblem, ValueError)) and os.getenv("ALLOCSIGNAL_DEBUG") == "1":
        with st.expander("Technical details"):
            st.code("".join(traceback.format_exception(exc)))


def masthead() -> None:
    image = f'<img class="ms-mark" src="{MARK_URI}" alt="AllocSignal allocation mark"/>' if MARK_URI else "◒"
    st.markdown(
        f"""
        <div class="ms-masthead"><div class="ms-lockup">{image}
        <div><div class="ms-wordmark">Alloc<span>Signal</span></div>
        <div class="ms-kicker">OPEN RESPONSE & ALLOCATION</div></div></div>
        <div class="ms-promise">Local-first <span>•</span> Explainable <span>•</span> Open source</div></div>
        """,
        unsafe_allow_html=True,
    )


def footer() -> None:
    st.markdown(
        f"<div class='ms-footer'>AllocSignal {__version__}<span>•</span>Decision support, not autopilot"
        "<span>•</span>AGPL-3.0-or-later</div>",
        unsafe_allow_html=True,
    )


def go_to(page_name: str) -> None:
    st.session_state["nav_target"] = page_name
    st.session_state["nav_epoch"] = int(st.session_state["nav_epoch"]) + 1


def _fingerprint(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_plan_demo() -> None:
    path = ROOT / "examples" / "demo_channel_plan.csv"
    loaded = load_data(path)
    st.session_state["plan_tables"] = None
    st.session_state["plan_table"] = None
    st.session_state["plan_raw"] = next(iter(loaded.tables.values()))
    st.session_state["plan_source"] = path.name
    st.session_state["plan_fingerprint"] = _fingerprint(path.read_bytes())
    st.session_state["channel_plan"] = None
    st.session_state["allocation_results"] = None
    st.session_state["calibration_results"] = {}
    st.session_state["plan_editor_epoch"] = int(st.session_state.get("plan_editor_epoch", 0)) + 1
    go_to("1 · Curves & assumptions")


def load_panel_demo() -> None:
    path = ROOT / "examples" / "demo_marketing_panel.csv"
    loaded = load_data(path)
    st.session_state["panel_tables"] = loaded.tables
    st.session_state["panel_table"] = next(iter(loaded.tables))
    st.session_state["panel_source"] = path.name
    st.session_state["panel_fingerprint"] = _fingerprint(path.read_bytes())
    st.session_state["panel_analysis"] = None
    go_to("3 · Panel evidence")


def _load_upload(uploaded, purpose: str) -> None:
    raw = uploaded.getvalue()
    fingerprint = _fingerprint(raw)
    state_key = "plan_upload_seen" if purpose == "Channel plan" else "panel_upload_seen"
    if st.session_state.get(state_key) == fingerprint:
        return
    loaded = load_data(raw, name=uploaded.name)
    st.session_state[state_key] = fingerprint
    if purpose == "Channel plan":
        st.session_state["plan_tables"] = loaded.tables
        st.session_state["plan_table"] = next(iter(loaded.tables))
        st.session_state["plan_raw"] = loaded.tables[st.session_state["plan_table"]]
        st.session_state["plan_source"] = loaded.source_name
        st.session_state["plan_fingerprint"] = fingerprint
        st.session_state["channel_plan"] = None
        st.session_state["allocation_results"] = None
        st.session_state["calibration_results"] = {}
        st.session_state["plan_editor_epoch"] = int(st.session_state.get("plan_editor_epoch", 0)) + 1
        go_to("1 · Curves & assumptions")
    else:
        st.session_state["panel_tables"] = loaded.tables
        st.session_state["panel_table"] = next(iter(loaded.tables))
        st.session_state["panel_source"] = loaded.source_name
        st.session_state["panel_fingerprint"] = fingerprint
        st.session_state["panel_analysis"] = None
        go_to("3 · Panel evidence")


for key, default in (
    ("nav_target", PAGES[0]),
    ("nav_epoch", 0),
    ("plan_raw", None),
    ("plan_tables", None),
    ("plan_table", None),
    ("plan_source", None),
    ("plan_fingerprint", None),
    ("channel_plan", None),
    ("plan_editor_epoch", 0),
    ("calibration_results", {}),
    ("planning_assumptions", {"margin": 0.42, "base_response": 500.0}),
    ("allocation_results", None),
    ("panel_tables", None),
    ("panel_table", None),
    ("panel_source", None),
    ("panel_fingerprint", None),
    ("panel_prepared", None),
    ("panel_roles", None),
    ("panel_analysis", None),
):
    st.session_state.setdefault(key, default)


with st.sidebar:
    image = f'<img class="ms-mark" src="{MARK_URI}" alt="AllocSignal mark"/>' if MARK_URI else "◒"
    st.markdown(
        f"<div class='ms-brand'><div class='ms-lockup'>{image}<div class='ms-name'>Alloc<span>Signal</span></div></div>"
        "<p class='ms-tag'>Response curves in. A constrained, challengeable marketing budget out.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown("### Start with a worked example")
    if full_width(st.button, "Demo · channel plan"):
        try:
            load_plan_demo()
            st.rerun()
        except Exception as exc:
            show_error(exc)
    if full_width(st.button, "Demo · regional panel"):
        try:
            load_panel_demo()
            st.rerun()
        except Exception as exc:
            show_error(exc)
    st.markdown("### Or bring your own data")
    purpose = st.selectbox("Upload type", ["Channel plan", "Panel history"])
    upload = st.file_uploader(
        "CSV, Excel, or JSON",
        type=["csv", "xlsx", "xls", "xlsm", "json"],
        key=f"{purpose.lower().replace(' ', '_')}_upload",
    )
    if upload is not None:
        try:
            _load_upload(upload, purpose)
        except Exception as exc:
            show_error(exc)

    if purpose == "Channel plan" and st.session_state.get("plan_tables"):
        names = list(st.session_state["plan_tables"])
        selected = st.selectbox("Table / sheet", names, index=names.index(st.session_state["plan_table"]))
        if selected != st.session_state["plan_table"]:
            st.session_state["plan_table"] = selected
            st.session_state["plan_raw"] = st.session_state["plan_tables"][selected]
            st.session_state["channel_plan"] = None
            st.session_state["allocation_results"] = None
            st.session_state["calibration_results"] = {}
            st.session_state["plan_editor_epoch"] = int(st.session_state["plan_editor_epoch"]) + 1
    elif purpose == "Panel history" and st.session_state.get("panel_tables"):
        names = list(st.session_state["panel_tables"])
        selected = st.selectbox("Table / sheet", names, index=names.index(st.session_state["panel_table"]))
        if selected != st.session_state["panel_table"]:
            st.session_state["panel_table"] = selected
            st.session_state["panel_analysis"] = None

    st.markdown("### Follow the workflow")
    page = st.radio(
        "Page",
        PAGES,
        index=PAGES.index(st.session_state["nav_target"]),
        key=f"nav_radio_{st.session_state['nav_epoch']}",
        label_visibility="collapsed",
    )
    st.session_state["nav_target"] = page

masthead()


def _curve_response(row: pd.Series, spend: np.ndarray | float) -> float | np.ndarray:
    """Evaluate one plotted curve through the tested, overflow-safe engine."""
    return adbudg_response(
        spend,
        floor=float(row["floor_response"]),
        ceiling=float(row["ceiling_response"]),
        half_saturation=float(row["half_saturation"]),
        shape=float(row["shape"]),
    )


def _curve_figure(plan: pd.DataFrame, recommended: pd.DataFrame | None = None) -> go.Figure:
    figure = go.Figure()
    palette = [COLORS["ink"], COLORS["coral"], COLORS["mint"], COLORS["gold"], "#6E7EB8", "#A0668B"]
    rec_lookup: dict[str, float] = {}
    if recommended is not None and {"channel", "recommended_spend"}.issubset(recommended.columns):
        rec_lookup = dict(zip(recommended["channel"].astype(str), recommended["recommended_spend"].astype(float)))
    for index, (_, row) in enumerate(plan.iterrows()):
        upper = max(float(row["max_spend"]), float(row["half_saturation"]) * 2.2, 1.0)
        x = np.linspace(0.0, upper, 140)
        color = palette[index % len(palette)]
        figure.add_trace(
            go.Scatter(
                x=x,
                y=_curve_response(row, x),
                mode="lines",
                name=str(row["channel"]),
                line=dict(color=color, width=2.5),
                hovertemplate="Spend %{x:,.1f}<br>Response %{y:,.1f}<extra>%{fullData.name}</extra>",
            )
        )
        current = float(row["current_spend"])
        figure.add_trace(
            go.Scatter(
                x=[current],
                y=[float(_curve_response(row, current))],
                mode="markers",
                showlegend=False,
                marker=dict(color=color, size=9, line=dict(color="white", width=1.5)),
                hovertemplate="Current spend %{x:,.1f}<br>Response %{y:,.1f}<extra></extra>",
            )
        )
        if str(row["channel"]) in rec_lookup:
            proposed = rec_lookup[str(row["channel"])]
            figure.add_trace(
                go.Scatter(
                    x=[proposed],
                    y=[float(_curve_response(row, proposed))],
                    mode="markers",
                    showlegend=False,
                    marker=dict(symbol="diamond", color=color, size=11, line=dict(color=COLORS["deep"], width=1.5)),
                    hovertemplate="Proposed spend %{x:,.1f}<br>Response %{y:,.1f}<extra></extra>",
                )
            )
    figure.update_layout(
        height=470,
        margin=dict(l=10, r=10, t=24, b=10),
        xaxis_title="Spend / effort (same unit as your plan)",
        yaxis_title="Attributed response units",
        legend_title_text="",
        hovermode="closest",
        plot_bgcolor="rgba(255,255,255,.55)",
    )
    return figure


def _planning_plan(horizon: str) -> pd.DataFrame:
    plan = st.session_state["channel_plan"].copy()
    if horizon == "Long-run judgment":
        increment = plan["ceiling_response"] - plan["floor_response"]
        plan["ceiling_response"] = plan["floor_response"] + increment * plan["long_run_multiplier"]
    return plan


def _allocation_totals(table: pd.DataFrame, margin: float, base_response: float) -> dict[str, float]:
    current_spend = float(table["current_spend"].sum())
    recommended_spend = float(table["recommended_spend"].sum())
    current_response = float(table["current_response"].sum()) + base_response
    recommended_response = float(table["recommended_response"].sum()) + base_response
    return {
        "current_spend": current_spend,
        "recommended_spend": recommended_spend,
        "current_response": current_response,
        "recommended_response": recommended_response,
        "current_profit": current_response * margin - current_spend,
        "recommended_profit": recommended_response * margin - recommended_spend,
    }


def _materially_different(left: float, right: float) -> bool:
    scale = max(abs(float(left)), abs(float(right)), 1.0)
    return not bool(np.isclose(float(left), float(right), rtol=1e-9, atol=1e-7 * scale))


def _budget_figure(table: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            y=table["channel"], x=table["current_spend"], name="Current", orientation="h",
            marker_color="#B9CBC5", hovertemplate="%{y}<br>Current %{x:,.1f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            y=table["channel"], x=table["recommended_spend"], name="Proposed", orientation="h",
            marker_color=COLORS["coral"], hovertemplate="%{y}<br>Proposed %{x:,.1f}<extra></extra>",
        )
    )
    figure.update_layout(
        barmode="group", height=max(340, 58 * len(table)), margin=dict(l=10, r=10, t=20, b=10),
        xaxis_title="Spend / effort", yaxis_title="", legend_title_text="", plot_bgcolor="rgba(255,255,255,.55)",
    )
    return figure


def welcome_page() -> None:
    st.markdown(
        """
        <section class="ms-hero"><div class="ms-eyebrow">MARKETING BUDGETS, WITHOUT FALSE PRECISION</div>
        <h1>Put the next unit where it <em>works hardest.</em></h1>
        <p>AllocSignal turns saturating channel-response assumptions into a constrained budget recommendation—and
        keeps the historical evidence, uncertainty, and implementation caveats close enough to challenge it.</p>
        <div class="ms-pills"><span class="ms-pill">No account</span><span class="ms-pill">No telemetry</span>
        <span class="ms-pill">Nonlinear response</span><span class="ms-pill">Panel-aware evidence</span>
        <span class="ms-pill">Auditable exports</span></div></section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(CAUTION)
    columns = st.columns(3)
    steps = [
        ("STEP 01", "Make the curves explicit", "Enter what each channel can do at zero, current, and saturation spend. The assumptions stop hiding inside an ROI ratio."),
        ("STEP 02", "Size, reallocate, constrain", "Compare the current plan, a fixed-budget reallocation, and a profit-sized plan under practical minima, maxima, and fixed commitments."),
        ("STEP 03", "Challenge with evidence", "Use repeated region, store, or campaign data to compare pooled, fixed-effects, and random-effects associations before implementing a test."),
    ]
    for column, (number, title, body) in zip(columns, steps):
        column.markdown(
            f"<div class='ms-step'><b>{number}</b><h3>{title}</h3><p>{body}</p></div>",
            unsafe_allow_html=True,
        )
    st.write("")
    metrics = st.columns(4)
    metrics[0].metric("Response model", "ADBUDG / Hill", "saturating, not linear ROI")
    metrics[1].metric("Budget views", "3", "current · reallocated · sized")
    metrics[2].metric("Panel estimators", "3", "pooled · FE · RE")
    metrics[3].metric("AI / uploads sent", "None", "local Python process")
    st.markdown(
        """
        <div class="ms-callout"><b>The key distinction:</b> panel models describe historical conditional
        associations; response curves are forward-looking planning assumptions. AllocSignal shows both, but it does
        not quietly turn one into the other.</div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Where AllocSignal fits in the Signal portfolio"):
        st.write(
            "PositionSignal maps where brands are perceived, ChoiceSignal models what people prefer, "
            "SegmentSignal finds who differs, AdoptSignal forecasts when adoption spreads, and WorthSignal values "
            "customers. AllocSignal asks a different decision question: **how much should we invest, and where, given "
            "diminishing returns and real constraints?**"
        )


def curves_page() -> None:
    st.title("Make the response assumptions visible")
    st.write(
        "Use one row per channel. Spend and response may be in thousands, units, leads, or sales—just keep the "
        "units consistent. The default curve reaches halfway from its floor to its ceiling at `half_saturation`."
    )
    raw = st.session_state.get("plan_raw")
    if raw is None:
        st.info("Load the fictional channel plan in the sidebar, or upload the channel-plan template.")
        template = ROOT / "examples" / "channel_plan_template.csv"
        if template.exists():
            full_width(
                st.download_button,
                "Download channel-plan template",
                template.read_bytes(),
                "allocsignal_channel_plan_template.csv",
                "text/csv",
            )
        return
    st.caption(f"{st.session_state.get('plan_source')} · {len(raw):,} channel row(s)")
    editor_columns = {
        "channel": st.column_config.TextColumn("Channel", help="A unique, human-readable channel name."),
        "current_spend": st.column_config.NumberColumn("Current spend", min_value=0.0, format="%.2f"),
        "min_spend": st.column_config.NumberColumn("Minimum", min_value=0.0, format="%.2f"),
        "max_spend": st.column_config.NumberColumn("Maximum", min_value=0.0, format="%.2f"),
        "floor_response": st.column_config.NumberColumn("Response at zero", min_value=0.0, format="%.2f"),
        "ceiling_response": st.column_config.NumberColumn("Saturation response", min_value=0.0, format="%.2f"),
        "half_saturation": st.column_config.NumberColumn("Half-saturation spend", min_value=0.01, format="%.2f"),
        "shape": st.column_config.NumberColumn("Shape c", min_value=0.05, format="%.2f"),
        "long_run_multiplier": st.column_config.NumberColumn("Long-run effect ×", min_value=0.01, format="%.2f"),
        "fixed": st.column_config.CheckboxColumn("Fixed?"),
    }
    edited = full_width(
        st.data_editor,
        raw,
        num_rows="dynamic",
        hide_index=True,
        column_config=editor_columns,
        key=(
            f"channel_editor_{st.session_state.get('plan_fingerprint') or 'manual'}_"
            f"{st.session_state.get('plan_editor_epoch', 0)}"
        ),
    )
    assumptions = st.session_state.get("planning_assumptions", {})
    inputs = st.columns(2)
    margin = inputs[0].number_input(
        "Contribution margin per response unit",
        min_value=0.0001,
        value=float(assumptions.get("margin", 0.42)),
        step=0.01,
        format="%.4f",
        help="Revenue less variable non-marketing cost per unit of the response outcome. Keep its currency scale consistent with spend.",
    )
    base_response = inputs[1].number_input(
        "Response not assigned to these channels",
        min_value=0.0,
        value=float(assumptions.get("base_response", 500.0)),
        step=10.0,
        help="A constant base used in total response and contribution. It does not affect reallocation when it is truly constant.",
    )
    st.markdown(
        "<div class='ms-note'><b>Curve reading.</b> Shape c &lt; 1 is concave from the start; c &gt; 1 is S-shaped. "
        "The maximum is an asymptote, not a promise that the observed market has already reached it.</div>",
        unsafe_allow_html=True,
    )
    if st.button("Validate & save these curves", type="primary"):
        try:
            plan = prepare_channel_plan(edited)
            st.session_state["channel_plan"] = plan
            st.session_state["plan_raw"] = edited.copy()
            st.session_state["planning_assumptions"] = {"margin": float(margin), "base_response": float(base_response)}
            st.session_state["allocation_results"] = None
            st.success("Curves and economic assumptions saved.")
        except Exception as exc:
            show_error(exc)

    plan = st.session_state.get("channel_plan")
    if plan is None:
        return
    checks = st.columns(4)
    checks[0].metric("Channels", f"{len(plan)}")
    checks[1].metric("Current budget", f"{plan['current_spend'].sum():,.1f}")
    checks[2].metric("Fixed channels", f"{int(plan['fixed'].sum())}")
    checks[3].metric("Response scale", "Additive", "independent channels")
    st.subheader("The curves you are asking the optimizer to believe")
    full_width(st.plotly_chart, _curve_figure(plan))
    st.caption("Circles mark current spend. Curves are channel-attributed response; the constant base response is not plotted.")
    with st.expander("Fit one channel from zero / current / increased / saturation anchors", expanded=False):
        st.write(
            "Use this when the evidence is structured managerial judgment. Ask several people to estimate the "
            "anchors independently before reconciling them; consensus reached too early can hide uncertainty."
        )
        selected_channel = st.selectbox("Channel to calibrate", plan["channel"].tolist(), key="anchor_channel")
        selected_row = plan.loc[plan["channel"] == selected_channel].iloc[0]
        current_x_default = float(selected_row["current_spend"])
        increased_x_default = current_x_default + max(
            (float(selected_row["max_spend"]) - current_x_default) * 0.55,
            max(current_x_default * 0.25, 1.0),
        )
        increased_x_default = min(increased_x_default, max(float(selected_row["max_spend"]), current_x_default + 1.0))
        saturation_x_default = max(
            float(selected_row["max_spend"]) * 1.8,
            increased_x_default * 1.5,
            current_x_default + 2.0,
        )
        anchor_inputs = st.columns(4)
        zero_y = anchor_inputs[0].number_input(
            "Response at zero spend",
            min_value=0.0,
            value=float(selected_row["floor_response"]),
            key=f"anchor_zero_y_{selected_channel}",
        )
        current_x = anchor_inputs[1].number_input(
            "Current / base spend",
            min_value=0.0,
            value=current_x_default,
            key=f"anchor_current_x_{selected_channel}",
        )
        current_y = anchor_inputs[1].number_input(
            "Response at current spend",
            min_value=0.0,
            value=float(_curve_response(selected_row, current_x_default)),
            key=f"anchor_current_y_{selected_channel}",
        )
        increased_x = anchor_inputs[2].number_input(
            "Plausible increased spend",
            min_value=0.0,
            value=float(increased_x_default),
            key=f"anchor_increased_x_{selected_channel}",
        )
        increased_y = anchor_inputs[2].number_input(
            "Response at increased spend",
            min_value=0.0,
            value=float(_curve_response(selected_row, increased_x_default)),
            key=f"anchor_increased_y_{selected_channel}",
        )
        saturation_x = anchor_inputs[3].number_input(
            "Spend near saturation",
            min_value=0.0,
            value=float(saturation_x_default),
            key=f"anchor_saturation_x_{selected_channel}",
        )
        saturation_y = anchor_inputs[3].number_input(
            "Response near saturation",
            min_value=0.0,
            value=float(_curve_response(selected_row, saturation_x_default)),
            key=f"anchor_saturation_y_{selected_channel}",
        )
        st.caption(
            "The highest anchor is a response observed or believed at a large finite spend. The fitted ceiling is "
            "an extrapolated asymptote and need not equal that anchor exactly."
        )
        if st.button("Fit these four anchors into the channel curve", key="fit_anchors", type="primary"):
            try:
                fitted = calibrate_from_anchors(
                    zero_response=float(zero_y),
                    current_spend=float(current_x),
                    current_response=float(current_y),
                    increased_spend=float(increased_x),
                    increased_response=float(increased_y),
                    saturation_spend=float(saturation_x),
                    saturation_response=float(saturation_y),
                )
                updated = plan.copy()
                mask = updated["channel"] == selected_channel
                updated.loc[mask, "floor_response"] = fitted.curve.floor
                updated.loc[mask, "ceiling_response"] = fitted.curve.ceiling
                updated.loc[mask, "half_saturation"] = fitted.curve.half_saturation
                updated.loc[mask, "shape"] = fitted.curve.shape
                st.session_state["channel_plan"] = updated
                st.session_state["plan_raw"] = updated.copy()
                st.session_state["calibration_results"] = {
                    **st.session_state.get("calibration_results", {}),
                    selected_channel: fitted,
                }
                st.session_state["allocation_results"] = None
                st.session_state["plan_editor_epoch"] = int(st.session_state["plan_editor_epoch"]) + 1
                st.rerun()
            except Exception as exc:
                show_error(exc)
        fitted = st.session_state.get("calibration_results", {}).get(selected_channel)
        if fitted is not None:
            fit_metrics = st.columns(3)
            fit_metrics[0].metric("Anchor RMSE", f"{fitted.rmse:,.3g}")
            fit_metrics[1].metric("Anchor R²", f"{fitted.r_squared:.3f}")
            fit_metrics[2].metric("Anchors", f"{fitted.n_observations}")
            full_width(st.dataframe, fitted.parameter_table(), hide_index=True)
            full_width(st.dataframe, fitted.fitted, hide_index=True)
            for warning in fitted.warnings:
                st.warning(warning)
    with st.expander("Calibration routes: historical data, experiments, or structured judgment", expanded=False):
        st.markdown(
            """
            **Historical route.** Repeated observations can test whether a channel varies enough and whether its
            within-entity association differs from the pooled story. Linear panel coefficients are not saturation
            parameters; use them as evidence, not an automatic conversion.

            **Experimental route.** Geo tests, matched markets, or randomized increments are the strongest way to
            identify incremental response over the tested range. Extrapolation beyond that range remains an assumption.

            **Judgmental route.** Elicit independent estimates for zero spend, current/base spend, an increased-spend
            point, and saturation; reconcile them, fit a curve, and stress-test the disputed inputs. The editable
            parameters above use the equivalent floor, ceiling, half-saturation, and shape representation.
            """
        )
    if full_width(st.button, "Continue to 2 · Allocate & stress-test →"):
        go_to("2 · Allocate & stress-test")
        st.rerun()


def allocation_page() -> None:
    st.title("Compare the current plan with feasible alternatives")
    plan = st.session_state.get("channel_plan")
    if plan is None:
        st.info("Validate a channel plan on page 1 first.")
        return
    assumptions = st.session_state["planning_assumptions"]
    current_budget = float(plan["current_spend"].sum())
    controls = st.columns([1.2, 1, 1])
    total_budget = controls[0].number_input(
        "Total budget for the constrained plan",
        min_value=0.0,
        value=current_budget,
        step=max(current_budget / 100, 1.0),
        help="This total is held exactly in the constrained reallocation. Fixed-channel spend still counts toward it.",
    )
    horizon = controls[1].selectbox(
        "Effect horizon",
        ["Short-run curve", "Long-run judgment"],
        help="Long-run uses each row's multiplier on the incremental ceiling. It is a scenario, not an estimated carryover model.",
    )
    sensitivity_width = controls[2].slider(
        "Sensitivity width",
        min_value=5,
        max_value=40,
        value=20,
        step=5,
        format="±%d%%",
        help="Low/high scenarios move attainable response and the spend needed to reach it in opposite directions.",
    )
    st.caption(
        "The constrained run keeps the chosen total budget. The sizing run may spend less or more until no feasible "
        "channel has positive marginal profit. Both respect every minimum, maximum, and fixed commitment."
    )
    if st.button("Run baseline, reallocation, sizing & sensitivity", type="primary"):
        try:
            working = _planning_plan(horizon)
            margin = float(assumptions["margin"])
            base = float(assumptions["base_response"])
            baseline = evaluate_allocation(working, margin=margin, base_response=base)
            constrained = optimize_fixed_budget(working, total_budget=float(total_budget), margin=margin, base_response=base)
            sized = optimize_profit(working, margin=margin, base_response=base)
            width = sensitivity_width / 100
            scenarios: dict[str, object] = {}
            for label, ceiling_factor, half_factor in (
                ("Low response", 1 - width, 1 + width),
                ("Base", 1.0, 1.0),
                ("High response", 1 + width, max(1 - width, 0.05)),
            ):
                stressed = working.copy()
                gap = stressed["ceiling_response"] - stressed["floor_response"]
                stressed["ceiling_response"] = stressed["floor_response"] + gap * ceiling_factor
                stressed["half_saturation"] = stressed["half_saturation"] * half_factor
                scenarios[label] = optimize_fixed_budget(
                    stressed, total_budget=float(total_budget), margin=margin, base_response=base
                )
            st.session_state["allocation_results"] = {
                "horizon": horizon,
                "budget": float(total_budget),
                "sensitivity_width": sensitivity_width,
                "plan": working,
                "baseline": baseline,
                "constrained": constrained,
                "sized": sized,
                "scenarios": scenarios,
            }
        except Exception as exc:
            show_error(exc)

    results = st.session_state.get("allocation_results")
    if not results:
        return
    margin = float(assumptions["margin"])
    base = float(assumptions["base_response"])
    constrained_table = results["constrained"].table.copy()
    sized_table = results["sized"].table.copy()
    constrained_totals = _allocation_totals(constrained_table, margin, base)
    sized_totals = _allocation_totals(sized_table, margin, base)
    chosen_budget_differs = _materially_different(
        constrained_totals["recommended_spend"], constrained_totals["current_spend"]
    )
    metrics = st.columns(4)
    metrics[0].metric("Current net contribution", f"{constrained_totals['current_profit']:,.1f}")
    metrics[1].metric(
        "Chosen-budget lift" if chosen_budget_differs else "Reallocation lift",
        f"{constrained_totals['recommended_profit'] - constrained_totals['current_profit']:,.1f}",
        f"response {constrained_totals['recommended_response'] - constrained_totals['current_response']:+,.1f}",
    )
    metrics[2].metric(
        "Sized-plan lift",
        f"{sized_totals['recommended_profit'] - sized_totals['current_profit']:,.1f}",
        f"spend {sized_totals['recommended_spend'] - sized_totals['current_spend']:+,.1f}",
    )
    metrics[3].metric("Planning horizon", results["horizon"].replace(" curve", ""))
    if chosen_budget_differs:
        st.info(
            f"The constrained plan changes total spend by "
            f"{constrained_totals['recommended_spend'] - constrained_totals['current_spend']:+,.1f}. "
            "Its lift and response deltas combine a budget-size change with a channel-mix change; "
            "they are not a pure reallocation effect."
        )
    st.markdown(CAUTION)
    tabs = st.tabs(
        [
            "Chosen-budget plan" if chosen_budget_differs else "Constrained reallocation",
            "Profit-sized plan",
            "Sensitivity",
            "Nerd table",
        ]
    )
    with tabs[0]:
        if chosen_budget_differs:
            st.subheader("Chosen budget and channel mix")
            st.markdown(
                f"This scenario proposes **{constrained_totals['recommended_spend']:,.1f}** in total versus "
                f"**{constrained_totals['current_spend']:,.1f}** now. The comparison therefore answers two "
                "questions together: how the total changes and how that chosen total is distributed."
            )
        else:
            st.subheader("Same total budget, different mix")
        full_width(st.plotly_chart, _budget_figure(constrained_table))
        display = constrained_table[
            ["channel", "current_spend", "recommended_spend", "change", "recommended_response", "marginal_profit", "at_min", "at_max"]
        ].copy()
        full_width(st.dataframe, display, hide_index=True)
        st.caption("At an interior optimum, feasible channels tend toward similar marginal profit. Bounds and fixed commitments prevent exact equality.")
    with tabs[1]:
        st.subheader("Let economic return size the total")
        full_width(st.plotly_chart, _budget_figure(sized_table))
        st.markdown(
            f"The sized scenario proposes **{sized_totals['recommended_spend']:,.1f}** in total versus "
            f"**{sized_totals['current_spend']:,.1f}** now, under the entered bounds and contribution margin."
        )
        full_width(
            st.dataframe,
            sized_table[["channel", "recommended_spend", "change", "marginal_profit", "elasticity", "at_min", "at_max"]],
            hide_index=True,
        )
    with tabs[2]:
        rows: list[dict[str, float | str]] = []
        spend_rows: list[pd.DataFrame] = []
        for label, result in results["scenarios"].items():
            totals = _allocation_totals(result.table, margin, base)
            rows.append(
                {
                    "scenario": label,
                    "total_spend": totals["recommended_spend"],
                    "total_response": totals["recommended_response"],
                    "net_contribution": totals["recommended_profit"],
                    "lift_vs_current": totals["recommended_profit"] - totals["current_profit"],
                }
            )
            part = result.table[["channel", "recommended_spend"]].copy()
            part["scenario"] = label
            spend_rows.append(part)
        sensitivity = pd.DataFrame(rows)
        full_width(st.dataframe, sensitivity, hide_index=True)
        long = pd.concat(spend_rows, ignore_index=True)
        figure = go.Figure()
        for label, color in zip(["Low response", "Base", "High response"], ["#B9CBC5", COLORS["coral"], COLORS["gold"]]):
            subset = long[long["scenario"] == label]
            figure.add_trace(go.Bar(x=subset["channel"], y=subset["recommended_spend"], name=label, marker_color=color))
        figure.update_layout(
            barmode="group", height=410, margin=dict(l=10, r=10, t=20, b=10),
            yaxis_title="Recommended spend", xaxis_title="", legend_title_text="",
        )
        full_width(st.plotly_chart, figure)
        st.caption(
            "Low/high scenarios jointly change attainable incremental response and half-saturation spend. They are "
            "structured stress tests, not confidence intervals."
        )
    with tabs[3]:
        full_width(st.dataframe, constrained_table, hide_index=True)
        st.caption(
            "Marginal profit is margin × marginal response − 1. Elasticity is the percentage response change for "
            "a 1% spend change at that point; it is not a constant ROI."
        )
    st.subheader("Curves with proposed constrained spend")
    full_width(st.plotly_chart, _curve_figure(results["plan"], constrained_table))
    st.caption("Circles are current spend; diamonds are the constrained proposal.")
    st.warning(INDEPENDENCE_NOTE)


def _coefficient_figure(analysis) -> go.Figure:
    figure = go.Figure()
    palette = {"Pooled OLS": "#B08D57", "Entity fixed effects": COLORS["coral"], "Random effects": COLORS["teal"]}
    for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
        frame = result.coefficients.copy()
        term_column = "term" if "term" in frame else frame.columns[0]
        term_text = frame[term_column].astype(str)
        public_term = ~term_text.str.lower().isin({"const", "intercept"}) & ~term_text.str.startswith("__period=")
        frame = frame[public_term]
        lower = next((name for name in ("ci_lower", "conf_low", "lower") if name in frame), None)
        upper = next((name for name in ("ci_upper", "conf_high", "upper") if name in frame), None)
        label = str(result.estimator)
        error = None
        if lower and upper:
            error = dict(
                type="data",
                symmetric=False,
                array=(frame[upper] - frame["estimate"]).clip(lower=0),
                arrayminus=(frame["estimate"] - frame[lower]).clip(lower=0),
                thickness=1.3,
            )
        figure.add_trace(
            go.Scatter(
                x=frame["estimate"], y=frame[term_column], mode="markers", name=label,
                marker=dict(size=10, color=palette.get(label, COLORS["ink"])), error_x=error,
                hovertemplate="%{y}<br>Estimate %{x:.4g}<extra>%{fullData.name}</extra>",
            )
        )
    figure.add_vline(x=0, line_dash="dot", line_color="#7A8D88")
    figure.update_layout(
        height=460, margin=dict(l=10, r=20, t=20, b=10), xaxis_title="Conditional association estimate",
        yaxis_title="", legend_title_text="", plot_bgcolor="rgba(255,255,255,.55)",
    )
    return figure


def panel_page() -> None:
    st.title("Challenge the planning story with repeated observations")
    st.write(
        "Use one row per entity and period—for example region × month or store × week. AllocSignal compares the "
        "naive pooled relationship with within-entity fixed effects and a random-effects model."
    )
    tables = st.session_state.get("panel_tables")
    if not tables:
        st.info("Load the fictional regional panel in the sidebar, or upload your own panel history.")
        template = ROOT / "examples" / "panel_template.csv"
        if template.exists():
            full_width(st.download_button, "Download panel template", template.read_bytes(), "allocsignal_panel_template.csv", "text/csv")
        return
    frame = tables[st.session_state["panel_table"]]
    st.caption(f"{st.session_state.get('panel_source')} · {len(frame):,} rows × {len(frame.columns)} columns")
    full_width(st.dataframe, frame.head(12), hide_index=True)
    columns = [str(column) for column in frame.columns]
    entity_guess = infer_column(columns, ("region", "store", "market", "entity", "account", "campaign", "id"))
    time_guess = infer_column(columns, ("period", "month", "week", "quarter", "year", "date"), fallback=min(1, len(columns) - 1))
    outcome_guess = infer_column(columns, ("sales", "revenue", "orders", "outcome", "conversion"), fallback=len(columns) - 1)
    roles = st.session_state.get("panel_roles") or {}
    role_columns = st.columns(3)
    entity = role_columns[0].selectbox(
        "Entity ID", columns, index=columns.index(roles.get("entity", entity_guess)) if roles.get("entity", entity_guess) in columns else 0
    )
    time = role_columns[1].selectbox(
        "Time", columns, index=columns.index(roles.get("time", time_guess)) if roles.get("time", time_guess) in columns else 0
    )
    outcome = role_columns[2].selectbox(
        "Outcome", columns, index=columns.index(roles.get("outcome", outcome_guess)) if roles.get("outcome", outcome_guess) in columns else 0
    )
    excluded = {entity, time, outcome}
    numeric = numeric_candidates(frame, excluded)
    default_predictors = roles.get("numeric_predictors") or [
        column for column in numeric if any(token in column.lower() for token in ("search", "display", "media", "spend", "price", "distribution"))
    ]
    if not default_predictors:
        default_predictors = numeric[: min(4, len(numeric))]
    numeric_predictors = st.multiselect("Numeric marketing variables and controls", numeric, default=[p for p in default_predictors if p in numeric])
    categoricals = [
        column for column in columns
        if column not in excluded | set(numeric_predictors) and 2 <= frame[column].nunique(dropna=True) <= 25
    ]
    categorical_predictors = st.multiselect(
        "Categorical controls (optional; reference-level dummies are created)",
        categoricals,
        default=[p for p in roles.get("categorical_predictors", []) if p in categoricals],
    )
    settings = st.columns(2)
    time_effects = settings[0].toggle(
        "Include time fixed effects",
        value=bool(roles.get("time_effects", False)),
        help="Controls for shocks shared by all entities in a period. It cannot rescue a predictor with no within-period variation.",
    )
    cluster_robust = settings[1].toggle(
        "Cluster uncertainty by entity",
        value=bool(roles.get("cluster_robust", True)),
        help="Allows arbitrary residual correlation within an entity. Few clusters still make inference fragile.",
    )
    if st.button("Validate panel & compare estimators", type="primary"):
        try:
            prepared = prepare_panel_data(
                frame,
                entity_column=entity,
                time_column=time,
                outcome_column=outcome,
                numeric_predictors=numeric_predictors,
                categorical_predictors=categorical_predictors,
            )
            analysis = analyze_panel(
                prepared.frame,
                entity_col=prepared.entity_column,
                time_col=prepared.time_column,
                outcome_col=prepared.outcome_column,
                predictors=prepared.predictors,
                time_effects=time_effects,
                cluster_robust=cluster_robust,
            )
            st.session_state["panel_prepared"] = prepared
            st.session_state["panel_analysis"] = analysis
            st.session_state["panel_roles"] = {
                "entity": entity,
                "time": time,
                "outcome": outcome,
                "numeric_predictors": numeric_predictors,
                "categorical_predictors": categorical_predictors,
                "time_effects": time_effects,
                "cluster_robust": cluster_robust,
            }
        except Exception as exc:
            show_error(exc)

    analysis = st.session_state.get("panel_analysis")
    prepared = st.session_state.get("panel_prepared")
    if analysis is None:
        return
    for warning in (*getattr(prepared, "warnings", ()), *getattr(analysis.diagnostics, "warnings", ())):
        st.warning(str(warning))
    diagnostics = analysis.diagnostics
    metrics = st.columns(4)
    metrics[0].metric(
        "Observations",
        f"{getattr(diagnostics, 'n_observations', getattr(diagnostics, 'nobs', len(prepared.frame))):,}",
    )
    metrics[1].metric("Entities", f"{getattr(diagnostics, 'n_entities', prepared.frame[prepared.entity_column].nunique()):,}")
    metrics[2].metric("Periods", f"{getattr(diagnostics, 'n_periods', prepared.frame[prepared.time_column].nunique()):,}")
    balance = getattr(diagnostics, "balanced", False)
    metrics[3].metric("Panel", "Balanced" if balance else "Unbalanced")
    st.warning(
        "These estimates are conditional associations. Fixed effects remove time-invariant entity differences; "
        "they do not remove time-varying confounding, reverse causality, measurement error, or targeting bias."
    )
    tabs = st.tabs(["Model comparison", "Within vs between", "Diagnostics", "Nerd output"])
    with tabs[0]:
        full_width(st.plotly_chart, _coefficient_figure(analysis))
        hausman = analysis.hausman
        statistic = getattr(hausman, "statistic", np.nan)
        p_value = getattr(hausman, "p_value", np.nan)
        valid = bool(getattr(hausman, "valid", np.isfinite(statistic) and np.isfinite(p_value)))
        if valid:
            if p_value < 0.05:
                st.markdown(
                    f"**Hausman comparison:** χ² = {statistic:.2f}, p = {p_value:.3g}. FE and RE differ more than "
                    "sampling noise would comfortably explain; the random-effects orthogonality assumption is doubtful."
                )
            else:
                st.markdown(
                    f"**Hausman comparison:** χ² = {statistic:.2f}, p = {p_value:.3g}. The test does not detect a "
                    "systematic FE–RE difference, but that is not proof the RE assumption is true."
                )
        else:
            st.info("The Hausman covariance comparison was not numerically reliable; use the estimator assumptions and diagnostics instead.")
        for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
            with st.expander(str(result.estimator)):
                full_width(st.dataframe, result.coefficients, hide_index=True)
                for warning in getattr(result, "warnings", ()):
                    st.warning(str(warning))
                for note in getattr(result, "notes", ()):
                    st.caption(str(note))
    with tabs[1]:
        within_between = analysis.within_between.copy()
        full_width(st.dataframe, within_between, hide_index=True)
        st.markdown(
            "If the pooled or between-entity slope points one way while the within-entity slope points another, the "
            "business story is vulnerable to aggregation bias (often called Simpson's paradox). Budget decisions "
            "usually need the within-entity or experimental story—not just cross-sectional differences."
        )
    with tabs[2]:
        variation = getattr(diagnostics, "variation", pd.DataFrame())
        vif = getattr(diagnostics, "vif", pd.DataFrame())
        st.subheader("Within and between variation")
        full_width(st.dataframe, variation, hide_index=True)
        st.subheader("Collinearity")
        full_width(st.dataframe, vif, hide_index=True)
        condition = getattr(diagnostics, "condition_number", np.nan)
        if np.isfinite(condition):
            st.caption(f"Standardized design condition number: {condition:,.1f}. Large values mean coefficients may be hard to separate.")
    with tabs[3]:
        for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
            st.markdown(f"#### {result.estimator}")
            metric_table = pd.DataFrame(
                {"metric": list(result.metrics), "value": list(result.metrics.values())}
            )
            full_width(st.dataframe, metric_table, hide_index=True)
        if hasattr(analysis.hausman, "details") and isinstance(analysis.hausman.details, pd.DataFrame):
            st.markdown("#### Hausman coefficient differences")
            full_width(st.dataframe, analysis.hausman.details, hide_index=True)


def _named_allocation_results(allocation: dict[str, object]) -> list[tuple[str, object]]:
    named = [
        ("Current baseline", allocation["baseline"]),
        ("Chosen-budget plan", allocation["constrained"]),
        ("Profit-sized plan", allocation["sized"]),
    ]
    named.extend((f"Sensitivity · {label}", result) for label, result in allocation["scenarios"].items())
    return named


def _allocation_summary_table(allocation: dict[str, object]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for run, result in _named_allocation_results(allocation):
        rows.append({"run": run, **result.summary_dict()})
    return pd.DataFrame(rows)


def _allocation_solver_table(allocation: dict[str, object]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for run, result in _named_allocation_results(allocation):
        table = result.table
        proposed = table["recommended_spend"].to_numpy(dtype=float)
        fixed = table["fixed"].to_numpy(dtype=bool)
        current = table["current_spend"].to_numpy(dtype=float)
        lower = np.where(fixed, current, table["min_spend"].to_numpy(dtype=float))
        upper = np.where(fixed, current, table["max_spend"].to_numpy(dtype=float))
        scale = max(1.0, float(np.max(np.abs(np.r_[lower, upper, proposed]))))
        tolerance = 2e-6 * scale
        lower_violation = float(np.maximum(lower - proposed, 0.0).max())
        upper_violation = float(np.maximum(proposed - upper, 0.0).max())
        fixed_change = float(np.abs(proposed[fixed] - current[fixed]).max()) if fixed.any() else 0.0
        budget_gap = (
            float(proposed.sum() - float(result.total_budget)) if result.total_budget is not None else np.nan
        )
        budget_ok = result.total_budget is None or abs(budget_gap) <= tolerance
        rows.append(
            {
                "run": run,
                "mode": result.mode,
                "success": bool(result.success),
                "message": result.message,
                "solver_status": result.solver_status,
                "solver_iterations": result.solver_iterations,
                "requested_budget": result.total_budget,
                "returned_total_spend": float(proposed.sum()),
                "budget_gap": budget_gap,
                "max_lower_bound_violation": lower_violation,
                "max_upper_bound_violation": upper_violation,
                "max_fixed_channel_change": fixed_change,
                "binding_minimum_channels": int(table["at_min"].sum()),
                "binding_maximum_channels": int(table["at_max"].sum()),
                "fixed_channels": int(fixed.sum()),
                "feasible_recomputed": bool(
                    result.success
                    and lower_violation <= tolerance
                    and upper_violation <= tolerance
                    and fixed_change <= tolerance
                    and budget_ok
                ),
                "feasibility_tolerance": tolerance,
            }
        )
    return pd.DataFrame(rows)


def _allocation_assumptions_table(
    allocation: dict[str, object], assumptions: dict[str, float], totals: dict[str, float]
) -> pd.DataFrame:
    budget_changed = _materially_different(totals["recommended_spend"], totals["current_spend"])
    rows: list[dict[str, object]] = [
        {
            "scope": "Economics",
            "setting": "Contribution margin per response unit",
            "value": assumptions["margin"],
            "interpretation": "Held constant across channels and allocations.",
        },
        {
            "scope": "Economics",
            "setting": "Response not assigned to channels",
            "value": assumptions["base_response"],
            "interpretation": "Constant base response; it does not drive channel reallocation.",
        },
        {
            "scope": "Horizon",
            "setting": "Effect horizon",
            "value": allocation["horizon"],
            "interpretation": "Long-run multipliers are judgments, not estimated carryover.",
        },
        {
            "scope": "Budget",
            "setting": "Current total spend",
            "value": totals["current_spend"],
            "interpretation": "Observed baseline used for deltas.",
        },
        {
            "scope": "Budget",
            "setting": "Chosen constrained-plan budget",
            "value": totals["recommended_spend"],
            "interpretation": (
                "Different from current: reported deltas combine budget-size and mix changes."
                if budget_changed
                else "Equal to current: reported deltas isolate mix within this curve scenario."
            ),
        },
        {
            "scope": "Sensitivity",
            "setting": "Width",
            "value": f"±{allocation['sensitivity_width']}%",
            "interpretation": "Structured assumption stress test; not a confidence interval.",
        },
        {
            "scope": "Channels",
            "setting": "Cross-channel structure",
            "value": "Additive independent response curves",
            "interpretation": INDEPENDENCE_NOTE,
        },
        {
            "scope": "Causality",
            "setting": "Status",
            "value": "Planning scenario",
            "interpretation": "Curve precision does not make channel response causal.",
        },
    ]
    for position, statement in enumerate(allocation["constrained"].assumptions, start=1):
        rows.append(
            {
                "scope": "Engine",
                "setting": f"Core assumption {position}",
                "value": statement,
                "interpretation": "Travels with every allocation result.",
            }
        )
    return pd.DataFrame(rows)


def _sensitivity_summary_table(allocation: dict[str, object]) -> pd.DataFrame:
    width = float(allocation["sensitivity_width"]) / 100.0
    factors = {
        "Low response": (1.0 - width, 1.0 + width),
        "Base": (1.0, 1.0),
        "High response": (1.0 + width, max(1.0 - width, 0.05)),
    }
    rows: list[dict[str, object]] = []
    for scenario, result in allocation["scenarios"].items():
        ceiling_factor, half_factor = factors.get(scenario, (np.nan, np.nan))
        rows.append(
            {
                "scenario": scenario,
                "incremental_ceiling_multiplier": ceiling_factor,
                "half_saturation_multiplier": half_factor,
                "margin_multiplier": 1.0,
                **result.summary_dict(),
            }
        )
    return pd.DataFrame(rows)


def _allocation_decision_summary(
    table: pd.DataFrame, margin: float, base_response: float
) -> pd.DataFrame:
    totals = _allocation_totals(table, margin, base_response)
    ordered = table.sort_values("change", ascending=False).reset_index(drop=True)
    budget_changed = _materially_different(totals["recommended_spend"], totals["current_spend"])
    return pd.DataFrame(
        [
            {
                "comparison_scope": (
                    "Budget-size plus channel-mix change" if budget_changed else "Channel-mix change at current total"
                ),
                "current_total_spend": totals["current_spend"],
                "chosen_total_spend": totals["recommended_spend"],
                "total_spend_change": totals["recommended_spend"] - totals["current_spend"],
                "current_total_response": totals["current_response"],
                "chosen_total_response": totals["recommended_response"],
                "response_change": totals["recommended_response"] - totals["current_response"],
                "current_net_contribution": totals["current_profit"],
                "chosen_net_contribution": totals["recommended_profit"],
                "net_contribution_change": totals["recommended_profit"] - totals["current_profit"],
                "largest_increase_channel": ordered.iloc[0]["channel"],
                "largest_increase": ordered.iloc[0]["change"],
                "largest_decrease_channel": ordered.iloc[-1]["channel"],
                "largest_decrease": ordered.iloc[-1]["change"],
                "causal_status": "Scenario conditional on curves, margin, independence, horizon, and constraints.",
            }
        ]
    )


def _panel_model_metrics(analysis) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
        rows.append(
            {
                "estimator": result.estimator,
                "observations": result.nobs,
                "entities": result.n_entities,
                "periods": result.n_periods,
                **dict(result.metrics),
            }
        )
    return pd.DataFrame(rows)


def _panel_notes_warnings(analysis, prepared) -> pd.DataFrame:
    rows: list[dict[str, str]] = [
        {
            "source": "All panel models",
            "kind": "causal status",
            "message": (
                "Conditional associations in observed data; fixed effects do not remove time-varying confounding, "
                "reverse causality, measurement error, or targeting bias."
            ),
        }
    ]
    for message in getattr(prepared, "warnings", ()):
        rows.append({"source": "Data preparation", "kind": "warning", "message": str(message)})
    for message in getattr(analysis.diagnostics, "warnings", ()):
        rows.append({"source": "Panel diagnostics", "kind": "warning", "message": str(message)})
    for result in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
        rows.extend(
            {"source": result.estimator, "kind": "note", "message": str(message)}
            for message in result.notes
        )
        rows.extend(
            {"source": result.estimator, "kind": "warning", "message": str(message)}
            for message in result.warnings
        )
    rows.append({"source": "Hausman comparison", "kind": "conclusion", "message": analysis.hausman.conclusion})
    rows.extend(
        {"source": "Hausman comparison", "kind": "warning", "message": str(message)}
        for message in analysis.hausman.warnings
    )
    return pd.DataFrame(rows)


def _panel_assumptions_table(roles: dict[str, object], prepared) -> pd.DataFrame:
    predictors = list(getattr(prepared, "predictors", ()))
    return pd.DataFrame(
        [
            {"setting": "Entity key", "value": roles.get("entity"), "interpretation": "Repeated unit identifier."},
            {"setting": "Time key", "value": roles.get("time"), "interpretation": "Period identifier; entity × time must be unique."},
            {"setting": "Outcome", "value": roles.get("outcome"), "interpretation": "Numeric dependent variable."},
            {
                "setting": "Estimated predictors",
                "value": json.dumps(predictors),
                "interpretation": "Includes generated reference-level dummy variables after preparation.",
            },
            {
                "setting": "Time fixed effects",
                "value": bool(roles.get("time_effects", False)),
                "interpretation": "Absorb shocks shared by all entities in a period; period terms remain in nerd exports.",
            },
            {
                "setting": "Entity-clustered uncertainty",
                "value": bool(roles.get("cluster_robust", True)),
                "interpretation": "Allows within-entity residual dependence; few clusters remain fragile.",
            },
            {
                "setting": "Confidence level",
                "value": 0.95,
                "interpretation": "Default two-sided model interval level.",
            },
            {
                "setting": "Causal status",
                "value": "Observational conditional association",
                "interpretation": "No estimator or Hausman result is a causal guarantee.",
            },
        ]
    )


def _panel_fitted_residuals(analysis, prepared) -> pd.DataFrame:
    nobs = int(analysis.pooled.nobs)
    if prepared is not None:
        frame = prepared.frame.reset_index(drop=True)
        keys = [prepared.entity_column, prepared.time_column, prepared.outcome_column]
        result = frame[keys].copy()
        result = result.rename(columns={prepared.outcome_column: "observed_outcome"})
    else:
        result = pd.DataFrame({"observation": np.arange(nobs)})
    for prefix, model in (
        ("pooled", analysis.pooled),
        ("fixed_effects", analysis.fixed_effects),
        ("random_effects", analysis.random_effects),
    ):
        result[f"{prefix}_fitted"] = np.asarray(model.fitted_values, dtype=float)
        result[f"{prefix}_residual"] = np.asarray(model.residuals, dtype=float)
    return result


def _residual_diagnostics(analysis) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for model in (analysis.pooled, analysis.fixed_effects, analysis.random_effects):
        residual = np.asarray(model.residuals, dtype=float)
        fitted = np.asarray(model.fitted_values, dtype=float)
        correlation = np.nan
        if len(residual) > 1 and np.std(residual) > 0 and np.std(fitted) > 0:
            correlation = float(np.corrcoef(fitted, residual)[0, 1])
        rows.append(
            {
                "estimator": model.estimator,
                "observations": len(residual),
                "residual_mean": float(np.mean(residual)),
                "residual_standard_deviation": float(np.std(residual, ddof=1)) if len(residual) > 1 else np.nan,
                "mean_absolute_error": float(np.mean(np.abs(residual))),
                "root_mean_squared_error": float(np.sqrt(np.mean(np.square(residual)))),
                "residual_minimum": float(np.min(residual)),
                "residual_q25": float(np.quantile(residual, 0.25)),
                "residual_median": float(np.median(residual)),
                "residual_q75": float(np.quantile(residual, 0.75)),
                "residual_maximum": float(np.max(residual)),
                "fitted_residual_correlation": correlation,
            }
        )
    return pd.DataFrame(rows)


def _hausman_covariance_tables(analysis) -> tuple[pd.DataFrame, pd.DataFrame]:
    hausman = analysis.hausman
    fixed_frame = getattr(hausman, "fixed_covariance", None)
    random_frame = getattr(hausman, "random_covariance", None)
    difference_frame = getattr(hausman, "covariance_difference", None)
    if fixed_frame is None or random_frame is None or difference_frame is None or fixed_frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    terms = list(fixed_frame.index.astype(str))
    fixed = fixed_frame.loc[terms, terms].to_numpy(dtype=float)
    random = random_frame.loc[terms, terms].to_numpy(dtype=float)
    difference = difference_frame.loc[terms, terms].to_numpy(dtype=float)
    basis_rows: list[dict[str, object]] = []
    for row_index, row_term in enumerate(terms):
        for column_index, column_term in enumerate(terms):
            basis_rows.append(
                {
                    "row_term": row_term,
                    "column_term": column_term,
                    "fixed_effects_covariance": fixed[row_index, column_index],
                    "random_effects_covariance": random[row_index, column_index],
                    "fe_minus_re_covariance": difference[row_index, column_index],
                    "covariance_basis": hausman.covariance_basis,
                }
            )
    scale = max(float(np.max(np.abs(difference))), np.finfo(float).tiny)
    tolerance = scale * 1e-9
    eigenvalues = np.linalg.eigvalsh(difference)
    rank = int(np.linalg.matrix_rank(difference, tol=tolerance))
    spectrum = pd.DataFrame(
        {
            "component": np.arange(1, len(eigenvalues) + 1),
            "eigenvalue": eigenvalues,
            "rank_used_for_df": rank,
            "comparison_terms": ", ".join(terms),
            "positive_semidefinite": bool(hausman.covariance_difference_psd),
            "numeric_tolerance": tolerance,
            "quadratic_form": "(FE−RE)' pinv(V_FE−V_RE) (FE−RE)",
            "covariance_basis": hausman.covariance_basis,
            "interpretation": (
                "Exact covariance basis used by the Hausman calculation. An indefinite difference invalidates the "
                "conventional chi-square interpretation."
            ),
        }
    )
    return pd.DataFrame(basis_rows), spectrum


def _panel_encoding_audit(prepared) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for source, generated in getattr(prepared, "encoded_from", {}).items():
        for column in generated:
            rows.append(
                {
                    "source_categorical_control": source,
                    "generated_dummy": column,
                    "reference_level_omitted": True,
                }
            )
    return pd.DataFrame(rows)


def _manifest_table(metadata: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "field": list(metadata),
            "value": [
                json.dumps(value, default=str) if isinstance(value, (dict, list, tuple)) else str(value)
                for value in metadata.values()
            ],
        }
    )


def decision_page() -> None:
    st.title("Turn the result into a testable decision")
    allocation = st.session_state.get("allocation_results")
    analysis = st.session_state.get("panel_analysis")
    if not allocation and analysis is None:
        st.info("Run a budget scenario or panel analysis first. This page keeps both evidence streams separate in one pack.")
        return
    export_tables: dict[str, pd.DataFrame] = {}
    metadata: dict[str, object] = {
        "product": "AllocSignal",
        "version": __version__,
        "generated_with": "Local deterministic Python analysis; no external AI service",
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "streamlit": st.__version__,
        "statsmodels": statsmodels.__version__,
        "independence_assumption": INDEPENDENCE_NOTE,
        "causal_status": "Planning scenario and observational associations; not a causal recommendation.",
    }
    if allocation:
        table = allocation["constrained"].table.copy()
        assumptions = st.session_state["planning_assumptions"]
        totals = _allocation_totals(table, float(assumptions["margin"]), float(assumptions["base_response"]))
        chosen_budget_differs = _materially_different(totals["recommended_spend"], totals["current_spend"])
        table = table.sort_values("change", ascending=False).reset_index(drop=True)
        biggest_add = table.iloc[0]
        biggest_cut = table.iloc[-1]
        st.subheader("Planning recommendation")
        if chosen_budget_differs:
            st.markdown(
                f"At the chosen total budget of **{totals['recommended_spend']:,.1f}** "
                f"({totals['recommended_spend'] - totals['current_spend']:+,.1f} versus current), the curve scenario "
                f"moves the most toward **{biggest_add['channel']}** ({biggest_add['change']:+,.1f}) and the most "
                f"away from **{biggest_cut['channel']}** ({biggest_cut['change']:+,.1f}). The modeled "
                f"net-contribution lift is **{totals['recommended_profit'] - totals['current_profit']:,.1f}**."
            )
            st.info(
                "That lift combines a change in total budget size with a change in channel mix. "
                "It must not be read as the effect of reallocation alone."
            )
        else:
            st.markdown(
                f"At the current total budget, the curve scenario moves the most toward **{biggest_add['channel']}** "
                f"({biggest_add['change']:+,.1f}) and the most away from **{biggest_cut['channel']}** "
                f"({biggest_cut['change']:+,.1f}). The modeled net-contribution lift from the mix change is "
                f"**{totals['recommended_profit'] - totals['current_profit']:,.1f}**."
            )
        st.caption(
            "That sentence is conditional on the entered response curves, margin, horizon, channel independence, "
            "and constraints. A zero proposed spend can mean a bound or model assumption—not that a channel has no strategic role."
        )
        export_tables["Allocation decision summary"] = _allocation_decision_summary(
            allocation["constrained"].table,
            float(assumptions["margin"]),
            float(assumptions["base_response"]),
        )
        export_tables["Allocation run summary"] = _allocation_summary_table(allocation)
        export_tables["Allocation assumptions"] = _allocation_assumptions_table(allocation, assumptions, totals)
        export_tables["Solver diagnostics"] = _allocation_solver_table(allocation)
        export_tables["Channel assumptions"] = allocation["plan"]
        export_tables["Current baseline"] = allocation["baseline"].table
        export_tables["Constrained plan"] = allocation["constrained"].table
        export_tables["Profit-sized plan"] = allocation["sized"].table
        export_tables["Sensitivity summary"] = _sensitivity_summary_table(allocation)
        sensitivity_rows = []
        for label, result in allocation["scenarios"].items():
            part = result.table.copy()
            part.insert(0, "scenario", label)
            sensitivity_rows.append(part)
        export_tables["Sensitivity allocations"] = pd.concat(sensitivity_rows, ignore_index=True)
        calibrations = st.session_state.get("calibration_results", {})
        if calibrations:
            parameter_rows: list[pd.DataFrame] = []
            fitted_rows: list[pd.DataFrame] = []
            for channel, calibration in calibrations.items():
                parameters = calibration.parameter_table().copy()
                parameters.insert(0, "channel", channel)
                parameter_rows.append(parameters)
                fitted = calibration.fitted.copy()
                fitted.insert(0, "channel", channel)
                fitted_rows.append(fitted)
            export_tables["Calibration parameters"] = pd.concat(parameter_rows, ignore_index=True)
            export_tables["Calibration anchors"] = pd.concat(fitted_rows, ignore_index=True)
            export_tables["Calibration diagnostics"] = pd.DataFrame(
                [
                    {
                        "channel": channel,
                        "success": calibration.success,
                        "anchor_rmse": calibration.rmse,
                        "anchor_r_squared": calibration.r_squared,
                        "anchor_count": calibration.n_observations,
                        "warnings": " | ".join(calibration.warnings),
                    }
                    for channel, calibration in calibrations.items()
                ]
            )
        metadata.update(
            {
                "planning_source": st.session_state.get("plan_source"),
                "planning_fingerprint_sha256": st.session_state.get("plan_fingerprint"),
                "effect_horizon": allocation["horizon"],
                "fixed_budget": allocation["budget"],
                "chosen_constrained_budget": allocation["budget"],
                "current_budget": totals["current_spend"],
                "chosen_budget_change": totals["recommended_spend"] - totals["current_spend"],
                "chosen_budget_comparison_scope": (
                    "budget size plus channel mix" if chosen_budget_differs else "channel mix at current total"
                ),
                "contribution_margin": assumptions["margin"],
                "base_response": assumptions["base_response"],
                "sensitivity_width_percent": allocation["sensitivity_width"],
                "judgmentally_calibrated_channels": list(calibrations),
            }
        )
    if analysis is not None:
        st.subheader("Historical evidence")
        fe = analysis.fixed_effects.coefficients.copy()
        term_col = "term" if "term" in fe else fe.columns[0]
        term_text = fe[term_col].astype(str)
        slopes = fe[
            ~term_text.str.lower().isin({"const", "intercept"}) & ~term_text.str.startswith("__period=")
        ].copy()
        if not slopes.empty:
            strongest = slopes.iloc[slopes["estimate"].abs().argmax()]
            st.markdown(
                f"The largest absolute fixed-effects coefficient is **{strongest[term_col]}** "
                f"({strongest['estimate']:+.4g} outcome units per input unit), conditional on the selected controls."
            )
        st.caption(
            "Coefficient size depends on measurement units. Statistical precision, business magnitude, historical "
            "support, and causal identification are separate questions."
        )
        prepared = st.session_state.get("panel_prepared")
        roles = st.session_state.get("panel_roles") or {}
        export_tables["Panel structure"] = analysis.diagnostics.summary_frame()
        export_tables["Panel assumptions"] = _panel_assumptions_table(roles, prepared)
        export_tables["Panel model comparison"] = analysis.model_comparison()
        export_tables["Panel model metrics"] = _panel_model_metrics(analysis)
        export_tables["Panel notes warnings"] = _panel_notes_warnings(analysis, prepared)
        export_tables["Panel fitted residuals"] = _panel_fitted_residuals(analysis, prepared)
        export_tables["Residual diagnostics"] = _residual_diagnostics(analysis)
        export_tables["Pooled coefficients"] = analysis.pooled.coefficients
        export_tables["Fixed-effects coefficients"] = analysis.fixed_effects.coefficients
        export_tables["Random-effects coefficients"] = analysis.random_effects.coefficients
        export_tables["Within-between slopes"] = analysis.within_between
        export_tables["Panel variation"] = analysis.diagnostics.variation
        export_tables["Panel VIF"] = analysis.diagnostics.vif
        hausman = analysis.hausman
        hausman_table = hausman.as_frame()
        hausman_table["valid_conventional_interpretation"] = hausman.valid
        hausman_table["warnings"] = " | ".join(hausman.warnings)
        export_tables["Hausman test"] = hausman_table
        covariance_basis, covariance_spectrum = _hausman_covariance_tables(analysis)
        if not covariance_basis.empty:
            export_tables["Hausman covariance basis"] = covariance_basis
            export_tables["Hausman covariance spectrum"] = covariance_spectrum
        encoding_audit = _panel_encoding_audit(prepared)
        if not encoding_audit.empty:
            export_tables["Panel encoding audit"] = encoding_audit
        metadata.update(
            {
                "panel_source": st.session_state.get("panel_source"),
                "panel_fingerprint_sha256": st.session_state.get("panel_fingerprint"),
                "panel_roles": roles,
                "panel_observations": getattr(analysis.diagnostics, "n_observations", None),
                "panel_entities": getattr(analysis.diagnostics, "n_entities", None),
                "panel_periods": getattr(analysis.diagnostics, "n_periods", None),
                "panel_balanced": getattr(analysis.diagnostics, "balanced", None),
                "hausman_compared_terms": list(hausman.compared_terms),
                "hausman_covariance_difference_psd": hausman.covariance_difference_psd,
                "hausman_valid_conventional_interpretation": hausman.valid,
            }
        )

    st.subheader("A sensible implementation sequence")
    actions = [
        ("01 · CHALLENGE", "Review the curve anchors", "Ask channel owners to defend zero, current, increased, and saturation response independently—especially where the recommendation is largest."),
        ("02 · TEST", "Move a bounded increment", "Use a geo test, randomized increment, or matched-market design where possible. Do not jump directly to the numerically preferred plan."),
        ("03 · MONITOR", "Update the evidence", "Predefine the outcome, time horizon, guardrails, and stopping rule; then recalibrate rather than protecting the old recommendation."),
    ]
    action_cards = "".join(
        f"<div class='ms-insight'><b>{number}</b><h3>{title}</h3><p>{body}</p></div>"
        for number, title, body in actions
    )
    st.markdown(f"<div class='ms-action-grid'>{action_cards}</div>", unsafe_allow_html=True)
    st.subheader("Download the evidence—not just the answer")
    export_tables = {"Analysis manifest": _manifest_table(metadata), **export_tables}
    downloads = st.columns(3)
    full_width(
        downloads[0].download_button,
        "Excel evidence pack",
        results_to_excel(export_tables),
        "allocsignal_evidence.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    full_width(
        downloads[1].download_button,
        "CSV evidence ZIP",
        tables_to_csv_zip(export_tables),
        "allocsignal_evidence_csv.zip",
        "application/zip",
    )
    full_width(
        downloads[2].download_button,
        "JSON + audit trail",
        results_to_json(export_tables, metadata),
        "allocsignal_evidence.json",
        "application/json",
    )


def methods_page() -> None:
    st.title("Methods & limits")
    st.markdown(CAUTION)
    tabs = st.tabs(["Plain-language method", "Response mathematics", "Panel estimators", "Limits & references"])
    with tabs[0]:
        st.subheader("What AllocSignal actually does")
        st.markdown(
            """
            1. **Frame the decision.** Each channel gets a current spend, feasible range, response floor, response
               ceiling, half-saturation spend, curve shape, and optional fixed commitment.
            2. **Evaluate the current plan.** Response is converted to contribution with the entered margin, then
               spend is subtracted.
            3. **Reallocate a fixed budget.** Deterministic pairwise searches and multi-start nonlinear refinement
               look for a high modeled net contribution while keeping the chosen total and every channel bound.
            4. **Size the budget.** A separate run lets total spend move within the combined bounds. An interior
               economic optimum has marginal response × margin ≈ 1.
            5. **Stress-test.** Low and high scenarios jointly change attainable response and half-saturation. They
               are scenario bounds, not statistical confidence intervals.
            6. **Challenge historically.** Pooled, entity fixed-effects, and random-effects models show how much
               the historical story depends on between-entity differences and model assumptions.
            """
        )
        st.info("Optimization answers 'best found under these assumptions.' Strategy still asks whether the assumptions, evidence, channel role, and implementation are credible.")
    with tabs[1]:
        st.subheader("ADBUDG / Hill response")
        st.latex(r"Y(x)=b+(a-b)\frac{x^c}{h^c+x^c}")
        st.write(
            "Here b is response at zero spend, a is the saturation response, h is half-saturation spend, and c "
            "controls shape. This is Little's ADBUDG response form written with d = hᶜ, which makes the scale parameter easier to explain."
        )
        st.latex(r"\pi(\mathbf{x})=m\left[Y_0+\sum_j Y_j(x_j)\right]-\sum_j x_j")
        st.write("The symbol m here is contribution margin per response unit—not market size. Y₀ is constant base response.")
        st.latex(r"\frac{d\pi}{dx_j}=m\frac{dY_j}{dx_j}-1")
        st.write(
            "Marginal profit, not average ROI, guides the next unit. At an unconstrained interior optimum it is zero; "
            "with a fixed total budget, feasible interior channels tend to have equal marginal contribution."
        )
        st.latex(r"\varepsilon_j(x)=\frac{dY_j}{dx_j}\frac{x_j}{Y_j(x_j)}")
        st.write("Elasticity changes with spend because the response curve saturates.")
    with tabs[2]:
        st.subheader("Three views of historical panel data")
        st.markdown(
            """
            - **Pooled OLS** treats all rows as one sample. It can mix persistent entity differences with changes over time.
            - **Entity fixed effects (FE)** subtract each entity's means, so slopes are identified from within-entity
              changes. Optional time effects absorb period shocks shared by all entities.
            - **Random effects (RE)** quasi-demeans the data and is more efficient only when unobserved entity effects
              are uncorrelated with every predictor—a strong, substantive assumption.
            - **Hausman comparison** tests whether common FE and RE slopes differ systematically. A fragile covariance
              difference can make the test numerically invalid; failure to reject does not prove RE is correct.
            """
        )
        st.latex(r"y_{it}=\alpha_i+\mathbf{x}_{it}'\boldsymbol{\beta}+\lambda_t+\varepsilon_{it}")
        st.write(
            "Entity-clustered standard errors allow residual dependence within each entity. They still rely on enough "
            "independent clusters and do not repair endogeneity. VIF, condition number, and within/between variation "
            "are shown because a coefficient is not useful if the data cannot separate it from the other variables."
        )
    with tabs[3]:
        st.subheader("Boundaries that matter")
        st.markdown(
            f"""
            - {INDEPENDENCE_NOTE}
            - Floor and ceiling responses are additive channel-attribution constructs. If several channels claim the
              same sale, total response is overstated.
            - Historical panels need genuine within-entity input variation. More rows do not compensate for no variation.
            - Lags, adstock/carryover, seasonality beyond optional time indicators, price endogeneity, competitive
              response, and cross-channel interaction require a richer design than this release estimates.
            - Long-run multipliers are explicit judgments. They are not an adstock model and must not be presented as one.
            - FE removes stable omitted differences, not time-varying confounders. RE's key orthogonality assumption is untestable in full.
            - P-values and confidence intervals describe sampling uncertainty under a model; curve sensitivity describes
              assumption uncertainty. Neither is a causal guarantee.
            - Optimization can recommend impractically large changes near weakly identified regions. Pilot changes and monitor.
            - Uploaded data remain in the local Python process in local mode. A hosted deployment creates a different trust boundary.
            """
        )
        with st.expander("Method references and implementation notes"):
            st.markdown(
                """
                - Little, J. D. C. (1970). *Models and managers: The concept of a decision calculus*. Management Science.
                - Hausman, J. A. (1978). *Specification tests in econometrics*. Econometrica.
                - Wooldridge, J. M. *Econometric Analysis of Cross Section and Panel Data*.
                - The workflow runs baseline → unconstrained sizing → constrained allocation → strategy, with
                  zero/base/increased/saturation calibration anchors and post-implementation monitoring.

                Full implementation notes and data conventions are in `docs/methods.md` and `docs/data_guide.md`.
                """
            )


if page == "Welcome":
    welcome_page()
elif page == "1 · Curves & assumptions":
    curves_page()
elif page == "2 · Allocate & stress-test":
    allocation_page()
elif page == "3 · Panel evidence":
    panel_page()
elif page == "4 · Decision & export":
    decision_page()
else:
    methods_page()

footer()
