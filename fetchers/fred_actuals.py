"""Step 6: fill in what actually happened, and score the surprise.

Looks at every event in the past week that is still missing an ``actual``, finds
the FRED series that carries it (fetchers/series_map.py), reads the observation
the release published, and stores it together with the surprise score.

Picking the right observation is the whole job. For a monthly release the
figure published on 11 September is August's, which FRED dates 1 August - so the
rule is "the newest observation dated before the release". A Fed decision is the
opposite: the number that matters is the one that takes effect on the day, so
those series are read at or after the event date instead.

Run: ``python -m fetchers.fred_actuals [--days 7] [--fomc-only] [--dry-run]``
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from common import config
from common.logging_setup import configure_logging
from common.stats import Stats
from common.timeutil import now_utc
from db import repo
from fetchers import fred
from fetchers.series_map import SeriesSpec, reason_unmapped, spec_for
from fetchers.surprise import compute_surprise
from fetchers.titles import resolve_alias

log = logging.getLogger("fetchers.fred_actuals")

DEFAULT_DAYS = 7

# How far back to pull observations, by transform. A year-on-year change needs
# the same month a year earlier plus slack for irregular publication dates.
LOOKBACK_DAYS = {
    "level": 120,
    "diff": 200,
    "pct_change_mom": 200,
    "pct_change_yoy": 500,
    "level_at_or_after": 30,
}

# For level_at_or_after, how far past the event to look for the new value.
FORWARD_WINDOW_DAYS = 10

# Tolerance when matching "the same observation a year earlier".
YOY_MATCH_DAYS = 25


def _non_missing(
    observations: list[tuple[date, float | None]]
) -> list[tuple[date, float]]:
    return [(d, v) for d, v in observations if v is not None]


def extract_actual(
    observations: list[tuple[date, float | None]],
    spec: SeriesSpec,
    asof: date,
) -> float | None:
    """Read the figure a release published, in the units the feed quotes.

    Pure: the caller does the fetching. Returns None whenever the observation
    the transform needs is not there, rather than guessing.
    """
    points = _non_missing(observations)
    if not points:
        return None

    if spec.transform == "level_at_or_after":
        horizon = asof + timedelta(days=FORWARD_WINDOW_DAYS)
        for day, value in points:
            if asof <= day <= horizon:
                return value * spec.scale
        return None

    # Everything else reads the newest observation published before the release -
    # but "before" is not the release date for a monthly series. FRED dates a
    # monthly observation by its *reference month*, and a US macro release in
    # month M reports month M-1. Anchoring on the release date would pick up the
    # observation dated the 1st of the release month, which is the month the
    # release has not measured yet: the CPI published on 12 May 2026 reports
    # April, not May. Anchoring on the 1st of the release month fixes that.
    # Weekly and daily series are dated by period end, so they anchor on the day.
    cutoff = asof.replace(day=1) if spec.frequency == "monthly" else asof
    before = [(d, v) for d, v in points if d < cutoff]
    if not before:
        return None
    current_date, current = before[-1]

    if spec.transform == "level":
        return current * spec.scale

    if spec.transform in ("diff", "pct_change_mom"):
        if len(before) < 2:
            return None
        _, previous = before[-2]
        if spec.transform == "diff":
            return (current - previous) * spec.scale
        if previous == 0:
            return None
        return (current / previous - 1.0) * 100.0

    if spec.transform == "pct_change_yoy":
        target = current_date - timedelta(days=365)
        candidates = [
            (abs((d - target).days), v)
            for d, v in before
            if abs((d - target).days) <= YOY_MATCH_DAYS
        ]
        if not candidates:
            return None
        _, year_ago = min(candidates, key=lambda pair: pair[0])
        if year_ago == 0:
            return None
        return (current / year_ago - 1.0) * 100.0

    return None


def _spec_for_event(title: str) -> SeriesSpec | None:
    """Series spec for a title, trying the alias table before giving up."""
    spec = spec_for(title)
    if spec is not None:
        return spec
    alias = resolve_alias(title)
    return spec_for(alias) if alias else None


def _fetch_windows(
    pairs: list[tuple[dict, "SeriesSpec"]], api_key: str, stats: Stats
) -> dict[str, list[tuple[date, float | None]]]:
    """One observation window per series, spanning every event that needs it.

    The window runs from the earliest event's date minus that series' lookback
    to the latest event's date plus the forward window, so a run covering four
    months of releases still gives each one its own reference period.
    """
    spans: dict[str, tuple[date, date, int]] = {}
    for event, spec in pairs:
        asof = event["ts_utc"].date()
        lookback = LOOKBACK_DAYS.get(spec.transform, 200)
        first, last, widest = spans.get(spec.series_id, (asof, asof, lookback))
        spans[spec.series_id] = (
            min(first, asof), max(last, asof), max(widest, lookback)
        )

    windows: dict[str, list[tuple[date, float | None]]] = {}
    for series_id, (first, last, lookback) in sorted(spans.items()):
        start = first - timedelta(days=lookback)
        end = last + timedelta(days=FORWARD_WINDOW_DAYS)
        try:
            windows[series_id] = fred.fetch_observations(
                series_id, api_key=api_key, start=start, end=end
            )
        except Exception as exc:
            stats.errors += 1
            log.exception("fetching %s failed: %s", series_id, exc)
            windows[series_id] = []
        log.info(
            "%-16s %4d observations %s .. %s",
            series_id, len(windows[series_id]), start, end,
        )
    return windows


# The only two FOMC-day titles that carry a number: the statement and the target
# range both read DFEDTARU. The press conference and the projections have no
# single figure, so a --fomc-only run that looked for them would find work it
# could never do.
FOMC_ACTUAL_TITLES = frozenset({"fomc statement", "federal funds rate"})


def run(
    days: int = DEFAULT_DAYS, *, fomc_only: bool = False, dry_run: bool = False
) -> Stats:
    stats = Stats("fred_actuals")
    api_key = config.require("FRED_API_KEY")

    now = now_utc()
    since = now - timedelta(days=days)
    events = repo.fetch_events_missing_actual(since, now)
    if fomc_only:
        events = [
            e for e in events
            if str(e.get("title", "")).strip().lower() in FOMC_ACTUAL_TITLES
        ]

    # The early exit that makes a five-minute cron affordable. On the ~250 days a
    # year with no Fed decision, and outside a release window on any other day,
    # this is the whole run: one Supabase query, one log line, done. Everything
    # expensive - the FRED windows - is below this line.
    if not events:
        log.info(
            "nothing to do: no %sevent in the last %d day(s) is missing an actual",
            "FOMC " if fomc_only else "", days,
        )
        stats.log(log)
        return stats

    stats.fetched = len(events)
    log.info(
        "%d %sevent(s) in the last %d days still missing an actual",
        len(events), "FOMC " if fomc_only else "", days,
    )

    # Resolve every event to a series first, so each series can be fetched once
    # over a window that covers *all* the dates referencing it. Fetching per
    # event would work but costs one API call each; caching a window derived
    # from a single event does not - the first event's window would be reused
    # for every later date and hand them all the same stale observation.
    pairs: list[tuple[dict, SeriesSpec]] = []
    for event in events:
        spec = _spec_for_event(event["title"])
        if spec is None:
            stats.skipped += 1
            log.info("skip %-32s %s", event["title"], reason_unmapped(event["title"]))
            continue
        pairs.append((event, spec))

    cache = _fetch_windows(pairs, api_key, stats)

    for event, spec in pairs:
        title = event["title"]
        asof = event["ts_utc"].date()
        observations = cache.get(spec.series_id, [])

        try:
            actual = extract_actual(observations, spec, asof)
        except Exception as exc:
            stats.errors += 1
            log.exception("%s: could not read %s: %s", title, spec.series_id, exc)
            continue

        if actual is None:
            stats.skipped += 1
            log.info(
                "skip %-32s %s has no usable observation yet for %s",
                title, spec.series_id, asof,
            )
            continue

        forecast = event.get("forecast")
        score = compute_surprise(actual, forecast)
        log.info(
            "%-32s actual=%s forecast=%s surprise=%s (%s)",
            title, _fmt(actual), _fmt(forecast), _fmt(score), spec.series_id,
        )

        if dry_run:
            stats.skipped += 1
            continue

        try:
            repo.update_event(event["id"], {"actual": actual, "surprise": score})
            stats.updated += 1
        except Exception as exc:
            stats.errors += 1
            log.exception("could not update %s: %s", event["id"], exc)

    if dry_run:
        stats.note("dry run, nothing written")
    stats.log(log)
    return stats


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.4g}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help=f"how far back to look for gaps (default {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--fomc-only", action="store_true",
        help="only fill FOMC decision events; exit immediately when there are none",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()

    configure_logging()
    run(days=args.days, fomc_only=args.fomc_only, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
