"""Per-period media-plan arithmetic on declared assumptions: adstock, reach/frequency, interactions.

Every quantity in this module is computed from parameters the analyst declares.
Nothing here is estimated from data; that boundary is deliberate and must be
preserved by callers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from .errors import DataProblem

MIN_PERIODS = 4
MAX_PERIODS = 52
MAX_RETENTION = 0.95
INTERACTION_MIN = 0.8
INTERACTION_MAX = 1.2
MAX_INTERACTIONS = 3
REACH_EPSILON = 1e-9


def _check_retention(retention: float) -> float:
    value = float(retention)
    if not np.isfinite(value) or not 0.0 <= value <= MAX_RETENTION:
        raise DataProblem(
            f"Carryover retention must be a declared number between 0 and {MAX_RETENTION}. "
            "It is a planning assumption, not an estimate, so out-of-range values are refused rather than clipped."
        )
    return value


def prepare_schedule(frame: pd.DataFrame, channel_column: str = "channel") -> pd.DataFrame:
    """Validate a channels × periods spend table and return it channel-indexed with float periods."""
    if channel_column not in frame.columns:
        raise DataProblem(f"The schedule needs a '{channel_column}' column with one row per channel.")
    if frame.empty:
        raise DataProblem("The schedule has no channel rows.")
    channels = frame[channel_column].astype("string").fillna("").str.strip()
    if (channels == "").any():
        raise DataProblem("Every schedule row needs a non-empty channel name.")
    if channels.duplicated().any():
        raise DataProblem("Channel names must be unique in the schedule.")
    period_columns = [column for column in frame.columns if column != channel_column]
    if not MIN_PERIODS <= len(period_columns) <= MAX_PERIODS:
        raise DataProblem(
            f"The schedule needs between {MIN_PERIODS} and {MAX_PERIODS} spend periods; "
            f"it has {len(period_columns)}."
        )
    spend = frame[period_columns].apply(pd.to_numeric, errors="coerce")
    if spend.isna().any().any():
        raise DataProblem("Spend per period must be complete numeric values (use 0 for dark periods).")
    if (spend < 0).any().any():
        raise DataProblem("Spend per period cannot be negative.")
    result = spend.astype(float)
    result.index = pd.Index(channels, name="channel")
    result.columns = [str(column) for column in period_columns]
    return result


def geometric_adstock(spend: Sequence[float] | np.ndarray, retention: float) -> np.ndarray:
    """Geometric adstock A_t = x_t + λ·A_{t−1} with declared retention λ (Broadbent, 1979)."""
    value = _check_retention(retention)
    values = np.asarray(spend, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise DataProblem("Adstock needs a one-dimensional, non-empty spend series.")
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataProblem("Adstock spend values must be finite and non-negative.")
    result = np.empty_like(values)
    carried = 0.0
    for index, amount in enumerate(values):
        carried = amount + value * carried
        result[index] = carried
    return result


def adstock_half_life(retention: float) -> float:
    """Periods until carried-over pressure halves: ln(0.5) / ln(λ); zero when λ = 0."""
    value = _check_retention(retention)
    if value == 0.0:
        return 0.0
    return float(np.log(0.5) / np.log(value))


def adstock_schedule(schedule: pd.DataFrame, retention: Mapping[str, float]) -> pd.DataFrame:
    """Apply per-channel geometric adstock to a prepared channel-indexed schedule."""
    missing = [str(channel) for channel in schedule.index if channel not in retention]
    if missing:
        raise DataProblem("Declare a carryover retention for every channel. Missing: " + ", ".join(missing))
    rows = {
        channel: geometric_adstock(schedule.loc[channel].to_numpy(dtype=float), float(retention[channel]))
        for channel in schedule.index
    }
    result = pd.DataFrame.from_dict(rows, orient="index", columns=schedule.columns)
    result.index.name = schedule.index.name
    return result


def reach_frequency(
    adstocked_spend: Sequence[float] | np.ndarray, audience_size: float, cost_per_impression: float
) -> pd.DataFrame:
    """Declared-parameter reach and frequency per period (Rust, 1986).

    I_t = A_t / c, reach_t = N·(1 − exp(−I_t/N)), frequency_t = I_t / max(reach_t, ε).
    """
    cost = float(cost_per_impression)
    if not np.isfinite(cost) or cost <= 0:
        raise DataProblem("Cost per impression-equivalent must be a positive declared number.")
    audience = float(audience_size)
    if not np.isfinite(audience) or audience <= 0:
        raise DataProblem("Audience size must be a positive declared number.")
    pressure = np.asarray(adstocked_spend, dtype=float)
    if pressure.ndim != 1 or pressure.size == 0 or not np.isfinite(pressure).all() or (pressure < 0).any():
        raise DataProblem("Effective spend must be a non-empty series of finite, non-negative values.")
    impressions = pressure / cost
    reach = audience * (1.0 - np.exp(-impressions / audience))
    frequency = impressions / np.maximum(reach, REACH_EPSILON)
    return pd.DataFrame({"impressions": impressions, "reach": reach, "frequency": frequency})


def apply_interactions(
    adstocked: pd.DataFrame, interactions: Sequence[tuple[str, str, float]]
) -> pd.DataFrame:
    """Scale both channels of each declared pair by κ in periods where both carry positive pressure.

    This is scenario arithmetic on declared multipliers — not an estimated synergy model.
    Multipliers compound multiplicatively when a channel appears in several declared pairs.
    """
    if len(interactions) > MAX_INTERACTIONS:
        raise DataProblem(f"Declare at most {MAX_INTERACTIONS} pairwise interaction multipliers.")
    adjusted = adstocked.astype(float).copy()
    seen: set[frozenset[str]] = set()
    for first, second, kappa in interactions:
        for channel in (first, second):
            if channel not in adstocked.index:
                raise DataProblem(f"Interaction channel '{channel}' is not in the schedule.")
        if first == second:
            raise DataProblem("An interaction pairs two different channels; a channel cannot pair with itself.")
        multiplier = float(kappa)
        if not np.isfinite(multiplier) or not INTERACTION_MIN <= multiplier <= INTERACTION_MAX:
            raise DataProblem(
                f"Interaction multipliers must stay between {INTERACTION_MIN} and {INTERACTION_MAX}. "
                "Larger effects need evidence, not a declared scenario knob."
            )
        pair = frozenset((first, second))
        if pair in seen:
            raise DataProblem(f"The pair '{first}' × '{second}' is declared more than once.")
        seen.add(pair)
        overlap = ((adstocked.loc[first] > 0) & (adstocked.loc[second] > 0)).to_numpy()
        columns = adstocked.columns[overlap]
        adjusted.loc[first, columns] *= multiplier
        adjusted.loc[second, columns] *= multiplier
    return adjusted
