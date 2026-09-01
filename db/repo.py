"""Every query in the project.

Fetchers and the web app call these functions; neither ever imports the Supabase
client. Datetimes are handed in and returned as timezone-aware UTC objects, so
callers never see a string that might or might not carry an offset.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from common.timeutil import iso_utc, parse_iso
from db.client import get_client

log = logging.getLogger(__name__)

EVENTS = "events"
EVENT_WEIGHTS = "event_weights"
PRICES_DAILY = "prices_daily"
NOTIFICATIONS_LOG = "notifications_log"
HEADLINES = "headlines"

# PostgREST rejects very large payloads; upserts go up in chunks of this size.
CHUNK = 500

# PostgREST caps an unbounded select at 1000 rows and says nothing about it: the
# response simply stops. That silently truncated the 10-year Fed funds history to
# 2016-2019, so every event was tagged with a 2019 rate and came out "holding".
# Every unbounded read therefore pages explicitly. See decisions.md.
PAGE = 1000


def _t(table: str, client: Any | None = None):
    return (client or get_client()).table(table)


def _chunks(rows: Sequence[dict], size: int = CHUNK) -> Iterable[Sequence[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _fetch_paged(make_query, *, page: int = PAGE) -> list[dict]:
    """Read every row a query matches, not just PostgREST's first page.

    ``make_query`` must return a *fresh* builder each call, ordered
    deterministically - paging an unordered query can repeat or skip rows.
    """
    out: list[dict] = []
    offset = 0
    while True:
        res = make_query().range(offset, offset + page - 1).execute()
        rows = res.data or []
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


def _hydrate_event(row: dict) -> dict:
    """Turn the ts_utc string PostgREST returns into an aware datetime."""
    out = dict(row)
    if isinstance(out.get("ts_utc"), str):
        out["ts_utc"] = parse_iso(out["ts_utc"], field="events.ts_utc")
    return out


# ---------------------------------------------------------------------------
# event_weights
# ---------------------------------------------------------------------------
def fetch_event_weights(client: Any | None = None) -> dict[str, int]:
    """Every weight, keyed by lowercased title for case-insensitive matching."""
    rows = _fetch_paged(
        lambda: _t(EVENT_WEIGHTS, client).select("title, weight").order("title")
    )
    return {r["title"].strip().lower(): int(r["weight"]) for r in rows}


def fetch_short_titles(client: Any | None = None) -> dict[str, str]:
    """Calendar abbreviations, keyed by lowercased title.

    Returns ``{}`` rather than raising when ``sql/002_short_title.sql`` has not
    been applied yet: the column is an display nicety, and the calendar falls
    back to the full title without it. Titles with a null short form are left
    out for the same reason.
    """
    try:
        rows = _fetch_paged(
            lambda: _t(EVENT_WEIGHTS, client).select("title, short_title").order("title")
        )
    except Exception as exc:
        log.warning(
            "short_title unavailable (%s); calendar will use full titles. "
            "Apply sql/002_short_title.sql to enable it.", type(exc).__name__
        )
        return {}
    return {
        r["title"].strip().lower(): r["short_title"]
        for r in rows
        if r.get("short_title")
    }


# ---------------------------------------------------------------------------
# headlines
# ---------------------------------------------------------------------------
def upsert_headlines(rows: Sequence[dict], client: Any | None = None) -> int:
    """Insert or update headlines by primary key (a hash of the url)."""
    if not rows:
        return 0
    written = 0
    for chunk in _chunks(list(rows)):
        _t(HEADLINES, client).upsert(list(chunk), on_conflict="id").execute()
        written += len(chunk)
    return written


def fetch_headline_fingerprints(
    since: datetime, client: Any | None = None
) -> tuple[set[str], set[str]]:
    """``(urls, normalised titles)`` already stored since ``since``.

    Only these two columns are read: the collector needs to know what it has
    seen, not what it said. Returns empty sets rather than raising if
    ``sql/004_headlines.sql`` has not been applied, so the fetcher degrades to
    "store everything, deduplicate within the batch" instead of failing.
    """
    try:
        rows = _fetch_paged(
            lambda: _t(HEADLINES, client)
            .select("url, title_norm")
            .gte("ts_utc", iso_utc(since, field="since"))
            .order("ts_utc")
            .order("url")
        )
    except Exception as exc:
        log.warning(
            "headline fingerprints unavailable (%s); apply sql/004_headlines.sql. "
            "Deduplicating within this batch only.", type(exc).__name__
        )
        return set(), set()
    urls = {r["url"] for r in rows if r.get("url")}
    titles = {r["title_norm"] for r in rows if r.get("title_norm")}
    return urls, titles


def fetch_recent_headlines(
    limit: int = 20, client: Any | None = None
) -> list[dict]:
    """The newest headlines for the Today page. Newest first."""
    try:
        res = (
            _t(HEADLINES, client)
            .select("*")
            .order("ts_utc", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        log.warning("headlines unavailable (%s)", type(exc).__name__)
        return []
    return list(res.data or [])


# ---------------------------------------------------------------------------
# events - reads
# ---------------------------------------------------------------------------
def fetch_event(event_id: str, client: Any | None = None) -> dict | None:
    res = _t(EVENTS, client).select("*").eq("id", event_id).limit(1).execute()
    rows = res.data or []
    return _hydrate_event(rows[0]) if rows else None


def fetch_events_between(
    start: datetime,
    end: datetime,
    *,
    min_weight: int | None = None,
    client: Any | None = None,
) -> list[dict]:
    """Events with start <= ts_utc <= end, oldest first."""
    def make_query():
        q = (
            _t(EVENTS, client)
            .select("*")
            .gte("ts_utc", iso_utc(start, field="start"))
            .lte("ts_utc", iso_utc(end, field="end"))
        )
        if min_weight is not None:
            q = q.gte("weight", min_weight)
        return q.order("ts_utc").order("id")

    return [_hydrate_event(r) for r in _fetch_paged(make_query)]


def fetch_events_by_ids(
    ids: Sequence[str], client: Any | None = None
) -> dict[str, dict]:
    """The stored rows for these ids, keyed by id. Used by the diff."""
    found: dict[str, dict] = {}
    for chunk in _chunks(list(ids), 200):
        res = _t(EVENTS, client).select("*").in_("id", list(chunk)).execute()
        for row in res.data or []:
            found[row["id"]] = _hydrate_event(row)
    return found


def fetch_recent_releases(
    before: datetime, *, limit: int = 10, client: Any | None = None
) -> list[dict]:
    """The most recent past events, newest first. Powers the "last 10" table."""
    res = (
        _t(EVENTS, client)
        .select("*")
        .lte("ts_utc", iso_utc(before, field="before"))
        .order("ts_utc", desc=True)
        .limit(limit)
        .execute()
    )
    return [_hydrate_event(r) for r in (res.data or [])]


def fetch_events_missing_actual(
    since: datetime, until: datetime, client: Any | None = None
) -> list[dict]:
    """Past events still waiting on an actual. Drives fred_actuals."""
    return [
        _hydrate_event(r)
        for r in _fetch_paged(
            lambda: _t(EVENTS, client)
            .select("*")
            .gte("ts_utc", iso_utc(since, field="since"))
            .lte("ts_utc", iso_utc(until, field="until"))
            .is_("actual", "null")
            .order("ts_utc")
            .order("id")
        )
    ]


def fetch_reminder_candidates(
    now: datetime,
    horizon: datetime,
    *,
    flag_column: str,
    min_weight: int = 4,
    client: Any | None = None,
) -> list[dict]:
    """Un-reminded events of at least min_weight between now and horizon.

    flag_column is reminded_24h or reminded_1h. Events already in the past are
    excluded, so a workflow that was down for a day does not fire a burst of
    reminders for releases that have already happened.
    """
    if flag_column not in ("reminded_24h", "reminded_1h"):
        raise ValueError(f"unknown reminder flag: {flag_column}")
    return [
        _hydrate_event(r)
        for r in _fetch_paged(
            lambda: _t(EVENTS, client)
            .select("*")
            .gt("ts_utc", iso_utc(now, field="now"))
            .lte("ts_utc", iso_utc(horizon, field="horizon"))
            .gte("weight", min_weight)
            .eq(flag_column, False)
            .order("ts_utc")
            .order("id")
        )
    ]


# ---------------------------------------------------------------------------
# events - writes
# ---------------------------------------------------------------------------
def upsert_events(rows: Sequence[dict], client: Any | None = None) -> int:
    """Insert or update by primary key.

    Only the columns present in the payload are written, so a caller that
    supplies scheduling columns cannot wipe an actual that another fetcher
    computed. Every row in a chunk must carry the same keys - PostgREST
    requires it - so callers build uniform dicts.
    """
    if not rows:
        return 0
    written = 0
    for chunk in _chunks(list(rows)):
        _t(EVENTS, client).upsert(list(chunk), on_conflict="id").execute()
        written += len(chunk)
    return written


def update_event(event_id: str, fields: dict, client: Any | None = None) -> None:
    """Patch one event. Datetime values are serialised to ISO-8601 UTC."""
    payload = {
        k: (iso_utc(v, field=k) if isinstance(v, datetime) else v)
        for k, v in fields.items()
    }
    _t(EVENTS, client).update(payload).eq("id", event_id).execute()


def mark_reminded(event_id: str, flag_column: str, client: Any | None = None) -> None:
    if flag_column not in ("reminded_24h", "reminded_1h"):
        raise ValueError(f"unknown reminder flag: {flag_column}")
    update_event(event_id, {flag_column: True}, client=client)


# ---------------------------------------------------------------------------
# prices_daily
# ---------------------------------------------------------------------------
def upsert_prices(rows: Sequence[dict], client: Any | None = None) -> int:
    if not rows:
        return 0
    written = 0
    for chunk in _chunks(list(rows)):
        _t(PRICES_DAILY, client).upsert(list(chunk), on_conflict="date").execute()
        written += len(chunk)
    return written


def fetch_prices(
    start: date, end: date, columns: str = "*", client: Any | None = None
) -> list[dict]:
    return _fetch_paged(
        lambda: _t(PRICES_DAILY, client)
        .select(columns)
        .gte("date", start.isoformat())
        .lte("date", end.isoformat())
        .order("date")
    )


def fetch_fed_funds(
    start: date, end: date, client: Any | None = None
) -> list[tuple[date, float]]:
    """(date, fed_funds) pairs, oldest first, skipping gaps. For the regime."""
    rows = fetch_prices(start, end, columns="date, fed_funds", client=client)
    out: list[tuple[date, float]] = []
    for row in rows:
        if row.get("fed_funds") is None:
            continue
        d = row["date"]
        out.append(
            (date.fromisoformat(d) if isinstance(d, str) else d, float(row["fed_funds"]))
        )
    return out


def latest_price_date(client: Any | None = None) -> date | None:
    """Newest date in prices_daily, or None when empty. Drives incremental runs."""
    res = (
        _t(PRICES_DAILY, client)
        .select("date")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    d = rows[0]["date"]
    return date.fromisoformat(d) if isinstance(d, str) else d


# ---------------------------------------------------------------------------
# notifications_log
# ---------------------------------------------------------------------------
def insert_notification(
    channel: str,
    message: str,
    *,
    event_id: str | None = None,
    ok: bool = True,
    ts: datetime | None = None,
    client: Any | None = None,
) -> None:
    row: dict[str, Any] = {
        "channel": channel,
        "message": message,
        "event_id": event_id,
        "ok": ok,
    }
    if ts is not None:
        row["ts_utc"] = iso_utc(ts, field="ts")
    _t(NOTIFICATIONS_LOG, client).insert(row).execute()
