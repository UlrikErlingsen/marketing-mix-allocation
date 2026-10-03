"""Safe local input and portable evidence-pack exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import re
from typing import BinaryIO
import zipfile

import numpy as np
import pandas as pd

from . import limits
from .errors import DataProblem


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm", ".json"}
# On the public demo the CSV reader works in chunks so it can stop as soon as a demo cap is passed.
CSV_CHUNK_ROWS = 250_000
# Excel holds at most 1,048,576 rows per sheet and openpyxl keeps every cell in memory, so the Excel workbook leaves
# out row-level tables above this many cells and says so on a "Read me" sheet; CSV and JSON exports keep every row.
EXCEL_MAX_TABLE_CELLS = 2_000_000
# JSON tables above this many rows are written as compact records instead of being re-parsed and indented, so a
# multi-million-row export never holds millions of Python dictionaries at once.
JSON_COMPACT_ROWS = 100_000
ILLEGAL_XML_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class LoadedData:
    """Named tables read from one local source."""

    tables: dict[str, pd.DataFrame]
    source_name: str


def _unique_column_names(columns: list[object]) -> list[str]:
    result: list[str] = []
    used: set[str] = set()
    for index, column in enumerate(columns):
        base = str(column).strip() or f"column_{index + 1}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}__{suffix}"
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


def _source_bytes(source: str | Path | bytes | BinaryIO) -> tuple[bytes, str]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        return path.read_bytes(), path.name
    if isinstance(source, bytes):
        return source, "uploaded.csv"
    name = Path(getattr(source, "name", "uploaded.csv")).name
    if hasattr(source, "seek"):
        source.seek(0)
    return source.read(), name


def _csv_dialect(raw: bytes) -> tuple[str, bool]:
    """Sniff the delimiter from the header line, as pandas' sep=None does, without the slow Python parser."""
    first_line = raw[:65536].decode("utf-8-sig", errors="ignore").splitlines()[:1]
    try:
        dialect = csv.Sniffer().sniff(first_line[0] if first_line else "")
    except csv.Error:
        return ",", False
    return dialect.delimiter, bool(dialect.skipinitialspace)


def _demo_size_problem() -> DataProblem:
    return DataProblem(
        limits.demo_limit(
            f"The public demo accepts at most {limits.DEMO_MAX_TABLE_ROWS:,} rows and "
            f"{limits.DEMO_MAX_TOTAL_CELLS:,} cells per file."
        )
    )


