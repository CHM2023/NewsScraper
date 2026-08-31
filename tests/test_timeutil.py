"""The UTC rule, enforced.

The concept doc lists timezones as a known risk: "One Sydney/US daylight-saving
bug will silently break the blackout and reminder logic." These tests are the
tripwire for exactly that.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from common.timeutil import (
    UTC,
    NaiveDatetimeError,
    ensure_aware,
    iso_utc,
    now_utc,
    parse_iso,
    start_of_utc_day,
    to_utc,
    utc_date_str,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ("common", "db", "fetchers", "web")


class TestRejectsNaive:
    """A naive datetime must never get past a boundary."""

    def test_ensure_aware_rejects_naive(self):
        with pytest.raises(NaiveDatetimeError):
            ensure_aware(datetime(2026, 10, 14, 12, 30))

    def test_to_utc_rejects_naive(self):
        with pytest.raises(NaiveDatetimeError):
            to_utc(datetime(2026, 10, 14, 12, 30))

    def test_iso_utc_rejects_naive(self):
        with pytest.raises(NaiveDatetimeError):
            iso_utc(datetime(2026, 10, 14, 12, 30))

    def test_utc_date_str_rejects_naive(self):
        with pytest.raises(NaiveDatetimeError):
            utc_date_str(datetime(2026, 10, 14, 12, 30))

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_the_output_of_utcnow_is_rejected(self):
        """datetime.utcnow() looks like UTC but is naive. It must not pass."""
        with pytest.raises(NaiveDatetimeError):
            ensure_aware(datetime.utcnow())  # noqa: DTZ003 - that is the point

    def test_error_names_the_field(self):
        with pytest.raises(NaiveDatetimeError, match="events.ts_utc"):
            ensure_aware(datetime(2026, 1, 1), field="events.ts_utc")

    def test_tzinfo_with_no_offset_is_still_naive(self):
        class NoOffset(timezone.__base__):  # tzinfo subclass returning None
            def utcoffset(self, dt):
                return None

            def dst(self, dt):
                return None

            def tzname(self, dt):
                return "fake"

        with pytest.raises(NaiveDatetimeError):
            ensure_aware(datetime(2026, 1, 1, tzinfo=NoOffset()))


class TestConversion:
    def test_now_utc_is_aware_and_utc(self):
        value = now_utc()
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)

    def test_offset_is_applied_not_dropped(self):
        """08:30 New York in summer is 12:30 UTC, not 08:30 UTC."""
        parsed = parse_iso("2026-09-04T08:30:00-04:00")
        assert parsed == datetime(2026, 9, 4, 12, 30, tzinfo=UTC)

    def test_winter_offset_differs_from_summer(self):
        summer = parse_iso("2026-07-15T08:30:00-04:00")
        winter = parse_iso("2026-01-15T08:30:00-05:00")
        assert summer.hour == 12
        assert winter.hour == 13

    def test_trailing_z_is_accepted(self):
        assert parse_iso("2026-10-14T12:30:00Z") == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)

    def test_string_without_an_offset_is_rejected(self):
        with pytest.raises(NaiveDatetimeError):
            parse_iso("2026-10-14T12:30:00")

    def test_nonsense_string_is_rejected(self):
        with pytest.raises(ValueError):
            parse_iso("next tuesday")

    def test_iso_utc_round_trips(self):
        original = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
        assert parse_iso(iso_utc(original)) == original

    def test_iso_utc_always_carries_an_offset(self):
        rendered = iso_utc(parse_iso("2026-09-04T08:30:00-04:00"))
        assert re.search(r"[+-]\d{2}:\d{2}$", rendered), rendered

    def test_utc_date_uses_utc_not_local(self):
        """22:00 New York on the 4th is already the 5th in UTC."""
        assert utc_date_str(parse_iso("2026-09-04T22:00:00-04:00")) == "2026-09-05"

    def test_start_of_utc_day(self):
        value = start_of_utc_day(parse_iso("2026-09-04T22:00:00-04:00"))
        assert (value.hour, value.minute, value.second) == (0, 0, 0)
        assert value.date().isoformat() == "2026-09-05"


class TestSourceDiscipline:
    """utcnow() is banned outright, per CLAUDE.md.

    The check walks the AST rather than grepping, so that prose *about*
    utcnow - which this file and common/timeutil.py both contain, explaining
    why it is banned - is not mistaken for a call to it.
    """

    def _python_files(self):
        for directory in SOURCE_DIRS:
            yield from (REPO_ROOT / directory).rglob("*.py")

    @staticmethod
    def _called_names(tree) -> list[tuple[str, int]]:
        """Every attribute call in the tree, as ``(name, lineno)``."""
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                found.append((node.func.attr, node.lineno))
        return found

    def test_no_module_calls_utcnow(self):
        offenders = []
        for path in self._python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name, lineno in self._called_names(tree):
                if name == "utcnow":
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
        assert not offenders, (
            "datetime.utcnow() returns a naive datetime and is banned; "
            f"use common.timeutil.now_utc() instead. Found at: {offenders}"
        )

    def test_no_module_uses_fromtimestamp_without_a_zone(self):
        offenders = []
        for path in self._python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr != "fromtimestamp":
                    continue
                keywords = {kw.arg for kw in node.keywords}
                if "tz" not in keywords:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
        assert not offenders, (
            "fromtimestamp() without tz= returns local time; pass tz=UTC. "
            f"Found at: {offenders}"
        )

    def test_the_ban_would_catch_a_real_call(self):
        """Guard the guard: the AST check must actually fire on a real call."""
        tree = ast.parse("import datetime\nx = datetime.datetime.utcnow()\n")
        assert ("utcnow", 2) in self._called_names(tree)
