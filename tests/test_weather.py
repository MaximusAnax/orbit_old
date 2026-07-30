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


class TestWeatherData:
    """Parsing and the local-day boundary.

    The local-day split is where fact and forecast are separated, so an
    off-by-one here silently attributes yesterday evening's observations to
    today's contract and fabricates a floor that does not exist.
    """

    def test_celsius_conversion(self):
        from orbit.data.weather import celsius_to_f

        assert celsius_to_f(0) == 32.0
        assert celsius_to_f(100) == 212.0
        assert celsius_to_f(23.9) == pytest.approx(75.02, abs=0.01)

    def test_daily_extremes_group_by_local_day(self):
        from orbit.data.weather import Observation, daily_extremes

        # 03:00 UTC on the 31st is 23:00 on the 30th at UTC-4.
        obs = [
            Observation(datetime(2026, 7, 30, 18, tzinfo=UTC), 78.0, "KNYC"),
            Observation(datetime(2026, 7, 30, 20, tzinfo=UTC), 82.0, "KNYC"),
            Observation(datetime(2026, 7, 31, 3, tzinfo=UTC), 70.0, "KNYC"),
            Observation(datetime(2026, 7, 31, 18, tzinfo=UTC), 65.0, "KNYC"),
        ]
        extremes = daily_extremes(obs, timezone_offset_h=-4)
        assert extremes["2026-07-30"] == (82.0, 70.0)
        assert extremes["2026-07-31"] == (65.0, 65.0)

    def test_station_day_reports_observed_extremes(self):
        from orbit.data.weather import StationDay

        day = StationDay("KNYC", "2026-07-30", observations=[70.0, 78.0, 74.0])
        assert day.observed_max == 78.0
        assert day.observed_min == 70.0
        assert day.is_usable()

    def test_a_station_day_with_nothing_is_not_usable(self):
        """No data must degrade to no opinion, never to a fabricated one."""
        from orbit.data.weather import StationDay

        assert not StationDay("KNYC", "2026-07-30").is_usable()

    def test_forecast_only_day_is_usable(self):
        from orbit.data.weather import StationDay

        day = StationDay("KNYC", "2026-07-30", remaining_forecast=75.0)
        assert day.is_usable()

    def test_station_day_feeds_the_model_directly(self):
        """The two halves line up: observations censor, forecast estimates."""
        from orbit.data.weather import StationDay

        day = StationDay(
            "KNYC", "2026-07-30", observations=[70.0, 79.0], remaining_forecast=72.0,
            hours_remaining=5.0,
        )
        dist = daily_max_distribution(
            observations=day.observations,
            remaining_forecast=day.remaining_forecast,
            lead_hours=day.hours_remaining,
        )
        assert dist.prob_at_or_above(78.0) == 1.0
        assert dist.prob_at_or_above(85.0) < 0.05


class TestCertaintyCurve:
    """The experiment that settles whether the weather edge exists.

    Built from synthetic days with a known shape so the measurement itself can
    be verified before it is pointed at real data.
    """

    def _day(self, date_str: str, hourly: list[float], offset_h: float = 0.0):
        from datetime import datetime as dt

        from orbit.data.weather import Observation

        base = dt.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        return [
            Observation(base + timedelta(hours=h - offset_h), t, "KTEST")
            for h, t in enumerate(hourly)
        ]

    def _typical_day(self, peak_hour: int = 15, peak: float = 80.0):
        """A normal diurnal curve peaking mid-afternoon."""
        return [
            peak - abs(h - peak_hour) * 1.5 for h in range(24)
        ]

    def test_detects_that_the_max_locks_in_mid_afternoon(self):
        from orbit.strategies.weather_study import build_certainty_curve

        obs = []
        for d in range(1, 29):
            obs += self._day(f"2026-06-{d:02d}", self._typical_day(peak_hour=15))
        curve = build_certainty_curve(obs, timezone_offset_h=0, station_id="KTEST")

        assert curve.days_analysed == 28
        # Before the peak nothing is settled; after it, everything is.
        assert curve.settled_fraction_at(10) == 0.0
        assert curve.settled_fraction_at(15) == 1.0
        assert curve.settled_fraction_at(18) == 1.0
        assert curve.first_hour_above(0.8) == 15

    def test_a_late_peaking_station_settles_late(self):
        """The result that would kill the strategy, and must be detectable."""
        from orbit.strategies.weather_study import build_certainty_curve

        obs = []
        for d in range(1, 29):
            obs += self._day(f"2026-06-{d:02d}", self._typical_day(peak_hour=23))
        curve = build_certainty_curve(obs, timezone_offset_h=0)
        assert curve.settled_fraction_at(15) == 0.0
        assert curve.first_hour_above(0.5) == 23

    def test_sparse_days_are_excluded_not_counted_as_settled(self):
        """A station that stops reporting must not look like an early peak.

        Otherwise the study manufactures exactly the result it is testing for.
        """
        from orbit.strategies.weather_study import build_certainty_curve

        obs = self._day("2026-06-01", self._typical_day())          # full day
        obs += self._day("2026-06-02", [70.0, 71.0, 72.0])           # 3 readings
        curve = build_certainty_curve(
            obs, timezone_offset_h=0, min_observations_per_day=12
        )
        assert curve.days_analysed == 1

    def test_remaining_rise_shrinks_through_the_day(self):
        from orbit.strategies.weather_study import build_certainty_curve

        obs = []
        for d in range(1, 15):
            obs += self._day(f"2026-06-{d:02d}", self._typical_day(peak_hour=15))
        curve = build_certainty_curve(obs, timezone_offset_h=0)
        gaps = {h.local_hour: h.mean_remaining_rise for h in curve.hours}
        assert gaps[6] > gaps[12] > gaps[15]
        assert gaps[15] == pytest.approx(0.0, abs=1e-9)

    def test_timezone_offset_shifts_the_curve(self):
        from orbit.strategies.weather_study import build_certainty_curve

        obs = []
        for d in range(1, 15):
            obs += self._day(f"2026-06-{d:02d}", self._typical_day(peak_hour=15))
        utc = build_certainty_curve(obs, timezone_offset_h=0)
        west = build_certainty_curve(obs, timezone_offset_h=-5)
        assert utc.first_hour_above(0.8) != west.first_hour_above(0.8)

    def test_summary_and_table_render(self):
        import json

        from orbit.strategies.weather_study import build_certainty_curve

        obs = []
        for d in range(1, 15):
            obs += self._day(f"2026-06-{d:02d}", self._typical_day())
        curve = build_certainty_curve(obs, timezone_offset_h=0, station_id="KTEST")
        json.dumps(curve.summary())
        assert "settled" in curve.format_table()

    def test_empty_input_is_safe(self):
        from orbit.strategies.weather_study import build_certainty_curve

        curve = build_certainty_curve([], timezone_offset_h=0)
        assert curve.days_analysed == 0
        assert curve.first_hour_above(0.5) is None


