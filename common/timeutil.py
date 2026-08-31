"""UTC time handling.

The single rule in this project: every datetime that crosses a module boundary,
reaches the database, or reaches a template is timezone-aware and in UTC.
Conversion to the viewer's local time happens in the browser and nowhere else.

``datetime.utcnow()`` returns a *naive* datetime that merely looks like UTC. Used
by accident it silently shifts release times by the local offset, which would
break the reminder and blackout logic in a way nothing would flag. Everything
here refuses naive datetimes loudly instead.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc


class NaiveDatetimeError(ValueError):
    """Raised when a datetime without tzinfo reaches a boundary."""


def now_utc() -> datetime:
    """Current time, timezone-aware, in UTC. Use instead of ``utcnow()``."""
    return datetime.now(UTC)


def ensure_aware(dt: datetime, *, field: str = "datetime") -> datetime:
    """Return ``dt`` unchanged, or raise if it is naive.

    ``tzinfo`` alone is not enough: a tzinfo whose ``utcoffset()`` is None is
    still naive as far as arithmetic and comparison are concerned.
    """
    if not isinstance(dt, datetime):
        raise TypeError(f"{field} must be a datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise NaiveDatetimeError(
            f"{field} is naive: {dt!r}. Every datetime in this project must be "
            f"timezone-aware. Use common.timeutil.now_utc() or parse_iso()."
        )
    return dt


def to_utc(dt: datetime, *, field: str = "datetime") -> datetime:
    """Convert an aware datetime to UTC. Raises on naive input."""
    return ensure_aware(dt, field=field).astimezone(UTC)


def parse_iso(value: str | datetime, *, field: str = "datetime") -> datetime:
    """Parse an ISO-8601 string to an aware UTC datetime.

    Accepts the trailing ``Z`` that Postgres and several APIs emit, which
    ``fromisoformat`` only learned to handle in 3.11. Rejects strings with no
    offset at all: a release time without a zone is not a fact we can use.
    """
    if isinstance(value, datetime):
        return to_utc(value, field=field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} is not ISO-8601: {value!r}") from exc
    return to_utc(parsed, field=field)


def iso_utc(dt: datetime, *, field: str = "datetime") -> str:
    """Serialise to ISO-8601 UTC, e.g. ``2026-10-14T12:30:00+00:00``."""
    return to_utc(dt, field=field).isoformat()


def utc_date(dt: datetime, *, field: str = "datetime") -> date:
    """The UTC calendar date of an aware datetime. Used to build event ids."""
    return to_utc(dt, field=field).date()


def utc_date_str(dt: datetime, *, field: str = "datetime") -> str:
    """``YYYY-MM-DD`` in UTC."""
    return utc_date(dt, field=field).isoformat()


def start_of_utc_day(dt: datetime) -> datetime:
    """Midnight UTC on the same UTC date."""
    return to_utc(dt).replace(hour=0, minute=0, second=0, microsecond=0)


def days_ahead(days: int, *, from_time: datetime | None = None) -> datetime:
    """``days`` from now (or from ``from_time``), in UTC."""
    base = to_utc(from_time) if from_time is not None else now_utc()
    return base + timedelta(days=days)
