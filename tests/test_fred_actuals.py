"""Reading the right observation out of a FRED series."""

from __future__ import annotations

from datetime import date

import pytest

from fetchers.fred_actuals import extract_actual
from fetchers.series_map import SERIES_MAP, SeriesSpec, reason_unmapped, spec_for

# A monthly index, the shape CPI and PCE arrive in.
MONTHLY = [
    (date(2025, 8, 1), 100.0),
    (date(2025, 9, 1), 100.4),
    (date(2026, 6, 1), 105.0),
    (date(2026, 7, 1), 105.5),
    (date(2026, 8, 1), 105.8),
]

# A level in thousands, the shape PAYEMS arrives in.
PAYROLLS = [
    (date(2026, 6, 1), 159_000.0),
    (date(2026, 7, 1), 159_142.0),
    (date(2026, 8, 1), 159_307.0),
]


class TestLevel:
    def test_takes_the_newest_observation_before_the_release(self):
        spec = SeriesSpec("ICSA", "level")
        assert extract_actual(MONTHLY, spec, date(2026, 9, 4)) == 105.8

    def test_a_monthly_release_reports_the_previous_month(self):
        """Released 15 July, a monthly series reports June - not July.

        FRED dates an observation by its reference month, so a 2026-07-01
        observation exists by the time we look but is not what the July release
        measured. Reading it would shift every actual forward a month.
        """
        spec = SeriesSpec("ICSA", "level")
        assert extract_actual(MONTHLY, spec, date(2026, 7, 15)) == 105.0

    def test_a_weekly_release_reports_the_period_just_ended(self):
        """Weekly series are dated by period end, so they anchor on the day."""
        spec = SeriesSpec("ICSA", "level", frequency="weekly")
        weekly = [(date(2026, 8, 15), 220_000.0), (date(2026, 8, 22), 210_000.0)]
        assert extract_actual(weekly, spec, date(2026, 8, 27)) == 210_000.0

    def test_scale_converts_units(self):
        """PERMIT is published in thousands; the feed quotes "1.42M"."""
        spec = SeriesSpec("PERMIT", "level", scale=1_000.0)
        observations = [(date(2026, 8, 1), 1_420.0)]
        assert extract_actual(observations, spec, date(2026, 9, 4)) == 1_420_000.0

    def test_no_observation_before_the_release_gives_none(self):
        spec = SeriesSpec("ICSA", "level")
        assert extract_actual(MONTHLY, spec, date(2020, 1, 1)) is None

    def test_empty_series_gives_none(self):
        assert extract_actual([], SeriesSpec("X", "level"), date(2026, 9, 4)) is None

    def test_missing_values_are_stepped_over(self):
        spec = SeriesSpec("X", "level")
        observations = [(date(2026, 8, 1), 105.8), (date(2026, 8, 2), None)]
        assert extract_actual(observations, spec, date(2026, 9, 4)) == 105.8


class TestDiff:
    def test_month_on_month_change(self):
        """The NFP release quotes the change, not the level."""
        spec = SeriesSpec("PAYEMS", "diff", scale=1_000.0)
        actual = extract_actual(PAYROLLS, spec, date(2026, 9, 4))
        assert actual == pytest.approx(165_000.0)

    def test_scale_is_applied_after_the_subtraction(self):
        spec = SeriesSpec("PAYEMS", "diff", scale=1_000.0)
        observations = [(date(2026, 7, 1), 100.0), (date(2026, 8, 1), 100.5)]
        assert extract_actual(observations, spec, date(2026, 9, 4)) == pytest.approx(500.0)

    def test_a_single_observation_is_not_enough(self):
        spec = SeriesSpec("PAYEMS", "diff", scale=1_000.0)
        assert extract_actual([(date(2026, 8, 1), 159_307.0)], spec, date(2026, 9, 4)) is None

    def test_a_fall_is_negative(self):
        spec = SeriesSpec("PAYEMS", "diff", scale=1_000.0)
        observations = [(date(2026, 7, 1), 159_142.0), (date(2026, 8, 1), 159_000.0)]
        assert extract_actual(observations, spec, date(2026, 9, 4)) < 0


class TestPctChangeMom:
    def test_percentage_change(self):
        """105.8 from 105.5 is +0.284%, which the feed would quote as 0.3."""
        spec = SeriesSpec("CPIAUCSL", "pct_change_mom")
        actual = extract_actual(MONTHLY, spec, date(2026, 9, 11))
        assert actual == pytest.approx((105.8 / 105.5 - 1) * 100)
        assert actual == pytest.approx(0.284, abs=0.01)

    def test_is_quoted_in_percent_not_as_a_fraction(self):
        """0.3 must not come back as 0.003 - the forecast is quoted as 0.3."""
        spec = SeriesSpec("CPIAUCSL", "pct_change_mom")
        assert extract_actual(MONTHLY, spec, date(2026, 9, 11)) > 0.1

    def test_a_zero_previous_value_gives_none(self):
        spec = SeriesSpec("X", "pct_change_mom")
        observations = [(date(2026, 7, 1), 0.0), (date(2026, 8, 1), 1.0)]
        assert extract_actual(observations, spec, date(2026, 9, 4)) is None

    def test_needs_two_observations(self):
        spec = SeriesSpec("X", "pct_change_mom")
        assert extract_actual([(date(2026, 8, 1), 1.0)], spec, date(2026, 9, 4)) is None


