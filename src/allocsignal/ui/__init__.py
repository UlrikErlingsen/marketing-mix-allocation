"""Alloc Signal user interface: the Signal Hub entry point.

The only package under ``allocsignal`` that imports Streamlit or Plotly. ``render()`` draws the whole app on the
current page and never calls ``st.set_page_config``; the standalone ``app.py`` or Signal Hub owns the page config.
"""

from allocsignal import __version__
from allocsignal.ui import signal_theme
from allocsignal.ui.app import render

APP_INFO = {"product": "Alloc Signal", "version": __version__, "repo": "marketing-mix-allocation", "slug": "alloc"}

__all__ = ["APP_INFO", "render", "signal_theme"]
