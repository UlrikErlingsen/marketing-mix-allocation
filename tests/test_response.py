from __future__ import annotations

import math

import numpy as np
import pytest

from allocsignal.response import (
    CurveCalibrationError,
    ResponseCurve,
    ResponseCurveError,
    adbudg_response,
    calibrate_curve,
    calibrate_from_anchors,
    gross_contribution,
    marginal_response,
    net_contribution,
    response_elasticity,
)


def test_adbudg_matches_classic_parameterization() -> None:
    spend = np.array([0.0, 5.0, 20.0, 100.0])
    floor, ceiling, half_saturation, shape = 12.0, 150.0, 20.0, 1.7
    d = half_saturation**shape
    expected = floor + (ceiling - floor) * spend**shape / (d + spend**shape)

    actual = adbudg_response(spend, floor, ceiling, half_saturation, shape)

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)


def test_half_saturation_is_response_midpoint() -> None:
    curve = ResponseCurve(floor=20, ceiling=180, half_saturation=50, shape=2.4)

    assert curve.response(50) == pytest.approx(100)
    assert curve.response(0) == pytest.approx(20)
    assert curve.response(1e12) == pytest.approx(180, rel=1e-9)


@pytest.mark.parametrize("shape", [0.65, 1.0, 1.8, 3.0])
def test_analytic_derivative_matches_central_difference(shape: float) -> None:
    spend = 37.0
    step = 1e-4
    curve = ResponseCurve(5, 240, 42, shape)
    numerical = (curve.response(spend + step) - curve.response(spend - step)) / (2 * step)

    assert curve.marginal_response(spend) == pytest.approx(numerical, rel=2e-7)


def test_zero_spend_derivative_is_mathematically_explicit() -> None:
    assert marginal_response(0, 0, 100, 20, 2) == 0
    assert marginal_response(0, 0, 100, 20, 1) == pytest.approx(5)
    assert math.isinf(marginal_response(0, 0, 100, 20, 0.5))
    assert marginal_response(0, 10, 10, 20, 0.5) == 0


def test_elasticity_definition_and_zero_level_behavior() -> None:
    curve = ResponseCurve(10, 100, 20, 1.5)
    spend = 30.0
    expected = curve.marginal_response(spend) * spend / curve.response(spend)

    assert curve.elasticity(spend) == pytest.approx(expected)
    assert curve.elasticity(0) == 0
    assert math.isnan(response_elasticity(0, 0, 100, 20, 1.5))


def test_contribution_helpers_use_profit_definition() -> None:
    response = np.array([100.0, 140.0])
    spend = np.array([20.0, 50.0])

    np.testing.assert_allclose(gross_contribution(response, 2.5), [250, 350])
    np.testing.assert_allclose(net_contribution(response, spend, 2.5), [230, 300])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"floor": -1, "ceiling": 10, "half_saturation": 2, "shape": 1}, "floor"),
        ({"floor": 10, "ceiling": 9, "half_saturation": 2, "shape": 1}, "ceiling"),
        ({"floor": 0, "ceiling": 10, "half_saturation": 0, "shape": 1}, "half"),
        ({"floor": 0, "ceiling": 10, "half_saturation": 2, "shape": 0}, "shape"),
    ],
)
def test_curve_validation_is_helpful(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ResponseCurveError, match=message):
        ResponseCurve(**kwargs)


def test_spend_validation_rejects_negative_or_non_finite() -> None:
    curve = ResponseCurve(0, 100, 20, 1)
    with pytest.raises(ResponseCurveError, match="negative"):
        curve.response(-1)
    with pytest.raises(ResponseCurveError, match="finite"):
        curve.response(np.inf)


def test_calibration_recovers_synthetic_curve() -> None:
    expected = ResponseCurve(8, 240, 55, 1.65)
    spend = np.array([0, 8, 20, 40, 65, 110, 220, 400], dtype=float)
    observed = expected.response(spend)

    result = calibrate_curve(spend, observed)

    assert result.success
    assert result.rmse < 1e-5
    assert result.r_squared == pytest.approx(1.0, abs=1e-10)
    assert result.curve.floor == pytest.approx(expected.floor, rel=1e-4)
    assert result.curve.ceiling == pytest.approx(expected.ceiling, rel=1e-4)
    assert result.curve.half_saturation == pytest.approx(expected.half_saturation, rel=1e-4)
    assert result.curve.shape == pytest.approx(expected.shape, rel=1e-4)
    assert list(result.fitted.columns) == [
        "spend",
        "observed_response",
        "fitted_response",
        "residual",
    ]


def test_four_named_anchors_warn_about_unidentified_uncertainty() -> None:
    result = calibrate_from_anchors(
        zero_response=5,
        current_spend=20,
        current_response=45,
        increased_spend=50,
        increased_response=95,
        saturation_spend=200,
        saturation_response=130,
    )

    assert result.n_observations == 4
    assert any("no residual degrees of freedom" in warning for warning in result.warnings)


def test_calibration_requires_enough_distinct_information() -> None:
    with pytest.raises(CurveCalibrationError, match="four observations"):
        calibrate_curve([0, 10, 20], [0, 5, 9])
    with pytest.raises(CurveCalibrationError, match="must vary"):
        calibrate_curve([0, 10, 20, 30], [5, 5, 5, 5])

