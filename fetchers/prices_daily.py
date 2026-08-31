"""Step 7: daily gold and the three macro series that drive it.

Writes one ``prices_daily`` row per calendar date holding the gold close, the
dollar index, the 10-year real yield and the Fed funds rate. Then tags every
event with the policy regime in force on its date, which Stage 3 needs in order
to condition on the regime rather than average across regimes that behaved in
opposite ways.

Two modes:

* ``--backfill-years 10`` - the one-off history load.
* no arguments - incremental, picking up from the newest date already stored
  with a few days of overlap so a revised observation is corrected.

Gold comes from FRED's LBMA series when that is current, and from yfinance's
``GC=F`` otherwise; the LBMA series has been discontinued once already, so the
fallback is not hypothetical. Whichever source answers, the values are merged
per date with FRED preferred, and the row is only written for dates that have at
least one value.

Run: ``python -m fetchers.prices_daily [--backfill-years 10] [--dry-run]``
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta

from common import config
from common.logging_setup import configure_logging
from common.stats import Stats
from common.timeutil import now_utc
from db import repo
from fetchers import fred
from fetchers.regime import classify_regime

log = logging.getLogger("fetchers.prices_daily")

# column -> FRED series id
FRED_SERIES: dict[str, str] = {
    # LBMA Gold Price, PM fix, USD. Preferred when current.
    "xau_close": "GOLDPMGBD228NLBM",
    # The Fed's broad trade-weighted dollar index. Not ICE DXY - see decisions.md.
    "dxy": "DTWEXBGS",
    "real_yield_10y": "DFII10",
    "fed_funds": "DFF",
}

# Yahoo tickers used when FRED cannot supply a column.
YAHOO_GOLD = "GC=F"
YAHOO_DXY = "DX-Y.NYB"

# If FRED's newest gold observation is older than this, treat the series as
# discontinued for our purposes and fall back.
STALE_AFTER_DAYS = 10

# Incremental runs re-read this far back, so revisions are picked up.
OVERLAP_DAYS = 7

DEFAULT_INCREMENTAL_DAYS = 30


def _fred_column(
    column: str, series_id: str, api_key: str, start: date, end: date, stats: Stats
) -> dict[date, float]:
    """One FRED series as ``{date: value}``, empty on failure."""
    try:
        observations = fred.fetch_observations(
            series_id, api_key=api_key, start=start, end=end
        )
    except Exception as exc:
        stats.errors += 1
        log.exception("%s (%s) failed: %s", column, series_id, exc)
        return {}

    values = {day: value for day, value in observations if value is not None}
    log.info("%-14s %5d values from FRED %s", column, len(values), series_id)
    return values


def _yahoo_close(ticker: str, start: date, end: date, stats: Stats) -> dict[date, float]:
    """Daily closes from Yahoo as ``{date: close}``, empty on failure.

    yfinance is imported here rather than at module scope: it is slow to import
    and is only needed when a FRED series lets us down.
    """
    try:
        import yfinance

        frame = yfinance.download(
            ticker,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=False,
        )
    except Exception as exc:
        stats.errors += 1
        log.exception("yfinance %s failed: %s", ticker, exc)
        return {}

    if frame is None or frame.empty:
        log.warning("yfinance %s returned nothing", ticker)
        return {}

    try:
        closes = frame["Close"]
        # A single-ticker download still returns a column-indexed frame.
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        values = {
            index.date(): float(value)
            for index, value in closes.items()
            if value == value  # drop NaN
        }
    except Exception as exc:
        stats.errors += 1
        log.exception("could not read %s closes: %s", ticker, exc)
        return {}

    log.info("%-14s %5d values from Yahoo %s", "(fallback)", len(values), ticker)
    return values


def _is_stale(values: dict[date, float], end: date) -> bool:
    if not values:
        return True
    return (end - max(values)).days > STALE_AFTER_DAYS


def collect_prices(
    api_key: str, start: date, end: date, stats: Stats
) -> dict[date, dict[str, float]]:
    """Gather every column and merge them into one row per date."""
    columns: dict[str, dict[date, float]] = {}
    for column, series_id in FRED_SERIES.items():
        columns[column] = _fred_column(column, series_id, api_key, start, end, stats)

    # Gold: fall back to Yahoo when the LBMA series is missing or stale.
    if _is_stale(columns["xau_close"], end):
        log.warning(
            "FRED gold series %s is empty or stale, falling back to %s",
            FRED_SERIES["xau_close"], YAHOO_GOLD,
        )
        stats.note(f"gold from {YAHOO_GOLD}, FRED LBMA unavailable or stale")
        fallback = _yahoo_close(YAHOO_GOLD, start, end, stats)
        # FRED values win where both exist; Yahoo fills the rest.
        columns["xau_close"] = {**fallback, **columns["xau_close"]}

    if not columns["dxy"]:
        log.warning("FRED %s returned nothing, trying %s", FRED_SERIES["dxy"], YAHOO_DXY)
        stats.note(f"dollar index from {YAHOO_DXY}")
        columns["dxy"] = _yahoo_close(YAHOO_DXY, start, end, stats)

    rows: dict[date, dict[str, float]] = defaultdict(dict)
    for column, values in columns.items():
        for day, value in values.items():
            if start <= day <= end:
                rows[day][column] = value

    stats.fetched = sum(len(v) for v in columns.values())
    return dict(rows)


def build_price_rows(merged: dict[date, dict[str, float]]) -> list[dict]:
    """Uniform rows for upsert, one per date, oldest first."""
    out = []
    for day in sorted(merged):
        row: dict[str, object] = {"date": day.isoformat()}
        for column in FRED_SERIES:
            row[column] = merged[day].get(column)
        out.append(row)
    return out


def update_regimes(stats: Stats, *, dry_run: bool = False, days_ahead: int = 400) -> None:
    """Tag events with the Fed regime in force on their date.

    Runs over a wide window on every daily run rather than only over new rows:
    the regime for an event a month away is not knowable until the rate history
    reaches it, and a rate change revises the label for recent events too.
    """
    now = now_utc()
    history_start = (now - timedelta(days=365 * 11)).date()
    series = repo.fetch_fed_funds(history_start, now.date())
    if not series:
        stats.note("no fed funds history stored yet, regimes not updated")
        log.warning("prices_daily has no fed_funds values; run a backfill first")
        return

    events = repo.fetch_events_between(
        now - timedelta(days=365 * 10), now + timedelta(days=days_ahead)
    )
    changed = 0
    for event in events:
        regime = classify_regime(series, event["ts_utc"].date())
        if regime is None or regime == event.get("regime"):
            continue
        if dry_run:
            changed += 1
            continue
        try:
            repo.update_event(event["id"], {"regime": regime})
            changed += 1
        except Exception as exc:
            stats.errors += 1
            log.exception("could not tag %s: %s", event["id"], exc)

    log.info("regime: %d event(s) %s", changed, "would change" if dry_run else "updated")
    stats.updated += changed


def run(
    *,
    backfill_years: int | None = None,
    dry_run: bool = False,
    skip_regime: bool = False,
) -> Stats:
    stats = Stats("prices_daily")
    api_key = config.require("FRED_API_KEY")

    end = now_utc().date()
    if backfill_years:
        start = end - timedelta(days=round(365.25 * backfill_years))
        log.info("backfilling %d years: %s .. %s", backfill_years, start, end)
    else:
        latest = repo.latest_price_date()
        if latest is None:
            start = end - timedelta(days=DEFAULT_INCREMENTAL_DAYS)
            log.info("prices_daily is empty; loading the last %d days", DEFAULT_INCREMENTAL_DAYS)
        else:
            start = latest - timedelta(days=OVERLAP_DAYS)
            log.info("incremental from %s (newest stored %s)", start, latest)

    merged = collect_prices(api_key, start, end, stats)
    rows = build_price_rows(merged)
    log.info("%d date(s) with at least one value", len(rows))

    if dry_run:
        stats.note("dry run, nothing written")
    elif rows:
        try:
            repo.upsert_prices(rows)
            stats.inserted += len(rows)
        except Exception as exc:
            stats.errors += 1
            log.exception("could not write prices: %s", exc)

    if not skip_regime:
        try:
            update_regimes(stats, dry_run=dry_run)
        except Exception as exc:
            stats.errors += 1
            log.exception("regime tagging failed: %s", exc)

    stats.log(log)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--backfill-years", type=int, default=None,
        help="load this many years of history instead of running incrementally",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument(
        "--skip-regime", action="store_true", help="load prices without re-tagging events"
    )
    args = parser.parse_args()

    configure_logging()
    run(
        backfill_years=args.backfill_years,
        dry_run=args.dry_run,
        skip_regime=args.skip_regime,
    )


if __name__ == "__main__":
    main()
