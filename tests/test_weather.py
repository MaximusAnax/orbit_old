"""Weather model.

The tests concentrate on the observation floor, because that is where the edge
lives and where the model most easily goes wrong. A daily maximum is a running
maximum: once a value is recorded it cannot be un-recorded, so a market whose
threshold has already been passed is *settled*, not merely likely.

Treating that as 98% instead of 100% is the difference between the strategy's
best trade and an ordinary one.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from orbit.core.money import cents_to_pips
from orbit.core.types import Side
from orbit.strategies.weather import (
    CalibrationRecord,
    CalibrationTracker,
    DailyMaxDistribution,
    ForecastSkill,
    SettlementRounding,
    WeatherEdgeStrategy,
    WeatherMarket,
    apply_rounding,
    daily_max_distribution,
)
from orbit.venues.base import normalize_two_sided_book

TS = datetime(2026, 7, 30, 18, 0, tzinfo=UTC)


def c(cents: int) -> int:
    return cents_to_pips(cents)


def book(key, bid, ask, size=100):
    return normalize_two_sided_book(
        market_key=key, timestamp=TS, bids=[(c(bid), size)], asks=[(c(ask), size)]
    )


class TestSettlementRounding:
    def test_nearest_integer_rounds_half_up(self):
        """Not banker's rounding: 74.5 must go to 75, not 74."""
        assert apply_rounding(74.5, SettlementRounding.NEAREST_INTEGER) == 75
        assert apply_rounding(75.4, SettlementRounding.NEAREST_INTEGER) == 75
        assert apply_rounding(75.6, SettlementRounding.NEAREST_INTEGER) == 76

    def test_truncate(self):
        assert apply_rounding(75.9, SettlementRounding.TRUNCATE) == 75

    def test_raw(self):
        assert apply_rounding(75.4, SettlementRounding.RAW) == 75.4


class TestObservationFloor:
    """The core of the strategy."""

    def test_a_passed_threshold_is_certain_not_likely(self):
        """Observed 76F against a 75F threshold: probability is exactly 1.0."""
        dist = daily_max_distribution(
            observations=[70.0, 74.0, 76.0],
            remaining_forecast=72.0,   # cooling off, irrelevant now
            lead_hours=4.0,
        )
        assert dist.prob_at_or_above(75.0) == 1.0

    def test_certainty_holds_even_with_a_pessimistic_forecast(self):
        """The floor is a fact; no forecast can argue it down."""
        dist = daily_max_distribution(
            observations=[80.0],
            remaining_forecast=60.0,
            lead_hours=6.0,
        )
        assert dist.prob_at_or_above(78.0) == 1.0

    def test_below_the_floor_the_forecast_still_governs(self):
        dist = daily_max_distribution(
            observations=[70.0],
            remaining_forecast=74.0,
            lead_hours=6.0,
        )
        p = dist.prob_at_or_above(75.0)
        assert 0.0 < p < 1.0

    def test_no_observations_is_a_plain_forecast(self):
        dist = daily_max_distribution(
            observations=[], remaining_forecast=75.0, lead_hours=24.0
        )
        # Forecast sits exactly on the rounding cutoff's high side.
        assert 0.5 < dist.prob_at_or_above(75.0) < 0.7

    def test_more_observations_only_ever_raise_the_floor(self):
        """A running maximum is monotone; probability must never decrease."""
        previous = 0.0
        obs: list[float] = []
        for reading in (68.0, 71.0, 70.0, 74.0, 73.0, 76.0):
            obs.append(reading)
            dist = daily_max_distribution(
                observations=obs, remaining_forecast=72.0, lead_hours=3.0
            )
            p = dist.prob_at_or_above(75.0)
            assert p >= previous - 1e-9, f"probability fell after observing {reading}"
            previous = p
        assert previous == 1.0

    def test_daily_minimum_markets_are_capped_from_above(self):
        """For a minimum, an observation is a ceiling rather than a floor."""
        dist = daily_max_distribution(
            observations=[30.0],
            remaining_forecast=35.0,
            lead_hours=4.0,
            is_minimum=True,
        )
        # The minimum is already 30, so "min >= 32" is impossible.
        assert dist.prob_at_or_above(32.0) == 0.0


