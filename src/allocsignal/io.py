"""Safe local input and portable evidence-pack exports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import BinaryIO
import zipfile

import pandas as pd

from .errors import DataProblem


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm", ".json"}
MAX_UPLOAD_MB = max(1, min(int(os.getenv("ALLOCSIGNAL_MAX_UPLOAD_MB", "200")), 500))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_JSON_BYTES = 30 * 1024 * 1024
MAX_UNCOMPRESSED_EXCEL_BYTES = 250 * 1024 * 1024
MAX_TABLE_ROWS = 500_000
MAX_TOTAL_CELLS = 8_000_000
CSV_CHUNK_ROWS = 25_000
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


def load_data(source: str | Path | bytes | BinaryIO, name: str | None = None) -> LoadedData:
    """Read CSV, Excel, or JSON without executing uploaded content."""
    raw, detected_name = _source_bytes(source)
    source_name = name or detected_name
    extension = Path(source_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DataProblem("Please use CSV, Excel, or JSON data.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise DataProblem(f"This file is larger than the configured {MAX_UPLOAD_MB} MB limit.")
    if extension == ".json" and len(raw) > MAX_JSON_BYTES:
        raise DataProblem("JSON uploads are limited to 30 MB because they expand in memory.")
    if not raw:
        raise DataProblem("This file is empty.")

    try:
        if extension == ".csv":
            chunks: list[pd.DataFrame] = []
            rows = 0
            cells = 0
            for chunk in pd.read_csv(BytesIO(raw), sep=None, engine="python", chunksize=CSV_CHUNK_ROWS):
                rows += len(chunk)
                cells += int(chunk.shape[0] * chunk.shape[1])
                if rows > MAX_TABLE_ROWS or cells > MAX_TOTAL_CELLS:
                    raise DataProblem("This CSV exceeds the local safety limit. Aggregate or keep fewer columns first.")
                chunks.append(chunk)
            tables = {"data": pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()}
        elif extension in {".xlsx", ".xls", ".xlsm"}:
            if extension in {".xlsx", ".xlsm"}:
                with zipfile.ZipFile(BytesIO(raw)) as workbook:
                    expanded_size = sum(member.file_size for member in workbook.infolist())
                    if expanded_size > MAX_UNCOMPRESSED_EXCEL_BYTES:
                        raise DataProblem("This workbook expands beyond 250 MB. Keep only the needed sheets.")
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
    except Exception as exc:
        raise DataProblem(
            "The file could not be read. Check that it opens normally and that the first row contains column names."
        ) from exc

    clean: dict[str, pd.DataFrame] = {}
    total_cells = 0
    for table_name, frame in tables.items():
        if frame is None or (frame.empty and len(frame.columns) == 0):
            continue
        copy = frame.copy()
        copy.columns = _unique_column_names(list(copy.columns))
        total_cells += int(copy.shape[0] * copy.shape[1])
        if len(copy) > MAX_TABLE_ROWS or total_cells > MAX_TOTAL_CELLS:
            raise DataProblem("The file contains more rows or cells than this local release accepts.")
        clean[str(table_name)] = copy
    if not clean:
        raise DataProblem("No usable tables were found in this file.")
    return LoadedData(tables=clean, source_name=source_name)


def safe_for_spreadsheet(frame: pd.DataFrame) -> pd.DataFrame:
    """Neutralize strings that spreadsheet programs could interpret as formulas."""
    safe = frame.copy()
    for column in safe.columns:
        series = safe[column].astype(object) if isinstance(safe[column].dtype, pd.CategoricalDtype) else safe[column]

        def neutralize(value: object) -> object:
            if not isinstance(value, str):
                return value
            cleaned = ILLEGAL_XML_CHARACTERS.sub("", value)
            return "'" + cleaned if cleaned.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else cleaned

        safe[column] = series.map(neutralize)
    return safe


def results_to_excel(tables: dict[str, pd.DataFrame]) -> bytes:
    """Create an in-memory Excel evidence pack with readable sheets."""
    if not tables:
        raise DataProblem("There are no result tables to export.")
    output = BytesIO()
    used_names: set[str] = set()
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
    payload: dict[str, object] = {
        name: json.loads(frame.to_json(orient="records", date_format="iso")) for name, frame in tables.items()
    }
    if metadata:
        payload["analysis_metadata"] = metadata
    return json.dumps(payload, indent=2, default=str, allow_nan=False).encode("utf-8")


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
