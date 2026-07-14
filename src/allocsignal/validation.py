"""Input preparation shared by the planning and panel workflows."""

from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

from .errors import DataProblem


CHANNEL_COLUMNS = [
    "channel",
    "current_spend",
    "min_spend",
    "max_spend",
    "floor_response",
    "ceiling_response",
    "half_saturation",
    "shape",
    "fixed",
    "long_run_multiplier",
]

CHANNEL_ALIASES = {
    "channel_name": "channel",
    "current": "current_spend",
    "spend": "current_spend",
    "minimum_spend": "min_spend",
    "minimum": "min_spend",
    "maximum_spend": "max_spend",
    "maximum": "max_spend",
    "minimum_response": "floor_response",
    "base_response": "floor_response",
    "saturation_response": "ceiling_response",
    "max_response": "ceiling_response",
    "half_saturation_spend": "half_saturation",
    "half_sat_spend": "half_saturation",
    "curve_shape": "shape",
    "is_fixed": "fixed",
    "long_term_multiplier": "long_run_multiplier",
}


@dataclass(frozen=True)
class PreparedPanel:
    """Numeric panel ready for estimation plus an encoding audit trail."""

    frame: pd.DataFrame
    entity_column: str
    time_column: str
    outcome_column: str
    predictors: list[str]
    encoded_from: dict[str, list[str]]
    warnings: tuple[str, ...]