class TestForecastSkill:
    def test_uncertainty_grows_with_lead_time(self):
        skill = ForecastSkill()
        sigmas = [skill.sigma(h) for h in (0, 6, 12, 24, 48, 72)]
        assert sigmas == sorted(sigmas)

    def test_near_term_is_much_tighter_than_multi_day(self):
        skill = ForecastSkill()
        assert skill.sigma(0) < 1.0
        assert skill.sigma(24) == pytest.approx(2.5, abs=0.01)
        assert skill.sigma(72) == pytest.approx(4.5, abs=0.01)

    def test_zero_lead_still_carries_some_error(self):
        """Observations get corrected; certainty comes from the floor, not here."""
        assert ForecastSkill().sigma(0.0) > 0.0

    def test_confidence_tightens_as_the_forecast_sharpens(self):
        far = DailyMaxDistribution(remaining_forecast=75, sigma=4.5)
        near = DailyMaxDistribution(remaining_forecast=75, sigma=1.0)
        assert near.confidence() > far.confidence()


class TestRoundingInteraction:
    def test_half_up_settlement_shifts_the_effective_cutoff(self):
        """Settling at 75 needs only 74.5 raw, which is worth real probability."""
        rounded = DailyMaxDistribution(
            remaining_forecast=74.5, sigma=2.0,
            rounding=SettlementRounding.NEAREST_INTEGER,
        )
        raw = DailyMaxDistribution(
            remaining_forecast=74.5, sigma=2.0, rounding=SettlementRounding.RAW
        )
        assert rounded.prob_at_or_above(75.0) > raw.prob_at_or_above(75.0)
        assert rounded.prob_at_or_above(75.0) == pytest.approx(0.5, abs=1e-9)

    def test_the_rounding_rule_materially_changes_the_price(self):
        """Why this is a verification item and not a detail.

        A forecast of 74.6F against a 75F threshold prices at 54c under
        round-half-up and 34c under truncation - a 20-cent swing from a
        settlement convention alone, which is an order of magnitude larger
        than any edge this model could hope to find. Assuming the wrong rule
        does not shrink the edge; it points it the wrong way.
        """
        args = {"remaining_forecast": 74.6, "sigma": 1.0}
        a = DailyMaxDistribution(**args, rounding=SettlementRounding.NEAREST_INTEGER)
        b = DailyMaxDistribution(**args, rounding=SettlementRounding.TRUNCATE)
        gap = a.prob_at_or_above(75.0) - b.prob_at_or_above(75.0)
        assert gap == pytest.approx(0.195, abs=0.01)


class TestBuckets:
    def test_bucket_probability_is_the_difference_of_tails(self):
        dist = DailyMaxDistribution(
            remaining_forecast=75.0, sigma=2.0, rounding=SettlementRounding.RAW
        )
        assert dist.prob_in_bucket(74.0, 76.0) == pytest.approx(
            dist.prob_at_or_above(74.0) - dist.prob_at_or_above(76.0)
        )

    def test_buckets_over_a_partition_sum_to_one(self):
        dist = DailyMaxDistribution(
            remaining_forecast=75.0, sigma=2.0, rounding=SettlementRounding.RAW
        )
        edges = [-1e6, 72, 74, 76, 78, 1e6]
        total = sum(
            dist.prob_in_bucket(lo, hi) for lo, hi in itertools.pairwise(edges)
        )
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_an_impossible_bucket_is_zero(self):
        dist = daily_max_distribution(
            observations=[80.0], remaining_forecast=70.0, lead_hours=2.0
        )
        assert dist.prob_in_bucket(70.0, 72.0) == 0.0


