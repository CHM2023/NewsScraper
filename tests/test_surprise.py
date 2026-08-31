"""The surprise score."""

from __future__ import annotations

import pytest

from fetchers.surprise import LIMIT, clamp, compute_surprise, describe


class TestComputeSurprise:
    def test_on_forecast_is_zero(self):
        """A release that lands on forecast should move gold very little."""
        assert compute_surprise(0.3, 0.3) == 0.0

    def test_above_forecast_is_positive(self):
        assert compute_surprise(0.4, 0.3) > 0

    def test_below_forecast_is_negative(self):
        assert compute_surprise(0.2, 0.3) < 0

    def test_the_formula(self):
        # (0.33 - 0.30) / 0.30 * 10 = 1.0
        assert compute_surprise(0.33, 0.30) == pytest.approx(1.0)

    def test_scales_by_ten(self):
        # A 10% relative miss becomes 1.0, not 0.1.
        assert compute_surprise(110.0, 100.0) == pytest.approx(1.0)

    def test_negative_forecast_uses_absolute_denominator(self):
        """A miss above a negative forecast is still a positive surprise.

        (-0.19 - -0.20) / |-0.20| * 10 = +0.5. Using the signed denominator
        would flip the sign and report a fall as a beat.
        """
        assert compute_surprise(-0.19, -0.20) == pytest.approx(0.5)

    def test_a_big_miss_on_a_negative_forecast_still_clamps(self):
        assert compute_surprise(-0.1, -0.2) == LIMIT

    @pytest.mark.parametrize("actual,forecast", [(None, 0.3), (0.3, None), (None, None)])
    def test_missing_input_gives_none_not_zero(self, actual, forecast):
        """The brief: do not compute surprise when the forecast is null."""
        assert compute_surprise(actual, forecast) is None

    def test_zero_forecast_gives_none(self):
        """A relative miss against zero is undefined; do not fabricate one."""
        assert compute_surprise(0.1, 0.0) is None

    def test_zero_actual_against_a_real_forecast_is_fine(self):
        """(0 - 0.3) / 0.3 * 10 = -10, which the band clamps to -3."""
        assert compute_surprise(0.0, 0.3) == -LIMIT

    @pytest.mark.parametrize("actual", [100.0, 1_000.0, 1e9])
    def test_clamped_above(self, actual):
        assert compute_surprise(actual, 0.3) == LIMIT

    @pytest.mark.parametrize("actual", [-100.0, -1e9])
    def test_clamped_below(self, actual):
        assert compute_surprise(actual, 0.3) == -LIMIT

    def test_result_always_inside_the_band(self):
        for actual in (-1e6, -1.0, 0.0, 0.5, 1e6):
            score = compute_surprise(actual, 0.4)
            assert -LIMIT <= score <= LIMIT

    def test_integers_are_accepted(self):
        assert compute_surprise(165000, 160000) == pytest.approx(0.3125)

    def test_nfp_example(self):
        """165K forecast, 142K actual: a clear downside miss."""
        score = compute_surprise(142_000.0, 165_000.0)
        assert score == pytest.approx((142_000 - 165_000) / 165_000 * 10)
        assert score < 0


class TestClamp:
    def test_inside_the_band_is_untouched(self):
        assert clamp(1.5) == 1.5

    def test_edges(self):
        assert clamp(99.0) == LIMIT
        assert clamp(-99.0) == -LIMIT


class TestDescribe:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (None, "n/a"),
            (0.0, "in line"),
            (0.2, "in line"),
            (-0.4, "in line"),
            (1.5, "above forecast"),
            (-1.5, "below forecast"),
            (0.5, "above forecast"),
            (-0.5, "below forecast"),
        ],
    )
    def test_labels(self, score, expected):
        assert describe(score) == expected
