"""Friendly domain errors for the AllocSignal workflow."""

from __future__ import annotations


class DataProblem(ValueError):
    """An expected, user-fixable problem with data or analysis setup."""


def friendly_message(exc: Exception) -> str:
    """Return a useful public message without exposing implementation details."""
    if isinstance(exc, (DataProblem, ValueError)):
        return str(exc)
    return "AllocSignal could not finish that step. Check the data and assumptions, then try again."

