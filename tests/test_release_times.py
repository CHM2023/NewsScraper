"""Release clock times and the Eastern-to-UTC conversion.

The concept doc names daylight saving as the bug most likely to break the
reminder and blackout logic silently. These tests pin the behaviour on both
sides of both changeovers.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from common.timeutil import UTC
from fetchers.release_times import (
    DEFAULT_RELEASE_TIME_ET,
    RELEASE_TIMES_ET,
    et_to_utc,
    release_time_et,
    scheduled_ts_utc,
)


class TestEtToUtc:
    def test_summer_is_utc_minus_four(self):
        """08:30 EDT is 12:30 UTC."""
        assert et_to_utc(date(2026, 7, 15), time(8, 30)).hour == 12

    def test_winter_is_utc_minus_five(self):
        """08:30 EST is 13:30 UTC - an hour later than in summer."""
        assert et_to_utc(date(2026, 1, 15), time(8, 30)).hour == 13

    def test_the_offset_actually_changes_across_the_year(self):
        summer = et_to_utc(date(2026, 7, 15), time(8, 30))
        winter = et_to_utc(date(2026, 1, 15), time(8, 30))
        assert summer.hour != winter.hour, "daylight saving is being ignored"

    @pytest.mark.parametrize(
        "day,expected_hour",
        [
            (date(2026, 3, 7), 13),   # before the March changeover: EST
            (date(2026, 3, 14), 12),  # after it: EDT
            (date(2026, 10, 31), 12),  # before the November changeover: EDT
            (date(2026, 11, 7), 13),  # after it: EST
        ],
    )
    def test_either_side_of_each_changeover(self, day, expected_hour):
        assert et_to_utc(day, time(8, 30)).hour == expected_hour

    def test_result_is_aware_and_utc(self):
        value = et_to_utc(date(2026, 7, 15), time(8, 30))
        assert value.tzinfo is not None
        assert value.utcoffset().total_seconds() == 0

    def test_minutes_survive(self):
        assert et_to_utc(date(2026, 7, 15), time(8, 30)).minute == 30

    def test_fomc_afternoon_stays_on_the_same_utc_day(self):
        """14:00 ET is 18:00 UTC, so the event id keeps the US date."""
        value = et_to_utc(date(2026, 9, 16), time(14, 0))
        assert (value.date(), value.hour) == (date(2026, 9, 16), 18)


class TestReleaseTimes:
    def test_known_titles(self):
        assert release_time_et("CPI m/m") == time(8, 30)
        assert release_time_et("ISM Manufacturing PMI") == time(10, 0)
        assert release_time_et("FOMC Statement") == time(14, 0)

    def test_unknown_title_uses_the_default(self):
        assert release_time_et("Beige Book") == DEFAULT_RELEASE_TIME_ET == time(8, 30)

    def test_every_release_lands_inside_the_us_trading_day(self):
        """No release may cross midnight UTC, or the event id would shift days."""
        for title in RELEASE_TIMES_ET:
            for day in (date(2026, 1, 15), date(2026, 7, 15)):
                ts = scheduled_ts_utc(day, title)
                assert ts.date() == day, f"{title} moved off its US date"
                assert 8 <= ts.hour <= 23, f"{title} at {ts.hour}:00 UTC"


class TestScheduledTs:
    def test_combines_lookup_and_conversion(self):
        assert scheduled_ts_utc(date(2026, 9, 4), "Non-Farm Employment Change").hour == 12

    def test_matches_what_the_feed_would_publish(self):
        from common.timeutil import parse_iso

        assert scheduled_ts_utc(date(2026, 9, 1), "ISM Manufacturing PMI") == parse_iso(
            "2026-09-01T10:00:00-04:00"
        )
