"""Fee math must be exact. These tests pin it against known values.

If Kalshi changes its schedule, these tests should fail loudly rather than let
a backtest quietly compute profits that do not exist.
"""

from __future__ import annotations

import math

import pytest

from orbit.core.fees import (
    KalshiFees,
    KalshiFeeSchedule,
    Liquidity,
    PolymarketFees,
    PolymarketFeeSchedule,
)
from orbit.core.money import PIPS_PER_CENT, cents_to_pips


class TestKalshiTradingFees:
    """Kalshi general schedule: fee = ceil_to_cent(0.07 * C * P * (1 - P))."""

    @pytest.mark.parametrize(
        ("cents", "contracts", "expected_dollars"),
        [
            # 0.07 * 100 * 0.50 * 0.50 = $1.75 exactly, no rounding needed.
            (50, 100, 1.75),
            # 0.07 * 100 * 0.25 * 0.75 = $1.3125 -> ceil to $1.32.
            (25, 100, 1.32),
            # 0.07 * 100 * 0.75 * 0.25 = $1.3125 -> ceil to $1.32 (symmetric).
            (75, 100, 1.32),
            # 0.07 * 100 * 0.90 * 0.10 = $0.63 exactly.
            (90, 100, 0.63),
            # 0.07 * 100 * 0.99 * 0.01 = $0.0693 -> ceil to $0.07.
            (99, 100, 0.07),
            # 0.07 * 100 * 0.01 * 0.99 = $0.0693 -> ceil to $0.07.
            (1, 100, 0.07),
        ],
    )
    def test_matches_published_formula(self, cents, contracts, expected_dollars):
        fees = KalshiFees()
        got = fees.trade_fee_pips(
            price_pips=cents_to_pips(cents),
            size=contracts,
            liquidity=Liquidity.TAKER,
        )
        assert got == pytest.approx(expected_dollars * 10_000, abs=1e-6)

    def test_fee_is_symmetric_about_fifty_cents(self):
        """P*(1-P) is symmetric, so buying at 30c costs what buying at 70c does."""
        fees = KalshiFees()
        for c in range(1, 50):
            lo = fees.trade_fee_pips(
                price_pips=cents_to_pips(c), size=500, liquidity=Liquidity.TAKER
            )
            hi = fees.trade_fee_pips(
                price_pips=cents_to_pips(100 - c), size=500, liquidity=Liquidity.TAKER
            )
            assert lo == hi, f"asymmetry at {c}c"

    def test_fee_peaks_at_the_middle_of_the_book(self):
        """The strategic fact: trading the wings is far cheaper than the middle.

        Uses a large size so the per-order cent-ceiling does not blur the peak.
        """
        fees = KalshiFees()
        per_contract = [
            (c, fees.fee_per_contract_pips(cents_to_pips(c), size=100_000))
            for c in range(1, 100)
        ]
        worst_price, worst_fee = max(per_contract, key=lambda kv: kv[1])
        assert worst_price == 50
        # ~1.75c at the mid vs ~0.07c at 99c: a 25x difference.
        assert worst_fee == pytest.approx(1.75 * PIPS_PER_CENT, rel=0.01)
        assert (
            fees.fee_per_contract_pips(cents_to_pips(99), size=100_000) < worst_fee / 20
        )

    def test_cent_ceiling_creates_ties_near_the_peak(self):
        """At ordinary sizes the ceiling flattens the top of the fee parabola.

        At 1000 contracts, 49c costs $17.493 and 50c costs $17.500 — both round
        up to $17.50. Quoting one tick off the mid to dodge fees does nothing;
        the saving only appears further out in the wings.
        """
        fees = KalshiFees()
        at_49 = fees.fee_per_contract_pips(cents_to_pips(49), size=1000)
        at_50 = fees.fee_per_contract_pips(cents_to_pips(50), size=1000)
        assert at_49 == at_50

        # But move meaningfully into the wing and the saving is large.
        at_90 = fees.fee_per_contract_pips(cents_to_pips(90), size=1000)
        assert at_90 < at_50 / 2

    def test_maker_is_free_on_the_general_schedule(self):
        fees = KalshiFees()
        assert (
            fees.trade_fee_pips(
                price_pips=cents_to_pips(50), size=1000, liquidity=Liquidity.MAKER
            )
            == 0
        )

    def test_maker_fee_applies_when_schedule_sets_one(self):
        fees = KalshiFees(KalshiFeeSchedule(maker_rate=0.0175))
        got = fees.trade_fee_pips(
            price_pips=cents_to_pips(50), size=100, liquidity=Liquidity.MAKER
        )
        # 0.0175 * 100 * 0.25 = $0.4375 -> ceil to $0.44.
        assert got == pytest.approx(0.44 * 10_000, abs=1e-6)

    def test_ceiling_is_per_order_so_small_orders_are_penalised(self):
        """One contract at 50c owes 2c of fee on a 50c notional — a 4% tax.

        This is why the risk engine must never send one-lot orders casually.
        """
        fees = KalshiFees()
        one = fees.trade_fee_pips(
            price_pips=cents_to_pips(50), size=1, liquidity=Liquidity.TAKER
        )
        assert one == 2 * PIPS_PER_CENT  # ceil($0.0175) = $0.02

        hundred = fees.trade_fee_pips(
            price_pips=cents_to_pips(50), size=100, liquidity=Liquidity.TAKER
        )
        assert hundred / 100 < one  # amortised rate improves with size

    def test_zero_and_negative_size_are_free(self):
        fees = KalshiFees()
        for size in (0, -5):
            assert (
                fees.trade_fee_pips(
                    price_pips=cents_to_pips(50), size=size, liquidity=Liquidity.TAKER
                )
                == 0
            )

    def test_fee_never_exceeds_notional(self):
        """A sanity bound: no fee schedule should cost more than the contract."""
        fees = KalshiFees()
        for c in range(1, 100):
            for size in (1, 10, 1000):
                fee = fees.trade_fee_pips(
                    price_pips=cents_to_pips(c), size=size, liquidity=Liquidity.TAKER
                )
                assert fee <= cents_to_pips(c) * size