class TestSettledThresholdCount:
    def _obs(self, hourly):
        from datetime import datetime as dt

        from orbit.data.weather import Observation

        base = dt(2026, 6, 1, tzinfo=UTC)
        return [
            Observation(base + timedelta(hours=h), t, "KTEST")
            for h, t in enumerate(hourly)
        ]

    def test_counts_thresholds_already_passed(self):
        from orbit.strategies.weather_study import count_settled_thresholds

        # Peaks at 80F by hour 15.
        hourly = [80.0 - abs(h - 15) * 1.5 for h in range(24)]
        result = count_settled_thresholds(
            self._obs(hourly),
            timezone_offset_h=0,
            thresholds=[70, 75, 78, 82, 90],
            at_local_hour=15,
            plausible_remaining_rise=3.0,
        )
        # 70, 75, 78 are at or below the 80F running max -> settled YES.
        assert result.mean_settled_yes_thresholds == 3.0
        # 90 is above 80 + 3 -> settled NO. 82 is still live.
        assert result.mean_settled_no_thresholds == 1.0
        assert result.mean_total == 4.0

    def test_early_in_the_day_almost_nothing_is_settled(self):
        from orbit.strategies.weather_study import count_settled_thresholds

        hourly = [80.0 - abs(h - 15) * 1.5 for h in range(24)]
        result = count_settled_thresholds(
            self._obs(hourly),
            timezone_offset_h=0,
            thresholds=[70, 75, 78, 82],
            at_local_hour=5,
            plausible_remaining_rise=20.0,
        )
        assert result.mean_settled_no_thresholds == 0.0

    def test_a_generous_rise_allowance_claims_less_certainty(self):
        """Being conservative must reduce claimed edge, never increase it."""
        from orbit.strategies.weather_study import count_settled_thresholds

        hourly = [80.0 - abs(h - 15) * 1.5 for h in range(24)]
        args = {
            "timezone_offset_h": 0,
            "thresholds": [82, 85, 90],
            "at_local_hour": 15,
        }
        tight = count_settled_thresholds(
            self._obs(hourly), **args, plausible_remaining_rise=1.0
        )
        loose = count_settled_thresholds(
            self._obs(hourly), **args, plausible_remaining_rise=15.0
        )
        assert loose.mean_settled_no_thresholds < tight.mean_settled_no_thresholds


class TestDollarEstimate:
    def test_sensitivity_to_capture_rate_is_linear_and_brutal(self):
        from orbit.strategies.weather_study import estimate_monthly_dollars

        base = {
            "settled_contracts_per_day": 4.0,
            "stations": 7,
            "edge_cents": 2.0,
            "contracts_per_trade": 50,
        }
        optimistic = estimate_monthly_dollars(**base, capture_rate=0.5)
        realistic = estimate_monthly_dollars(**base, capture_rate=0.05)
        assert optimistic["gross_dollars_per_month"] == pytest.approx(
            realistic["gross_dollars_per_month"] * 10
        )

    def test_assumptions_are_reported_alongside_the_number(self):
        from orbit.strategies.weather_study import estimate_monthly_dollars

        out = estimate_monthly_dollars(
            settled_contracts_per_day=4.0, stations=7, capture_rate=0.1,
            edge_cents=2.0, contracts_per_trade=50,
        )
        assert out["assumed_capture_rate"] == 0.1
        assert out["assumed_edge_cents"] == 2.0
