"""The ForexFactory sync: parsing the feed, filtering it, and what it says."""

from __future__ import annotations

from datetime import timedelta

import pytest

from common.timeutil import UTC, parse_iso
from fetchers import ff_sync
from fetchers.diff import Change, diff_events


class TestParseEntry:
    def test_a_usd_row_becomes_an_event(self, ff_thisweek, weights):
        entry = next(e for e in ff_thisweek if e["title"] == "Non-Farm Employment Change")
        row = ff_sync.parse_entry(entry, weights)
        assert row["id"] == "USD|Non-Farm Employment Change|2026-09-04"
        assert row["title"] == "Non-Farm Employment Change"
        assert row["country"] == "USD"
        assert row["ts_utc"] == parse_iso("2026-09-04T08:30:00-04:00")
        assert row["impact"] == "High"
        assert row["weight"] == 4
        assert row["forecast"] == pytest.approx(165_000.0)
        assert row["previous"] == pytest.approx(142_000.0)
        assert row["source"] == "forexfactory"

    @pytest.mark.parametrize("country", ["JPY", "EUR", "All"])
    def test_other_countries_are_dropped(self, ff_thisweek, weights, country):
        for entry in (e for e in ff_thisweek if e["country"] == country):
            assert ff_sync.parse_entry(entry, weights) is None

    def test_percentages_are_parsed(self, ff_thisweek, weights):
        entry = next(e for e in ff_thisweek if e["title"] == "Unemployment Rate")
        assert ff_sync.parse_entry(entry, weights)["forecast"] == pytest.approx(4.3)

    def test_an_empty_forecast_becomes_none(self, ff_thisweek, weights):
        entry = next(e for e in ff_thisweek if e["title"] == "Fed Chair Powell Speaks")
        assert ff_sync.parse_entry(entry, weights)["forecast"] is None

    def test_an_office_holder_title_still_gets_its_weight(self, ff_thisweek, weights):
        entry = next(e for e in ff_thisweek if e["title"] == "Fed Chair Powell Speaks")
        assert ff_sync.parse_entry(entry, weights)["weight"] == 4

    def test_an_unseeded_title_gets_weight_one(self, ff_thisweek, weights):
        entry = next(e for e in ff_thisweek if e["title"] == "Federal Budget Balance")
        assert ff_sync.parse_entry(entry, weights)["weight"] == 1

    @pytest.mark.parametrize(
        "entry",
        [
            {},
            {"country": "USD"},
            {"country": "USD", "title": "CPI m/m"},
            {"country": "USD", "title": "", "date": "2026-09-04T08:30:00-04:00"},
            {"country": "USD", "title": "CPI m/m", "date": "not a date"},
            {"country": "USD", "title": "CPI m/m", "date": "2026-09-04T08:30:00"},
            "not a dict",
        ],
    )
    def test_unusable_rows_return_none_rather_than_raising(self, entry, weights):
        assert ff_sync.parse_entry(entry, weights) is None


class TestCollect:
    def test_keeps_only_usd_rows(self, ff_thisweek, weights, monkeypatch):
        from common.stats import Stats

        monkeypatch.setattr(ff_sync, "fetch_feed", lambda url: list(ff_thisweek))
        stats = Stats("test")
        rows = ff_sync.collect(["one-feed"], weights, stats)

        assert {r["country"] for r in rows} == {"USD"}
        assert len(rows) == 8
        assert stats.fetched == len(ff_thisweek)

    def test_two_feeds_are_merged_and_deduplicated(self, ff_thisweek, weights, monkeypatch):
        from common.stats import Stats

        monkeypatch.setattr(ff_sync, "fetch_feed", lambda url: list(ff_thisweek))
        rows = ff_sync.collect(["a", "b"], weights, Stats("test"))
        assert len(rows) == 8, "the same release in both feeds must not double up"

    def test_an_unavailable_feed_is_counted_not_fatal(self, ff_thisweek, weights, monkeypatch):
        from common.stats import Stats

        def flaky(url):
            return list(ff_thisweek) if url == "good" else None

        monkeypatch.setattr(ff_sync, "fetch_feed", flaky)
        stats = Stats("test")
        rows = ff_sync.collect(["good", "dead"], weights, stats)

        assert len(rows) == 8, "the working feed must still be used"
        assert stats.errors == 1

    def test_rows_come_back_sorted_by_id(self, ff_thisweek, weights, monkeypatch):
        from common.stats import Stats

        monkeypatch.setattr(ff_sync, "fetch_feed", lambda url: list(ff_thisweek))
        rows = ff_sync.collect(["one"], weights, Stats("test"))
        assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)


