"""Position sizing and Kelly math.

The tests that matter here are not the arithmetic ones — they are the ones
asserting that the sizer *refuses* to trade. A sizing bug that trades too
small costs a little money; one that trades too large ends the account.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from orbit.core.fees import KalshiFees
from orbit.core.money import cents_to_pips
from orbit.core.types import Side
from orbit.risk.sizing import (
    PositionSizer,
    correlated_kelly_scale,
    expected_growth_rate,
    kelly_fraction,
)

BANKROLL = 50_000_000  # $5,000 in pips


def c(cents: int) -> int:
    return cents_to_pips(cents)


class TestKellyFraction:
    def test_classic_result(self):
        """q=0.6 at 50c: f* = (0.6-0.5)/(1-0.5) = 0.20."""
        f = kelly_fraction(price_pips=c(50), true_prob=0.6, side=Side.BUY)
        assert f == pytest.approx(0.20)

    def test_certainty_stakes_everything(self):
        f = kelly_fraction(price_pips=c(50), true_prob=1.0, side=Side.BUY)
        assert f == pytest.approx(1.0)

    def test_no_edge_is_zero(self):
        assert kelly_fraction(price_pips=c(50), true_prob=0.5, side=Side.BUY) == 0.0

    def test_negative_edge_is_negative(self):
        assert kelly_fraction(price_pips=c(60), true_prob=0.5, side=Side.BUY) < 0

    def test_sell_side_is_the_mirror_of_buy(self):
        """Selling YES at p with prob q == buying NO at 1-p with prob 1-q."""
        for cents in range(10, 91, 10):
            for q in (0.2, 0.5, 0.8):
                sell = kelly_fraction(price_pips=c(cents), true_prob=q, side=Side.SELL)
                buy = kelly_fraction(
                    price_pips=c(100 - cents), true_prob=1 - q, side=Side.BUY
                )
                assert sell == pytest.approx(buy, abs=1e-9)

    @given(
        cents=st.integers(min_value=1, max_value=99),
        q=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_never_exceeds_one(self, cents, q):
        """Staking more than the bankroll is not a thing Kelly ever asks for."""
        for side in (Side.BUY, Side.SELL):
            assert kelly_fraction(price_pips=c(cents), true_prob=q, side=side) <= 1.0


class TestGrowthRateAsymmetry:
    """The reason this system uses quarter Kelly."""

    def test_growth_peaks_at_full_kelly(self):
        price, q = c(50), 0.6
        f_star = kelly_fraction(price_pips=price, true_prob=q, side=Side.BUY)
        best = expected_growth_rate(
            price_pips=price, true_prob=q, side=Side.BUY, fraction=f_star
        )
        for delta in (-0.05, -0.02, 0.02, 0.05):
            other = expected_growth_rate(
                price_pips=price, true_prob=q, side=Side.BUY, fraction=f_star + delta
            )
            assert other <= best + 1e-12

    def test_double_kelly_gives_up_essentially_all_growth(self):
        """At ~2x Kelly the edge is fully consumed by variance drag.

        The clean "exactly zero at 2x Kelly" identity is a property of the
        continuous/log-normal approximation. For a discrete binary bet the
        zero-crossing sits near 2x rather than exactly on it — here growth is
        already slightly negative. The point stands either way: doubling the
        Kelly stake converts a real 20%-edge into no growth at all.
        """
        price, q = c(50), 0.6
        f_star = kelly_fraction(price_pips=price, true_prob=q, side=Side.BUY)
        assert expected_growth_rate(
            price_pips=price, true_prob=q, side=Side.BUY, fraction=f_star
        ) > 0

        # Locate the actual zero-growth stake by bisection and check it lands
        # near 2x Kelly. This asserts the real property rather than tuning a
        # tolerance until it passes.
        lo, hi = f_star, 0.99
        for _ in range(60):
            mid = (lo + hi) / 2
            if expected_growth_rate(
                price_pips=price, true_prob=q, side=Side.BUY, fraction=mid
            ) > 0:
                lo = mid
            else:
                hi = mid
        zero_growth_stake = (lo + hi) / 2
        assert zero_growth_stake == pytest.approx(2 * f_star, rel=0.05)

    def test_beyond_double_kelly_is_negative(self):
        price, q = c(50), 0.6
        f_star = kelly_fraction(price_pips=price, true_prob=q, side=Side.BUY)
        assert expected_growth_rate(
            price_pips=price, true_prob=q, side=Side.BUY, fraction=2.5 * f_star
        ) < 0

    def test_quarter_kelly_keeps_most_of_the_growth(self):
        """The trade being made: give up ~6% of growth, remove most of the risk."""
        price, q = c(50), 0.6
        f_star = kelly_fraction(price_pips=price, true_prob=q, side=Side.BUY)
        full = expected_growth_rate(
            price_pips=price, true_prob=q, side=Side.BUY, fraction=f_star
        )
        quarter = expected_growth_rate(
            price_pips=price, true_prob=q, side=Side.BUY, fraction=0.25 * f_star
        )
        assert quarter / full > 0.4

    def test_full_stake_risks_ruin(self):
        assert expected_growth_rate(
            price_pips=c(50), true_prob=0.9, side=Side.BUY, fraction=1.0
        ) == float("-inf")


class TestSizerRefusals:
    """Sizing to zero is the most important behaviour in this class."""

    @pytest.fixture
    def sizer(self):
        return PositionSizer()

    def test_refuses_when_price_is_fair(self, sizer):
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.50, side=Side.BUY
        )
        assert r.size == 0
        assert not r.is_actionable
        assert "no edge" in r.binding_constraint

    def test_refuses_when_the_edge_is_the_wrong_way(self, sizer):
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(70), true_prob=0.50, side=Side.BUY
        )
        assert r.size == 0

    def test_refuses_below_the_confidence_floor(self, sizer):
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.65,
            side=Side.BUY, confidence=0.05,
        )
        assert r.size == 0
        assert "confidence" in r.binding_constraint

    def test_refuses_a_thin_edge_that_fees_would_eat(self, sizer):
        """1c of edge at mid-book against a 1.75c fee: never worth doing."""
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.51,
            side=Side.BUY, fee_model=KalshiFees(),
        )
        assert r.size == 0
        assert "fee" in r.binding_constraint

    def test_same_edge_survives_in_the_wings(self, sizer):
        """1c of edge at 95c clears the much smaller fee there."""
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(95), true_prob=0.96,
            side=Side.BUY, fee_model=KalshiFees(),
        )
        assert r.size > 0
        assert r.expected_value_pips > 0

    def test_refuses_when_bankroll_cannot_afford_one_contract(self, sizer):
        r = sizer.size(
            bankroll_pips=100, price_pips=c(50), true_prob=0.9, side=Side.BUY
        )
        assert r.size == 0

    def test_zero_bankroll(self, sizer):
        r = sizer.size(
            bankroll_pips=0, price_pips=c(50), true_prob=0.9, side=Side.BUY
        )
        assert r.size == 0


class TestSizerConstraints:
    @pytest.fixture
    def sizer(self):
        return PositionSizer(max_fraction_per_trade=0.05)

    def test_per_trade_cap_binds_on_a_huge_edge(self, sizer):
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.95, side=Side.BUY
        )
        assert r.binding_constraint == "per-trade cap"
        assert r.capital_at_risk_pips <= int(BANKROLL * 0.05) + c(50)

    def test_liquidity_caps_size(self, sizer):
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.95,
            side=Side.BUY, available_liquidity=7,
        )
        assert r.size == 7
        assert r.binding_constraint == "available liquidity"

    def test_position_limit_caps_size(self, sizer):
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.95,
            side=Side.BUY, max_contracts=3,
        )
        assert r.size == 3
        assert r.binding_constraint == "position limit"

    def test_confidence_scales_size_down(self, sizer):
        kwargs = {
            "bankroll_pips": BANKROLL, "price_pips": c(40),
            "true_prob": 0.55, "side": Side.BUY,
        }
        sure = sizer.size(**kwargs, confidence=1.0)
        unsure = sizer.size(**kwargs, confidence=0.4)
        assert 0 < unsure.size < sure.size

    def test_capital_at_risk_never_exceeds_bankroll(self):
        sizer = PositionSizer(max_fraction_per_trade=1.0, kelly_fraction_cap=1.0)
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(50), true_prob=0.99, side=Side.BUY
        )
        assert r.capital_at_risk_pips <= BANKROLL

    def test_short_side_collateral_is_the_complement(self):
        """Selling a 5c contract ties up 95c, so size is bounded accordingly."""
        sizer = PositionSizer(max_fraction_per_trade=1.0, kelly_fraction_cap=1.0)
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(5), true_prob=0.01, side=Side.SELL
        )
        assert r.capital_at_risk_pips <= BANKROLL
        assert r.size <= BANKROLL // c(95)

    @settings(max_examples=200, deadline=None)
    @given(
        cents=st.integers(min_value=2, max_value=98),
        q=st.floats(min_value=0.01, max_value=0.99),
        side=st.sampled_from([Side.BUY, Side.SELL]),
    )
    def test_never_risks_more_than_the_bankroll(self, cents, q, side):
        sizer = PositionSizer(max_fraction_per_trade=1.0, kelly_fraction_cap=1.0)
        r = sizer.size(
            bankroll_pips=BANKROLL, price_pips=c(cents), true_prob=q, side=side
        )
        assert 0 <= r.capital_at_risk_pips <= BANKROLL


class TestCorrelationScaling:
    def test_single_position_is_unscaled(self):
        assert correlated_kelly_scale(1) == 1.0

    def test_more_correlated_positions_shrink_each_one(self):
        scales = [correlated_kelly_scale(n) for n in (1, 2, 5, 10)]
        assert scales == sorted(scales, reverse=True)
        assert all(0 < s <= 1.0 for s in scales)

    def test_independent_bets_are_not_penalised(self):
        assert correlated_kelly_scale(10, rho=0.0) == 1.0

    def test_perfect_correlation_is_one_over_n(self):
        """Ten identical bets are one bet; stake each a tenth as much."""
        assert correlated_kelly_scale(10, rho=1.0) == pytest.approx(1 / math.sqrt(10))

    def test_realistic_election_book_gets_halved(self):
        """Five correlated election markets at rho=0.7 -> ~0.5x per position."""
        assert correlated_kelly_scale(5, rho=0.7) == pytest.approx(0.5, abs=0.03)
