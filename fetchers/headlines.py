"""Collect market headlines from RSS, deduplicate them, and store them.

Concept doc 3.1B. This is collection and display only: the ``category`` and
``score`` columns stay empty, because classifying a headline is Stage 2 and
needs an LLM. What this gives the trader now is one column showing what the
market is reading, next to the calendar of what it is waiting for.

Headlines only - title, link, source, timestamp. No article text is fetched.
That keeps the run cheap, avoids every paywall, and sidesteps republishing
someone else's copy.

Deduplication happens twice, because the same story arrives more than once:

* **By url.** A feed re-lists the same item on every poll, so without this
  every fifteen minutes would insert the whole feed again.
* **By normalised title.** Two outlets carry one story under wording that
  differs by a comma and a colon. Url deduplication cannot catch that - each
  outlet links to its own copy - so titles are lowercased, stripped of
  punctuation and of the trailing " - Outlet" suffix feeds like to add, and
  compared.

One bad feed must never cost the others. Every fetch and every parse is
wrapped: a feed that is down, slow, or serving malformed XML is counted, logged
and skipped, and the run still stores what the other feeds returned.

Run: ``python -m fetchers.headlines [--limit 40] [--dry-run]``
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from common.logging_setup import configure_logging
from common.stats import Stats
from common.timeutil import UTC, iso_utc, now_utc
from db import repo

log = logging.getLogger("fetchers.headlines")


@dataclass(frozen=True)
class Feed:
    """One RSS source."""

    name: str
    url: str
    note: str = ""


# Verified live on 2026-09-01. Kitco and Reuters, both named in the concept doc,
# no longer publish a usable feed - see decisions.md. Yahoo's gold futures feed
# replaces Kitco as the gold-specific source and FXStreet replaces Reuters for
# macro. Every url here returned HTTP 200 and parsed entries when it was added.
FEEDS: tuple[Feed, ...] = (
    Feed("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
         "market pulse; 30 entries"),
    Feed("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml"
                 "?partnerId=wrss01&id=15839069",
         "markets; 30 entries"),
    Feed("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline"
                          "?s=GC%3DF&region=US&lang=en-US",
         "gold futures GC=F; the only gold-specific feed still free"),
    Feed("FXStreet", "https://www.fxstreet.com/rss/news",
         "macro and FX, which is what moves gold"),
)

# Kept so the reason survives the next person wondering where Kitco went.
RETIRED_FEEDS: dict[str, str] = {
    "Kitco": "every RSS path now 404s or redirects to the HTML news page",
    "Reuters commodities": "HTTP 401; Reuters withdrew its public RSS feeds",
}

DEFAULT_LIMIT = 40
# How far back to look when checking whether a title has already been stored.
DEDUPE_DAYS = 3
# A feed that has not answered in this long is not worth the rest of the run.
FEED_TIMEOUT = 15.0

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")
# Feeds append their own name: "Gold slips as dollar firms - Reuters".
_SUFFIX = re.compile(r"\s+[-|]\s+[^-|]{2,30}$")


def normalise_title(title: str) -> str:
    """A comparable form of a headline.

    Lowercase, no punctuation, no trailing outlet name, collapsed whitespace.
    Two feeds carrying the same story usually agree once all four are gone.
    """
    text = _SUFFIX.sub("", str(title or "").strip())
    text = _PUNCT.sub(" ", text.lower())
    return _SPACE.sub(" ", text).strip()


def headline_id(url: str, title: str) -> str:
    """Stable primary key: a hash of the url, or of the title without one."""
    basis = (url or "").strip() or f"title:{normalise_title(title)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:32]


def _published(entry) -> datetime | None:
    """The entry's publication time as an aware UTC datetime.

    feedparser normalises the several date formats feeds use into a UTC
    ``struct_time``. An entry with no parseable date is not dated ``now`` -
    that would put a week-old story at the top of the column - it is skipped.
    """
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None) or (
            entry.get(key) if hasattr(entry, "get") else None
        )
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None


def parse_feed(feed: Feed, raw: bytes | str, stats: Stats) -> list[dict]:
    """Turn one feed's payload into headline rows. Never raises."""
    try:
        import feedparser

        parsed = feedparser.parse(raw)
    except Exception as exc:  # a malformed feed is not a reason to stop
        stats.errors += 1
        stats.note(f"{feed.name}: could not be parsed ({type(exc).__name__})")
        log.warning("%s: parse failed: %s", feed.name, exc)
        return []

    rows: list[dict] = []
    undated = 0
    for entry in getattr(parsed, "entries", []):
        title = str(getattr(entry, "title", "") or "").strip()
        url = str(getattr(entry, "link", "") or "").strip()
        if not title:
            continue
        when = _published(entry)
        if when is None:
            undated += 1
            continue
        rows.append({
            "id": headline_id(url, title),
            "source": feed.name,
            "ts_utc": iso_utc(when, field="headlines.ts_utc"),
            "title": title[:500],
            "url": url[:1000] or None,
            "title_norm": normalise_title(title),
        })
    if undated:
        log.info("%s: %d entry(ies) had no usable date, skipped", feed.name, undated)
    return rows