class TestRoundTripAndSizing:
    def test_round_trip_cost_is_the_hurdle_to_beat(self):
        """Buy at 49c, sell at 51c: 2c gross, but fees eat most of it."""
        fees = KalshiFees()
        size = 100
        gross_pips = cents_to_pips(2) * size
        cost = fees.round_trip_cost_pips(
            cents_to_pips(49), cents_to_pips(51), size=size
        )
        assert cost > 0
        # ~1.75c/contract each way = ~3.5c round trip against a 2c gross edge.
        assert cost > gross_pips, "a 2c scalp at mid-book is fee-negative"

    def test_wing_scalp_can_survive_where_mid_scalp_cannot(self):
        """Same 2c gross edge at 95c clears fees comfortably."""
        fees = KalshiFees()
        size = 100
        gross_pips = cents_to_pips(2) * size
        cost = fees.round_trip_cost_pips(
            cents_to_pips(94), cents_to_pips(96), size=size
        )
        assert cost < gross_pips

    def test_min_profitable_size_rejects_fee_negative_edges(self):
        fees = KalshiFees()
        # 1c of edge at 50c, where the fee alone is 1.75c/contract.
        assert (
            fees.min_profitable_size(
                price_pips=cents_to_pips(50), edge_pips_per_contract=PIPS_PER_CENT
            )
            == 0
        )

    def test_min_profitable_size_finds_a_size_when_edge_is_real(self):
        fees = KalshiFees()
        size = fees.min_profitable_size(
            price_pips=cents_to_pips(95), edge_pips_per_contract=PIPS_PER_CENT
        )
        assert size > 0
        fee = fees.trade_fee_pips(
            price_pips=cents_to_pips(95), size=size, liquidity=Liquidity.TAKER
        )
        assert PIPS_PER_CENT * size > fee

    def test_min_profitable_size_rejects_nonpositive_edge(self):
        fees = KalshiFees()
        assert (
            fees.min_profitable_size(price_pips=cents_to_pips(50), edge_pips_per_contract=0)
            == 0
        )


