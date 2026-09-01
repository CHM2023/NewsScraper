"""Price collection: merging sources, the gold fallback, and row shape."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from common.stats import Stats
from fetchers import prices_daily as pd

START = date(2026, 8, 1)
END = date(2026, 8, 31)


@pytest.fixture
def stats():
    return Stats("test")


def fred_stub(values_by_series):
    """Build a replacement for fred.fetch_observations from a dict."""

    def fetch(series_id, *, api_key, start=None, end=None, limit=None):
        return values_by_series.get(series_id, [])

    return fetch


class TestCollectPrices:
    def test_columns_are_merged_by_date(self, monkeypatch, stats):
        monkeypatch.setattr(
            pd.fred, "fetch_observations",
            fred_stub({
                "DTWEXBGS": [(END, 121.5)],
                "DFII10": [(END, 1.85)],
                "DFF": [(END, 4.33)],
            }),
        )
        monkeypatch.setattr(pd, "_yahoo_close", lambda *a, **k: {END: 2400.0})
        merged = pd.collect_prices("key", START, END, stats)
        assert merged[END] == {
            "xau_close": 2400.0,
            "dxy": 121.5,
            "real_yield_10y": 1.85,
            "fed_funds": 4.33,
        }

    def test_dates_outside_the_range_are_dropped(self, monkeypatch, stats):
        monkeypatch.setattr(
            pd.fred, "fetch_observations",
            fred_stub({
                "DTWEXBGS": [(END, 121.5)],
                "DFII10": [(date(2020, 1, 1), 1.0), (END, 1.85)],
                "DFF": [(END, 4.33)],
            }),
        )
        merged = pd.collect_prices("key", START, END, stats)
        assert date(2020, 1, 1) not in merged

    def test_a_partial_day_is_kept(self, monkeypatch, stats):
        """A day with only the Fed funds rate is still worth a row."""
        monkeypatch.setattr(
            pd.fred, "fetch_observations",
            fred_stub({
                "DTWEXBGS": [(END, 121.5)],
                "DFII10": [(END, 1.85)],
                "DFF": [(END, 4.33), (date(2026, 8, 30), 4.33)],
            }),
        )
        merged = pd.collect_prices("key", START, END, stats)
        assert merged[date(2026, 8, 30)] == {"fed_funds": 4.33}


class TestGoldSource:
    """FRED withdrew its LBMA gold series, so Yahoo is the only source now."""

    def test_no_fred_gold_series_is_configured(self):
        assert pd.FRED_GOLD_SERIES is None

    def test_fred_is_not_called_for_gold(self, monkeypatch, stats):
        """A configured-away series must not cost a 400 on every run."""
        asked = []

        def spy(series_id, **kwargs):
            asked.append(series_id)
            return []

        monkeypatch.setattr(pd.fred, "fetch_observations", spy)
        monkeypatch.setattr(pd, "_yahoo_close", lambda *a, **k: {END: 2405.0})
        pd.collect_prices("key", START, END, stats)
        assert "GOLDPMGBD228NLBM" not in asked

    def test_a_configured_fred_series_would_be_preferred(self, monkeypatch, stats):
        """The door is left open if FRED ever publishes one again."""
        monkeypatch.setattr(pd, "FRED_GOLD_SERIES", "SOMEGOLD")
        monkeypatch.setattr(
            pd.fred, "fetch_observations", fred_stub({"SOMEGOLD": [(END, 2400.0)]})
        )
        tickers = []
        monkeypatch.setattr(
            pd, "_yahoo_close", lambda ticker, *a, **k: tickers.append(ticker) or {}
        )
        merged = pd.collect_prices("key", START, END, stats)
        assert merged[END]["xau_close"] == 2400.0
        assert pd.YAHOO_GOLD not in tickers

    def test_an_empty_fred_series_falls_back_to_yahoo(self, monkeypatch, stats):
        monkeypatch.setattr(pd.fred, "fetch_observations", fred_stub({}))
        monkeypatch.setattr(
            pd, "_yahoo_close",
            lambda ticker, start, end, st: {END: 2405.0} if ticker == pd.YAHOO_GOLD else {},
        )
        merged = pd.collect_prices("key", START, END, stats)
        assert merged[END]["xau_close"] == 2405.0

    def test_a_stale_fred_series_falls_back(self, monkeypatch, stats):
        """The LBMA series went stale before it was withdrawn entirely."""
        stale_day = END - timedelta(days=pd.STALE_AFTER_DAYS + 5)
        monkeypatch.setattr(pd, "FRED_GOLD_SERIES", "SOMEGOLD")
        monkeypatch.setattr(
            pd.fred, "fetch_observations",
            fred_stub({"SOMEGOLD": [(stale_day, 2300.0)]}),
        )
        monkeypatch.setattr(
            pd, "_yahoo_close",
            lambda ticker, start, end, st: {END: 2405.0} if ticker == pd.YAHOO_GOLD else {},
        )
        merged = pd.collect_prices("key", START, END, stats)
        assert merged[END]["xau_close"] == 2405.0

    def test_fred_values_win_where_both_sources_have_a_date(self, monkeypatch, stats):
        stale_day = END - timedelta(days=pd.STALE_AFTER_DAYS + 5)
        monkeypatch.setattr(pd, "FRED_GOLD_SERIES", "SOMEGOLD")
        monkeypatch.setattr(
            pd.fred, "fetch_observations",
            fred_stub({"SOMEGOLD": [(stale_day, 2300.0)]}),
        )
        monkeypatch.setattr(
            pd, "_yahoo_close",
            lambda ticker, start, end, st: {stale_day: 9999.0, END: 2405.0},
        )
        merged = pd.collect_prices("key", START, END, stats)
        assert merged[stale_day]["xau_close"] == 2300.0

    def test_the_fallback_is_recorded_in_the_run_notes(self, monkeypatch, stats):
        monkeypatch.setattr(pd.fred, "fetch_observations", fred_stub({}))
        monkeypatch.setattr(pd, "_yahoo_close", lambda *a, **k: {})
        pd.collect_prices("key", START, END, stats)
        assert any("GC=F" in note for note in stats.notes)


class TestIsStale:
    def test_empty_is_stale(self):
        assert pd._is_stale({}, END) is True

    def test_current_is_not(self):
        assert pd._is_stale({END: 1.0}, END) is False

    def test_a_few_days_behind_is_not(self):
        assert pd._is_stale({END - timedelta(days=3): 1.0}, END) is False

    def test_well_behind_is(self):
        assert pd._is_stale({END - timedelta(days=60): 1.0}, END) is True


class TestBuildPriceRows:
    def test_row_shape_and_ordering(self):
        merged = {
            date(2026, 8, 30): {"fed_funds": 4.33},
            date(2026, 8, 28): {"xau_close": 2400.0, "dxy": 121.5},
        }
        rows = pd.build_price_rows(merged)
        assert [r["date"] for r in rows] == ["2026-08-28", "2026-08-30"]

    def test_every_row_has_the_same_columns(self):
        """PostgREST requires uniform keys across one upsert batch."""
        merged = {
            date(2026, 8, 30): {"fed_funds": 4.33},
            date(2026, 8, 28): {"xau_close": 2400.0},
        }
        keysets = {tuple(sorted(r)) for r in pd.build_price_rows(merged)}
        assert len(keysets) == 1

    def test_absent_values_are_explicit_nulls(self):
        rows = pd.build_price_rows({date(2026, 8, 30): {"fed_funds": 4.33}})
        assert rows[0]["xau_close"] is None
        assert rows[0]["fed_funds"] == 4.33

    def test_dates_are_serialised_as_strings(self):
        rows = pd.build_price_rows({date(2026, 8, 30): {"fed_funds": 4.33}})
        assert rows[0]["date"] == "2026-08-30"

    def test_empty_input(self):
        assert pd.build_price_rows({}) == []


class TestYahooFailure:
    def test_an_import_or_download_error_is_contained(self, monkeypatch, stats):
        def explode(*args, **kwargs):
            raise RuntimeError("yahoo is down")

        monkeypatch.setattr(pd.fred, "fetch_observations", fred_stub({}))
        monkeypatch.setitem(__import__("sys").modules, "yfinance", None)
        result = pd._yahoo_close("GC=F", START, END, stats)
        assert result == {}
        assert stats.errors >= 1
