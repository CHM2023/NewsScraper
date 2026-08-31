"""Step 4: the current week's US releases from ForexFactory.

This is the fetcher that produces notifications. It pulls the weekly JSON
feed(s), keeps the USD rows, parses the display strings into numbers, and diffs
the result against what is already stored:

* an id that is not in the database  -> insert, and emit NEW
* a stored release time or forecast that moved -> update, and emit CHANGED
* everything else -> left alone

Only weight >= 4 events produce a message, per the brief; lower-weight rows are
still written, they just do not interrupt anyone.

The feed is the authority on timing and consensus for the week it covers, so
rows written here are marked ``source='forexfactory'`` and calendar_skeleton
will not overwrite them afterwards. Beyond that week the calendar is the
skeleton's: as of 2026-08-31 the next-week feed 404s, so it is fetched as
optional. See decisions.md.

Run: ``python -m fetchers.ff_sync [--dry-run] [--quiet]``
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from common.logging_setup import configure_logging
from common.stats import Stats
from common.timeutil import iso_utc, parse_iso
from db import repo
from fetchers import http, notify
from fetchers.diff import DiffResult, diff_events
from fetchers.parsing import parse_impact, parse_numeric
from fetchers.titles import event_id, weight_for

log = logging.getLogger("fetchers.ff_sync")


@dataclass(frozen=True)
class Feed:
    """A weekly feed, and whether its absence is a problem.

    As of 2026-08-31 only ff_calendar_thisweek.json is published;
    ff_calendar_nextweek.json (and lastweek, today, tomorrow) all return 404.
    The next-week feed is kept but marked optional, so it is picked up for free
    if the publisher restores it, and its absence does not write an error line
    on all 24 scheduled runs a day. See decisions.md.
    """

    url: str
    required: bool = True

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[-1]


FEEDS: tuple[Feed, ...] = (
    Feed("https://nfs.faireconomy.media/ff_calendar_thisweek.json", required=True),
    Feed("https://nfs.faireconomy.media/ff_calendar_nextweek.json", required=False),
)

COUNTRY = "USD"

# Below this weight an event is stored silently. The brief's rule.
NOTIFY_MIN_WEIGHT = 4

SOURCE = "forexfactory"

# Written on both insert and update. Uniform keys, because PostgREST requires
# every row in one upsert to carry the same columns.
WRITE_COLUMNS = (
    "id", "title", "country", "ts_utc", "impact", "weight", "forecast",
    "previous", "source",
)


def fetch_feed(url: str, *, required: bool = True) -> list[dict] | None:
    """One weekly feed, or None if it could not be fetched or was not a list."""
    payload = http.get_json(url, timeout=20.0, allow_404=not required)
    if payload is None:
        return None
    if not isinstance(payload, list):
        log.error("%s did not return a JSON array (got %s)", url, type(payload).__name__)
        return None
    return payload


def parse_entry(entry: dict, weights: dict[str, int]) -> dict | None:
    """Turn one feed entry into an event row, or None if it is unusable.

    Returns None for anything that is not a dated USD release: other countries,
    the "All" pseudo-country used for G20-style items, and rows whose date does
    not parse. Each of those is a normal feed condition, not an error.
    """
    if not isinstance(entry, dict):
        return None
    if (entry.get("country") or "").strip().upper() != COUNTRY:
        return None

    title = (entry.get("title") or "").strip()
    raw_date = entry.get("date")
    if not title or not raw_date:
        return None

    try:
        ts = parse_iso(raw_date, field="forexfactory.date")
    except ValueError as exc:
        log.warning("skipping %r: %s", title, exc)
        return None

    weight = weight_for(title, weights)
    return {
        "id": event_id(title, ts, COUNTRY),
        "title": title,
        "country": COUNTRY,
        "ts_utc": ts,
        "impact": parse_impact(entry.get("impact")),
        "weight": weight,
        "forecast": parse_numeric(entry.get("forecast")),
        "previous": parse_numeric(entry.get("previous")),
        "source": SOURCE,
    }


def collect(
    feeds: Iterable[Feed | str], weights: dict[str, int], stats: Stats
) -> list[dict]:
    """Fetch every feed and return the parsed USD rows, later feeds winning."""
    rows: dict[str, dict] = {}
    for feed in feeds:
        feed = feed if isinstance(feed, Feed) else Feed(feed)
        url = feed.url
        entries = fetch_feed(url, required=feed.required)
        if entries is None:
            if feed.required:
                stats.errors += 1
                stats.note(f"feed unavailable: {url}")
            else:
                stats.note(f"optional feed not published: {feed.name}")
            continue
        stats.fetched += len(entries)
        kept = 0
        for entry in entries:
            try:
                row = parse_entry(entry, weights)
            except Exception as exc:  # one bad row never stops the batch
                stats.errors += 1
                log.exception("bad feed row %r: %s", entry, exc)
                continue
            if row is None:
                continue
            rows[row["id"]] = row
            kept += 1
        log.info("%s: %d entries, %d USD rows kept", feed.name, len(entries), kept)
    return [rows[k] for k in sorted(rows)]


def _serialise(row: dict) -> dict:
    """The row as PostgREST wants it: ts_utc as an ISO-8601 string."""
    out = {k: row.get(k) for k in WRITE_COLUMNS}
    out["ts_utc"] = iso_utc(row["ts_utc"], field="ts_utc")
    return out


def format_new(row: dict) -> str:
    """``NEW: <title> - <UTC time> - weight <n> - forecast <x>``."""
    forecast = "n/a" if row.get("forecast") is None else _fmt(row["forecast"])
    return (
        f"NEW: {row['title']} - {iso_utc(row['ts_utc'])} - "
        f"weight {row['weight']} - forecast {forecast}"
    )


def format_changed(row: dict, changes: Sequence[Any]) -> str:
    detail = "; ".join(c.describe() for c in changes)
    return (
        f"CHANGED: {row['title']} - {iso_utc(row['ts_utc'])} - "
        f"weight {row['weight']} - {detail}"
    )


def _fmt(value: float) -> str:
    """Render a parsed number without trailing zero noise."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"