class TestPolymarketFees:
    def test_zero_fee_schedule_is_actually_zero(self):
        fees = PolymarketFees()
        for c in (1, 25, 50, 99):
            for liq in (Liquidity.MAKER, Liquidity.TAKER):
                assert (
                    fees.trade_fee_pips(
                        price_pips=cents_to_pips(c), size=1000, liquidity=liq
                    )
                    == 0
                )

    def test_bps_fee_charges_on_notional(self):
        fees = PolymarketFees(PolymarketFeeSchedule(taker_fee_bps=100))  # 1%
        got = fees.trade_fee_pips(
            price_pips=cents_to_pips(50), size=100, liquidity=Liquidity.TAKER
        )
        # notional = 0.50 * 100 = $50; 1% = $0.50
        assert got == pytest.approx(0.50 * 10_000, abs=1.0)

    def test_settlement_is_free(self):
        assert PolymarketFees().settlement_fee_pips(size=100, settled_yes=True) == 0


class TestCrossVenueFeeAsymmetry:
    """The asymmetry that makes cross-venue trading directional.

    With Polymarket at zero fees and Kalshi charging takers, the same nominal
    price is not the same effective price. Any arb model that ignores this will
    systematically overstate its edge on the Kalshi leg.
    """

    def test_kalshi_leg_is_strictly_more_expensive_at_mid(self):
        k, p = KalshiFees(), PolymarketFees()
        args = {"price_pips": cents_to_pips(50), "size": 200, "liquidity": Liquidity.TAKER}
        assert k.trade_fee_pips(**args) > p.trade_fee_pips(**args)

    def test_breakeven_gap_at_mid_is_material(self):
        """Round-tripping 50c on Kalshi costs ~3.5c; the arb must clear that."""
        k = KalshiFees()
        size = 500
        cost = k.round_trip_cost_pips(cents_to_pips(50), cents_to_pips(50), size=size)
        per_contract_cents = cost / size / PIPS_PER_CENT
        assert 3.0 < per_contract_cents < 4.0
        assert not math.isnan(per_contract_cents)


class TestFillFragmentation:
    """The cent-ceiling applies per fill, not per order.

    Under-modelling this is the most common way a prediction-market backtest
    overstates profit, and it bites hardest on exactly the small orders and
    thin books a $5k account trades.
    """

    def test_fragmenting_an_order_costs_more(self):
        fees = KalshiFees()
        args = {"price_pips": cents_to_pips(50), "liquidity": Liquidity.TAKER}
        one_block = fees.trade_fee_pips(size=20, n_fills=1, **args)
        twenty_pieces = fees.trade_fee_pips(size=20, n_fills=20, **args)
        assert twenty_pieces > one_block
        # 20 x ceil(1.75c) = 40c against ceil(35.0c) = 35c.
        assert twenty_pieces == 40 * PIPS_PER_CENT
        assert one_block == 35 * PIPS_PER_CENT

    def test_fee_is_monotone_in_fragmentation(self):
        fees = KalshiFees()
        args = {"price_pips": cents_to_pips(37), "size": 60,
                "liquidity": Liquidity.TAKER}
        costs = [fees.trade_fee_pips(n_fills=n, **args) for n in (1, 2, 3, 6, 60)]
        assert costs == sorted(costs)

    def test_n_fills_cannot_exceed_size(self):
        fees = KalshiFees()
        args = {"price_pips": cents_to_pips(50), "size": 3,
                "liquidity": Liquidity.TAKER}
        assert fees.trade_fee_pips(n_fills=3, **args) == fees.trade_fee_pips(
            n_fills=99, **args
        )

    def test_n_fills_is_ignored_below_one(self):
        fees = KalshiFees()
        args = {"price_pips": cents_to_pips(50), "size": 10,
                "liquidity": Liquidity.TAKER}
        assert fees.trade_fee_pips(n_fills=0, **args) == fees.trade_fee_pips(
            n_fills=1, **args
        )

    def test_polymarket_fragmentation_is_cost_neutral(self):
        """A proportional fee has no rounding to exploit or suffer."""
        fees = PolymarketFees(PolymarketFeeSchedule(taker_fee_bps=100))
        args = {"price_pips": cents_to_pips(50), "size": 100,
                "liquidity": Liquidity.TAKER}
        assert fees.trade_fee_pips(n_fills=1, **args) == fees.trade_fee_pips(
            n_fills=50, **args
        )
