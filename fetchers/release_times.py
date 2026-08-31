"""Release clock times, and the conversion from US Eastern to UTC.

FRED's release calendar gives a date but no time; ForexFactory gives a full
timestamp. For the ten months where only FRED has data, the skeleton has to
supply the time itself, because an event stored at midnight would sort wrongly
on the "today" page, land in the wrong UTC day, and make the 24h/1h reminders
fire at the wrong moment.

These are the standing publication times, which have been stable for years:
BLS and BEA releases at 08:30 ET, ISM at 10:00 ET, FOMC statements at 14:00 ET.
The conversion runs through the real IANA zone, so a release in January (EST,
UTC-5) and one in July (EDT, UTC-4) land on different UTC clock times - which is
the daylight-saving bug the concept doc calls out as a known risk.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from common.timeutil import UTC

EASTERN = ZoneInfo("America/New_York")

# Canonical title -> publication time in US Eastern.
RELEASE_TIMES_ET: dict[str, time] = {
    "CPI m/m": time(8, 30),
    "Core CPI m/m": time(8, 30),
    "CPI y/y": time(8, 30),
    "PPI m/m": time(8, 30),
    "Core PPI m/m": time(8, 30),
    "Core PCE Price Index m/m": time(8, 30),
    "Non-Farm Employment Change": time(8, 30),
    "Unemployment Rate": time(8, 30),
    "Average Hourly Earnings m/m": time(8, 30),
    "Retail Sales m/m": time(8, 30),
    "Core Retail Sales m/m": time(8, 30),
    "Unemployment Claims": time(8, 30),
    "ISM Manufacturing PMI": time(10, 0),
    "ISM Services PMI": time(10, 0),
    "FOMC Statement": time(14, 0),
    "Federal Funds Rate": time(14, 0),
    "FOMC Economic Projections": time(14, 0),
    "FOMC Press Conference": time(14, 30),
    "FOMC Meeting Minutes": time(14, 0),
}

# Used when a title has no entry above. 08:30 ET covers almost every US macro
# release, so it is the least surprising guess.
DEFAULT_RELEASE_TIME_ET = time(8, 30)


def release_time_et(title: str) -> time:
    """The Eastern publication time for a title, or the 08:30 ET default."""
    return RELEASE_TIMES_ET.get(title, DEFAULT_RELEASE_TIME_ET)


def et_to_utc(day: date, clock: time) -> datetime:
    """Combine a US Eastern date and clock time into an aware UTC datetime.

    Ambiguous and non-existent local times (the two daylight-saving changeover
    hours) cannot arise here: no US macro release is published at 02:00 ET.
    """
    local = datetime.combine(day, clock).replace(tzinfo=EASTERN)
    return local.astimezone(UTC)


def scheduled_ts_utc(day: date, title: str) -> datetime:
    """The UTC timestamp for a release of ``title`` on Eastern date ``day``."""
    return et_to_utc(day, release_time_et(title))
