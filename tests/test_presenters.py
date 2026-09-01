"""View models: colours, number formatting, and the no-local-time rule."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from common.timeutil import UTC, NaiveDatetimeError, parse_iso
from fetchers.blackout import blackout_windows
from web import presenters

TS = parse_iso("2026-10-14T12:30:00Z")


def row(**extra):
    base = {
        "id": "USD|CPI m/m|2026-10-14",
        "title": "CPI m/m",
        "country": "USD",
        "ts_utc": TS,
        "impact": "High",
        "weight": 5,
        "forecast": 0.3,
        "previous": 0.2,
        "actual": None,
        "surprise": None,
        "regime": "holding",
        "source": "forexfactory",
    }
    base.update(extra)
    return base


class TestWeightColours:
    def test_weight_five_is_red(self):
        assert presenters.weight_colour(5) == "#c0392b"

    def test_weight_four_is_orange(self):
        assert presenters.weight_colour(4) == "#e67e22"

    @pytest.mark.parametrize("weight", [1, 2, 3])
    def test_lower_weights_are_grey(self, weight):
        assert presenters.weight_colour(weight) == presenters.LOW_WEIGHT_COLOUR

    def test_missing_weight_is_grey(self):
        assert presenters.weight_colour(None) == presenters.LOW_WEIGHT_COLOUR

    @pytest.mark.parametrize(
        "weight,expected", [(5, "w5"), (4, "w4"), (3, "w-low"), (1, "w-low"), (None, "w-low")]
    )
    def test_css_classes(self, weight, expected):
        assert presenters.weight_class(weight) == expected


class TestFormatNumber:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (0.3, "0.3"),
            (4.3, "4.3"),
            (-0.1, "-0.1"),
            (48, "48"),
            (48.0, "48"),
            (165_000.0, "165K"),
            (7_380_000.0, "7.38M"),
            (-291_100_000_000.0, "-291.10B"),
        ],
    )
    def test_rendering(self, value, expected):
        assert presenters.format_number(value) == expected

    def test_missing_reads_n_a_not_zero(self):
        """A forecast that was never published must not look like a zero."""
        assert presenters.format_number(None) == "n/a"

    def test_zero_is_shown_as_zero(self):
        assert presenters.format_number(0) == "0"

    def test_unparseable_value_is_passed_through(self):
        assert presenters.format_number("weird") == "weird"

    def test_unit_suffix(self):
        assert presenters.format_number(0.3, unit="%") == "0.3%"


class TestSurprise:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, "n/a"),
            (1.2, "+1.2 (above forecast)"),
            (-1.2, "-1.2 (below forecast)"),
            (0.0, "+0.0 (in line)"),
        ],
    )
    def test_formatting(self, value, expected):
        assert presenters.format_surprise(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [(None, "s-none"), (1.2, "s-up"), (-1.2, "s-down"), (0.1, "s-flat")],
    )
    def test_classes(self, value, expected):
        assert presenters.surprise_class(value) == expected


class TestEventView:
    def test_shape(self):
        view = presenters.event_view(row())
        assert view["title"] == "CPI m/m"
        assert view["weight"] == 5
        assert view["weight_class"] == "w5"
        assert view["forecast"] == "0.3"
        assert view["previous"] == "0.2"
        assert view["actual"] == "n/a"
        assert view["has_actual"] is False

    def test_timestamp_is_utc_iso_with_an_offset(self):
        """The server must never emit a local time."""
        assert presenters.event_view(row())["ts_utc"] == "2026-10-14T12:30:00+00:00"

    def test_a_string_timestamp_from_postgrest_is_accepted(self):
        view = presenters.event_view(row(ts_utc="2026-10-14T12:30:00+00:00"))
        assert view["ts_utc"] == "2026-10-14T12:30:00+00:00"

    def test_an_offset_timestamp_is_normalised_to_utc(self):
        view = presenters.event_view(row(ts_utc="2026-10-14T08:30:00-04:00"))
        assert view["ts_utc"] == "2026-10-14T12:30:00+00:00"

    def test_a_naive_timestamp_is_rejected(self):
        with pytest.raises(NaiveDatetimeError):
            presenters.event_view(row(ts_utc=datetime(2026, 10, 14, 12, 30)))

    def test_missing_regime_reads_unknown(self):
        assert presenters.event_view(row(regime=None))["regime"] == "unknown"

    def test_missing_impact_reads_dash(self):
        assert presenters.event_view(row(impact=None))["impact"] == "-"

    def test_has_actual_is_true_once_filled(self):
        assert presenters.event_view(row(actual=0.4))["has_actual"] is True


class TestCalendarEvent:
    def test_fullcalendar_shape(self):
        event = presenters.calendar_event(row())
        assert event["id"] == "USD|CPI m/m|2026-10-14"
        assert event["title"] == "CPI m/m"
        assert event["start"] == "2026-10-14T12:30:00Z"
        assert event["backgroundColor"] == "#c0392b"

    def test_start_is_offset_aware_and_ends_in_z(self):
        """The feed must never hand FullCalendar a zoneless instant.

        A start with no offset is read as *local* time by the browser, which
        shifts every release by the viewer's UTC offset and shows it silently.
        That is the bug this assertion exists to catch.
        """
        start = presenters.calendar_event(row())["start"]
        assert start.endswith("Z"), start
        assert "+" not in start
        # Round-trips to the same instant the row carries.
        assert parse_iso(start) == parse_iso("2026-10-14T12:30:00+00:00")

    def test_colour_follows_weight(self):
        assert presenters.calendar_event(row(weight=4))["backgroundColor"] == "#e67e22"
        assert presenters.calendar_event(row(weight=1))["backgroundColor"] == "#7f8c8d"

    def test_detail_travels_in_extended_props(self):
        props = presenters.calendar_event(row(actual=0.4, surprise=1.1))["extendedProps"]
        assert props["actual"] == "0.4"
        assert props["surprise"].startswith("+1.1")
        assert props["regime"] == "holding"

    def test_many_events(self):
        assert len(presenters.calendar_events([row(), row(weight=3)])) == 2


class TestParseRangeParam:
    def test_bare_date_becomes_utc_midnight(self):
        value = presenters.parse_range_param("2026-09-01", field="start")
        assert value == datetime(2026, 9, 1, tzinfo=UTC)

    def test_full_timestamp_is_converted_to_utc(self):
        value = presenters.parse_range_param("2026-09-01T08:30:00-04:00", field="start")
        assert value == datetime(2026, 9, 1, 12, 30, tzinfo=UTC)

    def test_z_suffix(self):
        assert presenters.parse_range_param("2026-09-01T00:00:00Z", field="start").hour == 0

    @pytest.mark.parametrize("value", ["", "   ", "not a date"])
    def test_junk_raises(self, value):
        with pytest.raises(ValueError):
            presenters.parse_range_param(value, field="start")

    def test_a_timestamp_without_an_offset_is_rejected(self):
        with pytest.raises(NaiveDatetimeError):
            presenters.parse_range_param("2026-09-01T12:30:00", field="start")


class TestBlackoutView:
    def test_active_window(self):
        window = blackout_windows([row()])[0]
        view = presenters.blackout_view(window, TS)
        assert view["active"] is True
        assert view["title"] == "CPI m/m"
        assert view["ts_utc"] == "2026-10-14T12:30:00+00:00"

    def test_upcoming_window_counts_down(self):
        window = blackout_windows([row()])[0]
        moment = TS - timedelta(minutes=90)
        view = presenters.blackout_view(window, moment)
        assert view["active"] is False
        assert view["minutes_until"] == 60

    def test_countdown_never_goes_negative(self):
        window = blackout_windows([row()])[0]
        view = presenters.blackout_view(window, TS + timedelta(hours=5))
        assert view["minutes_until"] == 0


class TestSummarise:
    def test_counts(self):
        events = [row(weight=5), row(weight=4), row(weight=1)]
        assert presenters.summarise(events) == {"total": 3, "high": 2, "top": 1}

    def test_empty(self):
        assert presenters.summarise([]) == {"total": 0, "high": 0, "top": 0}
