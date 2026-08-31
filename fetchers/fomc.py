"""FOMC meeting dates.

FRED has no release covering FOMC decisions, so the dates come from the Federal
Reserve's own calendar page. That page is plain HTML with stable class names, so
it is parsed with a regex rather than pulling in a scraping dependency for one
page - see decisions.md.

A decision is announced on the *last* day of each meeting, at 14:00 ET.
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
from datetime import date

from fetchers import http

log = logging.getLogger(__name__)

FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

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


def parse_fomc_calendar(html: str) -> list[date]:
    """Extract every scheduled announcement date from the Fed calendar page.

    Returns the closing day of each meeting, sorted and de-duplicated. Rows that
    do not parse are skipped rather than raising: a layout change to one year's
    block must not lose the others.
    """
    found: set[date] = set()

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
                found.add(date(year, month, day))
            except ValueError:
                log.debug("skipping impossible FOMC date: %s-%s-%s", year, month, day)

    return sorted(found)


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
