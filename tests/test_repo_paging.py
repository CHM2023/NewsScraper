"""PostgREST's silent 1000-row cap.

Found on a live run: prices_daily held 3651 rows but a default select returned
exactly 1000, so the 10-year Fed funds history stopped at 2019 and every event
was tagged with a 2019 rate. The response is not an error and carries no marker -
it simply stops - so the only defence is to page explicitly.
"""

from __future__ import annotations

from datetime import date

import pytest

from db import repo


class FakeQuery:
    """Mimics PostgREST: never returns more than `cap` rows for one range."""

    def __init__(self, rows, cap, calls):
        self._rows, self._cap, self._calls = rows, cap, calls
        self._start, self._end = 0, len(rows) - 1

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        window = self._rows[self._start : self._end + 1][: self._cap]
        self._calls.append((self._start, self._end, len(window)))
        return type("Res", (), {"data": window})()


class TestFetchPaged:
    def test_it_reads_past_the_cap(self):
        rows = [{"i": i} for i in range(3651)]
        calls = []
        got = repo._fetch_paged(lambda: FakeQuery(rows, 1000, calls), page=1000)
        assert len(got) == 3651

    def test_it_preserves_order_and_content(self):
        rows = [{"i": i} for i in range(2500)]
        got = repo._fetch_paged(lambda: FakeQuery(rows, 1000, []), page=1000)
        assert [r["i"] for r in got] == list(range(2500))

    def test_it_asks_for_successive_windows(self):
        rows = [{"i": i} for i in range(2500)]
        calls = []
        repo._fetch_paged(lambda: FakeQuery(rows, 1000, calls), page=1000)
        assert [(c[0], c[1]) for c in calls] == [(0, 999), (1000, 1999), (2000, 2999)]

    def test_a_short_page_ends_the_loop(self):
        rows = [{"i": i} for i in range(10)]
        calls = []
        repo._fetch_paged(lambda: FakeQuery(rows, 1000, calls), page=1000)
        assert len(calls) == 1, "one short page means stop, not another round trip"

    def test_an_exact_multiple_still_terminates(self):
        """2000 rows at page 1000 needs a third, empty request to know it is done."""
        rows = [{"i": i} for i in range(2000)]
        calls = []
        got = repo._fetch_paged(lambda: FakeQuery(rows, 1000, calls), page=1000)
        assert len(got) == 2000
        assert len(calls) == 3

    def test_empty_result(self):
        assert repo._fetch_paged(lambda: FakeQuery([], 1000, []), page=1000) == []


class TestPagedReadersUseIt:
    """The readers that can exceed 1000 rows must go through _fetch_paged."""

    @pytest.mark.parametrize(
        "name",
        [
            "fetch_event_weights",
            "fetch_events_between",
            "fetch_events_missing_actual",
            "fetch_reminder_candidates",
            "fetch_prices",
        ],
    )
    def test_reader_is_paged(self, name):
        import inspect

        source = inspect.getsource(getattr(repo, name))
        assert "_fetch_paged" in source, f"{name} would truncate at {repo.PAGE} rows"

    def test_limited_readers_are_not_paged(self):
        """fetch_recent_releases asks for 10 rows on purpose."""
        import inspect

        source = inspect.getsource(repo.fetch_recent_releases)
        assert "_fetch_paged" not in source
        assert ".limit(" in source


class TestFedFundsPassesThrough:
    def test_it_returns_every_row_the_page_reader_gives_it(self, monkeypatch):
        rows = [
            {"date": date(2016, 1, 1).replace(day=1).isoformat(), "fed_funds": 0.4},
        ] + [{"date": f"2020-01-{d:02d}", "fed_funds": 1.5} for d in range(1, 29)]
        monkeypatch.setattr(repo, "fetch_prices", lambda *a, **k: rows)
        got = repo.fetch_fed_funds(date(2015, 1, 1), date(2026, 1, 1))
        assert len(got) == len(rows)

    def test_missing_values_are_skipped(self, monkeypatch):
        rows = [
            {"date": "2020-01-01", "fed_funds": 1.5},
            {"date": "2020-01-02", "fed_funds": None},
        ]
        monkeypatch.setattr(repo, "fetch_prices", lambda *a, **k: rows)
        assert len(repo.fetch_fed_funds(date(2015, 1, 1), date(2026, 1, 1))) == 1
