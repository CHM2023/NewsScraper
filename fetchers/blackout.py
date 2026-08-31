"""Pure blackout windows: the minutes around a release when spreads blow out.

A weight 4 or 5 release moves XAU/USD violently for a few minutes either side of
the print, and the initial move frequently reverses. The platform informs rather
than trades, so this is presented, not enforced: the "today" page shows whether
the trader is currently inside a window, and which event caused it.

The windows are deliberately asymmetric. Liquidity thins out well before a
release as market makers step back, and the worst of the whipsaw is over sooner
than that afterwards - so the default is 30 minutes before and 15 after.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from common.timeutil import ensure_aware

BEFORE_MINUTES = 30
AFTER_MINUTES = 15
MIN_WEIGHT = 4


@dataclass(frozen=True)
class Window:
    """A period to stay out of, and the event responsible for it."""

    start: datetime
    end: datetime
    event_id: str
    title: str
    weight: int
    ts_utc: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= ensure_aware(moment, field="moment") <= self.end

    def minutes_until_start(self, moment: datetime) -> float:
        return (self.start - ensure_aware(moment, field="moment")).total_seconds() / 60.0


def blackout_windows(
    events: Sequence[dict],
    *,
    before_minutes: int = BEFORE_MINUTES,
    after_minutes: int = AFTER_MINUTES,
    min_weight: int = MIN_WEIGHT,
) -> list[Window]:
    """One window per qualifying event, ordered by start time.

    Events below ``min_weight`` produce no window: a weekly jobless claims print
    is not a reason to stand aside, and treating it as one would make the
    indicator meaningless through constant firing.
    """
    windows: list[Window] = []
    for event in events:
        weight = int(event.get("weight") or 0)
        if weight < min_weight:
            continue
        ts = event.get("ts_utc")
        if ts is None:
            continue
        ts = ensure_aware(ts, field="events.ts_utc")
        windows.append(
            Window(
                start=ts - timedelta(minutes=before_minutes),
                end=ts + timedelta(minutes=after_minutes),
                event_id=event.get("id", ""),
                title=event.get("title", ""),
                weight=weight,
                ts_utc=ts,
            )
        )
    return sorted(windows, key=lambda w: w.start)


def active_window(
    moment: datetime,
    events: Sequence[dict],
    **kwargs,
) -> Window | None:
    """The window ``moment`` falls inside, or None.

    When several releases land together - the 08:30 employment trio, or an FOMC
    statement and its press conference - the highest-weighted one is reported,
    because that is the event the trader is actually standing aside for.
    """
    ensure_aware(moment, field="moment")
    inside = [w for w in blackout_windows(events, **kwargs) if w.contains(moment)]
    if not inside:
        return None
    return max(inside, key=lambda w: (w.weight, -w.start.timestamp()))


def is_in_blackout(moment: datetime, events: Sequence[dict], **kwargs) -> bool:
    """Whether ``moment`` is inside any window."""
    return active_window(moment, events, **kwargs) is not None


def next_window(
    moment: datetime,
    events: Sequence[dict],
    **kwargs,
) -> Window | None:
    """The next window that has not started yet, or None."""
    ensure_aware(moment, field="moment")
    upcoming = [w for w in blackout_windows(events, **kwargs) if w.start > moment]
    return upcoming[0] if upcoming else None


def merge_windows(windows: Iterable[Window]) -> list[tuple[datetime, datetime]]:
    """Collapse overlapping windows into plain (start, end) spans.

    Used for drawing: the 08:30 employment releases produce three identical
    windows that should appear as one band, not three stacked ones.
    """
    ordered = sorted(windows, key=lambda w: w.start)
    merged: list[tuple[datetime, datetime]] = []
    for window in ordered:
        if merged and window.start <= merged[-1][1]:
            start, end = merged[-1]
            merged[-1] = (start, max(end, window.end))
        else:
            merged.append((window.start, window.end))
    return merged
