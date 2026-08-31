"""Pure Fed regime classification: hiking, holding or cutting.

Rule 2 of the concept doc's "three rules that make the results honest": gold's
reaction to the same news has flipped over the decade. In 2022 a hot CPI meant
faster hikes and gold fell; in other years the same print meant inflation fear
and gold rose. Every event is tagged with the regime it landed in so Stage 3 can
condition on it, and so the UI can offer the filter. Without this the event study
gives confidently wrong answers.

The regime is read off the Fed funds rate's direction over the preceding 90
days. The threshold is 0.125 - half a standard 25bp move - so that the noise in
the effective rate around a quarter end does not read as a policy change, while
a single genuine cut or hike does.
"""

from __future__ import annotations

from datetime import date, timedelta

HIKING = "hiking"
HOLDING = "holding"
CUTTING = "cutting"
REGIMES = (HIKING, HOLDING, CUTTING)

WINDOW_DAYS = 90
THRESHOLD = 0.125


def _value_asof(series: list[tuple[date, float]], asof: date) -> float | None:
    """The most recent observation on or before ``asof``.

    The series is daily but has gaps at weekends and holidays, so an exact date
    match would fail roughly three days in seven.
    """
    latest: float | None = None
    for day, value in series:
        if day <= asof:
            latest = value
        else:
            break
    return latest


def classify_regime(
    series: list[tuple[date, float]],
    asof: date,
    *,
    window_days: int = WINDOW_DAYS,
    threshold: float = THRESHOLD,
) -> str | None:
    """Classify the policy regime at ``asof`` from a Fed funds series.

    ``series`` is ``(date, rate)`` pairs, oldest first. Returns None - not
    "holding" - when there is not enough history either side of the window, so a
    thin backfill cannot mislabel a decade of events as a flat rate environment.
    """
    if not series:
        return None

    ordered = sorted(series)
    now = _value_asof(ordered, asof)
    then = _value_asof(ordered, asof - timedelta(days=window_days))
    if now is None or then is None:
        return None

    change = now - then
    if change > threshold:
        return HIKING
    if change < -threshold:
        return CUTTING
    return HOLDING
