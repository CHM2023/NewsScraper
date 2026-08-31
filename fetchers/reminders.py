"""Step 5: 24-hour and 60-minute reminders for the events that matter.

Runs every 15 minutes in CI. For each tier it asks the database for events of
weight >= 4 inside the window whose flag is still false, sends one message, and
flips the flag - so a reminder is sent exactly once even though the workflow
runs 96 times a day.

The two tiers do not overlap. The 24h tier deliberately ignores anything closer
than an hour, and sending the 1h reminder also flips the 24h flag. Without that,
an event ff_sync discovers *inside* the 24h window (a newly scheduled Fed
speech, say) would fire a "24 hours away" message about something 40 minutes
out, and then fire again as the 1h reminder.

Run: ``python -m fetchers.reminders [--dry-run]``
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import timedelta

from common.logging_setup import configure_logging
from common.stats import Stats
from common.timeutil import iso_utc, now_utc
from db import repo
from fetchers import notify

log = logging.getLogger("fetchers.reminders")

MIN_WEIGHT = 4


@dataclass(frozen=True)
class Tier:
    """One reminder horizon."""

    label: str
    flag: str
    lead_minutes: int
    # Events closer than this belong to a nearer tier and are left to it.
    floor_minutes: int
    # Flags to set once the message is away.
    sets: tuple[str, ...]


TIERS: tuple[Tier, ...] = (
    Tier("1h", "reminded_1h", lead_minutes=60, floor_minutes=0,
         sets=("reminded_1h", "reminded_24h")),
    Tier("24h", "reminded_24h", lead_minutes=24 * 60, floor_minutes=60,
         sets=("reminded_24h",)),
)


def format_reminder(row: dict, tier: Tier) -> str:
    """``REMINDER 1h: <title> - <UTC time> - weight <n> - forecast <x>``."""
    forecast = row.get("forecast")
    rendered = "n/a" if forecast is None else _fmt(float(forecast))
    return (
        f"REMINDER {tier.label}: {row['title']} - {iso_utc(row['ts_utc'])} - "
        f"weight {row['weight']} - forecast {rendered}"
    )


def _fmt(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"


def run_tier(tier: Tier, stats: Stats, *, dry_run: bool = False) -> None:
    """Send every outstanding reminder for one tier."""
    now = now_utc()
    window_start = now + timedelta(minutes=tier.floor_minutes)
    window_end = now + timedelta(minutes=tier.lead_minutes)

    candidates = repo.fetch_reminder_candidates(
        window_start, window_end, flag_column=tier.flag, min_weight=MIN_WEIGHT
    )
    stats.fetched += len(candidates)
    log.info(
        "%s tier: %d candidate(s) between %s and %s",
        tier.label, len(candidates), iso_utc(window_start), iso_utc(window_end),
    )

    for row in candidates:
        message = format_reminder(row, tier)
        if dry_run:
            log.info("would send: %s", message)
            stats.skipped += 1
            continue

        # Flip the flags first. A duplicate-suppressed reminder is a much
        # smaller problem than a loop that re-sends every 15 minutes because
        # the flag write failed after a successful send.
        try:
            for flag in tier.sets:
                repo.mark_reminded(row["id"], flag)
        except Exception as exc:
            stats.errors += 1
            log.exception("could not flag %s, not sending: %s", row["id"], exc)
            continue

        if notify.send(message, event_id=row["id"]):
            stats.updated += 1
        else:
            stats.errors += 1
            log.error("reminder not delivered for %s", row["id"])


def run(*, dry_run: bool = False) -> Stats:
    stats = Stats("reminders")

    if not dry_run and not notify.enabled():
        # Flags are flipped before sending, so running for real with no bot
        # configured would mark every due event as reminded and lose it
        # permanently. Degrade to a dry run instead: the events stay pending and
        # fire properly once a token exists.
        notify.warn_disabled_once()
        stats.note("telegram not configured: reported due reminders, flagged none")
        dry_run = True

    for tier in TIERS:
        try:
            run_tier(tier, stats, dry_run=dry_run)
        except Exception as exc:
            stats.errors += 1
            log.exception("%s tier failed: %s", tier.label, exc)
    stats.log(log)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, send nothing")
    args = parser.parse_args()

    configure_logging()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
