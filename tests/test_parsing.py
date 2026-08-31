"""Parsing the display strings a calendar feed publishes."""

from __future__ import annotations

import pytest

from fetchers.parsing import parse_impact, parse_numeric


class TestParseNumeric:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0.3%", 0.3),
            ("-0.1%", -0.1),
            ("4.3%", 4.3),
            ("2.4", 2.4),
            ("48.9", 48.9),
            ("0", 0.0),
        ],
    )
    def test_plain_and_percent(self, raw, expected):
        assert parse_numeric(raw) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("165K", 165_000.0),
            ("230K", 230_000.0),
            ("7.38M", 7_380_000.0),
            ("-291.1B", -291_100_000_000.0),
            ("1.2T", 1_200_000_000_000.0),
            ("165k", 165_000.0),
        ],
    )
    def test_suffixes_expand(self, raw, expected):
        assert parse_numeric(raw) == pytest.approx(expected)

    def test_percent_is_not_divided_by_a_hundred(self):
        """0.3% stays 0.3, because the FRED actual is also quoted as 0.3."""
        assert parse_numeric("0.3%") == pytest.approx(0.3)

    @pytest.mark.parametrize("raw", ["", "  ", "-", "--", "n/a", "N/A", "None", "Tentative", None])
    def test_blanks_become_none(self, raw):
        assert parse_numeric(raw) is None

    def test_thousands_separator(self):
        assert parse_numeric("1,234.5") == pytest.approx(1234.5)
        assert parse_numeric("-1,234") == pytest.approx(-1234.0)

    @pytest.mark.parametrize("raw,expected", [("<0.1%", 0.1), (">2.5%", 2.5)])
    def test_inequality_markers_use_the_bound(self, raw, expected):
        assert parse_numeric(raw) == pytest.approx(expected)

    def test_currency_marker_is_stripped(self):
        assert parse_numeric("$1.25M") == pytest.approx(1_250_000.0)

    def test_numbers_pass_straight_through(self):
        assert parse_numeric(4.2) == pytest.approx(4.2)
        assert parse_numeric(7) == pytest.approx(7.0)

    def test_booleans_are_not_numbers(self):
        """bool subclasses int; a True must never become 1.0 on a chart."""
        assert parse_numeric(True) is None

    @pytest.mark.parametrize("raw", ["abc", "12-14", "1.2.3", "%", "K"])
    def test_junk_returns_none_rather_than_raising(self, raw):
        assert parse_numeric(raw) is None

    def test_zero_is_kept_distinct_from_missing(self):
        """A forecast of 0.0 is a real forecast; None is the absence of one."""
        assert parse_numeric("0.0%") == 0.0
        assert parse_numeric("") is None


class TestParseImpact:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("High", "High"),
            ("high", "High"),
            ("Medium", "Medium"),
            ("Low", "Low"),
            ("Holiday", "Holiday"),
            ("", None),
            (None, None),
            ("something else", None),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert parse_impact(raw) == expected
