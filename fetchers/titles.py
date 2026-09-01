"""Canonical event titles, weight lookup and event ids.

Two fetchers write the same rows. ``calendar_skeleton`` knows release *dates* a
year out and names them the way FRED does ("Consumer Price Index"). ``ff_sync``
knows forecasts a fortnight out and names them the way ForexFactory does ("CPI
m/m"). If those two disagree the same release lands in the database twice.

The fix is that FRED release names are translated to the ForexFactory title for
the headline number of that release, so the two sources produce the *same*
``event_id`` and the second writer updates the first writer's row in place.
ForexFactory's secondary prints for the same release (Core CPI m/m, CPI y/y,
Unemployment Rate) are inserted as their own rows, but only inside the two-week
window where forecasts exist - which is exactly when the extra detail is useful.
"""

from __future__ import annotations

import re
from datetime import datetime

from common.timeutil import utc_date_str

# Titles the brief did not weight explicitly fall back to this.
DEFAULT_WEIGHT = 1

# FRED release name -> every ForexFactory title that release publishes, headline
# first. Keys are matched case-insensitively after whitespace normalisation.
#
# One release is several numbers. The BLS Employment Situation carries payrolls,
# the unemployment rate and average hourly earnings; CPI day carries headline
# m/m, y/y and core. ForexFactory lists them as separate rows and the trader
# reads them as separate events - Core CPI is weight 5 in its own right, because
# it is the number the Fed actually watches. Mapping a release to a single title
# meant that beyond the one-week ForexFactory window the calendar showed "CPI
# m/m" alone and silently dropped the rest.
#
# Every title here must have its own entry in series_map.SERIES_MAP, or its
# actual will never be filled in.
FRED_RELEASE_TO_TITLES: dict[str, tuple[str, ...]] = {
    "consumer price index": ("CPI m/m", "CPI y/y", "Core CPI m/m"),
    "employment situation": (
        "Non-Farm Employment Change",
        "Unemployment Rate",
        "Average Hourly Earnings m/m",
    ),
    "producer price index": ("PPI m/m", "Core PPI m/m"),
    "personal income and outlays": ("Core PCE Price Index m/m",),
    "advance monthly sales for retail and food services": (
        "Retail Sales m/m",
        "Core Retail Sales m/m",
    ),
    "unemployment insurance weekly claims report": ("Unemployment Claims",),
    "ism manufacturing report on business": ("ISM Manufacturing PMI",),
    "ism services report on business": ("ISM Services PMI",),
}

# The headline print of each release, kept because a few callers only want the
# one title that stands for the whole release.
FRED_RELEASE_TO_TITLE: dict[str, str] = {
    name: titles[0] for name, titles in FRED_RELEASE_TO_TITLES.items()
}

# The titles calendar_skeleton is responsible for, in the order the brief lists
# them. Anything not resolvable at run time is logged and skipped, never faked.
SKELETON_TITLES: tuple[str, ...] = (
    "CPI m/m",
    "CPI y/y",
    "Core CPI m/m",
    "Core PCE Price Index m/m",
    "Non-Farm Employment Change",
    "Unemployment Rate",
    "Average Hourly Earnings m/m",
    "PPI m/m",
    "Core PPI m/m",
    "FOMC Statement",
    "Federal Funds Rate",
    "FOMC Press Conference",
    "FOMC Economic Projections",
    "Retail Sales m/m",
    "Core Retail Sales m/m",
    "ISM Manufacturing PMI",
    "Unemployment Claims",
)

# Feed titles that vary with whoever holds the office, or with the year, mapped
# onto a stable seeded title. Applied only when the exact title is unknown.
_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^fed chair .+ testifies$"), "Fed Chair Testifies"),
    (re.compile(r"^fed chair .+ speaks$"), "Fed Chair Speaks"),
    (re.compile(r"^fed chair .+ testimony$"), "Fed Chair Testifies"),
    (re.compile(r"jackson hole"), "Jackson Hole Symposium"),
    (re.compile(r"^fomc press conference$"), "FOMC Press Conference"),
    (re.compile(r"^fomc economic projections$"), "FOMC Economic Projections"),
    (re.compile(r"^fomc meeting minutes$"), "FOMC Meeting Minutes"),
    (re.compile(r"^(fomc member|treasury sec|fed) .+ speaks$"), "FOMC Member Speaks"),
)

_WHITESPACE = re.compile(r"\s+")


def normalize(title: str) -> str:
    """Lowercase, collapse whitespace. The key every lookup uses."""
    return _WHITESPACE.sub(" ", str(title).strip()).lower()


def canonical_from_fred_release(release_name: str) -> str | None:
    """The headline ForexFactory-style title for a FRED release, or None."""
    return FRED_RELEASE_TO_TITLE.get(normalize(release_name))


def titles_from_fred_release(release_name: str) -> tuple[str, ...]:
    """Every title a FRED release publishes, headline first."""
    return FRED_RELEASE_TO_TITLES.get(normalize(release_name), ())


def resolve_alias(title: str) -> str | None:
    """The seeded title an office-holder-specific feed title stands for."""
    key = normalize(title)
    for pattern, canonical in _ALIASES:
        if pattern.search(key):
            return canonical
    return None


def weight_for(title: str, weights: dict[str, int]) -> int:
    """Look up a gold weight for a feed title.

    ``weights`` is keyed by lowercased title, as db.repo.fetch_event_weights
    returns it. Exact case-insensitive match wins; failing that an alias is
    tried, so "Fed Chair Powell Testifies" still scores 4 after the chair
    changes. Anything still unknown gets DEFAULT_WEIGHT, per the brief.
    """
    key = normalize(title)
    if key in weights:
        return int(weights[key])
    alias = resolve_alias(title)
    if alias and normalize(alias) in weights:
        return int(weights[normalize(alias)])
    return DEFAULT_WEIGHT


def event_id(title: str, ts_utc: datetime, country: str = "USD") -> str:
    """Stable primary key: ``USD|<title>|<YYYY-MM-DD>``.

    The date component is the UTC date of the release. Every US macro release in
    scope lands between 12:00 and 20:00 UTC, so the UTC date and the US calendar
    date agree and the id stays stable whichever source wrote it first. A feed
    time that crossed midnight UTC would break that, which is why the skeleton
    assigns realistic release times rather than midnight.
    """
    return f"{country}|{title}|{utc_date_str(ts_utc, field='ts_utc')}"
