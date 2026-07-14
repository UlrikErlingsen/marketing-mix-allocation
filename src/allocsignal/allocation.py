"""Constrained marketing-budget allocation for AllocSignal.

The allocator treats channel response curves as additive and independent.  It
does not infer cross-channel synergies or causal effects.  That deliberately
simple assumption makes the economic logic inspectable:

    profit = (base response + sum(channel response)) * margin - sum(spend)

Fixed-budget reallocation uses deterministic multi-start SLSQP.  Multi-starts
reduce (but cannot eliminate) local-optimum risk for S-shaped response curves,
so solver diagnostics and that limitation travel with every result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult, minimize, minimize_scalar

from .response import ResponseCurve, ResponseCurveError


REQUIRED_PLAN_COLUMNS = (
    "channel",
    "current_spend",
    "min_spend",
    "max_spend",
    "floor_response",
    "ceiling_response",
    "half_saturation",
    "shape",
)

NUMERIC_PLAN_COLUMNS = REQUIRED_PLAN_COLUMNS[1:]

INDEPENDENCE_ASSUMPTION = (
    "Channel responses are additive and independent; interactions, spillovers and "
    "cannibalisation are not modelled."
)

DEFAULT_ASSUMPTIONS = (
    INDEPENDENCE_ASSUMPTION,
    "Response curves are planning assumptions, not causal estimates.",
    "Profit equals total response times contribution margin minus marketing spend.",
    "Base response and unit margin are held constant as allocation changes.",
)

MAX_SAFE_INPUT_SCALE = 1e15
MIN_SAFE_POSITIVE_SPEND = 1e-8


class ChannelPlanError(ValueError):
    """Raised when a channel plan is missing or violates required bounds."""


class AllocationInfeasibleError(ChannelPlanError):
    """Raised when spend constraints cannot accommodate the requested budget."""


class AllocationOptimizationError(ValueError):
    """Raised when the numerical solver does not produce a feasible solution."""


@dataclass(frozen=True)
class AllocationResult:
    """A solver result plus a Streamlit-ready channel table."""

    mode: str
    success: bool
    message: str
    margin: float
    base_response: float
    total_budget: float | None
    total_spend: float
    total_response: float
    gross_contribution: float
    profit: float
    baseline_profit: float
    incremental_profit_vs_baseline: float
    solver_status: int | None
    solver_iterations: int | None
    table: pd.DataFrame
    assumptions: tuple[str, ...] = DEFAULT_ASSUMPTIONS

    @property
    def net_contribution(self) -> float:
        """Alias for profit after marketing cost."""

        return self.profit

    def summary_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "success": self.success,
            "message": self.message,
            "margin": self.margin,
            "base_response": self.base_response,
            "total_budget": self.total_budget,
            "total_spend": self.total_spend,
            "total_response": self.total_response,
            "gross_contribution": self.gross_contribution,
            "profit": self.profit,
            "baseline_profit": self.baseline_profit,
            "incremental_profit_vs_baseline": self.incremental_profit_vs_baseline,
            "solver_status": self.solver_status,
            "solver_iterations": self.solver_iterations,
        }

    def summary_frame(self) -> pd.DataFrame:
        return pd.DataFrame([self.summary_dict()])


@dataclass(frozen=True)
class SensitivityResult:
    """Scenario summaries and channel-level allocations from a stress test."""

    summary: pd.DataFrame
    allocations: pd.DataFrame
    assumptions: tuple[str, ...] = DEFAULT_ASSUMPTIONS


def _finite_nonnegative(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ChannelPlanError(f"{name} must be a number.") from exc
    if not math.isfinite(number):
        raise ChannelPlanError(f"{name} must be finite.")
    if number < 0:
        raise ChannelPlanError(f"{name} must be zero or positive.")
    return number


def _coerce_fixed(value: Any, row_number: int) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "fixed", "lock", "locked"}:
        return True
    if text in {"false", "no", "n", "0", "", "flexible", "open"}:
        return False
    raise ChannelPlanError(
        f"Row {row_number}: fixed must be true/false (or yes/no), not {value!r}."
    )


def validate_channel_plan(plan: pd.DataFrame) -> pd.DataFrame:
    """Return a normalized, validated copy of a channel-plan table."""

    if not isinstance(plan, pd.DataFrame):
        raise ChannelPlanError("Channel plan must be a pandas DataFrame.")
    if plan.empty:
        raise ChannelPlanError("Channel plan is empty; add at least one channel.")
    missing = [column for column in REQUIRED_PLAN_COLUMNS if column not in plan.columns]
    if missing:
        raise ChannelPlanError(
            "Channel plan is missing required column(s): " + ", ".join(missing) + "."
        )

    normalized = plan.loc[:, list(REQUIRED_PLAN_COLUMNS)].copy()
    normalized.insert(
        len(normalized.columns),
        "fixed",
        plan["fixed"].copy() if "fixed" in plan.columns else False,
    )
    normalized["channel"] = normalized["channel"].astype("string").str.strip()
    blank_channels = normalized["channel"].isna() | normalized["channel"].eq("")
    if blank_channels.any():
        rows = ", ".join(str(index + 1) for index in np.flatnonzero(blank_channels.to_numpy()))
        raise ChannelPlanError(f"Channel names cannot be blank (row(s): {rows}).")
    duplicate_channels = normalized["channel"].duplicated(keep=False)
    if duplicate_channels.any():
        names = ", ".join(sorted(normalized.loc[duplicate_channels, "channel"].unique()))
        raise ChannelPlanError(f"Channel names must be unique; duplicates: {names}.")

    for column in NUMERIC_PLAN_COLUMNS:
        original = normalized[column]
        converted = pd.to_numeric(original, errors="coerce")
        bad = converted.isna() | ~np.isfinite(converted)
        if bad.any():
            rows = ", ".join(str(index + 1) for index in np.flatnonzero(bad.to_numpy()))
            raise ChannelPlanError(f"{column} contains a missing or non-numeric value at row(s) {rows}.")
        normalized[column] = converted.astype(float)

    numeric_magnitude = float(normalized[list(NUMERIC_PLAN_COLUMNS)].abs().to_numpy(dtype=float).max())
    if numeric_magnitude > MAX_SAFE_INPUT_SCALE:
        raise ChannelPlanError(
            "Channel-plan values are too large for reliable numerical optimization. "
            "Rescale spend and response into thousands, millions, or another consistent unit."
        )
    if (normalized["half_saturation"] < MIN_SAFE_POSITIVE_SPEND).any():
        names = ", ".join(normalized.loc[normalized["half_saturation"] < MIN_SAFE_POSITIVE_SPEND, "channel"])
        raise ChannelPlanError(
            "half_saturation is below the optimizer's reliable numeric scale "
            f"({names}). Rescale all spend fields into a larger consistent unit."
        )

    normalized["fixed"] = [
        _coerce_fixed(value, row_number)
        for row_number, value in enumerate(normalized["fixed"], start=1)
    ]

    nonnegative_columns = (
        "current_spend",
        "min_spend",
        "max_spend",
        "floor_response",
        "ceiling_response",
    )
    for column in nonnegative_columns:
        bad = normalized[column] < 0
        if bad.any():
            names = ", ".join(normalized.loc[bad, "channel"])
            raise ChannelPlanError(f"{column} cannot be negative ({names}).")
    if (normalized["half_saturation"] <= 0).any():
        names = ", ".join(normalized.loc[normalized["half_saturation"] <= 0, "channel"])
        raise ChannelPlanError(f"half_saturation must be greater than zero ({names}).")
    if (normalized["shape"] <= 0).any():
        names = ", ".join(normalized.loc[normalized["shape"] <= 0, "channel"])
        raise ChannelPlanError(f"shape must be greater than zero ({names}).")
    bad_bounds = normalized["min_spend"] > normalized["max_spend"]
    if bad_bounds.any():
        names = ", ".join(normalized.loc[bad_bounds, "channel"])
        raise ChannelPlanError(f"min_spend exceeds max_spend ({names}).")
    outside = (normalized["current_spend"] < normalized["min_spend"]) | (
        normalized["current_spend"] > normalized["max_spend"]
    )
    if outside.any():
        names = ", ".join(normalized.loc[outside, "channel"])
        raise ChannelPlanError(
            f"current_spend must lie between min_spend and max_spend ({names})."
        )
    bad_response_bounds = normalized["floor_response"] > normalized["ceiling_response"]
    if bad_response_bounds.any():
        names = ", ".join(normalized.loc[bad_response_bounds, "channel"])
        raise ChannelPlanError(
            f"floor_response exceeds ceiling_response ({names})."
        )

    # Constructing the curves also validates the same public invariants used in
    # later evaluation, and keeps validation errors tied to channel names.
    for row in normalized.itertuples(index=False):
        try:
            ResponseCurve(
                row.floor_response,
                row.ceiling_response,
                row.half_saturation,
                row.shape,
            )
        except ResponseCurveError as exc:
            raise ChannelPlanError(f"{row.channel}: {exc}") from exc
    return normalized.reset_index(drop=True)


def _curves(plan: pd.DataFrame) -> list[ResponseCurve]:
    return [
        ResponseCurve(row.floor_response, row.ceiling_response, row.half_saturation, row.shape)
        for row in plan.itertuples(index=False)
    ]


def _effective_bounds(plan: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    current = plan["current_spend"].to_numpy(dtype=float)
    fixed = plan["fixed"].to_numpy(dtype=bool)
    lower = np.where(fixed, current, plan["min_spend"].to_numpy(dtype=float))
    upper = np.where(fixed, current, plan["max_spend"].to_numpy(dtype=float))
    return lower, upper


def _spend_vector(
    spends: Mapping[str, float] | Sequence[float] | pd.Series | np.ndarray | None,
    plan: pd.DataFrame,
) -> np.ndarray:
    if spends is None:
        return plan["current_spend"].to_numpy(dtype=float)
    channels = plan["channel"].tolist()
    if isinstance(spends, Mapping):
        missing = [channel for channel in channels if channel not in spends]
        extras = [str(channel) for channel in spends if channel not in set(channels)]
        if missing or extras:
            detail: list[str] = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extras:
                detail.append("unknown " + ", ".join(extras))
            raise ChannelPlanError("Spend mapping does not match channels: " + "; ".join(detail) + ".")
        values = [spends[channel] for channel in channels]
    elif isinstance(spends, pd.Series) and set(channels).issubset(set(spends.index)):
        values = spends.reindex(channels).tolist()
    else:
        try:
            values = list(spends)
        except TypeError as exc:
            raise ChannelPlanError("spends must be a vector or channel-to-spend mapping.") from exc
    try:
        vector = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ChannelPlanError("spends must contain only numbers.") from exc
    if vector.ndim != 1 or len(vector) != len(plan):
        raise ChannelPlanError(f"spends must contain exactly {len(plan)} values.")
    if not np.all(np.isfinite(vector)) or np.any(vector < 0):
        raise ChannelPlanError("spends must contain finite, non-negative values.")
    return vector


def _check_spend_bounds(spends: np.ndarray, plan: pd.DataFrame) -> None:
    lower, upper = _effective_bounds(plan)
    tolerance = 1e-7 * np.maximum(1.0, np.maximum(np.abs(lower), np.abs(upper)))
    outside = (spends < lower - tolerance) | (spends > upper + tolerance)
    if np.any(outside):
        names = ", ".join(plan.loc[outside, "channel"])
        raise ChannelPlanError(
            "Recommended spend violates min/max or fixed-channel constraints for: " + names + "."
        )


def _economic_values(
    spends: np.ndarray,
    curves: list[ResponseCurve],
    margin: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    responses = np.array(
        [curve.response(spend) for curve, spend in zip(curves, spends, strict=True)],
        dtype=float,
    )
    marginals = np.array(
        [curve.marginal_response(spend) for curve, spend in zip(curves, spends, strict=True)],
        dtype=float,
    )
    elasticities = np.array(
        [curve.elasticity(spend) for curve, spend in zip(curves, spends, strict=True)],
        dtype=float,
    )
    if margin == 0:
        marginal_profit = np.full_like(marginals, -1.0, dtype=float)
    else:
        with np.errstate(over="ignore", invalid="ignore"):
            marginal_profit = margin * marginals - 1.0
    return responses, marginals, elasticities, marginal_profit


def _validate_economic_scale(
    plan: pd.DataFrame,
    margin: float,
    base_response: float,
) -> None:
    """Reject finite inputs whose combined economics overflow ordinary floats."""
    if margin > MAX_SAFE_INPUT_SCALE or base_response > MAX_SAFE_INPUT_SCALE:
        raise ChannelPlanError(
            "Margin or base response is too large for reliable numerical optimization. "
            "Rescale spend, response, and margin into consistent larger units."
        )
    extended = np.longdouble
    max_response = extended(base_response) + np.sum(
        plan["ceiling_response"].to_numpy(dtype=np.longdouble), dtype=np.longdouble
    )
    max_gross = max_response * extended(margin)
    max_spend = np.sum(plan["max_spend"].to_numpy(dtype=np.longdouble), dtype=np.longdouble)
    float_limit = extended(np.finfo(float).max) / extended(4.0)
    if (
        not np.isfinite(max_response)
        or not np.isfinite(max_gross)
        or not np.isfinite(max_spend)
        or abs(max_gross) > float_limit
        or abs(max_spend) > float_limit
    ):
        raise ChannelPlanError(
            "These units would overflow the contribution calculation. "
            "Rescale spend and response before optimization."
        )


def _objective(spends: np.ndarray, curves: list[ResponseCurve], margin: float) -> float:
    responses = sum(float(curve.response(spend)) for curve, spend in zip(curves, spends, strict=True))
    return -(margin * responses - float(np.sum(spends)))


def _objective_gradient(
    spends: np.ndarray,
    curves: list[ResponseCurve],
    margin: float,
) -> np.ndarray:
    derivatives = np.array(
        [curve.marginal_response(spend) for curve, spend in zip(curves, spends, strict=True)],
        dtype=float,
    )
    # Infinite right-hand derivatives can occur at zero for c < 1.  A large,
    # finite descent direction is friendlier to SLSQP while preserving direction.
    derivatives = np.nan_to_num(derivatives, nan=0.0, posinf=1e30, neginf=-1e30)
    return -(margin * derivatives - 1.0)


def _build_result(
    plan: pd.DataFrame,
    spends: np.ndarray,
    *,
    margin: float,
    base_response: float,
    mode: str,
    message: str,
    total_budget: float | None,
    solver_status: int | None,
    solver_iterations: int | None,
    success: bool = True,
) -> AllocationResult:
    curves = _curves(plan)
    current = plan["current_spend"].to_numpy(dtype=float)
    current_response, _, _, _ = _economic_values(current, curves, margin)
    responses, marginal, elasticity, marginal_profit = _economic_values(spends, curves, margin)
    total_response = base_response + float(np.sum(responses))
    total_spend = float(np.sum(spends))
    contribution = total_response * margin
    profit = contribution - total_spend
    baseline_total_response = base_response + float(np.sum(current_response))
    baseline_profit = baseline_total_response * margin - float(np.sum(current))
    if not all(
        math.isfinite(value)
        for value in (total_response, total_spend, contribution, profit, baseline_total_response, baseline_profit)
    ):
        raise ChannelPlanError(
            "The selected units produced a non-finite response or contribution. "
            "Rescale spend, response, and margin before optimization."
        )
    lower, upper = _effective_bounds(plan)
    scale = np.maximum(1.0, np.maximum(np.abs(lower), np.abs(upper)))
    tolerance = 1e-6 * scale

    table = pd.DataFrame(
        {
            "channel": plan["channel"].astype(str),
            "current_spend": current,
            "recommended_spend": spends,
            "change": spends - current,
            "min_spend": plan["min_spend"].to_numpy(dtype=float),
            "max_spend": plan["max_spend"].to_numpy(dtype=float),
            "fixed": plan["fixed"].to_numpy(dtype=bool),
            "current_response": current_response,
            "recommended_response": responses,
            "response_change": responses - current_response,
            "gross_contribution": responses * margin,
            "net_contribution": responses * margin - spends,
            "marginal_response": marginal,
            "marginal_profit": marginal_profit,
            "elasticity": elasticity,
            "at_min": np.abs(spends - lower) <= tolerance,
            "at_max": np.abs(spends - upper) <= tolerance,
        }
    )
    return AllocationResult(
        mode=mode,
        success=success,
        message=message,
        margin=margin,
        base_response=base_response,
        total_budget=total_budget,
        total_spend=total_spend,
        total_response=total_response,
        gross_contribution=contribution,
        profit=profit,
        baseline_profit=baseline_profit,
        incremental_profit_vs_baseline=profit - baseline_profit,
        solver_status=solver_status,
        solver_iterations=solver_iterations,
        table=table,
    )


def evaluate_allocation(
    plan: pd.DataFrame,
    margin: float,
    base_response: float = 0.0,
    spends: Mapping[str, float] | Sequence[float] | pd.Series | np.ndarray | None = None,
    *,
    mode: str = "baseline",
) -> AllocationResult:
    """Evaluate current or supplied spend without running an optimizer."""

    normalized = validate_channel_plan(plan)
    margin_value = _finite_nonnegative(margin, "margin")
    base_value = _finite_nonnegative(base_response, "base_response")
    _validate_economic_scale(normalized, margin_value, base_value)
    vector = _spend_vector(spends, normalized)
    _check_spend_bounds(vector, normalized)
    total_budget = float(np.sum(vector)) if mode == "fixed_budget" else None
    return _build_result(
        normalized,
        vector,
        margin=margin_value,
        base_response=base_value,
        mode=mode,
        message="Allocation evaluated without numerical optimization.",
        total_budget=total_budget,
        solver_status=None,
        solver_iterations=None,
    )


def _project_to_budget(
    seed: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    budget: float,
) -> np.ndarray:
    values = np.clip(np.asarray(seed, dtype=float), lower, upper)
    difference = budget - float(np.sum(values))
    tolerance = 1e-10 * max(1.0, budget)
    if difference > 0:
        room = upper - values
    else:
        room = values - lower
    total_room = float(np.sum(room))
    if total_room + tolerance < abs(difference):
        raise AllocationInfeasibleError("Could not construct a feasible allocation for this budget.")
    if total_room > 0:
        values += np.sign(difference) * min(abs(difference) / total_room, 1.0) * room
    # Eliminate tiny floating residuals deterministically on a channel with room.
    residual = budget - float(np.sum(values))
    if abs(residual) > 0:
        if residual > 0:
            candidates = np.flatnonzero(upper - values >= residual - tolerance)
        else:
            candidates = np.flatnonzero(values - lower >= -residual - tolerance)
        if len(candidates):
            values[candidates[0]] += residual
    return np.clip(values, lower, upper)


def _unique_starts(starts: list[np.ndarray]) -> list[np.ndarray]:
    unique: list[np.ndarray] = []
    for candidate in starts:
        if not any(np.allclose(candidate, existing, rtol=0, atol=1e-8) for existing in unique):
            unique.append(candidate)
    return unique


def _fixed_budget_starts(
    plan: pd.DataFrame,
    lower: np.ndarray,
    upper: np.ndarray,
    budget: float,
    curves: list[ResponseCurve],
    margin: float,
) -> list[np.ndarray]:
    current = plan["current_spend"].to_numpy(dtype=float)
    starts = [
        _project_to_budget(current, lower, upper, budget),
        _project_to_budget(lower, lower, upper, budget),
        _project_to_budget(upper, lower, upper, budget),
        _project_to_budget((lower + upper) / 2.0, lower, upper, budget),
    ]

    marginal_at_current = -_objective_gradient(np.clip(current, lower, upper), curves, margin)
    orders = [
        np.argsort(-marginal_at_current),
        np.argsort(marginal_at_current),
        np.arange(len(plan)),
        np.arange(len(plan))[::-1],
    ]
    for order in orders:
        candidate = lower.copy()
        remaining = budget - float(np.sum(candidate))
        for index in order:
            addition = min(remaining, upper[index] - candidate[index])
            candidate[index] += max(addition, 0.0)
            remaining -= max(addition, 0.0)
            if remaining <= 1e-9 * max(1.0, budget):
                break
        starts.append(_project_to_budget(candidate, lower, upper, budget))

    # Under S-shaped response, a corner and the equal split can sit in different
    # attraction basins.  A deterministic pairwise global search supplies SLSQP
    # with seeds on the other side of those activation thresholds.  With two
    # channels this searches the complete feasible budget line; with more
    # channels repeated pair exchanges are a robust, inexpensive globalisation
    # heuristic for the separable objective.
    base_starts = _unique_starts(starts)
    pairwise_starts = [
        _pairwise_global_refine(start, lower, upper, curves, margin)
        for start in base_starts
    ]
    return _unique_starts([*base_starts, *pairwise_starts])


def _refine_scalar_grid_minimum(
    grid: np.ndarray,
    objective_values: np.ndarray,
    objective,
) -> float:
    """Refine the best point from a global grid without assuming global convexity."""

    finite = np.isfinite(objective_values)
    if not finite.any():
        raise AllocationOptimizationError(
            "The economic objective became non-finite. Rescale spend, response, and margin."
        )
    finite_positions = np.flatnonzero(finite)
    best_position = int(finite_positions[np.argmin(objective_values[finite])])
    best_value = float(grid[best_position])
    if best_position == 0 or best_position == len(grid) - 1:
        return best_value

    left = float(grid[best_position - 1])
    right = float(grid[best_position + 1])
    if right <= left:
        return best_value

    span = right - left
    refined = minimize_scalar(
        lambda unit: float(objective(left + span * float(unit))),
        bounds=(0.0, 1.0),
        method="bounded",
        options={"xatol": 1e-12, "maxiter": 500},
    )
    if refined.success and math.isfinite(float(refined.fun)):
        refined_value = left + span * float(refined.x)
        if float(refined.fun) < float(objective_values[best_position]):
            return refined_value
    return best_value


def _pairwise_global_refine(
    seed: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    curves: list[ResponseCurve],
    margin: float,
    *,
    max_sweeps: int = 3,
) -> np.ndarray:
    """Improve a fixed-budget seed through globally searched pair exchanges."""

    values = np.asarray(seed, dtype=float).copy()
    if margin == 0 or len(values) < 2:
        return values
    best_objective = _objective(values, curves, margin)
    objective_tolerance = np.finfo(float).eps * max(1.0, abs(best_objective)) * 100

    for _ in range(max_sweeps):
        improved = False
        for first in range(len(values) - 1):
            for second in range(first + 1, len(values)):
                pair_total = float(values[first] + values[second])
                low = max(float(lower[first]), pair_total - float(upper[second]))
                high = min(float(upper[first]), pair_total - float(lower[second]))
                if high <= low:
                    continue

                # Uniform coverage handles ordinary scales.  Log-focused points
                # around both channels' half-saturation spends catch narrow
                # activation regions from steep S-curves.
                uniform = np.linspace(low, high, 1_025, dtype=float)
                factors = np.geomspace(1e-6, 1e6, 241)
                focused_first = np.clip(curves[first].half_saturation * factors, low, high)
                focused_second = np.clip(
                    pair_total - curves[second].half_saturation * factors,
                    low,
                    high,
                )
                grid = np.unique(
                    np.concatenate(
                        [uniform, focused_first, focused_second, np.array([values[first], low, high])]
                    )
                )
                second_spend = pair_total - grid
                with np.errstate(over="ignore", invalid="ignore"):
                    grid_objective = -margin * (
                        np.asarray(curves[first].response(grid), dtype=float)
                        + np.asarray(curves[second].response(second_spend), dtype=float)
                    )

                def pair_objective(first_spend: float) -> float:
                    second_value = pair_total - first_spend
                    return -margin * (
                        float(curves[first].response(first_spend))
                        + float(curves[second].response(second_value))
                    )

                first_spend = _refine_scalar_grid_minimum(
                    grid, grid_objective, pair_objective
                )
                candidate = values.copy()
                candidate[first] = first_spend
                candidate[second] = pair_total - first_spend
                candidate_objective = _objective(candidate, curves, margin)
                if candidate_objective < best_objective - objective_tolerance:
                    values = candidate
                    best_objective = candidate_objective
                    improved = True
        if not improved:
            break
    return values


def _profit_grid_seed(
    lower: np.ndarray,
    upper: np.ndarray,
    curves: list[ResponseCurve],
    margin: float,
) -> np.ndarray:
    seed = np.empty_like(lower)
    for index, (low, high, curve) in enumerate(zip(lower, upper, curves, strict=True)):
        if math.isclose(low, high, rel_tol=0.0, abs_tol=1e-12):
            seed[index] = low
            continue
        grid = np.unique(
            np.concatenate(
                [
                    np.linspace(low, high, 1_025, dtype=float),
                    np.clip(
                        curve.half_saturation * np.geomspace(1e-6, 1e6, 241),
                        low,
                        high,
                    ),
                    np.array([low, high], dtype=float),
                ]
            )
        )
        with np.errstate(over="ignore", invalid="ignore"):
            objective_values = grid - margin * np.asarray(curve.response(grid), dtype=float)

        def channel_objective(spend: float) -> float:
            return spend - margin * float(curve.response(spend))

        seed[index] = _refine_scalar_grid_minimum(
            grid, objective_values, channel_objective
        )
    return seed


def _is_feasible(
    values: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    budget: float | None = None,
) -> bool:
    tolerance = 2e-6 * max(1.0, float(np.max(np.abs(np.r_[lower, upper]))))
    if np.any(values < lower - tolerance) or np.any(values > upper + tolerance):
        return False
    if budget is not None and not math.isclose(
        float(np.sum(values)), budget, rel_tol=2e-7, abs_tol=2e-6 * max(1.0, budget)
    ):
        return False
    return True


def _best_slsqp(
    starts: list[np.ndarray],
    lower: np.ndarray,
    upper: np.ndarray,
    curves: list[ResponseCurve],
    margin: float,
    budget: float | None,
) -> tuple[OptimizeResult, int]:
    constraint = None
    if budget is not None:
        constraint = {
            "type": "eq",
            "fun": lambda values: float(np.sum(values) - budget),
            "jac": lambda values: np.ones_like(values),
        }
    candidates: list[OptimizeResult] = []
    attempted: list[OptimizeResult] = []
    bounds = list(zip(lower, upper, strict=True))
    for start in starts:
        raw = np.asarray(start, dtype=float).copy()
        if _is_feasible(raw, lower, upper, budget):
            raw_objective = _objective(raw, curves, margin)
            if math.isfinite(raw_objective):
                candidates.append(
                    OptimizeResult(
                        x=raw,
                        fun=raw_objective,
                        success=True,
                        status=0,
                        nit=0,
                        message="Feasible deterministic start retained.",
                    )
                )
        result = minimize(
            _objective,
            start,
            args=(curves, margin),
            method="SLSQP",
            jac=_objective_gradient,
            bounds=bounds,
            constraints=() if constraint is None else (constraint,),
            options={"ftol": 1e-11, "maxiter": 2_000, "disp": False},
        )
        attempted.append(result)
        result_values = np.asarray(result.x, dtype=float)
        if result.success and _is_feasible(result_values, lower, upper, budget):
            try:
                if budget is None:
                    result_values = np.clip(result_values, lower, upper)
                else:
                    result_values = _project_to_budget(
                        result_values, lower, upper, budget
                    )
            except AllocationInfeasibleError:
                continue
            result_objective = _objective(result_values, curves, margin)
            if math.isfinite(result_objective):
                normalized_result = OptimizeResult(result)
                normalized_result.x = result_values
                normalized_result.fun = result_objective
                candidates.append(normalized_result)
    if not candidates:
        details = "; ".join(dict.fromkeys(str(result.message) for result in attempted))
        raise AllocationOptimizationError(
            "The optimizer did not return a feasible allocation. " + details
        )
    best = min(candidates, key=lambda item: float(item.fun))
    return best, len(starts)


def optimize_fixed_budget(
    plan: pd.DataFrame,
    total_budget: float,
    margin: float,
    base_response: float = 0.0,
) -> AllocationResult:
    """Reallocate an exact budget subject to channel min/max/fixed constraints."""

    normalized = validate_channel_plan(plan)
    budget = _finite_nonnegative(total_budget, "total_budget")
    margin_value = _finite_nonnegative(margin, "margin")
    base_value = _finite_nonnegative(base_response, "base_response")
    _validate_economic_scale(normalized, margin_value, base_value)
    lower, upper = _effective_bounds(normalized)
    lower_total = float(np.sum(lower))
    upper_total = float(np.sum(upper))
    tolerance = 1e-8 * max(1.0, budget, lower_total, upper_total)
    if budget < lower_total - tolerance or budget > upper_total + tolerance:
        raise AllocationInfeasibleError(
            f"Budget {budget:,.2f} is infeasible: constraints require a total between "
            f"{lower_total:,.2f} and {upper_total:,.2f}."
        )

    curves = _curves(normalized)
    if np.allclose(lower, upper, rtol=0, atol=tolerance):
        values = lower.copy()
        if not math.isclose(float(np.sum(values)), budget, rel_tol=0, abs_tol=tolerance):
            raise AllocationInfeasibleError(
                "All channels are fixed, but their spend does not equal the requested budget."
            )
        return _build_result(
            normalized,
            values,
            margin=margin_value,
            base_response=base_value,
            mode="fixed_budget",
            message="All channels were fixed; no reallocation was possible.",
            total_budget=budget,
            solver_status=0,
            solver_iterations=0,
        )

    starts = _fixed_budget_starts(
        normalized, lower, upper, budget, curves, margin_value
    )
    best, start_count = _best_slsqp(
        starts, lower, upper, curves, margin_value, budget
    )
    values = np.asarray(best.x, dtype=float)
    # Ensure display/export totals agree exactly with the budget after harmless
    # solver tolerance, without leaving the feasible region.
    values = _project_to_budget(values, lower, upper, budget)
    message = (
        f"Best feasible result from {start_count} deterministic SLSQP start(s). "
        "S-shaped curves can create local optima, so stress-test the recommendation."
    )
    return _build_result(
        normalized,
        values,
        margin=margin_value,
        base_response=base_value,
        mode="fixed_budget",
        message=message,
        total_budget=budget,
        solver_status=int(best.status),
        solver_iterations=int(getattr(best, "nit", 0)),
    )


def optimize_profit(
    plan: pd.DataFrame,
    margin: float,
    base_response: float = 0.0,
) -> AllocationResult:
    """Size spend to maximize modeled profit within channel bounds.

    Unlike fixed-budget reallocation, total spend may rise or fall.  For an
    interior optimum, marginal profit should be approximately zero: one more
    spend unit produces one unit of marginal contribution.
    """

    normalized = validate_channel_plan(plan)
    margin_value = _finite_nonnegative(margin, "margin")
    base_value = _finite_nonnegative(base_response, "base_response")
    _validate_economic_scale(normalized, margin_value, base_value)
    lower, upper = _effective_bounds(normalized)
    curves = _curves(normalized)
    if np.allclose(lower, upper, rtol=0, atol=1e-12):
        return _build_result(
            normalized,
            lower.copy(),
            margin=margin_value,
            base_response=base_value,
            mode="profit_sizing",
            message="All channels were fixed; total spend could not change.",
            total_budget=None,
            solver_status=0,
            solver_iterations=0,
        )

    current = normalized["current_spend"].to_numpy(dtype=float)
    grid_seed = _profit_grid_seed(lower, upper, curves, margin_value)
    starts = _unique_starts(
        [
            np.clip(current, lower, upper),
            lower.copy(),
            upper.copy(),
            (lower + upper) / 2.0,
            grid_seed,
        ]
    )
    best, start_count = _best_slsqp(
        starts, lower, upper, curves, margin_value, None
    )
    message = (
        f"Best feasible result from {start_count} deterministic SLSQP start(s), including "
        "a channel-wise grid seed. Total spend was free within the supplied bounds."
    )
    return _build_result(
        normalized,
        np.asarray(best.x, dtype=float),
        margin=margin_value,
        base_response=base_value,
        mode="profit_sizing",
        message=message,
        total_budget=None,
        solver_status=int(best.status),
        solver_iterations=int(getattr(best, "nit", 0)),
    )


DEFAULT_STRESS_SCENARIOS = pd.DataFrame(
    [
        {
            "scenario": "Downside",
            "response_multiplier": 0.85,
            "half_saturation_multiplier": 1.20,
            "margin_multiplier": 0.90,
        },
        {
            "scenario": "Base",
            "response_multiplier": 1.00,
            "half_saturation_multiplier": 1.00,
            "margin_multiplier": 1.00,
        },
        {
            "scenario": "Upside",
            "response_multiplier": 1.15,
            "half_saturation_multiplier": 0.85,
            "margin_multiplier": 1.10,
        },
    ]
)


def _validate_scenarios(scenarios: pd.DataFrame | None) -> pd.DataFrame:
    if scenarios is None:
        return DEFAULT_STRESS_SCENARIOS.copy()
    if not isinstance(scenarios, pd.DataFrame) or scenarios.empty:
        raise ChannelPlanError("scenarios must be a non-empty pandas DataFrame.")
    required = (
        "scenario",
        "response_multiplier",
        "half_saturation_multiplier",
        "margin_multiplier",
    )
    missing = [column for column in required if column not in scenarios.columns]
    if missing:
        raise ChannelPlanError("Scenario table is missing: " + ", ".join(missing) + ".")
    normalized = scenarios.loc[:, list(required)].copy()
    normalized["scenario"] = normalized["scenario"].astype("string").str.strip()
    if normalized["scenario"].isna().any() or normalized["scenario"].eq("").any():
        raise ChannelPlanError("Scenario names cannot be blank.")
    if normalized["scenario"].duplicated().any():
        raise ChannelPlanError("Scenario names must be unique.")
    for column in required[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        if (
            normalized[column].isna().any()
            or (~np.isfinite(normalized[column])).any()
            or (normalized[column] <= 0).any()
        ):
            raise ChannelPlanError(f"{column} must contain finite values greater than zero.")
    return normalized.reset_index(drop=True)


def stress_test_allocation(
    plan: pd.DataFrame,
    margin: float,
    base_response: float = 0.0,
    *,
    mode: str = "fixed_budget",
    total_budget: float | None = None,
    scenarios: pd.DataFrame | None = None,
) -> SensitivityResult:
    """Re-optimise deterministic downside/base/upside planning scenarios.

    ``response_multiplier`` scales each channel's response range above its
    floor; ``half_saturation_multiplier`` changes the spend needed to reach the
    midpoint; and ``margin_multiplier`` changes unit economics.  The output is
    a stress test of assumptions, not a probability interval.
    """

    normalized = validate_channel_plan(plan)
    margin_value = _finite_nonnegative(margin, "margin")
    base_value = _finite_nonnegative(base_response, "base_response")
    scenario_table = _validate_scenarios(scenarios)
    if mode not in {"fixed_budget", "profit_sizing"}:
        raise ChannelPlanError("mode must be 'fixed_budget' or 'profit_sizing'.")
    budget = total_budget
    if mode == "fixed_budget" and budget is None:
        budget = float(normalized["current_spend"].sum())

    summaries: list[dict[str, Any]] = []
    allocations: list[pd.DataFrame] = []
    for scenario in scenario_table.itertuples(index=False):
        scenario_plan = normalized.copy()
        response_range = (
            scenario_plan["ceiling_response"] - scenario_plan["floor_response"]
        )
        scenario_plan["ceiling_response"] = (
            scenario_plan["floor_response"]
            + response_range * float(scenario.response_multiplier)
        )
        scenario_plan["half_saturation"] *= float(scenario.half_saturation_multiplier)
        scenario_margin = margin_value * float(scenario.margin_multiplier)
        if mode == "fixed_budget":
            result = optimize_fixed_budget(
                scenario_plan,
                float(budget),
                scenario_margin,
                base_value,
            )
        else:
            result = optimize_profit(scenario_plan, scenario_margin, base_value)

        summary = result.summary_dict()
        summary.update(
            {
                "scenario": str(scenario.scenario),
                "response_multiplier": float(scenario.response_multiplier),
                "half_saturation_multiplier": float(
                    scenario.half_saturation_multiplier
                ),
                "margin_multiplier": float(scenario.margin_multiplier),
                "allocation_json": json.dumps(
                    dict(
                        zip(
                            result.table["channel"],
                            result.table["recommended_spend"].round(8),
                            strict=True,
                        )
                    ),
                    sort_keys=True,
                ),
            }
        )
        summaries.append(summary)
        channel_table = result.table.copy()
        channel_table.insert(0, "scenario", str(scenario.scenario))
        allocations.append(channel_table)

    preferred = [
        "scenario",
        "response_multiplier",
        "half_saturation_multiplier",
        "margin_multiplier",
        "success",
        "total_spend",
        "total_response",
        "gross_contribution",
        "profit",
        "incremental_profit_vs_baseline",
        "allocation_json",
        "message",
    ]
    summary_frame = pd.DataFrame(summaries)
    summary_frame = summary_frame.loc[:, preferred + [c for c in summary_frame if c not in preferred]]
    allocation_frame = pd.concat(allocations, ignore_index=True)
    return SensitivityResult(summary=summary_frame, allocations=allocation_frame)


# Friendly plural alias for callers that think in scenario sets.
stress_test_allocations = stress_test_allocation


__all__ = [
    "AllocationInfeasibleError",
    "AllocationOptimizationError",
    "AllocationResult",
    "ChannelPlanError",
    "DEFAULT_ASSUMPTIONS",
    "DEFAULT_STRESS_SCENARIOS",
    "INDEPENDENCE_ASSUMPTION",
    "REQUIRED_PLAN_COLUMNS",
    "SensitivityResult",
    "evaluate_allocation",
    "optimize_fixed_budget",
    "optimize_profit",
    "stress_test_allocation",
    "stress_test_allocations",
    "validate_channel_plan",
]