class TestPctChangeYoy:
    def test_uses_the_observation_a_year_earlier(self):
        spec = SeriesSpec("CPIAUCNS", "pct_change_yoy")
        actual = extract_actual(MONTHLY, spec, date(2026, 9, 11))
        assert actual == pytest.approx((105.8 / 100.0 - 1) * 100)

    def test_none_when_a_year_ago_is_missing(self):
        spec = SeriesSpec("CPIAUCNS", "pct_change_yoy")
        recent = [(date(2026, 7, 1), 105.5), (date(2026, 8, 1), 105.8)]
        assert extract_actual(recent, spec, date(2026, 9, 11)) is None

    def test_tolerates_a_slightly_off_anniversary(self):
        spec = SeriesSpec("X", "pct_change_yoy")
        observations = [(date(2025, 8, 10), 100.0), (date(2026, 8, 1), 110.0)]
        assert extract_actual(observations, spec, date(2026, 9, 1)) == pytest.approx(10.0)


class TestLevelAtOrAfter:
    def test_reads_the_value_on_the_day(self):
        """An FOMC decision changes the rate that afternoon."""
        spec = SeriesSpec("DFEDTARU", "level_at_or_after")
        observations = [
            (date(2026, 9, 15), 4.50),
            (date(2026, 9, 16), 4.25),
            (date(2026, 9, 17), 4.25),
        ]
        assert extract_actual(observations, spec, date(2026, 9, 16)) == 4.25

    def test_does_not_return_the_stale_previous_rate(self):
        spec = SeriesSpec("DFEDTARU", "level_at_or_after")
        observations = [(date(2026, 9, 15), 4.50), (date(2026, 9, 16), 4.25)]
        assert extract_actual(observations, spec, date(2026, 9, 16)) != 4.50

    def test_falls_forward_over_a_gap(self):
        spec = SeriesSpec("DFEDTARU", "level_at_or_after")
        observations = [(date(2026, 9, 18), 4.25)]
        assert extract_actual(observations, spec, date(2026, 9, 16)) == 4.25

    def test_gives_up_beyond_the_forward_window(self):
        spec = SeriesSpec("DFEDTARU", "level_at_or_after")
        observations = [(date(2026, 12, 1), 4.25)]
        assert extract_actual(observations, spec, date(2026, 9, 16)) is None

    def test_none_when_the_value_is_not_published_yet(self):
        spec = SeriesSpec("DFEDTARU", "level_at_or_after")
        assert extract_actual([(date(2026, 9, 15), 4.50)], spec, date(2026, 9, 16)) is None


class TestReferenceMonth:
    """The off-by-one-month bug found on the first live run of fred_actuals.

    Values are the real CPIAUCSL index for 2026, so the expected m/m figures are
    the ones the BLS actually published.
    """

    CPI = [
        (date(2026, 1, 1), 326.588), (date(2026, 2, 1), 327.460),
        (date(2026, 3, 1), 330.293), (date(2026, 4, 1), 332.407),
        (date(2026, 5, 1), 333.979), (date(2026, 6, 1), 332.568),
        (date(2026, 7, 1), 332.813),
    ]

    @pytest.mark.parametrize(
        "released,expected",
        [
            ("2026-05-12", 0.6400),   # April
            ("2026-06-10", 0.4729),   # May
            ("2026-07-14", -0.4225),  # June
            ("2026-08-12", 0.0737),   # July
        ],
    )
    def test_each_release_reports_its_own_month(self, released, expected):
        spec = SeriesSpec("CPIAUCSL", "pct_change_mom")
        got = extract_actual(self.CPI, spec, date.fromisoformat(released))
        assert got == pytest.approx(expected, abs=0.001)

    def test_consecutive_releases_differ(self):
        """The bug made every release of a series return the same number."""
        spec = SeriesSpec("CPIAUCSL", "pct_change_mom")
        values = [
            extract_actual(self.CPI, spec, date.fromisoformat(d))
            for d in ("2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12")
        ]
        assert len(set(values)) == len(values)

    def test_a_release_early_in_the_month_still_reports_the_month_before(self):
        spec = SeriesSpec("PAYEMS", "diff", scale=1_000.0)
        payrolls = [
            (date(2026, 5, 1), 159_000.0),
            (date(2026, 6, 1), 159_020.0),
            (date(2026, 7, 1), 158_997.0),
        ]
        # Released 7 August, NFP reports July: 158997 - 159020 = -23 thousand.
        assert extract_actual(payrolls, spec, date(2026, 8, 7)) == pytest.approx(-23_000.0)


class TestSeriesMap:
    def test_lookup_is_case_insensitive(self):
        assert spec_for("CPI M/M") is spec_for("cpi m/m")

    def test_unknown_title(self):
        assert spec_for("Beige Book") is None

    def test_unmapped_titles_have_a_stated_reason(self):
        assert "ISM" in reason_unmapped("ISM Manufacturing PMI")
        assert reason_unmapped("Something Else")

    def test_every_spec_has_a_valid_transform(self):
        for title, spec in SERIES_MAP.items():
            assert spec.transform in (
                "level", "diff", "pct_change_mom", "pct_change_yoy", "level_at_or_after"
            ), title

    def test_an_invalid_transform_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            SeriesSpec("X", "sideways")

    def test_an_invalid_frequency_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            SeriesSpec("X", "level", frequency="fortnightly")

    def test_sub_monthly_series_are_marked_as_such(self):
        """Anything not monthly must say so, or it reads the wrong period."""
        assert SERIES_MAP["unemployment claims"].frequency == "weekly"
        assert SERIES_MAP["fomc statement"].frequency == "daily"

    def test_payrolls_are_scaled_to_persons(self):
        """The feed's "165K" parses to 165000, so PAYEMS thousands need x1000."""
        assert SERIES_MAP["non-farm employment change"].scale == 1_000.0
