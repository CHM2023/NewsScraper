"""Title canonicalisation, weight lookup and event ids."""

from __future__ import annotations

from datetime import datetime

import pytest

from common.timeutil import UTC, parse_iso
from fetchers.titles import (
    DEFAULT_WEIGHT,
    canonical_from_fred_release,
    event_id,
    normalize,
    resolve_alias,
    weight_for,
)


class TestNormalize:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("CPI m/m", "cpi m/m"),
            ("  CPI  m/m  ", "cpi m/m"),
            ("FOMC\tStatement", "fomc statement"),
            ("Non-Farm Employment Change", "non-farm employment change"),
        ],
    )
    def test_lowercases_and_collapses_whitespace(self, raw, expected):
        assert normalize(raw) == expected


class TestWeightLookup:
    def test_exact_match(self, weights):
        assert weight_for("FOMC Statement", weights) == 5

    def test_is_case_insensitive(self, weights):
        assert weight_for("fomc statement", weights) == 5
        assert weight_for("FOMC STATEMENT", weights) == 5

    def test_unknown_title_gets_the_default(self, weights):
        """The brief: unknown titles get weight 1."""
        assert weight_for("Beige Book", weights) == DEFAULT_WEIGHT == 1

    def test_office_holder_alias_still_scores(self, weights):
        """The chair changes; the weight should not have to be re-seeded."""
        assert weight_for("Fed Chair Powell Speaks", weights) == 4
        assert weight_for("Fed Chair Smith Testifies", weights) == 4

    def test_alias_to_a_title_absent_from_the_table_falls_back(self):
        assert weight_for("Fed Chair Powell Speaks", {}) == DEFAULT_WEIGHT

    def test_nfp_outranks_its_co_releases(self, weights):
        """Only one of the three 08:30 employment prints may trigger reminders."""
        assert weight_for("Non-Farm Employment Change", weights) == 4
        assert weight_for("Unemployment Rate", weights) == 3
        assert weight_for("Average Hourly Earnings m/m", weights) == 3


class TestAliases:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Fed Chair Powell Testifies", "Fed Chair Testifies"),
            ("Fed Chair Powell Speaks", "Fed Chair Speaks"),
            ("Jackson Hole Symposium", "Jackson Hole Symposium"),
            ("FOMC Meeting Minutes", "FOMC Meeting Minutes"),
        ],
    )
    def test_known_aliases(self, raw, expected):
        assert resolve_alias(raw) == expected

    def test_unknown_returns_none(self):
        assert resolve_alias("Crude Oil Inventories") is None


class TestFredReleaseMapping:
    @pytest.mark.parametrize(
        "release,expected",
        [
            ("Consumer Price Index", "CPI m/m"),
            ("consumer price index", "CPI m/m"),
            ("Employment Situation", "Non-Farm Employment Change"),
            ("Personal Income and Outlays", "Core PCE Price Index m/m"),
            ("Unemployment Insurance Weekly Claims Report", "Unemployment Claims"),
        ],
    )
    def test_maps_to_the_feed_title(self, release, expected):
        assert canonical_from_fred_release(release) == expected

    def test_unmapped_release_returns_none(self):
        assert canonical_from_fred_release("Beige Book") is None


class TestEventId:
    def test_shape(self):
        ts = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
        assert event_id("CPI m/m", ts) == "USD|CPI m/m|2026-10-14"

    def test_uses_the_utc_date(self):
        ts = parse_iso("2026-09-04T08:30:00-04:00")
        assert event_id("Non-Farm Employment Change", ts).endswith("2026-09-04")

    def test_two_sources_agree_on_the_id(self):
        """The whole point: the skeleton and the feed must collide, not duplicate.

        The skeleton builds 08:30 Eastern from a FRED release date; the feed
        supplies the same instant with an offset. Both must produce one id.
        """
        from fetchers.release_times import scheduled_ts_utc

        from datetime import date

        skeleton_ts = scheduled_ts_utc(date(2026, 9, 4), "Non-Farm Employment Change")
        feed_ts = parse_iso("2026-09-04T08:30:00-04:00")
        assert skeleton_ts == feed_ts
        assert event_id("Non-Farm Employment Change", skeleton_ts) == event_id(
            "Non-Farm Employment Change", feed_ts
        )

    def test_country_is_part_of_the_key(self):
        ts = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
        assert event_id("CPI m/m", ts, "EUR").startswith("EUR|")

    def test_naive_timestamp_is_rejected(self):
        from common.timeutil import NaiveDatetimeError

        with pytest.raises(NaiveDatetimeError):
            event_id("CPI m/m", datetime(2026, 10, 14, 12, 30))
