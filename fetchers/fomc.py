"""FOMC meeting dates.

FRED has no release covering FOMC decisions, so the dates come from the Federal
Reserve's own calendar page. That page is plain HTML with stable class names, so
it is parsed with a regex rather than pulling in a scraping dependency for one
page - see decisions.md.

A decision is announced on the *last* day of each meeting, at 14:00 ET.

Four meetings a year also publish the Summary of Economic Projections and the
dot plot. The Fed marks those on this page itself, with an asterisk on the date
("15-16*"), so that is what the parser reads rather than inferring anything -
if the Fed ever moves the SEP to a different meeting, the page is right and a
month-based rule would be wrong. The offline fallback table has no markers, so
there the SEP meetings are derived from their months (March, June, September,
December), which matches the published 2026 and 2027 calendars exactly.
Meetings that straddle a month boundary are published with a two-month heading
("January/February", "31-1"), which is why the parser takes the month from the
last name and the day from the last number.

The fallback table is the same data, transcribed from that page on 31 Aug 2026
and verified against it. It exists so a single failed HTTP call does not silently
drop the highest-weight events in the calendar - but it is only a stopgap, and
the fetcher logs loudly when it has to use it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from fetchers import http

log = logging.getLogger(__name__)

FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

# Months whose meeting carries a Summary of Economic Projections. Used *only*
# for the fallback table, where the page's own asterisks are not available.
PROJECTION_MONTHS: frozenset[int] = frozenset({3, 6, 9, 12})


@dataclass(frozen=True)
class Meeting:
    """One FOMC decision: the announcement day, and whether it publishes an SEP."""

    day: date
    has_projections: bool


MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Announcement dates (the closing day of each two-day meeting), transcribed from
# federalreserve.gov/monetarypolicy/fomccalendars.htm on 2026-08-31.
FALLBACK_DECISION_DATES: tuple[date, ...] = (
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
    date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28), date(2027, 6, 9),
    date(2027, 7, 28), date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8),
)

# "2026 FOMC Meetings" headings split the page into year sections.
_YEAR_HEADING = re.compile(r"(\d{4})\s+FOMC\s+Meetings", re.IGNORECASE)

# Each meeting renders as a month div followed by a date div.
_MEETING = re.compile(
    r'fomc-meeting__month[^>]*>\s*(?:<[^>]+>\s*)*([A-Za-z/\s]+?)\s*(?:</|<)'
    r'.*?'
    r'fomc-meeting__date[^>]*>\s*(?:<[^>]+>\s*)*([0-9\-–\s*]+?)\s*(?:</|<)',
    re.IGNORECASE | re.DOTALL,
)

_DAY_SPLIT = re.compile(r"[-–]")


def _last_day(date_text: str) -> int | None:
    """The closing day of a meeting: the last number in "27-28" or "31-1"."""
    cleaned = date_text.replace("*", "").strip()
    parts = [p.strip() for p in _DAY_SPLIT.split(cleaned) if p.strip().isdigit()]
    if not parts:
        return None
    day = int(parts[-1])
    return day if 1 <= day <= 31 else None


def _last_month(month_text: str) -> int | None:
    """The month the meeting closes in: the last name in "January/February"."""
    names = [n.strip().lower() for n in month_text.split("/") if n.strip()]
    if not names:
        return None
    return MONTHS.get(names[-1])


def _has_projections(date_text: str) -> bool:
    """Whether the Fed marked this meeting as publishing an SEP.

    The marker is an asterisk on the date cell, e.g. ``15-16*``.
    """
    return "*" in date_text


def parse_fomc_meetings(html: str) -> list[Meeting]:
    """Every scheduled meeting on the Fed calendar page, with its SEP marker.

    Returns the closing day of each meeting, sorted and de-duplicated. Rows that
    do not parse are skipped rather than raising: a layout change to one year's
    block must not lose the others.
    """
    found: dict[date, bool] = {}

    # Split the document into year sections so each meeting gets the right year.
    headings = list(_YEAR_HEADING.finditer(html))
    if not headings:
        log.warning("no year headings found in FOMC calendar HTML")
        return []

    for index, heading in enumerate(headings):
        year = int(heading.group(1))
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(html)
        section = html[start:end]

        for month_text, date_text in _MEETING.findall(section):
            month = _last_month(month_text)
            day = _last_day(date_text)
            if month is None or day is None:
                log.debug("skipping unparsed FOMC row: %r %r", month_text, date_text)
                continue
            try:
                meeting_day = date(year, month, day)
            except ValueError:
                log.debug("skipping impossible FOMC date: %s-%s-%s", year, month, day)
                continue
            # A duplicated row must not clear a marker seen on the first one.
            found[meeting_day] = found.get(meeting_day, False) or _has_projections(date_text)

    return [Meeting(day, found[day]) for day in sorted(found)]


def parse_fomc_calendar(html: str) -> list[date]:
    """Just the announcement dates, sorted and de-duplicated."""
    return [m.day for m in parse_fomc_meetings(html)]


def fallback_meetings() -> list[Meeting]:
    """The transcribed table, with SEP derived from the month.

    The table carries no asterisks, so this is the documented second-best rule.
    It reproduces the published 2026 and 2027 SEP meetings exactly.
    """
    return [
        Meeting(day, day.month in PROJECTION_MONTHS) for day in FALLBACK_DECISION_DATES
    ]


def fetch_meetings(*, allow_fallback: bool = True) -> tuple[list[Meeting], str]:
    """Meetings from the Fed site, falling back to the stored table.

    Returns ``(meetings, source)``. The live page carries the SEP markers; the
    fallback derives them from the month, and says so in the source string.
    """
    html = http.get_text(FOMC_CALENDAR_URL, timeout=20.0)
    if html:
        parsed = parse_fomc_meetings(html)
        if parsed:
            sep = sum(1 for m in parsed if m.has_projections)
            log.info(
                "parsed %d FOMC dates from federalreserve.gov (%d with projections)",
                len(parsed), sep,
            )
            return parsed, "federalreserve.gov"
        log.warning("FOMC calendar page fetched but nothing parsed out of it")
    else:
        log.warning("could not fetch the FOMC calendar page")

    if not allow_fallback:
        return [], "none"

    log.warning(
        "using the transcribed FOMC fallback table (last verified 2026-08-31); "
        "projection meetings derived from the month, not from the page"
    )
    return fallback_meetings(), "fallback-table"


def fetch_decision_dates(*, allow_fallback: bool = True) -> tuple[list[date], str]:
    """Announcement dates from the Fed site, falling back to the stored table.

    Returns ``(dates, source)`` where source is "federalreserve.gov" or
    "fallback-table", so the caller can log which one was used.
    """
    html = http.get_text(FOMC_CALENDAR_URL, timeout=20.0)
    if html:
        parsed = parse_fomc_calendar(html)
        if parsed:
            log.info("parsed %d FOMC dates from federalreserve.gov", len(parsed))
            return parsed, "federalreserve.gov"
        log.warning("FOMC calendar page fetched but nothing parsed out of it")
    else:
        log.warning("could not fetch the FOMC calendar page")

    if not allow_fallback:
        return [], "none"

    log.warning(
        "using the transcribed FOMC fallback table (last verified 2026-08-31); "
        "check federalreserve.gov if dates look stale"
    )
    return list(FALLBACK_DECISION_DATES), "fallback-table"