def _slug(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    return text or "column"


def prepare_channel_plan(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize and validate one-row-per-channel ADBUDG planning inputs."""
    if frame is None or frame.empty:
        raise DataProblem("Add at least one channel before planning a budget.")
    work = frame.copy()
    normalized: dict[object, str] = {}
    seen: set[str] = set()
    for column in work.columns:
        candidate = CHANNEL_ALIASES.get(_slug(column), _slug(column))
        if candidate in seen:
            raise DataProblem(f"Two columns map to '{candidate}'. Keep only one of them.")
        normalized[column] = candidate
        seen.add(candidate)
    work = work.rename(columns=normalized)

    required = CHANNEL_COLUMNS[:-2]
    missing = [column for column in required if column not in work.columns]
    if missing:
        raise DataProblem("The channel plan is missing: " + ", ".join(missing) + ".")
    if "fixed" not in work:
        work["fixed"] = False
    if "long_run_multiplier" not in work:
        work["long_run_multiplier"] = 1.0
    work = work[CHANNEL_COLUMNS].copy()

    work["channel"] = work["channel"].astype(str).str.strip()
    if work["channel"].eq("").any() or work["channel"].str.lower().eq("nan").any():
        raise DataProblem("Every channel needs a non-empty name.")
    if work["channel"].duplicated().any():
        duplicates = work.loc[work["channel"].duplicated(keep=False), "channel"].unique().tolist()
        raise DataProblem("Channel names must be unique. Repeated: " + ", ".join(map(str, duplicates[:5])) + ".")

    numeric = [column for column in CHANNEL_COLUMNS if column not in {"channel", "fixed"}]
    for column in numeric:
        converted = pd.to_numeric(work[column], errors="coerce")
        invalid = converted.isna() | ~np.isfinite(converted)
        if invalid.any():
            rows = ", ".join(str(index + 1) for index in np.flatnonzero(invalid.to_numpy())[:5])
            raise DataProblem(f"'{column}' must contain finite numbers (check row(s) {rows}).")
        work[column] = converted.astype(float)

    fixed_text = work["fixed"].astype(str).str.strip().str.lower()
    truthy = {"true", "1", "yes", "y", "fixed"}
    falsy = {"false", "0", "no", "n", "", "nan", "none"}
    unknown = ~fixed_text.isin(truthy | falsy)
    if unknown.any():
        raise DataProblem("'fixed' must use true/false (or yes/no).")
    work["fixed"] = fixed_text.isin(truthy)

    if (work[["current_spend", "min_spend", "max_spend", "floor_response"]] < 0).any().any():
        raise DataProblem("Spend bounds, current spend, and floor response cannot be negative.")
    if (work["min_spend"] > work["max_spend"]).any():
        raise DataProblem("Every minimum spend must be at or below its maximum spend.")
    outside = (work["current_spend"] < work["min_spend"] - 1e-9) | (
        work["current_spend"] > work["max_spend"] + 1e-9
    )
    if outside.any():
        names = ", ".join(work.loc[outside, "channel"].head().tolist())
        raise DataProblem(f"Current spend must sit inside the minimum/maximum bounds ({names}).")
    if (work["ceiling_response"] <= work["floor_response"]).any():
        raise DataProblem("Saturation response must be greater than floor response for every channel.")
    if (work["half_saturation"] <= 0).any():
        raise DataProblem("Half-saturation spend must be greater than zero.")
    if (work["shape"] <= 0).any():
        raise DataProblem("Curve shape must be greater than zero.")
    if (work["long_run_multiplier"] <= 0).any():
        raise DataProblem("Long-run multipliers must be greater than zero.")
    return work.reset_index(drop=True)


def infer_column(columns: list[str], tokens: tuple[str, ...], fallback: int = 0) -> str:
    """Choose the first column whose normalized name contains a useful token."""
    if not columns:
        raise DataProblem("This table has no columns.")
    return next((column for column in columns if any(token in _slug(column) for token in tokens)), columns[fallback])


def numeric_candidates(frame: pd.DataFrame, excluded: set[str] | None = None) -> list[str]:
    """Columns with at least some numeric, finite content."""
    excluded = excluded or set()
    result: list[str] = []
    for column in frame.columns:
        if str(column) in excluded:
            continue
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.notna().sum() >= 2 and np.isfinite(converted.dropna()).all():
            result.append(str(column))
    return result


def prepare_panel_data(
    frame: pd.DataFrame,
    entity_column: str,
    time_column: str,
    outcome_column: str,
    numeric_predictors: list[str],
    categorical_predictors: list[str] | None = None,
) -> PreparedPanel:
    """Validate panel roles and one-hot encode explicitly selected controls."""
    categorical_predictors = categorical_predictors or []
    selected = [entity_column, time_column, outcome_column, *numeric_predictors, *categorical_predictors]
    if len(set(selected)) != len(selected):
        raise DataProblem("Entity, time, outcome, and predictor roles must not overlap.")
    missing_columns = [column for column in selected if column not in frame.columns]
    if missing_columns:
        raise DataProblem("Selected columns were not found: " + ", ".join(missing_columns) + ".")
    if not numeric_predictors and not categorical_predictors:
        raise DataProblem("Select at least one marketing or control predictor.")

    work = frame[selected].copy()
    missing_rows = work.isna().any(axis=1)
    if missing_rows.any():
        raise DataProblem(
            f"The selected panel contains {int(missing_rows.sum()):,} incomplete row(s). "
            "Remove or resolve them before estimation; AllocSignal does not silently impute panel data."
        )
    if work[[entity_column, time_column]].duplicated().any():
        duplicate_count = int(work[[entity_column, time_column]].duplicated(keep=False).sum())
        raise DataProblem(
            f"Entity × time must be unique; {duplicate_count:,} row(s) belong to duplicated panel keys."
        )
    if work[entity_column].nunique() < 2:
        raise DataProblem("Panel analysis needs at least two entities.")
    counts = work.groupby(entity_column, observed=True).size()
    if (counts < 2).any():
        raise DataProblem("Every included entity needs at least two time observations for within-entity estimation.")
    if work[time_column].nunique() < 2:
        raise DataProblem("Panel analysis needs at least two time periods.")

    for column in [outcome_column, *numeric_predictors]:
        converted = pd.to_numeric(work[column], errors="coerce")
        invalid = converted.isna() | ~np.isfinite(converted)
        if invalid.any():
            raise DataProblem(f"'{column}' must be numeric and finite in every selected row.")
        work[column] = converted.astype(float)
    if work[outcome_column].nunique() < 2:
        raise DataProblem("The outcome does not vary.")

    encoded_from: dict[str, list[str]] = {}
    encoded_predictors = list(numeric_predictors)
    warnings: list[str] = []
    for column in categorical_predictors:
        values = work[column].astype(str)
        levels = sorted(values.unique().tolist())
        if len(levels) < 2:
            warnings.append(f"Categorical control '{column}' has one level and was removed.")
            work = work.drop(columns=[column])
            continue
        if len(levels) > 25:
            raise DataProblem(f"'{column}' has {len(levels)} levels. Use at most 25 or regroup rare levels.")
        dummies = pd.get_dummies(values, prefix=_slug(column), drop_first=True, dtype=float)
        dummies.columns = [str(name) for name in dummies.columns]
        if not dummies.columns.is_unique:
            raise DataProblem(
                f"Encoding '{column}' would create repeated predictor names. "
                "Rename the control or regroup its levels before estimation."
            )
        retained_columns = set(work.columns) - {column}
        collisions = sorted(set(dummies.columns) & retained_columns)
        if collisions:
            raise DataProblem(
                f"Encoding '{column}' would overwrite existing predictor name(s): "
                + ", ".join(collisions)
                + ". Rename the control, the conflicting column, or regroup its levels."
            )
        work = pd.concat([work.drop(columns=[column]), dummies], axis=1)
        encoded_from[column] = list(dummies.columns)
        encoded_predictors.extend(dummies.columns.tolist())
        if len(encoded_predictors) != len(set(encoded_predictors)):
            raise DataProblem(
                "Categorical encoding produced duplicate predictor names. "
                "Rename the conflicting controls before estimation."
            )
    constants = [column for column in encoded_predictors if work[column].nunique() < 2]
    if constants:
        work = work.drop(columns=constants)
        encoded_predictors = [column for column in encoded_predictors if column not in constants]
        warnings.append("Removed constant predictor(s): " + ", ".join(constants) + ".")
    if not encoded_predictors:
        raise DataProblem("No varying predictors remain after preparation.")
    return PreparedPanel(
        frame=work.reset_index(drop=True),
        entity_column=entity_column,
        time_column=time_column,
        outcome_column=outcome_column,
        predictors=encoded_predictors,
        encoded_from=encoded_from,
        warnings=tuple(warnings),
    )
