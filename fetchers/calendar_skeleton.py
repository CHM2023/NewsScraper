"""Step 3: the next twelve months of US release dates.

ForexFactory only publishes two weeks ahead, so on its own the calendar page
would be empty past the middle of next month. This fetcher fills the other ten
months from sources that publish a year out: FRED's release calendar for the
statistical agencies, and the Federal Reserve's own page for FOMC decisions.

Rows written here are marked ``source='skeleton'``: they carry a date, a
standing publication time and a gold weight, but no forecast. When ff_sync later
reaches the same release it recognises the row by its id and fills in the
forecast, taking ownership of it. This fetcher never touches a row ff_sync owns,
so a precise feed timestamp is not overwritten by a standing-time guess.

Run: ``python -m fetchers.calendar_skeleton [--months 12] [--dry-run]``
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from common import config
from common.logging_setup import configure_logging
from common.stats import Stats
from common.timeutil import iso_utc, now_utc
from db import repo
from fetchers import fomc, http
from fetchers.release_times import scheduled_ts_utc
from fetchers.titles import (
    FRED_RELEASE_TO_TITLE,
    SKELETON_TITLES,
    event_id,
    normalize,
    weight_for,
)

log = logging.getLogger("fetchers.calendar_skeleton")

FRED_BASE = "https://api.stlouisfed.org/fred"

# FRED filters release dates by "realtime period". Asking for everything from
# today to the far future is what makes it return *scheduled* dates rather than
# only the ones already published.
FAR_FUTURE = "9999-12-31"

DEFAULT_MONTHS = 12
FOMC_TITLE = "FOMC Statement"


def fetch_release_index(api_key: str) -> dict[str, int]:
    """Every FRED release, as ``normalised name -> release id``.

    Resolving ids by name rather than hard-coding them means a renumbered or
    retired release shows up as a clear "could not resolve" log line instead of
    silently fetching some other agency's calendar.
    """
    payload = http.get_json(
        f"{FRED_BASE}/releases",
        params={"api_key": api_key, "file_type": "json", "limit": 1000},
    )
    if not payload:
        return {}
    index: dict[str, int] = {}
    for release in payload.get("releases", []):
        name = release.get("name")
        rid = release.get("id")
        if name and rid is not None:
            index[normalize(name)] = int(rid)
    log.info("resolved %d FRED releases", len(index))
    return index


def fetch_release_dates(
    api_key: str, release_id: int, start: date, end: date
) -> list[date]:
    """Scheduled dates for one release, clipped to ``[start, end]``."""
    payload = http.get_json(
        f"{FRED_BASE}/release/dates",
        params={
            "release_id": release_id,
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": start.isoformat(),
            "realtime_end": FAR_FUTURE,
            "include_release_dates_with_no_data": "true",
            "sort_order": "asc",
            "limit": 1000,
        },
    )
    if not payload:
        return []

    out: list[date] = []
    for entry in payload.get("release_dates", []):
        raw = entry.get("date")
        if not raw:
            continue
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            log.warning("release %s: unparseable date %r, skipped", release_id, raw)
            continue
        if start <= day <= end:
            out.append(day)
    return sorted(set(out))


def build_rows(
    schedule: dict[str, list[date]], weights: dict[str, int]
) -> list[dict]:
    """Turn ``title -> [dates]`` into event rows, deduplicated by id."""
    rows: dict[str, dict] = {}
    for title, days in schedule.items():
        weight = weight_for(title, weights)
        for day in days:
            ts = scheduled_ts_utc(day, title)
            rid = event_id(title, ts)
            rows[rid] = {
                "id": rid,
                "title": title,
                "country": "USD",
                "ts_utc": iso_utc(ts, field="ts_utc"),
                "weight": weight,
                "source": "skeleton",
            }
    return [rows[k] for k in sorted(rows)]


def collect_schedule(api_key: str, start: date, end: date, stats: Stats) -> dict[str, list[date]]:
    """Gather release dates for every title the skeleton is responsible for."""
    schedule: dict[str, list[date]] = {}

    index = fetch_release_index(api_key)
    if not index:
        stats.errors += 1
        stats.note("FRED /releases returned nothing; agency dates unavailable")

    # FRED-sourced releases.
    wanted = {
        title: fred_name
        for fred_name, title in FRED_RELEASE_TO_TITLE.items()
        if title in SKELETON_TITLES
    }
    for title, fred_name in sorted(wanted.items()):
        release_id = index.get(normalize(fred_name))
        if release_id is None:
            stats.skipped += 1
            stats.note(f"no FRED release named {fred_name!r}; {title} not scheduled")
            log.warning("could not resolve FRED release %r for %s", fred_name, title)
            continue
        try:
            days = fetch_release_dates(api_key, release_id, start, end)
        except Exception as exc:  # one release must not stop the rest
            stats.errors += 1
            log.exception("release %s (%s) failed: %s", release_id, title, exc)
            continue
        if not days:
            stats.note(f"{title}: no scheduled dates in window")
        schedule[title] = days
        stats.fetched += len(days)
        log.info("%-28s %2d dates (FRED release %s)", title, len(days), release_id)

    # FOMC decisions, from the Federal Reserve calendar.
    try:
        fomc_dates, source = fomc.fetch_decision_dates()
    except Exception as exc:
        fomc_dates, source = [], "error"
        stats.errors += 1
        log.exception("FOMC calendar failed: %s", exc)
    in_window = [d for d in fomc_dates if start <= d <= end]
    if in_window:
        schedule[FOMC_TITLE] = in_window
        stats.fetched += len(in_window)
    else:
        stats.note("no FOMC dates in window")
    log.info("%-28s %2d dates (%s)", FOMC_TITLE, len(in_window), source)

    return schedule


def sync(months: int = DEFAULT_MONTHS, *, dry_run: bool = False) -> Stats:
    """Fetch the schedule and write the rows the skeleton owns."""
    stats = Stats("calendar_skeleton")
    api_key = config.require("FRED_API_KEY")

    start = now_utc().date()
    end = start + timedelta(days=round(months * 30.44))
    log.info("building skeleton for %s .. %s", start, end)

    schedule = collect_schedule(api_key, start, end, stats)
    weights = repo.fetch_event_weights()
    rows = build_rows(schedule, weights)
    if not rows:
        log.warning("nothing to write")
        stats.log(log)
        return stats

    existing = repo.fetch_events_by_ids([r["id"] for r in rows])

    to_insert: list[dict] = []
    to_update: list[dict] = []
    for row in rows:
        stored = existing.get(row["id"])
        if stored is None:
            to_insert.append(row)
            continue
        if stored.get("source") == "forexfactory":
            # ff_sync has a real feed timestamp for this one; leave it alone.
            stats.skipped += 1
            continue
        if iso_utc(stored["ts_utc"]) != row["ts_utc"] or stored.get("weight") != row["weight"]:
            to_update.append(row)
        else:
            stats.skipped += 1

    if dry_run:
        log.info("dry run: would insert %d, update %d", len(to_insert), len(to_update))
        stats.note("dry run, nothing written")
        stats.log(log)
        return stats

    if to_insert:
        repo.upsert_events(to_insert)
        stats.inserted += len(to_insert)
    if to_update:
        repo.upsert_events(to_update)
        stats.updated += len(to_update)

    stats.log(log)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--months", type=int, default=DEFAULT_MONTHS,
        help=f"how far ahead to schedule (default {DEFAULT_MONTHS})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and report, write nothing"
    )
    args = parser.parse_args()

    configure_logging()
    sync(months=args.months, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