def fetch_feed(feed: Feed, stats: Stats) -> list[dict]:
    """Fetch and parse one feed. A failure is counted and skipped, never raised."""
    from fetchers import http

    try:
        raw = http.get_text(feed.url, timeout=FEED_TIMEOUT)
    except Exception as exc:
        stats.errors += 1
        stats.note(f"{feed.name}: unreachable ({type(exc).__name__})")
        log.warning("%s: fetch failed: %s", feed.name, exc)
        return []
    if not raw:
        stats.errors += 1
        stats.note(f"{feed.name}: returned nothing")
        log.warning("%s: returned nothing", feed.name)
        return []

    rows = parse_feed(feed, raw, stats)
    log.info("%-14s %3d headline(s)", feed.name, len(rows))
    return rows


def deduplicate(rows: list[dict], seen_urls: set[str], seen_titles: set[str]) -> list[dict]:
    """Drop rows already stored, and rows repeating another row in this batch.

    ``seen_urls`` and ``seen_titles`` start as what the database already holds
    and are extended as the batch is walked, so the first feed to carry a story
    keeps it and later feeds do not duplicate it.
    """
    out: list[dict] = []
    for row in rows:
        url = (row.get("url") or "").strip()
        norm = row.get("title_norm") or ""
        if url and url in seen_urls:
            continue
        if norm and norm in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if norm:
            seen_titles.add(norm)
        out.append(row)
    return out


def run(*, limit: int = DEFAULT_LIMIT, dry_run: bool = False) -> Stats:
    """Collect every feed, deduplicate, and store what is new."""
    stats = Stats("headlines")

    collected: list[dict] = []
    for feed in FEEDS:
        collected.extend(fetch_feed(feed, stats))
    stats.fetched = len(collected)

    if not collected:
        # Every feed failed. Worth an error, not an exception: the next run in
        # fifteen minutes will try again.
        log.warning("no headlines from any feed")
        stats.log(log)
        return stats

    # Newest first, so when two feeds carry one story the fresher copy wins.
    collected.sort(key=lambda r: r["ts_utc"], reverse=True)

    since = now_utc() - timedelta(days=DEDUPE_DAYS)
    known_urls, known_titles = repo.fetch_headline_fingerprints(since)
    fresh = deduplicate(collected, known_urls, known_titles)
    stats.skipped = len(collected) - len(fresh)

    fresh = fresh[:limit]
    if dry_run:
        log.info("dry run: would store %d headline(s)", len(fresh))
        for row in fresh[:10]:
            log.info("   %-14s %s", row["source"], row["title"][:70])
        stats.note("dry run, nothing written")
        stats.log(log)
        return stats

    if fresh:
        try:
            repo.upsert_headlines(fresh)
            stats.inserted = len(fresh)
        except Exception as exc:
            # Counted and reported, never swallowed: a run that stored nothing
            # must not look like a run that had nothing to store.
            stats.errors += 1
            stats.note(
                "could not write headlines - if this is the first run, apply "
                "sql/004_headlines.sql (it adds title_norm)"
            )
            log.error("storing %d headline(s) failed: %s", len(fresh), exc)

    stats.log(log)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"most headlines to store in one run (default {DEFAULT_LIMIT})",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()

    configure_logging()
    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
