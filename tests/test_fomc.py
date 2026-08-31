"""FOMC calendar parsing, against the captured Federal Reserve page."""

from __future__ import annotations

from datetime import date

import pytest

from fetchers.fomc import (
    FALLBACK_DECISION_DATES,
    _last_day,
    _last_month,
    parse_fomc_calendar,
)


class TestParseCalendar:
    def test_finds_every_meeting_in_the_fixture(self, fomc_html):
        assert len(parse_fomc_calendar(fomc_html)) == 12

    def test_returns_the_closing_day_not_the_opening_one(self, fomc_html):
        """A decision is announced on day two of a two-day meeting."""
        dates = parse_fomc_calendar(fomc_html)
        assert date(2026, 1, 28) in dates
        assert date(2026, 1, 27) not in dates

    def test_matches_the_published_2026_schedule(self, fomc_html):
        dates = parse_fomc_calendar(fomc_html)
        expected = [
            date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
            date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
            date(2026, 10, 28), date(2026, 12, 9),
        ]
        assert [d for d in dates if d.year == 2026] == expected

    def test_meeting_spanning_two_months_takes_the_later_one(self, fomc_html):
        """"January/February" with "31-1" closes on 1 February."""
        assert date(2027, 2, 1) in parse_fomc_calendar(fomc_html)

    def test_asterisk_marking_a_projections_meeting_is_ignored(self, fomc_html):
        assert date(2026, 3, 18) in parse_fomc_calendar(fomc_html)

    def test_years_are_kept_apart(self, fomc_html):
        dates = parse_fomc_calendar(fomc_html)
        assert {d.year for d in dates} == {2026, 2027}

    def test_results_are_sorted_and_unique(self, fomc_html):
        dates = parse_fomc_calendar(fomc_html)
        assert dates == sorted(set(dates))

    def test_empty_html_yields_nothing_rather_than_raising(self):
        assert parse_fomc_calendar("") == []

    def test_page_without_year_headings_yields_nothing(self):
        assert parse_fomc_calendar("<html><body>no meetings here</body></html>") == []

    def test_a_broken_row_does_not_lose_the_others(self):
        html = """
        <h4>2026 FOMC Meetings</h4>
        <div class="fomc-meeting__month"><strong>Januturday</strong></div>
        <div class="fomc-meeting__date">27-28</div>
        <div class="fomc-meeting__month"><strong>March</strong></div>
        <div class="fomc-meeting__date">17-18*</div>
        """
        assert parse_fomc_calendar(html) == [date(2026, 3, 18)]


class TestHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [("27-28*", 28), ("27-28", 28), ("31-1", 1), ("8-9*", 9), ("17", 17)],
    )
    def test_last_day(self, raw, expected):
        assert _last_day(raw) == expected

    @pytest.mark.parametrize("raw", ["", "*", "abc"])
    def test_last_day_rejects_junk(self, raw):
        assert _last_day(raw) is None

    def test_last_day_rejects_impossible_days(self):
        assert _last_day("40") is None

    @pytest.mark.parametrize(
        "raw,expected",
        [("January", 1), ("January/February", 2), ("december", 12), ("  March  ", 3)],
    )
    def test_last_month(self, raw, expected):
        assert _last_month(raw) == expected

    def test_last_month_rejects_junk(self):
        assert _last_month("Smarch") is None


class TestFallbackTable:
    def test_is_sorted_and_unique(self):
        assert list(FALLBACK_DECISION_DATES) == sorted(set(FALLBACK_DECISION_DATES))

    def test_has_eight_meetings_a_year(self):
        """The FOMC holds eight regularly scheduled meetings each year."""
        for year in (2026, 2027):
            assert sum(1 for d in FALLBACK_DECISION_DATES if d.year == year) == 8

    def test_agrees_with_the_captured_page_where_they_overlap(self, fomc_html):
        parsed = set(parse_fomc_calendar(fomc_html))
        overlap = [d for d in FALLBACK_DECISION_DATES if d in parsed]
        assert len(overlap) >= 8, "the transcribed table has drifted from the page"