def announce(result: DiffResult, stats: Stats, *, quiet: bool = False) -> None:
    """Send NEW/CHANGED messages for the events that clear the weight bar.

    With no bot configured the messages are still logged at INFO - that is the
    useful record of what the run found - but no send is attempted and the
    disabled notice is said once rather than once per event.
    """
    if not quiet and not notify.enabled():
        notify.warn_disabled_once()
        stats.note("telegram not configured: messages logged, none sent")
        quiet = True

    for row in result.new:
        if row["weight"] < NOTIFY_MIN_WEIGHT:
            continue
        message = format_new(row)
        log.info(message)
        if not quiet:
            notify.send(message, event_id=row["id"])

    for row, changes in result.changed:
        if row["weight"] < NOTIFY_MIN_WEIGHT:
            continue
        message = format_changed(row, changes)
        log.info(message)
        if not quiet:
            notify.send(message, event_id=row["id"])


def sync(*, dry_run: bool = False, quiet: bool = False) -> Stats:
    """Fetch the feeds, diff against the database, write and notify."""
    stats = Stats("ff_sync")

    weights = repo.fetch_event_weights()
    log.info("loaded %d event weights", len(weights))

    rows = collect(FEEDS, weights, stats)
    if not rows:
        log.warning("no USD rows in either feed; nothing to do")
        stats.log(log)
        return stats

    existing = repo.fetch_events_by_ids([r["id"] for r in rows])
    result = diff_events(rows, existing)
    new_count, changed_count, unchanged_count = result.counts
    log.info("diff: %d new, %d changed, %d unchanged", new_count, changed_count, unchanged_count)
    stats.skipped += unchanged_count

    if dry_run:
        for row in result.new:
            log.info("would insert: %s", format_new(row))
        for row, changes in result.changed:
            log.info("would update: %s", format_changed(row, changes))
        stats.note("dry run, nothing written or sent")
        stats.log(log)
        return stats

    if result.new:
        repo.upsert_events([_serialise(r) for r in result.new])
        stats.inserted += len(result.new)
    if result.changed:
        repo.upsert_events([_serialise(r) for r, _ in result.changed])
        stats.updated += len(result.changed)

    # Notify only after the write succeeds, so a failed write never produces a
    # message about an event that is not in the database.
    announce(result, stats, quiet=quiet)

    stats.log(log)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--quiet", action="store_true", help="write, but send no Telegram messages")
    args = parser.parse_args()

    configure_logging()
    sync(dry_run=args.dry_run, quiet=args.quiet)


if __name__ == "__main__":
    main()
