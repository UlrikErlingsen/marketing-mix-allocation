"""Saturating marketing-response curves used by AllocSignal.

The implementation follows the ADBUDG/Hill form used in marketing-science
resource-allocation work::

    response(x) = b + (a - b) * x**c / (d + x**c)

AllocSignal exposes ``half_saturation`` rather than ``d`` because it is easier to
elicit and explain.  The two parameterisations are identical when
``d = half_saturation**c``.  At the half-saturation spend, response is exactly
the midpoint between the floor and ceiling.

All functions are deterministic and accept either a scalar spend or a one-
dimensional array.  Response is a level (for example, sales units), marginal
response is response units per one spend unit, and elasticity is the point
elasticity of that response level with respect to spend.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import warnings
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.special import expit


class ResponseCurveError(ValueError):
    """Raised when response-curve inputs are not economically meaningful."""


class CurveCalibrationError(ResponseCurveError):
    """Raised when anchor observations cannot identify a useful curve."""


def _finite_number(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ResponseCurveError(f"{name} must be a number.") from exc
    if not math.isfinite(number):
        raise ResponseCurveError(f"{name} must be finite.")
    return number


def _validate_parameters(
    floor: float,
    ceiling: float,
    half_saturation: float,
    shape: float,
) -> tuple[float, float, float, float]:
    floor_value = _finite_number(floor, "floor")
    ceiling_value = _finite_number(ceiling, "ceiling")
    half_value = _finite_number(half_saturation, "half_saturation")
    shape_value = _finite_number(shape, "shape")
    if floor_value < 0:
        raise ResponseCurveError("floor must be zero or positive.")
    if ceiling_value < floor_value:
        raise ResponseCurveError("ceiling must be greater than or equal to floor.")
    if half_value <= 0:
        raise ResponseCurveError("half_saturation must be greater than zero.")
    if shape_value <= 0:
        raise ResponseCurveError("shape must be greater than zero.")
    return floor_value, ceiling_value, half_value, shape_value


def _spend_array(spend: float | Iterable[float] | np.ndarray) -> tuple[np.ndarray, bool]:
    scalar = np.isscalar(spend)
    try:
        values = np.asarray(spend, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ResponseCurveError("spend must contain only numbers.") from exc
    if values.ndim > 1:
        raise ResponseCurveError("spend must be a scalar or one-dimensional array.")
    if not np.all(np.isfinite(values)):
        raise ResponseCurveError("spend must contain only finite values.")
    if np.any(values < 0):
        raise ResponseCurveError("spend cannot be negative.")
    return values, scalar


def _return_scalar_if_needed(values: np.ndarray, scalar: bool) -> float | np.ndarray:
    if scalar:
        return float(np.asarray(values))
    return values


def adbudg_response(
    spend: float | Iterable[float] | np.ndarray,
    floor: float,
    ceiling: float,
    half_saturation: float,
    shape: float,
) -> float | np.ndarray:
    """Return the ADBUDG/Hill response level at ``spend``.

    ``floor`` is the response at zero spend, ``ceiling`` is the asymptote,
    ``half_saturation`` is the spend at the response midpoint, and ``shape``
    controls curvature.  A shape above one creates an S-curve; a shape at or
    below one creates a concave response curve.
    """

    floor_value, ceiling_value, half_value, shape_value = _validate_parameters(
        floor, ceiling, half_saturation, shape
    )
    values, scalar = _spend_array(spend)
    share = np.zeros_like(values, dtype=float)
    positive = values > 0
    if np.any(positive):
        # expit(c * log(x / h)) equals x**c / (h**c + x**c), while
        # avoiding overflow for unusually large spend or shape values.
        log_ratio = np.log(values[positive]) - math.log(half_value)
        share[positive] = expit(shape_value * log_ratio)
    response = floor_value + (ceiling_value - floor_value) * share
    return _return_scalar_if_needed(response, scalar)


def marginal_response(
    spend: float | Iterable[float] | np.ndarray,
    floor: float,
    ceiling: float,
    half_saturation: float,
    shape: float,
) -> float | np.ndarray:
    """Return the analytic derivative ``d response / d spend``.

    At zero spend the right-hand derivative is zero when ``shape > 1``,
    ``(ceiling - floor) / half_saturation`` when ``shape == 1``, and positive
    infinity when ``0 < shape < 1``.  The infinity is a mathematical property
    of the Hill curve rather than a numerical error; practical models should
    not interpret it as literally infinite media productivity.
    """

    floor_value, ceiling_value, half_value, shape_value = _validate_parameters(
        floor, ceiling, half_saturation, shape
    )
    values, scalar = _spend_array(spend)
    delta = ceiling_value - floor_value
    derivative = np.zeros_like(values, dtype=float)

    if delta > 0:
        positive = values > 0
        if np.any(positive):
            log_ratio = np.log(values[positive]) - math.log(half_value)
            # delta*c/h * r**(c-1) / (1+r**c)**2, evaluated in log
            # space for stable tails.
            log_derivative = (
                math.log(delta * shape_value / half_value)
                + (shape_value - 1.0) * log_ratio
                - 2.0 * np.logaddexp(0.0, shape_value * log_ratio)
            )
            with np.errstate(over="ignore", under="ignore"):
                derivative[positive] = np.exp(log_derivative)

        at_zero = values == 0
        if np.any(at_zero):
            if math.isclose(shape_value, 1.0, rel_tol=1e-12, abs_tol=1e-12):
                derivative[at_zero] = delta / half_value
            elif shape_value < 1.0:
                derivative[at_zero] = np.inf
            else:
                derivative[at_zero] = 0.0

    return _return_scalar_if_needed(derivative, scalar)


def response_elasticity(
    spend: float | Iterable[float] | np.ndarray,
    floor: float,
    ceiling: float,
    half_saturation: float,
    shape: float,
) -> float | np.ndarray:
    """Return point elasticity ``(dY/dX) * X / Y``.

    Elasticity is undefined when the response level is zero and is returned as
    ``NaN``.  At zero spend with a positive floor it is zero.
    """

    values, scalar = _spend_array(spend)
    response = np.asarray(
        adbudg_response(values, floor, ceiling, half_saturation, shape), dtype=float
    )
    derivative = np.asarray(
        marginal_response(values, floor, ceiling, half_saturation, shape), dtype=float
    )
    elasticity = np.full_like(response, np.nan, dtype=float)
    positive_response = response != 0
    at_zero = values == 0
    elasticity[positive_response & at_zero] = 0.0
    calculable = positive_response & ~at_zero
    with np.errstate(invalid="ignore", over="ignore"):
        elasticity[calculable] = (
            derivative[calculable] * values[calculable] / response[calculable]
        )
    return _return_scalar_if_needed(elasticity, scalar)


def gross_contribution(response: float | Iterable[float], margin: float) -> float | np.ndarray:
    """Return response multiplied by unit contribution margin."""

    margin_value = _finite_number(margin, "margin")
    if margin_value < 0:
        raise ResponseCurveError("margin must be zero or positive.")
    try:
        values = np.asarray(response, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ResponseCurveError("response must contain only numbers.") from exc
    if not np.all(np.isfinite(values)):
        raise ResponseCurveError("response must contain only finite values.")
    result = values * margin_value
    return _return_scalar_if_needed(result, np.isscalar(response))


def net_contribution(
    response: float | Iterable[float],
    spend: float | Iterable[float],
    margin: float,
) -> float | np.ndarray:
    """Return contribution after marketing cost: ``response * margin - spend``."""

    contribution = np.asarray(gross_contribution(response, margin), dtype=float)
    try:
        spend_values = np.asarray(spend, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ResponseCurveError("spend must contain only numbers.") from exc
    if not np.all(np.isfinite(spend_values)) or np.any(spend_values < 0):
        raise ResponseCurveError("spend must contain finite, non-negative values.")
    try:
        result = contribution - spend_values
    except ValueError as exc:
        raise ResponseCurveError("response and spend must have compatible shapes.") from exc
    return _return_scalar_if_needed(result, np.isscalar(response) and np.isscalar(spend))


@dataclass(frozen=True)
class ResponseCurve:
    """Validated ADBUDG/Hill curve with an interpretable parameterisation."""

    floor: float
    ceiling: float
    half_saturation: float
    shape: float

    def __post_init__(self) -> None:
        values = _validate_parameters(
            self.floor, self.ceiling, self.half_saturation, self.shape
        )
        object.__setattr__(self, "floor", values[0])
        object.__setattr__(self, "ceiling", values[1])
        object.__setattr__(self, "half_saturation", values[2])
        object.__setattr__(self, "shape", values[3])

    @property
    def d(self) -> float:
        """Return the equivalent classic ADBUDG scale parameter ``d``."""

        try:
            return float(self.half_saturation**self.shape)
        except OverflowError:
            return math.inf

    def response(self, spend: float | Iterable[float]) -> float | np.ndarray:
        return adbudg_response(
            spend, self.floor, self.ceiling, self.half_saturation, self.shape
        )

    def marginal_response(self, spend: float | Iterable[float]) -> float | np.ndarray:
        return marginal_response(
            spend, self.floor, self.ceiling, self.half_saturation, self.shape
        )

    def elasticity(self, spend: float | Iterable[float]) -> float | np.ndarray:
        return response_elasticity(
            spend, self.floor, self.ceiling, self.half_saturation, self.shape
        )

    def profit(
        self,
        spend: float | Iterable[float],
        margin: float,
    ) -> float | np.ndarray:
        return net_contribution(self.response(spend), spend, margin)

    def as_dict(self) -> dict[str, float]:
        return {
            "floor": self.floor,
            "ceiling": self.ceiling,
            "half_saturation": self.half_saturation,
            "shape": self.shape,
            "d": self.d,
        }


@dataclass(frozen=True)
class CalibrationResult:
    """Curve fit and diagnostics from observed spend-response anchors."""

    curve: ResponseCurve
    rmse: float
    r_squared: float
    n_observations: int
    fitted: pd.DataFrame
    covariance: np.ndarray
    standard_errors: dict[str, float]
    warnings: tuple[str, ...]
    success: bool = True

    def parameter_table(self) -> pd.DataFrame:
        values = self.curve.as_dict()
        values.pop("d")
        return pd.DataFrame(
            {
                "parameter": list(values),
                "estimate": list(values.values()),
                "standard_error": [self.standard_errors.get(name, np.nan) for name in values],
            }
        )


def calibrate_curve(
    spend: Iterable[float],
    observed_response: Iterable[float],
    *,
    max_shape: float = 10.0,
) -> CalibrationResult:
    """Fit a response curve to at least four distinct spend anchors.

    This is an aid to judgmental calibration, not a causal estimator.  Four
    points identify four parameters exactly but leave no residual degrees of
    freedom for reliable parameter uncertainty; additional observations are
    strongly preferable.
    """

    try:
        x = np.asarray(list(spend), dtype=float)
        y = np.asarray(list(observed_response), dtype=float)
    except (TypeError, ValueError) as exc:
        raise CurveCalibrationError("Anchor spends and responses must be numeric.") from exc
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise CurveCalibrationError("Anchor spends and responses must be equal-length vectors.")
    if len(x) < 4 or len(np.unique(x)) < 4:
        raise CurveCalibrationError(
            "At least four observations at distinct spend levels are required to fit "
            "floor, ceiling, half-saturation and shape."
        )
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise CurveCalibrationError("Anchor spends and responses must be finite.")
    if np.any(x < 0) or np.any(y < 0):
        raise CurveCalibrationError("Anchor spends and responses cannot be negative.")
    if float(np.ptp(y)) <= np.finfo(float).eps:
        raise CurveCalibrationError("Responses must vary across anchors to identify a curve.")
    max_shape_value = _finite_number(max_shape, "max_shape")
    if max_shape_value <= 0.1:
        raise CurveCalibrationError("max_shape must be greater than 0.1.")

    order = np.argsort(x)
    x = x[order]
    y = y[order]
    max_x = float(np.max(x))
    max_y = float(np.max(y))
    y_scale = max(max_y, 1.0)
    positive_x = x[x > 0]
    if len(positive_x) == 0:
        raise CurveCalibrationError("At least one anchor must have positive spend.")

    floor_initial = max(float(y[np.argmin(x)]), 0.0)
    delta_initial = max(max_y - floor_initial, 0.1 * y_scale)
    midpoint = floor_initial + delta_initial / 2.0
    half_initial = float(x[np.argmin(np.abs(y - midpoint))])
    if half_initial <= 0:
        half_initial = float(np.median(positive_x))
    half_initial = max(half_initial, max_x * 1e-5, 1e-6)

    epsilon_y = max(y_scale * 1e-10, 1e-10)
    half_lower = max(max_x * 1e-8, 1e-8)
    half_upper = max(max_x * 100.0, half_lower * 100.0)
    floor_upper = max(max_y * 2.0 + 1.0, 1.0)
    delta_upper = max(y_scale * 100.0, 1.0)

    def calibration_function(
        values: np.ndarray,
        floor_parameter: float,
        delta_parameter: float,
        half_parameter: float,
        shape_parameter: float,
    ) -> np.ndarray:
        positive = values > 0
        share = np.zeros_like(values, dtype=float)
        if np.any(positive):
            share[positive] = expit(
                shape_parameter
                * (np.log(values[positive]) - math.log(half_parameter))
            )
        return floor_parameter + delta_parameter * share

    warning_messages: list[str] = []
    if len(x) == 4:
        warning_messages.append(
            "Four anchors leave no residual degrees of freedom; treat parameter uncertainty "
            "as unidentified and run scenario sensitivity."
        )
    if np.any(np.diff(y) < 0):
        warning_messages.append(
            "Observed response is not monotonic in spend; a monotonic Hill curve will smooth "
            "over those reversals."
        )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", OptimizeWarning)
        try:
            parameters, covariance_raw = curve_fit(
                calibration_function,
                x,
                y,
                p0=[floor_initial, delta_initial, half_initial, 1.2],
                bounds=(
                    [0.0, epsilon_y, half_lower, 0.1],
                    [floor_upper, delta_upper, half_upper, max_shape_value],
                ),
                maxfev=100_000,
            )
        except (RuntimeError, ValueError, FloatingPointError) as exc:
            raise CurveCalibrationError(
                "The anchors did not yield a stable response curve. Check their scale, add "
                "more spend levels, or enter curve parameters directly."
            ) from exc
        warning_messages.extend(str(item.message) for item in caught)

    floor_fit, delta_fit, half_fit, shape_fit = (float(value) for value in parameters)
    curve = ResponseCurve(floor_fit, floor_fit + delta_fit, half_fit, shape_fit)
    fitted_values = np.asarray(curve.response(x), dtype=float)
    residuals = y - fitted_values
    rmse = float(np.sqrt(np.mean(np.square(residuals))))
    total_sum_squares = float(np.sum(np.square(y - np.mean(y))))
    r_squared = (
        float(1.0 - np.sum(np.square(residuals)) / total_sum_squares)
        if total_sum_squares > 0
        else math.nan
    )

    # curve_fit estimates covariance for [floor, delta, half, shape]. Transform
    # it to [floor, ceiling=floor+delta, half, shape] via the delta method.
    covariance_raw = np.asarray(covariance_raw, dtype=float)
    transform = np.array(
        [[1.0, 0.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    )
    if covariance_raw.shape == (4, 4) and np.all(np.isfinite(covariance_raw)):
        covariance = transform @ covariance_raw @ transform.T
        standard_error_values = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    else:
        covariance = np.full((4, 4), np.nan)
        standard_error_values = np.full(4, np.nan)
        warning_messages.append(
            "Parameter standard errors could not be estimated from these anchors."
        )

    fitted_frame = pd.DataFrame(
        {
            "spend": x,
            "observed_response": y,
            "fitted_response": fitted_values,
            "residual": residuals,
        }
    )
    standard_errors = dict(
        zip(
            ("floor", "ceiling", "half_saturation", "shape"),
            (float(value) for value in standard_error_values),
            strict=True,
        )
    )
    return CalibrationResult(
        curve=curve,
        rmse=rmse,
        r_squared=r_squared,
        n_observations=len(x),
        fitted=fitted_frame,
        covariance=covariance,
        standard_errors=standard_errors,
        warnings=tuple(dict.fromkeys(warning_messages)),
    )


def calibrate_from_anchors(
    *,
    zero_response: float,
    current_spend: float,
    current_response: float,
    increased_spend: float,
    increased_response: float,
    saturation_spend: float,
    saturation_response: float,
    max_shape: float = 10.0,
) -> CalibrationResult:
    """Fit a curve from named zero/current/increased/saturation anchors."""

    spends = [0.0, current_spend, increased_spend, saturation_spend]
    responses = [
        zero_response,
        current_response,
        increased_response,
        saturation_response,
    ]
    if not (0 < float(current_spend) < float(increased_spend) < float(saturation_spend)):
        raise CurveCalibrationError(
            "Anchor spends must be ordered: 0 < current < increased < saturation."
        )
    return calibrate_curve(spends, responses, max_shape=max_shape)


__all__ = [
    "CalibrationResult",
    "CurveCalibrationError",
    "ResponseCurve",
    "ResponseCurveError",
    "adbudg_response",
    "calibrate_curve",
    "calibrate_from_anchors",
    "gross_contribution",
    "marginal_response",
    "net_contribution",
    "response_elasticity",
]
