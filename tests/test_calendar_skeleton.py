"""The annual calendar skeleton: date handling and row construction."""

from __future__ import annotations

from datetime import date

import pytest

from common.timeutil import parse_iso
from fetchers import calendar_skeleton as cs
from fetchers import fomc
from fetchers.titles import FRED_RELEASE_TO_TITLE, SKELETON_TITLES


class TestBuildRows:
    def test_one_row_per_date(self, weights):
        schedule = {"CPI m/m": [date(2026, 9, 11), date(2026, 10, 13)]}
        rows = cs.build_rows(schedule, weights)
        assert len(rows) == 2

    def test_row_shape(self, weights):
        rows = cs.build_rows({"CPI m/m": [date(2026, 9, 11)]}, weights)
        row = rows[0]
        assert row == {
            "id": "USD|CPI m/m|2026-09-11",
            "title": "CPI m/m",
            "country": "USD",
            "ts_utc": "2026-09-11T12:30:00+00:00",
            "weight": 5,
            "source": "skeleton",
        }

    def test_it_writes_no_forecast_columns(self, weights):
        """The skeleton must not blank a forecast ff_sync already stored."""
        row = cs.build_rows({"CPI m/m": [date(2026, 9, 11)]}, weights)[0]
        assert "forecast" not in row and "previous" not in row
        assert "actual" not in row and "impact" not in row

    def test_timestamp_is_iso_with_an_offset(self, weights):
        row = cs.build_rows({"CPI m/m": [date(2026, 9, 11)]}, weights)[0]
        assert row["ts_utc"].endswith("+00:00")
        assert parse_iso(row["ts_utc"]).tzinfo is not None

    def test_release_time_follows_the_title(self, weights):
        schedule = {"ISM Manufacturing PMI": [date(2026, 9, 1)], "FOMC Statement": [date(2026, 9, 16)]}
        rows = {r["title"]: r for r in cs.build_rows(schedule, weights)}
        assert rows["ISM Manufacturing PMI"]["ts_utc"] == "2026-09-01T14:00:00+00:00"
        assert rows["FOMC Statement"]["ts_utc"] == "2026-09-16T18:00:00+00:00"

    def test_daylight_saving_is_respected(self, weights):
        """The same 08:30 ET release is 12:30 UTC in September, 13:30 in January."""
        rows = cs.build_rows(
            {"CPI m/m": [date(2026, 9, 11), date(2027, 1, 13)]}, weights
        )
        stamps = sorted(r["ts_utc"] for r in rows)
        assert stamps[0].endswith("T12:30:00+00:00")
        assert stamps[1].endswith("T13:30:00+00:00")

    def test_weights_come_from_the_table(self, weights):
        schedule = {"CPI m/m": [date(2026, 9, 11)], "Unemployment Claims": [date(2026, 9, 3)]}
        rows = {r["title"]: r["weight"] for r in cs.build_rows(schedule, weights)}
        assert rows == {"CPI m/m": 5, "Unemployment Claims": 1}

    def test_unknown_title_gets_weight_one(self):
        rows = cs.build_rows({"Beige Book": [date(2026, 9, 2)]}, {})
        assert rows[0]["weight"] == 1

    def test_duplicate_dates_collapse(self, weights):
        rows = cs.build_rows({"CPI m/m": [date(2026, 9, 11), date(2026, 9, 11)]}, weights)
        assert len(rows) == 1

    def test_rows_are_sorted_by_id(self, weights):
        schedule = {
            "CPI m/m": [date(2026, 10, 13)],
            "PPI m/m": [date(2026, 9, 10)],
            "FOMC Statement": [date(2026, 9, 16)],
        }
        rows = cs.build_rows(schedule, weights)
        assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)

    def test_empty_schedule(self, weights):
        assert cs.build_rows({}, weights) == []

    def test_ids_match_what_ff_sync_would_produce(self, weights, ff_thisweek):
        """The two writers must land on the same primary key."""
        from fetchers import ff_sync

        entry = next(e for e in ff_thisweek if e["title"] == "Non-Farm Employment Change")
        feed_row = ff_sync.parse_entry(entry, weights)
        skeleton_row = cs.build_rows(
            {"Non-Farm Employment Change": [date(2026, 9, 4)]}, weights
        )[0]
        assert skeleton_row["id"] == feed_row["id"]


