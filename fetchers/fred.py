"""Shared FRED observation client.

Both the actuals fetcher and the price fetcher pull series observations, so the
call, its error handling and FRED's "." placeholder for a missing value live in
one place.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from fetchers import http

log = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"

# FRED writes a missing observation as a single full stop.
MISSING = "."


def fetch_observations(
    series_id: str,
    *,
    api_key: str,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100_000,
) -> list[tuple[date, float | None]]:
    """``(date, value)`` pairs for a series, oldest first.

    Values FRED marks as missing come back as None rather than being dropped, so
    a caller computing a month-on-month change can tell "no data yet" apart from
    "the previous observation does not exist".

    Returns an empty list on any failure - a series that has been discontinued
    or renamed is a normal thing to discover at run time, and it must not stop
    the other series in the batch.
    """
    params: dict[str, object] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "limit": limit,
    }
    if start is not None:
        params["observation_start"] = start.isoformat()
    if end is not None:
        params["observation_end"] = end.isoformat()

    payload = http.get_json(f"{FRED_BASE}/series/observations", params=params)
    if not payload:
        log.warning("no observations returned for %s", series_id)
        return []

    out: list[tuple[date, float | None]] = []
    for entry in payload.get("observations", []):
        raw_date = entry.get("date")
        raw_value = entry.get("value")
        if not raw_date:
            continue
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            log.warning("%s: unparseable observation date %r", series_id, raw_date)
            continue
        if raw_value is None or raw_value == MISSING:
            out.append((day, None))
            continue
        try:
            out.append((day, float(raw_value)))
        except (TypeError, ValueError):
            log.warning("%s: unparseable value %r on %s", series_id, raw_value, raw_date)
            out.append((day, None))

    log.debug("%s: %d observations", series_id, len(out))
    return out


def latest_value(observations: Iterable[tuple[date, float | None]]) -> float | None:
    """The newest non-missing value, or None."""
    latest: float | None = None
    for _, value in observations:
        if value is not None:
            latest = value
    return latest
