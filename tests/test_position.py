"""Position and PnL accounting.

Every dollar the system thinks it has flows through this class. The tests
below pin the four transitions (open / add / reduce / flip) and, critically,
assert a *conservation law*: cash spent plus settlement received must equal
reported PnL, exactly, with no rounding drift.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from orbit.core.money import cents_to_pips, complement
from orbit.core.types import Fill, Position, Side

TS = datetime(2026, 1, 1, tzinfo=UTC)


def fill(side: Side, size: int, cents: int, fee_pips: int = 0) -> Fill:
    return Fill(
        market_key="kalshi:TEST",
        timestamp=TS,
        side=side,
        size=size,
        price_pips=cents_to_pips(cents),
        fee_pips=fee_pips,
        liquidity="taker",
        order_id="o1",
        client_order_id="c1",
    )


class TestOpeningAndAdding:
    def test_open_long(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50))
        assert p.size == 100
        assert p.cost_basis_pips == 100 * cents_to_pips(50)
        assert p.avg_price_pips == cents_to_pips(50)
        assert p.realized_pnl_pips == 0

    def test_open_short_records_negative_basis(self):
        """Selling YES at 40c is buying NO at 60c: $60 of collateral locked."""
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.SELL, 100, 40))
        assert p.size == -100
        assert p.cost_basis_pips == -100 * cents_to_pips(40)
        assert p.avg_price_pips == cents_to_pips(40)
        assert p.collateral_pips() == 100 * complement(cents_to_pips(40))

    def test_adding_averages_the_entry(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 40))
        p.apply_fill(fill(Side.BUY, 100, 60))
        assert p.size == 200
        assert p.avg_price_pips == cents_to_pips(50)
        assert p.realized_pnl_pips == 0


class TestReducing:
    def test_partial_close_of_a_long_realises_profit(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50))
        p.apply_fill(fill(Side.SELL, 50, 60))
        assert p.size == 50
        assert p.realized_pnl_pips == 50 * cents_to_pips(10)  # $5.00
        assert p.avg_price_pips == cents_to_pips(50)  # remainder keeps its basis

    def test_covering_a_short_at_a_lower_price_is_profit(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.SELL, 100, 40))
        p.apply_fill(fill(Side.BUY, 100, 30))
        assert p.is_flat
        assert p.realized_pnl_pips == 100 * cents_to_pips(10)  # $10.00

    def test_full_close_at_a_loss(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 60))
        p.apply_fill(fill(Side.SELL, 100, 45))
        assert p.is_flat
        assert p.realized_pnl_pips == -100 * cents_to_pips(15)
        assert p.cost_basis_pips == 0


class TestFlipping:
    def test_flip_long_to_short_realises_then_reopens(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50))
        p.apply_fill(fill(Side.SELL, 150, 60))
        assert p.size == -50
        # Closed 100 at +10c, then opened a 50-lot short at 60c.
        assert p.realized_pnl_pips == 100 * cents_to_pips(10)
        assert p.avg_price_pips == cents_to_pips(60)
        assert p.cost_basis_pips == -50 * cents_to_pips(60)

    def test_flip_short_to_long(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.SELL, 100, 70))
        p.apply_fill(fill(Side.BUY, 250, 60))
        assert p.size == 150
        assert p.realized_pnl_pips == 100 * cents_to_pips(10)
        assert p.avg_price_pips == cents_to_pips(60)


class TestFees:
    def test_fees_reduce_realised_pnl_on_both_sides(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50, fee_pips=cents_to_pips(2)))
        p.apply_fill(fill(Side.SELL, 100, 55, fee_pips=cents_to_pips(2)))
        gross = 100 * cents_to_pips(5)
        assert p.fees_paid_pips == 2 * cents_to_pips(2)
        assert p.realized_pnl_pips == gross - 2 * cents_to_pips(2)

    def test_a_winning_trade_can_be_a_losing_trade_after_fees(self):
        """The core lesson of this venue: 1c of edge does not cover mid fees."""
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50, fee_pips=175 * 100))  # $1.75
        p.apply_fill(fill(Side.SELL, 100, 51, fee_pips=175 * 100))
        assert p.realized_pnl_pips < 0


class TestSettlement:
    def test_long_settling_yes_pays_out(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50))
        pnl = p.settle(settled_yes=True)
        assert pnl == 100 * cents_to_pips(50)  # paid $50, received $100
        assert p.is_flat

    def test_long_settling_no_loses_the_premium(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50))
        pnl = p.settle(settled_yes=False)
        assert pnl == -100 * cents_to_pips(50)

    def test_short_settling_no_keeps_the_premium(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.SELL, 100, 40))
        pnl = p.settle(settled_yes=False)
        assert pnl == 100 * cents_to_pips(40)

    def test_short_settling_yes_loses_the_complement(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.SELL, 100, 40))
        pnl = p.settle(settled_yes=True)
        assert pnl == -100 * complement(cents_to_pips(40))


class TestUnrealisedAndCollateral:
    def test_unrealised_tracks_the_mark(self):
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.BUY, 100, 50))
        assert p.unrealized_pnl_pips(cents_to_pips(60)) == 100 * cents_to_pips(10)
        assert p.unrealized_pnl_pips(cents_to_pips(50)) == 0
        assert p.unrealized_pnl_pips(cents_to_pips(40)) == -100 * cents_to_pips(10)

    def test_flat_position_has_no_exposure(self):
        p = Position("kalshi:TEST")
        assert p.unrealized_pnl_pips(cents_to_pips(99)) == 0
        assert p.collateral_pips() == 0
        assert p.avg_price_pips is None

    def test_shorting_a_cheap_contract_locks_a_lot_of_collateral(self):
        """Selling a 5c longshot ties up 95c per contract to earn 5c.

        The reason "sell overpriced longshots" is far less attractive than it
        looks at small account sizes: the return on *deployed capital* is tiny
        even when the edge is real.
        """
        p = Position("kalshi:TEST")
        p.apply_fill(fill(Side.SELL, 100, 5))
        assert p.collateral_pips() == 100 * cents_to_pips(95)
        max_profit = 100 * cents_to_pips(5)
        assert max_profit / p.collateral_pips() < 0.06


class TestConservationLaw:
    """The books must balance exactly — no rounding drift, ever."""

    @settings(max_examples=300, deadline=None)
    @given(
        trades=st.lists(
            st.tuples(
                st.sampled_from([Side.BUY, Side.SELL]),
                st.integers(min_value=1, max_value=500),
                st.integers(min_value=1, max_value=99),
            ),
            min_size=1,
            max_size=12,
        ),
        settles_yes=st.booleans(),
    )
    def test_pnl_equals_cash_flow(self, trades, settles_yes):
        """Realised PnL after settlement must equal net cash in minus out.

        Computed two independent ways: by the Position class, and by naively
        summing every cash movement. They must agree to the pip.
        """
        p = Position("kalshi:TEST")
        cash = 0
        for side, size, cents in trades:
            f = fill(side, size, cents)
            cash += f.cash_delta_pips
            p.apply_fill(f)

        cash += p.size * (10_000 if settles_yes else 0)
        p.settle(settled_yes=settles_yes)

        assert p.realized_pnl_pips == cash
        assert p.is_flat
        assert p.cost_basis_pips == 0

    @settings(max_examples=200, deadline=None)
    @given(
        trades=st.lists(
            st.tuples(
                st.sampled_from([Side.BUY, Side.SELL]),
                st.integers(min_value=1, max_value=300),
                st.integers(min_value=1, max_value=99),
                st.integers(min_value=0, max_value=500),
            ),
            min_size=1,
            max_size=10,
        )
    )
    def test_fees_are_never_lost(self, trades):
        p = Position("kalshi:TEST")
        total_fees = 0
        for side, size, cents, fee in trades:
            total_fees += fee
            p.apply_fill(fill(side, size, cents, fee_pips=fee))
        assert p.fees_paid_pips == total_fees

    def test_round_trip_at_the_same_price_is_exactly_flat(self):
        for cents in range(1, 100):
            p = Position("kalshi:TEST")
            p.apply_fill(fill(Side.BUY, 137, cents))
            p.apply_fill(fill(Side.SELL, 137, cents))
            assert p.realized_pnl_pips == 0, f"drift at {cents}c"
            assert p.cost_basis_pips == 0


class TestFillInvariants:
    def test_cash_delta_signs(self):
        assert fill(Side.BUY, 100, 50).cash_delta_pips == -100 * cents_to_pips(50)
        assert fill(Side.SELL, 100, 50).cash_delta_pips == 100 * cents_to_pips(50)

    def test_fees_always_cost_cash(self):
        buy = fill(Side.BUY, 10, 50, fee_pips=1000)
        sell = fill(Side.SELL, 10, 50, fee_pips=1000)
        assert buy.cash_delta_pips == -10 * cents_to_pips(50) - 1000
        assert sell.cash_delta_pips == 10 * cents_to_pips(50) - 1000

    @pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
    def test_signed_size(self, side):
        assert fill(side, 7, 50).signed_size == side.sign * 7