class TestFetchReleaseDates:
    def test_dates_outside_the_window_are_dropped(self, monkeypatch):
        payload = {
            "release_dates": [
                {"date": "2026-08-01"},   # before the window
                {"date": "2026-09-11"},
                {"date": "2026-10-13"},
                {"date": "2027-12-01"},   # after it
            ]
        }
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: payload)
        found = cs.fetch_release_dates("key", 10, date(2026, 9, 1), date(2026, 11, 1))
        assert found == [date(2026, 9, 11), date(2026, 10, 13)]

    def test_unparseable_date_is_skipped_not_fatal(self, monkeypatch):
        payload = {"release_dates": [{"date": "not-a-date"}, {"date": "2026-09-11"}]}
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: payload)
        assert cs.fetch_release_dates("k", 10, date(2026, 1, 1), date(2027, 1, 1)) == [
            date(2026, 9, 11)
        ]

    def test_a_failed_call_returns_no_dates(self, monkeypatch):
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: None)
        assert cs.fetch_release_dates("k", 10, date(2026, 1, 1), date(2027, 1, 1)) == []

    def test_results_are_sorted_and_unique(self, monkeypatch):
        payload = {"release_dates": [{"date": "2026-10-13"}, {"date": "2026-09-11"}, {"date": "2026-09-11"}]}
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: payload)
        found = cs.fetch_release_dates("k", 10, date(2026, 1, 1), date(2027, 1, 1))
        assert found == [date(2026, 9, 11), date(2026, 10, 13)]

    def test_it_asks_for_future_dates(self, monkeypatch):
        """Without a far-future realtime_end, FRED returns only past releases."""
        captured = {}

        def capture(url, params=None, **kwargs):
            captured.update(params or {})
            return {"release_dates": []}

        monkeypatch.setattr(cs.http, "get_json", capture)
        cs.fetch_release_dates("k", 10, date(2026, 9, 1), date(2027, 9, 1))
        assert captured["realtime_end"] == cs.FAR_FUTURE
        assert captured["include_release_dates_with_no_data"] == "true"


class TestReleaseIndex:
    def test_names_are_normalised(self, monkeypatch):
        payload = {"releases": [{"id": 10, "name": "Consumer Price Index"}]}
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: payload)
        assert cs.fetch_release_index("k") == {"consumer price index": 10}

    def test_a_failed_call_returns_an_empty_index(self, monkeypatch):
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: None)
        assert cs.fetch_release_index("k") == {}

    def test_entries_missing_a_name_or_id_are_skipped(self, monkeypatch):
        payload = {"releases": [{"id": 10}, {"name": "x"}, {"id": 1, "name": "Ok"}]}
        monkeypatch.setattr(cs.http, "get_json", lambda *a, **k: payload)
        assert cs.fetch_release_index("k") == {"ok": 1}


class TestConfiguration:
    def test_every_skeleton_title_is_reachable(self):
        """Each title is either mapped from a FRED release or is the FOMC one."""
        mapped = set(FRED_RELEASE_TO_TITLE.values())
        fomc_titles = set(cs.FOMC_DECISION_TITLES) | {cs.FOMC_PROJECTION_TITLE}
        for title in SKELETON_TITLES:
            assert title in mapped or title in fomc_titles, title

    def test_skeleton_titles_have_release_times(self):
        from fetchers.release_times import RELEASE_TIMES_ET

        for title in SKELETON_TITLES:
            assert title in RELEASE_TIMES_ET, f"{title} would default to 08:30 ET"


class TestFomcDayIsComplete:
    """A Fed decision day is four events, and daylight saving moves them.

    The statement, the target range and the projections publish at 14:00 ET and
    the press conference at 14:30 ET. 14:00 ET is 18:00 UTC under EDT and 19:00
    UTC under EST, so a hardcoded offset would put the December meeting an hour
    wrong - which is the daylight-saving bug the concept doc calls out.
    """

    def _rows(self, meetings):
        schedule = {}
        days = [m.day for m in meetings]
        for title in cs.FOMC_DECISION_TITLES:
            schedule[title] = list(days)
        projections = [m.day for m in meetings if m.has_projections]
        if projections:
            schedule[cs.FOMC_PROJECTION_TITLE] = projections
        weights = {
            "fomc statement": 5, "federal funds rate": 5,
            "fomc press conference": 5, "fomc economic projections": 5,
        }
        return cs.build_rows(schedule, weights)

    def test_september_2026_is_edt_and_lands_at_1800z(self):
        rows = self._rows([fomc.Meeting(date(2026, 9, 16), True)])
        by_title = {r["title"]: r["ts_utc"] for r in rows}
        assert by_title["FOMC Statement"] == "2026-09-16T18:00:00+00:00"
        assert by_title["Federal Funds Rate"] == "2026-09-16T18:00:00+00:00"
        assert by_title["FOMC Economic Projections"] == "2026-09-16T18:00:00+00:00"
        assert by_title["FOMC Press Conference"] == "2026-09-16T18:30:00+00:00"

    def test_december_2026_is_est_and_lands_an_hour_later(self):
        rows = self._rows([fomc.Meeting(date(2026, 12, 9), True)])
        by_title = {r["title"]: r["ts_utc"] for r in rows}
        assert by_title["FOMC Statement"] == "2026-12-09T19:00:00+00:00"
        assert by_title["Federal Funds Rate"] == "2026-12-09T19:00:00+00:00"
        assert by_title["FOMC Economic Projections"] == "2026-12-09T19:00:00+00:00"
        assert by_title["FOMC Press Conference"] == "2026-12-09T19:30:00+00:00"

    def test_a_meeting_without_projections_gets_three_rows(self):
        rows = self._rows([fomc.Meeting(date(2026, 4, 29), False)])
        titles = {r["title"] for r in rows}
        assert titles == set(cs.FOMC_DECISION_TITLES)
        assert cs.FOMC_PROJECTION_TITLE not in titles

    def test_every_fomc_row_is_weight_five(self):
        rows = self._rows([fomc.Meeting(date(2026, 9, 16), True)])
        assert {r["weight"] for r in rows} == {5}

    def test_ids_are_distinct_across_the_four_titles(self):
        rows = self._rows([fomc.Meeting(date(2026, 9, 16), True)])
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)) == 4