class TestStrategy:
    @pytest.fixture
    def strategy(self):
        return WeatherEdgeStrategy(min_edge_pips=200, haircut=0.5)

    def test_finds_the_settled_market_edge(self, strategy):
        """The trade the whole module exists for.

        Observed high is already 78F, so 'above 75F' has settled YES. If the
        market still offers it at 92c, that is 8c of certainty for sale.
        """
        market = WeatherMarket(
            market_key="kalshi:KXHIGHNY-26JUL30-T75",
            station="KNYC",
            threshold=75.0,
            close_time=TS + timedelta(hours=3),
        )
        result = strategy.evaluate(
            market,
            book("kalshi:KXHIGHNY-26JUL30-T75", 90, 92),
            observations=[70.0, 78.0],
            remaining_forecast=74.0,
            now=TS,
        )
        assert result is not None
        fv, side, edge = result
        assert side is Side.BUY
        assert fv.probability == 1.0, "settled markets must not be haircut"
        assert edge == c(8)

    def test_settled_the_other_way_is_a_sell(self, strategy):
        """Minimum already at 28F makes 'min >= 30F' impossible."""
        market = WeatherMarket(
            market_key="kalshi:KXLOWNY-26JUL30-T30",
            station="KNYC",
            threshold=30.0,
            is_minimum=True,
            close_time=TS + timedelta(hours=2),
        )
        result = strategy.evaluate(
            market,
            book("kalshi:KXLOWNY-26JUL30-T30", 6, 8),
            observations=[28.0],
            remaining_forecast=33.0,
            now=TS,
        )
        assert result is not None
        fv, side, edge = result
        assert side is Side.SELL
        assert fv.probability == 0.0
        assert edge == c(6)

    def test_a_fairly_priced_market_is_left_alone(self, strategy):
        market = WeatherMarket(
            market_key="kalshi:X", station="KNYC", threshold=75.0,
            close_time=TS + timedelta(hours=24),
        )
        assert strategy.evaluate(
            market,
            book("kalshi:X", 49, 51),
            observations=[],
            remaining_forecast=74.5,
            now=TS,
        ) is None

    def test_unsettled_opinions_are_haircut(self, strategy):
        """A new model's first job is to be measured, not trusted."""
        market = WeatherMarket(
            market_key="kalshi:X", station="KNYC", threshold=75.0,
            close_time=TS + timedelta(hours=24),
        )
        fv = strategy.fair_value(
            market, observations=[], remaining_forecast=80.0, now=TS
        )
        # Undiluted the model would be very confident; the haircut pulls it
        # back toward 50c.
        assert 0.5 < fv.probability < 0.95
        assert fv.confidence < 1.0

    def test_small_edges_are_ignored(self):
        strategy = WeatherEdgeStrategy(min_edge_pips=500)
        market = WeatherMarket(
            market_key="kalshi:X", station="KNYC", threshold=75.0,
            close_time=TS + timedelta(hours=3),
        )
        assert strategy.evaluate(
            market,
            book("kalshi:X", 96, 98),
            observations=[78.0],
            remaining_forecast=74.0,
            now=TS,
        ) is None

    def test_bucket_market_pricing(self, strategy):
        market = WeatherMarket(
            market_key="kalshi:B", station="KNYC", bucket=(74.0, 76.0),
            close_time=TS + timedelta(hours=12),
        )
        fv = strategy.fair_value(
            market, observations=[], remaining_forecast=75.0, now=TS
        )
        assert 0.0 < fv.probability < 1.0

    def test_market_without_threshold_or_bucket_is_an_error(self, strategy):
        market = WeatherMarket(market_key="kalshi:X", station="KNYC")
        with pytest.raises(ValueError, match="neither threshold nor bucket"):
            strategy.fair_value(
                market, observations=[], remaining_forecast=75.0, now=TS
            )


class TestCalibration:
    def test_a_perfect_model_scores_zero_brier(self):
        t = CalibrationTracker()
        for _ in range(50):
            t.add(CalibrationRecord("m", 1.0, True, c(50), TS))
        assert t.brier_score() == pytest.approx(0.0)

    def test_a_coin_flip_model_scores_a_quarter(self):
        t = CalibrationTracker()
        for i in range(100):
            t.add(CalibrationRecord("m", 0.5, i % 2 == 0, c(50), TS))
        assert t.brier_score() == pytest.approx(0.25)

    def test_beats_market_is_none_until_there_is_enough_data(self):
        t = CalibrationTracker()
        for _ in range(50):
            t.add(CalibrationRecord("m", 0.9, True, c(50), TS))
        assert t.beats_market() is None

    def test_detects_a_model_that_beats_the_market(self):
        t = CalibrationTracker()
        for _ in range(150):
            # Model says 90% and is right; market says 50%.
            t.add(CalibrationRecord("m", 0.9, True, c(50), TS))
        assert t.beats_market() is True
        assert t.brier_score() < t.market_brier_score()

    def test_detects_a_model_that_loses_to_the_market(self):
        """The result that should stop the strategy running."""
        t = CalibrationTracker()
        for _ in range(150):
            t.add(CalibrationRecord("m", 0.2, True, c(80), TS))
        assert t.beats_market() is False

    def test_reliability_bins_report_predicted_against_observed(self):
        t = CalibrationTracker(n_bins=10)
        for _ in range(80):
            t.add(CalibrationRecord("m", 0.75, True, c(70), TS))
        for _ in range(20):
            t.add(CalibrationRecord("m", 0.75, False, c(70), TS))
        bins = [b for b in t.reliability() if b[2] > 0]
        assert len(bins) == 1
        mean_pred, observed, count = bins[0]
        assert mean_pred == pytest.approx(0.75)
        assert observed == pytest.approx(0.80)
        assert count == 100

    def test_summary_is_serialisable(self):
        import json

        t = CalibrationTracker()
        t.add(CalibrationRecord("m", 0.6, True, c(55), TS))
        json.dumps(t.summary())