class TestMessages:
    def _row(self, **extra):
        base = {
            "id": "USD|CPI m/m|2026-10-14",
            "title": "CPI m/m",
            "ts_utc": parse_iso("2026-10-14T12:30:00Z"),
            "weight": 5,
            "forecast": 0.3,
        }
        base.update(extra)
        return base

    def test_new_message_matches_the_brief(self):
        """NEW: <title> - <UTC time> - weight <n> - forecast <x>"""
        message = ff_sync.format_new(self._row())
        assert message == (
            "NEW: CPI m/m - 2026-10-14T12:30:00+00:00 - weight 5 - forecast 0.3"
        )

    def test_new_message_without_a_forecast(self):
        assert ff_sync.format_new(self._row(forecast=None)).endswith("forecast n/a")

    def test_large_forecasts_are_not_rendered_in_scientific_notation(self):
        message = ff_sync.format_new(self._row(forecast=165_000.0))
        assert "165000" in message and "e+" not in message

    def test_changed_message_names_what_moved(self):
        message = ff_sync.format_changed(
            self._row(forecast=0.4), [Change("forecast", 0.3, 0.4)]
        )
        assert message.startswith("CHANGED: CPI m/m")
        assert "forecast: 0.3 -> 0.4" in message

    def test_changed_message_lists_several_moves(self):
        message = ff_sync.format_changed(
            self._row(),
            [Change("ts_utc", "a", "b"), Change("forecast", 0.3, 0.4)],
        )
        assert "ts_utc" in message and "forecast" in message


class TestAnnounce:
    def _result(self, weight):
        row = {
            "id": "USD|X|2026-10-14",
            "title": "X",
            "ts_utc": parse_iso("2026-10-14T12:30:00Z"),
            "weight": weight,
            "forecast": 0.3,
        }
        return diff_events([row], {}), row

    def test_high_weight_events_are_sent(self, monkeypatch):
        from common.stats import Stats

        sent = []
        monkeypatch.setattr(ff_sync.notify, "send", lambda m, **kw: sent.append(m) or True)
        result, _ = self._result(5)
        ff_sync.announce(result, Stats("t"))
        assert len(sent) == 1

    @pytest.mark.parametrize("weight", [1, 2, 3])
    def test_low_weight_events_are_stored_silently(self, monkeypatch, weight):
        from common.stats import Stats

        sent = []
        monkeypatch.setattr(ff_sync.notify, "send", lambda m, **kw: sent.append(m) or True)
        result, _ = self._result(weight)
        ff_sync.announce(result, Stats("t"))
        assert sent == [], "only weight >= 4 may interrupt the trader"

    def test_the_threshold_is_four(self, monkeypatch):
        from common.stats import Stats

        sent = []
        monkeypatch.setattr(ff_sync.notify, "send", lambda m, **kw: sent.append(m) or True)
        result, _ = self._result(4)
        ff_sync.announce(result, Stats("t"))
        assert len(sent) == 1
        assert ff_sync.NOTIFY_MIN_WEIGHT == 4

    def test_quiet_mode_sends_nothing(self, monkeypatch):
        from common.stats import Stats

        sent = []
        monkeypatch.setattr(ff_sync.notify, "send", lambda m, **kw: sent.append(m) or True)
        result, _ = self._result(5)
        ff_sync.announce(result, Stats("t"), quiet=True)
        assert sent == []


class TestSerialise:
    def test_timestamp_becomes_an_iso_string_with_an_offset(self):
        row = {
            "id": "USD|CPI m/m|2026-10-14",
            "title": "CPI m/m",
            "country": "USD",
            "ts_utc": parse_iso("2026-10-14T12:30:00Z"),
            "impact": "High",
            "weight": 5,
            "forecast": 0.3,
            "previous": 0.2,
            "source": "forexfactory",
        }
        out = ff_sync._serialise(row)
        assert out["ts_utc"] == "2026-10-14T12:30:00+00:00"
        assert isinstance(out["ts_utc"], str)

    def test_every_row_carries_the_same_columns(self, ff_thisweek, weights, monkeypatch):
        """PostgREST requires uniform keys across one upsert batch."""
        from common.stats import Stats

        monkeypatch.setattr(ff_sync, "fetch_feed", lambda url: list(ff_thisweek))
        rows = ff_sync.collect(["one"], weights, Stats("t"))
        keysets = {tuple(sorted(ff_sync._serialise(r))) for r in rows}
        assert len(keysets) == 1
        assert set(keysets.pop()) == set(ff_sync.WRITE_COLUMNS)
