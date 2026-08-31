"""Fed regime classification - concept doc rule 2, "condition on regime"."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from fetchers.regime import (
    CUTTING,
    HIKING,
    HOLDING,
    REGIMES,
    THRESHOLD,
    WINDOW_DAYS,
    classify_regime,
)


def ramp(start_day: date, days: int, first: float, last: float) -> list[tuple[date, float]]:
    """A daily series moving linearly from ``first`` to ``last``."""
    if days == 1:
        return [(start_day, first)]
    step = (last - first) / (days - 1)
    return [(start_day + timedelta(days=i), first + step * i) for i in range(days)]


ASOF = date(2026, 8, 31)
START = ASOF - timedelta(days=200)


class TestClassify:
    def test_a_rising_rate_is_hiking(self):
        series = ramp(START, 201, 3.00, 5.00)
        assert classify_regime(series, ASOF) == HIKING

    def test_a_falling_rate_is_cutting(self):
        series = ramp(START, 201, 5.00, 3.00)
        assert classify_regime(series, ASOF) == CUTTING

    def test_a_flat_rate_is_holding(self):
        series = [(START + timedelta(days=i), 4.33) for i in range(201)]
        assert classify_regime(series, ASOF) == HOLDING

    def test_one_quarter_point_hike_is_enough(self):
        """A single 25bp move must register; the threshold is half of one."""
        series = [
            (day, 4.00 if (ASOF - day).days > 30 else 4.25)
            for day in [START + timedelta(days=i) for i in range(201)]
        ]
        assert classify_regime(series, ASOF) == HIKING

    def test_one_quarter_point_cut_is_enough(self):
        series = [
            (day, 4.50 if (ASOF - day).days > 30 else 4.25)
            for day in [START + timedelta(days=i) for i in range(201)]
        ]
        assert classify_regime(series, ASOF) == CUTTING

    def test_noise_below_the_threshold_stays_holding(self):
        """The effective rate twitches around quarter ends; that is not policy."""
        series = [
            (day, 4.33 + (0.05 if i % 2 else 0.0))
            for i, day in enumerate(START + timedelta(days=i) for i in range(201))
        ]
        assert classify_regime(series, ASOF) == HOLDING

    def test_the_threshold_boundary(self):
        before = ASOF - timedelta(days=WINDOW_DAYS)
        series = [(before, 4.00), (ASOF, 4.00 + THRESHOLD)]
        assert classify_regime(series, ASOF) == HOLDING, "exactly at the threshold holds"
        series = [(before, 4.00), (ASOF, 4.00 + THRESHOLD + 0.01)]
        assert classify_regime(series, ASOF) == HIKING

    def test_only_the_window_matters(self):
        """A hike a year ago does not make today a hiking regime."""
        old = ramp(ASOF - timedelta(days=400), 100, 3.00, 5.00)
        flat = [(ASOF - timedelta(days=d), 5.00) for d in range(120, -1, -1)]
        assert classify_regime(old + flat, ASOF) == HOLDING

    def test_it_reads_the_regime_at_a_past_date_not_today(self):
        """Tagging a 2022 event must use 2022's rates, not the latest ones."""
        hiking = ramp(date(2022, 1, 1), 200, 0.25, 2.50)
        cutting = ramp(date(2024, 8, 1), 200, 5.50, 4.50)
        series = hiking + cutting
        assert classify_regime(series, date(2022, 7, 1)) == HIKING
        assert classify_regime(series, date(2025, 1, 1)) == CUTTING


class TestGaps:
    def test_weekend_gaps_are_tolerated(self):
        """The series is daily but skips weekends; exact matching would fail."""
        series = [
            (day, 4.00 + (0.5 if (day - START).days > 150 else 0.0))
            for day in (START + timedelta(days=i) for i in range(201))
            if (START + timedelta(days=(day - START).days)).weekday() < 5
        ]
        assert classify_regime(series, ASOF) == HIKING

    def test_asof_on_a_weekend_uses_the_last_weekday(self):
        series = ramp(START, 201, 3.00, 5.00)
        saturday = date(2026, 8, 29)
        assert saturday.weekday() == 5
        assert classify_regime(series, saturday) == HIKING

    def test_unsorted_input_is_handled(self):
        series = list(reversed(ramp(START, 201, 3.00, 5.00)))
        assert classify_regime(series, ASOF) == HIKING


class TestInsufficientData:
    def test_empty_series_gives_none(self):
        assert classify_regime([], ASOF) is None

    def test_no_history_before_the_window_gives_none(self):
        """A thin backfill must not label a decade of events as holding."""
        series = ramp(ASOF - timedelta(days=10), 11, 4.00, 4.00)
        assert classify_regime(series, ASOF) is None

    def test_no_observation_at_or_before_asof_gives_none(self):
        series = ramp(date(2027, 1, 1), 200, 4.0, 4.0)
        assert classify_regime(series, ASOF) is None

    def test_none_is_returned_not_holding(self):
        """None and "holding" mean different things and must not be conflated."""
        assert classify_regime([], ASOF) is not HOLDING


class TestContract:
    def test_output_is_always_a_known_regime_or_none(self):
        series = ramp(START, 201, 3.0, 5.0)
        for offset in range(0, 200, 17):
            result = classify_regime(series, START + timedelta(days=offset))
            assert result is None or result in REGIMES

    def test_regimes_match_the_database_constraint(self):
        """sql/001_init.sql constrains events.regime to these three values."""
        assert set(REGIMES) == {"hiking", "holding", "cutting"}

    def test_window_is_ninety_days(self):
        assert WINDOW_DAYS == 90