def _read_csv(raw: bytes) -> pd.DataFrame:
    delimiter, skip_space = _csv_dialect(raw)
    options = {"sep": delimiter, "skipinitialspace": skip_space, "encoding": "utf-8-sig"}
    row_cap, cell_cap = limits.max_table_rows(), limits.max_total_cells()
    if row_cap is None and cell_cap is None:
        # Locally the fast C parser reads the whole table in one pass; there is no row or cell limit.
        return pd.read_csv(BytesIO(raw), **options)
    chunks: list[pd.DataFrame] = []
    rows = 0
    cells = 0
    for chunk in pd.read_csv(BytesIO(raw), chunksize=CSV_CHUNK_ROWS, **options):
        rows += len(chunk)
        cells += int(chunk.shape[0] * chunk.shape[1])
        if (row_cap is not None and rows > row_cap) or (cell_cap is not None and cells > cell_cap):
            raise _demo_size_problem()
        chunks.append(chunk)
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def load_data(source: str | Path | bytes | BinaryIO, name: str | None = None) -> LoadedData:
    """Read CSV, Excel, or JSON without executing uploaded content.

    Locally there is no size, row or cell limit; a public demo (``SIGNAL_PUBLIC=1``) applies :mod:`allocsignal.limits`.
    """
    raw, detected_name = _source_bytes(source)
    source_name = name or detected_name
    extension = Path(source_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DataProblem("Please use CSV, Excel, or JSON data.")
    byte_cap = limits.max_upload_bytes()
    if byte_cap is not None and len(raw) > byte_cap:
        raise DataProblem(limits.demo_limit(f"The public demo accepts files up to {limits.DEMO_MAX_UPLOAD_MB} MB."))
    json_cap = limits.max_json_bytes()
    if extension == ".json" and json_cap is not None and len(raw) > json_cap:
        raise DataProblem(limits.demo_limit(f"The public demo accepts JSON files up to {limits.DEMO_MAX_JSON_MB} MB."))
    if not raw:
        raise DataProblem("This file is empty.")

    try:
        if extension == ".csv":
            tables = {"data": _read_csv(raw)}
        elif extension in {".xlsx", ".xls", ".xlsm"}:
            expansion_cap = limits.max_expanded_excel_bytes()
            if extension in {".xlsx", ".xlsm"} and expansion_cap is not None:
                with zipfile.ZipFile(BytesIO(raw)) as workbook:
                    expanded_size = sum(member.file_size for member in workbook.infolist())
                    if expanded_size > expansion_cap:
                        raise DataProblem(
                            limits.demo_limit(
                                f"On the public demo a workbook may unzip to at most {limits.DEMO_MAX_EXPANDED_EXCEL_MB} MB."
                            )
                        )
            tables = pd.read_excel(BytesIO(raw), sheet_name=None)
        else:
            payload = json.loads(raw.decode("utf-8-sig"))
            if isinstance(payload, list):
                tables = {"data": pd.DataFrame(payload)}
            elif isinstance(payload, dict) and all(isinstance(value, list) for value in payload.values()):
                tables = {str(key): pd.DataFrame(value) for key, value in payload.items()}
            else:
                tables = {"data": pd.DataFrame(payload)}
    except DataProblem:
        raise
    except MemoryError as exc:
        raise DataProblem(limits.MEMORY_MESSAGE) from exc
    except Exception as exc:
        raise DataProblem(
            "The file could not be read. Check that it opens normally and that the first row contains column names."
        ) from exc

    clean: dict[str, pd.DataFrame] = {}
    total_cells = 0
    row_cap, cell_cap = limits.max_table_rows(), limits.max_total_cells()
    for table_name, frame in tables.items():
        if frame is None or (frame.empty and len(frame.columns) == 0):
            continue
        # The frames were just parsed and are owned here: rename in place instead of copying a large table.
        frame.columns = _unique_column_names(list(frame.columns))
        total_cells += int(frame.shape[0] * frame.shape[1])
        if (row_cap is not None and len(frame) > row_cap) or (cell_cap is not None and total_cells > cell_cap):
            raise _demo_size_problem()
        clean[str(table_name)] = frame
    if not clean:
        raise DataProblem("No usable tables were found in this file.")
    return LoadedData(tables=clean, source_name=source_name)


def _neutralize(value: object) -> object:
    if not isinstance(value, str):
        return value
    cleaned = ILLEGAL_XML_CHARACTERS.sub("", value)
    return "'" + cleaned if cleaned.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else cleaned


def safe_for_spreadsheet(frame: pd.DataFrame) -> pd.DataFrame:
    """Neutralize strings that spreadsheet programs could interpret as formulas."""
    safe = frame.copy()
    for column in safe.columns:
        series = safe[column].astype(object) if isinstance(safe[column].dtype, pd.CategoricalDtype) else safe[column]
        if pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_datetime64_any_dtype(series.dtype):
            continue  # no strings to neutralize
        # Neutralize each distinct value once; long tables repeat a few labels many times.
        codes, uniques = pd.factorize(series, use_na_sentinel=True)
        cleaned = np.array([_neutralize(value) for value in uniques] + [None], dtype=object)
        values = cleaned[codes]
        missing = codes < 0
        if missing.any():
            values[missing] = series.to_numpy(dtype=object)[missing]
        safe[column] = values
    return safe


def results_to_excel(tables: dict[str, pd.DataFrame]) -> bytes:
    """Create an in-memory Excel evidence pack with readable sheets."""
    if not tables:
        raise DataProblem("There are no result tables to export.")
    output = BytesIO()
    used_names: set[str] = set()
    left_out = {name: frame for name, frame in tables.items() if int(frame.shape[0] * max(frame.shape[1], 1)) > EXCEL_MAX_TABLE_CELLS}
    if left_out:
        note = pd.DataFrame(
            {
                "table": list(left_out),
                "rows": [len(frame) for frame in left_out.values()],
                "where_to_find_it": "CSV evidence ZIP and JSON export (every row); too large for an Excel sheet",
            }
        )
        tables = {"Read me large tables": note, **{name: frame for name, frame in tables.items() if name not in left_out}}
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for raw_name, frame in tables.items():
            base = re.sub(r"[\\/*?:\[\]]", "-", str(raw_name))[:31] or "Results"
            sheet_name = base
            suffix = 2
            while sheet_name in used_names:
                tail = f"_{suffix}"
                sheet_name = base[: 31 - len(tail)] + tail
                suffix += 1
            used_names.add(sheet_name)
            safe = safe_for_spreadsheet(frame)
            safe.to_excel(writer, sheet_name=sheet_name, index=False)
            sheet = writer.sheets[sheet_name]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cells in sheet.columns:
                widths = [len(str(cell.value)) if cell.value is not None else 0 for cell in cells[:2000]]
                sheet.column_dimensions[cells[0].column_letter].width = min(max(widths, default=8) + 2, 44)
    return output.getvalue()


def results_to_json(tables: dict[str, pd.DataFrame], metadata: dict | None = None) -> bytes:
    """Serialize evidence tables and reproducibility metadata as UTF-8 JSON."""
    large = {name for name, frame in tables.items() if len(frame) > JSON_COMPACT_ROWS}
    payload: dict[str, object] = {
        name: json.loads(frame.to_json(orient="records", date_format="iso"))
        for name, frame in tables.items()
        if name not in large
    }
    if metadata:
        payload["analysis_metadata"] = metadata
    text = json.dumps(payload, indent=2, default=str, allow_nan=False)
    if not large:
        return text.encode("utf-8")
    # Splice very long tables in as compact record arrays (same content, one line per table).
    parts = [
        f"  {json.dumps(str(name))}: {tables[name].to_json(orient='records', date_format='iso')}"
        for name in tables
        if name in large
    ]
    body = text[1:-1].strip("\n")
    return ("{\n" + ",\n".join(parts + ([body] if body else [])) + "\n}").encode("utf-8")


def tables_to_csv_zip(tables: dict[str, pd.DataFrame]) -> bytes:
    """Package equivalent accessible CSV tables in one archive."""
    if not tables:
        raise DataProblem("There are no result tables to export.")
    output = BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for raw_name, frame in tables.items():
            filename = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw_name).strip()).strip("_") or "results"
            archive.writestr(f"{filename}.csv", safe_for_spreadsheet(frame).to_csv(index=False))
    return output.getvalue()
