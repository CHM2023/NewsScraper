"""The diff that decides whether the trader gets a message."""

from __future__ import annotations

from datetime import timedelta

import pytest

from common.timeutil import UTC, parse_iso
from fetchers.diff import Change, diff_events, values_differ

TS = parse_iso("2026-09-04T12:30:00Z")


def row(event_id="USD|CPI m/m|2026-09-04", *, ts=TS, forecast=0.3, **extra):
    base = {
        "id": event_id,
        "title": "CPI m/m",
        "ts_utc": ts,
        "forecast": forecast,
        "weight": 5,
    }
    base.update(extra)
    return base


class TestValuesDiffer:
    def test_equal_values_do_not(self):
        assert values_differ(0.3, 0.3) is False

    def test_float_noise_is_not_a_revision(self):
        assert values_differ(0.3, 0.1 + 0.2) is False

    def test_a_real_revision_is(self):
        assert values_differ(0.3, 0.4) is True

    def test_both_none_is_not_a_change(self):
        assert values_differ(None, None) is False

    def test_none_to_value_is_a_change(self):
        """The moment a consensus is published is worth reporting."""
        assert values_differ(None, 0.3) is True

    def test_value_to_none_is_a_change(self):
        assert values_differ(0.3, None) is True

    def test_datetimes_compare_by_instant(self):
        assert values_differ(TS, TS) is False
        assert values_differ(TS, TS + timedelta(minutes=30)) is True

    def test_same_instant_written_two_ways_is_not_a_change(self):
        assert values_differ(TS, parse_iso("2026-09-04T08:30:00-04:00")) is False


class TestDiffEvents:
    def test_unknown_id_is_new(self):
        result = diff_events([row()], {})
        assert result.counts == (1, 0, 0)
        assert result.new[0]["id"] == "USD|CPI m/m|2026-09-04"

    def test_identical_row_is_unchanged(self):
        stored = {row()["id"]: row()}
        result = diff_events([row()], stored)
        assert result.counts == (0, 0, 1)

    def test_moved_forecast_is_changed(self):
        stored = {row()["id"]: row(forecast=0.3)}
        result = diff_events([row(forecast=0.4)], stored)
        assert result.counts == (0, 1, 0)
        _, changes = result.changed[0]
        assert [c.field for c in changes] == ["forecast"]
        assert (changes[0].old, changes[0].new) == (0.3, 0.4)

    def test_moved_time_is_changed(self):
        stored = {row()["id"]: row(ts=TS)}
        incoming = row(ts=TS + timedelta(hours=1))
        result = diff_events([incoming], stored)
        assert result.counts == (0, 1, 0)
        assert result.changed[0][1][0].field == "ts_utc"

    def test_both_fields_moving_reports_both(self):
        stored = {row()["id"]: row(ts=TS, forecast=0.3)}
        incoming = row(ts=TS + timedelta(hours=1), forecast=0.5)
        _, changes = diff_events([incoming], stored).changed[0]
        assert {c.field for c in changes} == {"ts_utc", "forecast"}

    def test_unwatched_field_moving_is_not_a_change(self):
        """previous and impact are written through without waking anyone."""
        stored = {row()["id"]: row(previous=0.2, impact="High")}
        incoming = row(previous=0.9, impact="Low")
        assert diff_events([incoming], stored).counts == (0, 0, 1)

    def test_skeleton_row_gaining_a_forecast_is_changed(self):
        """A skeleton row has no forecast; ff_sync supplying one is news."""
        stored = {row()["id"]: row(forecast=None)}
        result = diff_events([row(forecast=0.3)], stored)
        assert result.counts == (0, 1, 0)

    def test_duplicate_ids_in_one_feed_are_collapsed(self):
        result = diff_events([row(), row(forecast=0.9)], {})
        assert result.counts == (1, 0, 0)
        assert result.new[0]["forecast"] == 0.3, "the first occurrence wins"

    def test_rows_without_an_id_are_dropped(self):
        assert diff_events([{"title": "x"}], {}).counts == (0, 0, 0)

    def test_mixed_batch(self):
        stored = {
            "USD|CPI m/m|2026-09-04": row(forecast=0.3),
            "USD|PPI m/m|2026-09-04": row("USD|PPI m/m|2026-09-04", forecast=0.2),
        }
        incoming = [
            row(forecast=0.3),
            row("USD|PPI m/m|2026-09-04", forecast=0.5),
            row("USD|Retail Sales m/m|2026-09-04"),
        ]
        result = diff_events(incoming, stored)
        assert result.counts == (1, 1, 1)

    def test_custom_watch_list(self):
        stored = {row()["id"]: row(previous=0.2)}
        result = diff_events([row(previous=0.9)], stored, watched=("previous",))
        assert result.counts == (0, 1, 0)


class TestChange:
    def test_describe_is_readable(self):
        assert Change("forecast", 0.3, 0.4).describe() == "forecast: 0.3 -> 0.4"

    def test_describe_handles_none(self):
        assert Change("forecast", None, 0.4).describe() == "forecast: none -> 0.4"

    def test_describe_renders_datetimes_iso(self):
        described = Change("ts_utc", TS, TS).describe()
        assert "2026-09-04T12:30:00+00:00" in described
