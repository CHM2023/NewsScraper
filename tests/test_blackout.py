"""Blackout windows around high-weight releases."""

from __future__ import annotations

from datetime import timedelta

import pytest

from common.timeutil import NaiveDatetimeError, parse_iso
from fetchers.blackout import (
    AFTER_MINUTES,
    BEFORE_MINUTES,
    MIN_WEIGHT,
    active_window,
    blackout_windows,
    is_in_blackout,
    merge_windows,
    next_window,
)

RELEASE = parse_iso("2026-10-14T12:30:00Z")


def event(title="CPI m/m", *, weight=5, ts=RELEASE, event_id=None):
    return {
        "id": event_id or f"USD|{title}|2026-10-14",
        "title": title,
        "weight": weight,
        "ts_utc": ts,
    }


class TestWindows:
    def test_one_window_per_qualifying_event(self):
        assert len(blackout_windows([event()])) == 1

    def test_window_spans_before_and_after_the_release(self):
        window = blackout_windows([event()])[0]
        assert window.start == RELEASE - timedelta(minutes=BEFORE_MINUTES)
        assert window.end == RELEASE + timedelta(minutes=AFTER_MINUTES)

    def test_the_window_is_asymmetric(self):
        """Liquidity thins before the print sooner than it returns after it."""
        assert BEFORE_MINUTES > AFTER_MINUTES

    @pytest.mark.parametrize("weight", [1, 2, 3])
    def test_low_weight_events_produce_no_window(self, weight):
        assert blackout_windows([event(weight=weight)]) == []

    def test_the_bar_is_weight_four(self):
        assert MIN_WEIGHT == 4
        assert len(blackout_windows([event(weight=4)])) == 1

    def test_custom_margins(self):
        window = blackout_windows([event()], before_minutes=60, after_minutes=60)[0]
        assert window.start == RELEASE - timedelta(minutes=60)
        assert window.end == RELEASE + timedelta(minutes=60)

    def test_windows_come_back_in_time_order(self):
        events = [
            event("Late", ts=RELEASE + timedelta(hours=2)),
            event("Early", ts=RELEASE),
        ]
        titles = [w.title for w in blackout_windows(events)]
        assert titles == ["Early", "Late"]

    def test_events_without_a_timestamp_are_skipped(self):
        assert blackout_windows([{"id": "x", "title": "y", "weight": 5}]) == []

    def test_a_missing_weight_is_treated_as_zero(self):
        assert blackout_windows([{"id": "x", "title": "y", "ts_utc": RELEASE}]) == []

    def test_a_naive_timestamp_is_rejected(self):
        from datetime import datetime

        with pytest.raises(NaiveDatetimeError):
            blackout_windows([event(ts=datetime(2026, 10, 14, 12, 30))])


class TestActiveWindow:
    def test_inside_the_window(self):
        assert is_in_blackout(RELEASE, [event()]) is True

    def test_just_before_the_window_opens(self):
        moment = RELEASE - timedelta(minutes=BEFORE_MINUTES + 1)
        assert is_in_blackout(moment, [event()]) is False

    def test_at_the_moment_it_opens(self):
        moment = RELEASE - timedelta(minutes=BEFORE_MINUTES)
        assert is_in_blackout(moment, [event()]) is True

    def test_at_the_moment_it_closes(self):
        moment = RELEASE + timedelta(minutes=AFTER_MINUTES)
        assert is_in_blackout(moment, [event()]) is True

    def test_just_after_it_closes(self):
        moment = RELEASE + timedelta(minutes=AFTER_MINUTES + 1)
        assert is_in_blackout(moment, [event()]) is False

    def test_it_names_the_event(self):
        window = active_window(RELEASE, [event()])
        assert window.title == "CPI m/m"
        assert window.event_id == "USD|CPI m/m|2026-10-14"

    def test_simultaneous_releases_report_the_heaviest(self):
        """The 08:30 employment trio: the trader stands aside for the NFP."""
        events = [
            event("Average Hourly Earnings m/m", weight=4, event_id="a"),
            event("Non-Farm Employment Change", weight=5, event_id="b"),
        ]
        assert active_window(RELEASE, events).title == "Non-Farm Employment Change"

    def test_no_events_means_no_blackout(self):
        assert active_window(RELEASE, []) is None

    def test_naive_moment_is_rejected(self):
        from datetime import datetime

        with pytest.raises(NaiveDatetimeError):
            is_in_blackout(datetime(2026, 10, 14, 12, 30), [event()])


class TestNextWindow:
    def test_finds_the_next_one(self):
        moment = RELEASE - timedelta(hours=5)
        assert next_window(moment, [event()]).title == "CPI m/m"

    def test_ignores_windows_already_started(self):
        assert next_window(RELEASE, [event()]) is None

    def test_picks_the_earliest_of_several(self):
        events = [
            event("Later", ts=RELEASE + timedelta(days=1)),
            event("Sooner", ts=RELEASE),
        ]
        moment = RELEASE - timedelta(hours=5)
        assert next_window(moment, events).title == "Sooner"

    def test_minutes_until_start(self):
        moment = RELEASE - timedelta(minutes=90)
        window = next_window(moment, [event()])
        assert window.minutes_until_start(moment) == pytest.approx(60.0)


class TestMerge:
    def test_identical_windows_collapse_to_one(self):
        events = [event("a", event_id="a"), event("b", event_id="b")]
        assert len(merge_windows(blackout_windows(events))) == 1

    def test_separate_windows_stay_separate(self):
        events = [event("a", event_id="a"), event("b", event_id="b", ts=RELEASE + timedelta(hours=6))]
        assert len(merge_windows(blackout_windows(events))) == 2

    def test_overlapping_windows_are_joined(self):
        events = [
            event("a", event_id="a"),
            event("b", event_id="b", ts=RELEASE + timedelta(minutes=20)),
        ]
        merged = merge_windows(blackout_windows(events))
        assert len(merged) == 1
        assert merged[0][0] == RELEASE - timedelta(minutes=BEFORE_MINUTES)
        assert merged[0][1] == RELEASE + timedelta(minutes=20 + AFTER_MINUTES)

    def test_empty_input(self):
        assert merge_windows([]) == []
