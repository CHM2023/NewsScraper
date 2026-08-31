"""Pure surprise score: how far a release landed from what was expected.

    surprise = clamp((actual - forecast) / |forecast| * 10, -3, +3)

The concept doc's central point is that direction and surprise are different
things. CPI rising when everyone expected it to rise moves gold very little; the
same print against a forecast of zero change moves it a lot. Stage 3 conditions
on this number, so it is stored on every event that has both figures.

The x10 factor turns the typical relative miss on a macro release - a few
percent - into something that spans the -3..+3 band rather than clustering
around zero. It is a display scaling, not a statistical claim.
"""

from __future__ import annotations

SCALE = 10.0
LIMIT = 3.0


def clamp(value: float, low: float = -LIMIT, high: float = LIMIT) -> float:
    """Constrain a value to the band, so one freak print cannot dominate."""
    return max(low, min(high, value))


def compute_surprise(actual: float | None, forecast: float | None) -> float | None:
    """The clamped surprise score, or None when it cannot be computed.

    None is returned - never a fabricated zero - when either figure is missing,
    which is the brief's rule, and also when the forecast is exactly zero. A
    zero forecast makes the relative miss undefined: a 0.1 actual against a 0.0
    forecast is an infinite relative surprise, and quietly substituting some
    absolute measure would put a number on the same scale as the others that
    does not mean the same thing. Better to leave it null and show "n/a".
    """
    if actual is None or forecast is None:
        return None
    if forecast == 0:
        return None
    return clamp((float(actual) - float(forecast)) / abs(float(forecast)) * SCALE)


def describe(surprise: float | None) -> str:
    """A short label for the UI: above / in line with / below forecast."""
    if surprise is None:
        return "n/a"
    if surprise >= 0.5:
        return "above forecast"
    if surprise <= -0.5:
        return "below forecast"
    return "in line"
