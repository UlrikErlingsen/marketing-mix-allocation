"""Data limits: none when Alloc Signal runs on your own computer, hard caps only on a public demo.

Run locally (standalone, inside a local Signal Hub or on an internal company server), the app imposes no limit on
file size, rows, cells or the size of a panel model; the computer's memory is the limit. A public demo sets
``SIGNAL_PUBLIC=1`` and then every cap below protects the shared server. All caps live in this module and are read at
call time.
"""

from __future__ import annotations

import os

# Demo caps, applied only when SIGNAL_PUBLIC=1. They are the limits of earlier releases, plus a cap on the dense
# panel design (rows x model columns, including period indicators) that the panel estimators build in memory.
DEMO_MAX_UPLOAD_MB = 200
DEMO_MAX_JSON_MB = 30
DEMO_MAX_EXPANDED_EXCEL_MB = 250
DEMO_MAX_TABLE_ROWS = 500_000
DEMO_MAX_TOTAL_CELLS = 8_000_000
DEMO_MAX_PANEL_DESIGN_CELLS = 10_000_000

DEMO_NOTE = "This is a limit of the public demo only; the downloadable Alloc Signal app has no built-in limit."
MEMORY_MESSAGE = (
    "There is not enough memory on this computer for this file or model. Close other programs, keep only the "
    "columns you need, switch off time fixed effects for very long panels, or run Alloc Signal on a computer with "
    "more memory."
)


def is_public() -> bool:
    """True on a public demo (``SIGNAL_PUBLIC=1``); independent of Hub mode (``SIGNAL_HUB``)."""
    return os.environ.get("SIGNAL_PUBLIC") == "1"


def _cap(value: int) -> int | None:
    return value if is_public() else None


def max_upload_bytes() -> int | None:
    return _cap(DEMO_MAX_UPLOAD_MB * 1024 * 1024)


def max_json_bytes() -> int | None:
    return _cap(DEMO_MAX_JSON_MB * 1024 * 1024)


def max_expanded_excel_bytes() -> int | None:
    return _cap(DEMO_MAX_EXPANDED_EXCEL_MB * 1024 * 1024)


def max_table_rows() -> int | None:
    return _cap(DEMO_MAX_TABLE_ROWS)


def max_total_cells() -> int | None:
    return _cap(DEMO_MAX_TOTAL_CELLS)


def max_panel_design_cells() -> int | None:
    return _cap(DEMO_MAX_PANEL_DESIGN_CELLS)


def demo_limit(message: str) -> str:
    """A capped message: what was exceeded, plus the reminder that only the demo has the cap."""
    return f"{message} {DEMO_NOTE}"
