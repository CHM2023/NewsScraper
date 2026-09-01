"""Pure view models: database rows in, template-ready dicts out.

Keeping this separate from web/app.py means the display rules - which colour a
weight gets, how a missing forecast reads, what FullCalendar is handed - can be
tested without starting a server or touching Supabase.

One rule runs through all of it: **no local time is ever produced here.** Every
timestamp leaves as an ISO-8601 UTC string in ``ts_utc``, which the template
puts in a ``data-utc`` attribute for web/static/js/tz.js to convert in the
browser. The concept doc calls a daylight-saving mistake the bug that would
"silently break the blackout and reminder logic"; the defence is that the server
has no opinion about the viewer's timezone at all.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from common.timeutil import UTC, iso_utc, parse_iso
from fetchers.surprise import describe as describe_surprise

# Concept doc 3.3: red 5, orange 4, grey 3 and below.
WEIGHT_COLOURS: dict[int, str] = {5: "#c0392b", 4: "#e67e22"}
LOW_WEIGHT_COLOUR = "#7f8c8d"

WEIGHT_LABELS: dict[int, str] = {
    5: "Highest impact on gold",
    4: "High impact on gold",
    3: "Moderate",
    2: "Background",
    1: "Background",
}


def weight_colour(weight: int | None) -> str:
    """The calendar colour for a weight."""
    return WEIGHT_COLOURS.get(int(weight or 0), LOW_WEIGHT_COLOUR)


def weight_class(weight: int | None) -> str:
    """CSS class for the weight badge: ``w5``, ``w4`` or ``w-low``."""
    value = int(weight or 0)
    return f"w{value}" if value >= 4 else "w-low"


def format_number(value: Any, *, unit: str = "") -> str:
    """Render a stored float the way the feed would have shown it.

    Missing values read "n/a" rather than "0" or an empty cell, so that a
    forecast that was never published cannot be mistaken for a forecast of zero.
    """
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if abs(number) >= 1_000_000_000:
        rendered = f"{number / 1_000_000_000:.2f}B"
    elif abs(number) >= 1_000_000:
        rendered = f"{number / 1_000_000:.2f}M"
    elif abs(number) >= 10_000:
        rendered = f"{number / 1_000:.0f}K"
    elif number == int(number):
        rendered = str(int(number))
    else:
        # A computed actual carries the full precision of the index arithmetic -
        # a CPI m/m arrives as 0.0736691443554482. The database keeps that, since
        # Stage 3 will do sums on it, but the trader is reading a figure the BLS
        # published as 0.1: rounding here is the difference between a number and
        # a wall of noise. Values below 0.01 keep more places rather than
        # collapsing to "0".
        places = 2 if abs(number) >= 0.01 else 4
        rendered = f"{number:.{places}f}".rstrip("0").rstrip(".")
        if rendered in ("", "-", "-0"):
            rendered = "0"
    return f"{rendered}{unit}"


def format_surprise(value: Any) -> str:
    """The surprise score with its label, e.g. ``+1.2 (above forecast)``."""
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:+.1f} ({describe_surprise(number)})"


def surprise_class(value: Any) -> str:
    """CSS class driving the red/green tint on a surprise cell."""
    if value is None:
        return "s-none"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "s-none"
    if number >= 0.5:
        return "s-up"
    if number <= -0.5:
        return "s-down"
    return "s-flat"


def event_view(row: dict) -> dict:
    """One event as the templates want it."""
    ts = row.get("ts_utc")
    ts = ts if isinstance(ts, datetime) else parse_iso(ts, field="events.ts_utc")
    weight = int(row.get("weight") or 1)
    surprise = row.get("surprise")

    return {
        "id": row.get("id", ""),
        "title": row.get("title", ""),
        "country": row.get("country", "USD"),
        # The only representation of time the server emits.
        "ts_utc": iso_utc(ts, field="events.ts_utc"),
        "weight": weight,
        "weight_class": weight_class(weight),
        "weight_colour": weight_colour(weight),
        "weight_label": WEIGHT_LABELS.get(weight, "Background"),
        "impact": row.get("impact") or "-",
        "forecast": format_number(row.get("forecast")),
        "previous": format_number(row.get("previous")),
        "actual": format_number(row.get("actual")),
        "surprise": format_surprise(surprise),
        "surprise_class": surprise_class(surprise),
        "regime": row.get("regime") or "unknown",
        "source": row.get("source") or "skeleton",
        "has_actual": row.get("actual") is not None,
    }


def event_views(rows: Iterable[dict]) -> list[dict]:
    return [event_view(row) for row in rows]


def calendar_event(row: dict) -> dict:
    """One event in the shape FullCalendar's JSON feed expects."""
    view = event_view(row)
    return {
        "id": view["id"],
        "title": view["title"],
        # FullCalendar is configured with timeZone 'UTC', so it renders this
        # instant unchanged rather than shifting it into the browser's zone.
        "start": view["ts_utc"],
        "backgroundColor": view["weight_colour"],
        "borderColor": view["weight_colour"],
        "extendedProps": {
            "weight": view["weight"],
            "forecast": view["forecast"],
            "previous": view["previous"],
            "actual": view["actual"],
            "surprise": view["surprise"],
            "regime": view["regime"],
        },
    }


def calendar_events(rows: Iterable[dict]) -> list[dict]:
    return [calendar_event(row) for row in rows]


def parse_range_param(value: str, *, field: str) -> datetime:
    """Parse a ``start``/``end`` query parameter from the calendar.

    FullCalendar sends either a bare ``YYYY-MM-DD`` or a full ISO timestamp,
    depending on the view. A bare date is taken as midnight UTC - the server
    still refuses to guess a local zone.
    """
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=UTC)
    except ValueError:
        return parse_iso(text, field=field)


def blackout_view(window, now: datetime) -> dict:
    """The banner shown while a high-weight release is imminent or landing."""
    return {
        "title": window.title,
        "weight": window.weight,
        "event_id": window.event_id,
        "ts_utc": iso_utc(window.ts_utc),
        "start_utc": iso_utc(window.start),
        "end_utc": iso_utc(window.end),
        "active": window.contains(now),
        "minutes_until": max(0, round(window.minutes_until_start(now))),
    }


def summarise(events: Sequence[dict]) -> dict:
    """Counts for the page header."""
    views = list(events)
    return {
        "total": len(views),
        "high": sum(1 for e in views if int(e.get("weight") or 0) >= 4),
        "top": sum(1 for e in views if int(e.get("weight") or 0) == 5),
    }
