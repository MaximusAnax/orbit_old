"""Logical-consistency arbitrage.

The critical property under test is not "does it find opportunities" but
**"does it ever report a guaranteed profit that is not guaranteed"**. A false
positive here is a naked directional position the system believes is riskless,
which is the most expensive kind of bug available.

So the central test brute-forces every feasible resolution of every reported
opportunity and asserts the PnL is positive in all of them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from orbit.core.fees import KalshiFees, PolymarketFees
from orbit.core.money import PIPS_PER_DOLLAR, cents_to_pips
from orbit.core.types import Side
from orbit.strategies.constraints import (
    ArbLeg,
    ComplementConstraint,
    ConstraintScanner,
    CrossVenueConstraint,
    MonotoneConstraint,
    PartitionConstraint,
    ThresholdBucketConstraint,
    build_monotone_ladder,
)
from orbit.venues.base import normalize_two_sided_book

TS = datetime(2026, 1, 1, tzinfo=UTC)
FEES = {"kalshi": KalshiFees(), "polymarket": PolymarketFees()}
FREE = {}  # no fee model -> zero fees, for isolating the arithmetic


def c(cents: int) -> int:
    return cents_to_pips(cents)


def book(key: str, bid: int | None, ask: int | None, size: int = 1000):
    return normalize_two_sided_book(
        market_key=key,
        timestamp=TS,
        bids=[(c(bid), size)] if bid is not None else [],
        asks=[(c(ask), size)] if ask is not None else [],
    )


def brute_force_worst_case(constraint, legs, fees_pips: int = 0) -> int:
    """Independently recompute the worst case, without the class under test."""
    index = {k: i for i, k in enumerate(constraint.market_keys)}
    worst = None
    for scenario in constraint.feasible_outcomes():
        total = 0
        for leg in legs:
            i = index[leg.market_key]
            payout = PIPS_PER_DOLLAR if scenario[i] else 0
            total += leg.side.sign * (payout - leg.limit_pips) * leg.size
        total -= fees_pips
        worst = total if worst is None else min(worst, total)
    return worst or 0


class TestComplementParity:
    def test_finds_a_crossed_book(self):
        """yes_bid 55c + no_bid 48c = 103c > $1: buy both, collect 3c."""
        con = ComplementConstraint(["kalshi:A"])
        books = {"kalshi:A": book("kalshi:A", bid=55, ask=52)}
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None
        assert opp.is_profitable
        assert opp.worst_case_profit_pips == 1000 * c(3)

    def test_no_opportunity_on_a_normal_book(self):
        con = ComplementConstraint(["kalshi:A"])
        assert con.scan({"kalshi:A": book("kalshi:A", bid=45, ask=48)},
                        fee_models=FREE) is None

    def test_fees_can_erase_a_thin_cross(self):
        """A 1c cross at mid-book does not survive Kalshi's 1.75c taker fee."""
        con = ComplementConstraint(["kalshi:A"])
        books = {"kalshi:A": book("kalshi:A", bid=50, ask=49)}
        assert con.scan(books, fee_models=FREE) is not None
        assert con.scan(books, fee_models=FEES) is None

    def test_profit_is_identical_in_both_resolutions(self):
        con = ComplementConstraint(["kalshi:A"])
        opp = con.scan({"kalshi:A": book("kalshi:A", bid=55, ask=52)}, fee_models=FREE)
        assert opp.worst_case_profit_pips == opp.best_case_profit_pips


class TestMonotoneLadder:
    def test_detects_an_inverted_date_ladder(self):
        """'by March' bidding 40c while 'by June' offers at 35c is impossible.

        March implies June, so March can never be worth more. Sell March, buy
        June, and the pair profits in all three feasible outcomes.
        """
        con = MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"])
        books = {
            "kalshi:MAR": book("kalshi:MAR", bid=40, ask=42),
            "kalshi:JUN": book("kalshi:JUN", bid=33, ask=35),
        }
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None
        assert opp.worst_case_profit_pips == 1000 * c(5)
        sides = {leg.market_key: leg.side for leg in opp.legs}
        assert sides["kalshi:MAR"] is Side.SELL
        assert sides["kalshi:JUN"] is Side.BUY

    def test_consistent_ladder_yields_nothing(self):
        """Narrow correctly cheaper than broad: nothing to do."""
        con = MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"])
        books = {
            "kalshi:MAR": book("kalshi:MAR", bid=28, ask=30),
            "kalshi:JUN": book("kalshi:JUN", bid=40, ask=42),
        }
        assert con.scan(books, fee_models=FREE) is None

    def test_the_wrong_direction_is_never_traded(self):
        """Buying narrow and selling broad loses badly in the (F, T) state.

        This is the bug that a brute-force worst-case check exists to catch:
        the position looks like an arb and is in fact a large naked bet.
        """
        con = MonotoneConstraint(["k:MAR", "k:JUN"])
        legs = [
            ArbLeg("k:MAR", Side.BUY, 1000, c(30)),
            ArbLeg("k:JUN", Side.SELL, 1000, c(35)),
        ]
        opp = con.evaluate(legs, fee_models=FREE)
        assert opp.worst_case_profit_pips < 0
        assert not opp.is_profitable

    def test_impossible_outcome_is_excluded(self):
        """(narrow=True, broad=False) must never appear in the feasible set."""
        con = MonotoneConstraint(["A", "B"])
        assert (True, False) not in set(con.feasible_outcomes())
        assert len(list(con.feasible_outcomes())) == 3

    def test_ladder_builds_all_pairs_not_just_neighbours(self):
        """Non-adjacent rungs can be inconsistent while neighbours look fine."""
        cons = build_monotone_ladder(["A", "B", "C", "D"])
        assert len(cons) == 6  # C(4,2), not 3
        pairs = {con.market_keys for con in cons}
        assert ("A", "C") in pairs and ("A", "D") in pairs

    def test_strike_ladder_violation(self):
        """'BTC >= 110k' cannot be worth more than 'BTC >= 100k'."""
        con = MonotoneConstraint(["kalshi:BTC110", "kalshi:BTC100"])
        books = {
            "kalshi:BTC110": book("kalshi:BTC110", bid=30, ask=32),
            "kalshi:BTC100": book("kalshi:BTC100", bid=25, ask=27),
        }
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None and opp.is_profitable


class TestPartitionDutchBook:
    def test_finds_a_field_sum_below_one_dollar(self):
        """Three exhaustive outcomes at 30+30+35 = 95c: buy all, collect 5c."""
        con = PartitionConstraint(["k:A", "k:B", "k:C"])
        books = {
            "k:A": book("k:A", bid=28, ask=30),
            "k:B": book("k:B", bid=28, ask=30),
            "k:C": book("k:C", bid=33, ask=35),
        }
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None
        assert opp.worst_case_profit_pips == 1000 * c(5)
        assert opp.worst_case_profit_pips == opp.best_case_profit_pips

    def test_no_opportunity_when_the_field_sums_above_one(self):
        con = PartitionConstraint(["k:A", "k:B"])
        books = {"k:A": book("k:A", bid=48, ask=52), "k:B": book("k:B", bid=48, ask=52)}
        assert con.scan(books, fee_models=FREE) is None

    def test_exactly_one_outcome_resolves_yes(self):
        con = PartitionConstraint(["A", "B", "C"])
        scenarios = list(con.feasible_outcomes())
        assert len(scenarios) == 3
        assert all(sum(s) == 1 for s in scenarios)

    def test_selling_an_overpriced_field_is_also_an_arb(self):
        """Three exhaustive outcomes bidding 35+35+35 = 105c: sell all three."""
        con = PartitionConstraint(["k:A", "k:B", "k:C"])
        books = {
            "k:A": book("k:A", bid=35, ask=37),
            "k:B": book("k:B", bid=35, ask=37),
            "k:C": book("k:C", bid=35, ask=37),
        }
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None and opp.is_profitable
        assert all(leg.side is Side.SELL for leg in opp.legs)
        assert opp.worst_case_profit_pips == 1000 * c(5)

    def test_netting_only_matters_when_shorting_the_field(self):
        """Buying a field is already minimal outlay; shorting one is not.

        Without netting, a short field ties up the complement of every leg.
        With it, the real obligation is $1 per set because only one outcome can
        pay - here the difference is roughly 2x the capital for identical
        profit, which decides whether the trade is worth doing at all.
        """
        short_books = {
            "k:A": book("k:A", bid=35, ask=37),
            "k:B": book("k:B", bid=35, ask=37),
            "k:C": book("k:C", bid=35, ask=37),
        }
        netted = PartitionConstraint(["k:A", "k:B", "k:C"], nets_collateral=True)
        gross = PartitionConstraint(["k:A", "k:B", "k:C"], nets_collateral=False)
        a = netted.scan(short_books, fee_models=FREE)
        b = gross.scan(short_books, fee_models=FREE)
        assert a.capital_pips < b.capital_pips
        assert a.return_on_capital > b.return_on_capital

        # Buying the field: netting changes nothing.
        buy_books = {
            "k:A": book("k:A", bid=28, ask=30),
            "k:B": book("k:B", bid=28, ask=30),
            "k:C": book("k:C", bid=33, ask=35),
        }
        assert (
            netted.scan(buy_books, fee_models=FREE).capital_pips
            == gross.scan(buy_books, fee_models=FREE).capital_pips
        )


class TestThresholdBucketConsistency:
    def test_buckets_cheaper_than_the_threshold(self):
        """Threshold bids 60c while its two buckets cost 25+30 = 55c."""
        con = ThresholdBucketConstraint(["k:ABOVE", "k:B1", "k:B2"])
        books = {
            "k:ABOVE": book("k:ABOVE", bid=60, ask=62),
            "k:B1": book("k:B1", bid=23, ask=25),
            "k:B2": book("k:B2", bid=28, ask=30),
        }
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None and opp.is_profitable
        assert opp.worst_case_profit_pips == 1000 * c(5)

    def test_threshold_cheaper_than_its_buckets(self):
        con = ThresholdBucketConstraint(["k:ABOVE", "k:B1", "k:B2"])
        books = {
            "k:ABOVE": book("k:ABOVE", bid=48, ask=50),
            "k:B1": book("k:B1", bid=28, ask=30),
            "k:B2": book("k:B2", bid=28, ask=30),
        }
        opp = con.scan(books, fee_models=FREE)
        assert opp is not None and opp.is_profitable

    def test_consistent_representations_yield_nothing(self):
        con = ThresholdBucketConstraint(["k:ABOVE", "k:B1", "k:B2"])
        books = {
            "k:ABOVE": book("k:ABOVE", bid=53, ask=57),
            "k:B1": book("k:B1", bid=26, ask=29),
            "k:B2": book("k:B2", bid=26, ask=29),
        }
        assert con.scan(books, fee_models=FREE) is None

    def test_threshold_resolves_yes_exactly_when_a_bucket_does(self):
        con = ThresholdBucketConstraint(["T", "B1", "B2"])
        for scenario in con.feasible_outcomes():
            threshold, *buckets = scenario
            assert threshold == any(buckets)


class TestCrossVenue:
    def test_refuses_to_trade_unverified_resolution_criteria(self):
        """The default must be inaction: 'looks like the same market' is not enough."""
        con = CrossVenueConstraint(["kalshi:X", "polymarket:Y"])
        books = {
            "kalshi:X": book("kalshi:X", bid=40, ask=42),
            "polymarket:Y": book("polymarket:Y", bid=50, ask=52),
        }
        assert con.scan(books, fee_models=FEES) is None

    def test_trades_once_resolution_is_verified(self):
        con = CrossVenueConstraint(
            ["kalshi:X", "polymarket:Y"], resolution_verified=True
        )
        books = {
            "kalshi:X": book("kalshi:X", bid=40, ask=42),
            "polymarket:Y": book("polymarket:Y", bid=50, ask=52),
        }
        opp = con.scan(books, fee_models=FEES)
        assert opp is not None and opp.is_profitable
        # Buy the cheap venue, sell the expensive one.
        sides = {leg.market_key: leg.side for leg in opp.legs}
        assert sides["kalshi:X"] is Side.BUY
        assert sides["polymarket:Y"] is Side.SELL

    def test_direction_flips_when_the_gap_reverses(self):
        con = CrossVenueConstraint(
            ["kalshi:X", "polymarket:Y"], resolution_verified=True
        )
        books = {
            "kalshi:X": book("kalshi:X", bid=60, ask=62),
            "polymarket:Y": book("polymarket:Y", bid=50, ask=52),
        }
        opp = con.scan(books, fee_models=FEES)
        sides = {leg.market_key: leg.side for leg in opp.legs}
        assert sides["polymarket:Y"] is Side.BUY
        assert sides["kalshi:X"] is Side.SELL

    def test_requires_exactly_two_markets(self):
        with pytest.raises(ValueError, match="exactly two"):
            CrossVenueConstraint(["a", "b", "c"])


class TestNoFalseArbitrage:
    """The bug that must never ship: a 'guaranteed' profit that is not."""

    @pytest.mark.parametrize(
        ("constraint", "books"),
        [
            (
                ComplementConstraint(["k:A"]),
                {"k:A": book("k:A", bid=55, ask=52)},
            ),
            (
                MonotoneConstraint(["k:MAR", "k:JUN"]),
                {
                    "k:MAR": book("k:MAR", bid=40, ask=42),
                    "k:JUN": book("k:JUN", bid=33, ask=35),
                },
            ),
            (
                PartitionConstraint(["k:A", "k:B", "k:C"]),
                {
                    "k:A": book("k:A", bid=28, ask=30),
                    "k:B": book("k:B", bid=28, ask=30),
                    "k:C": book("k:C", bid=33, ask=35),
                },
            ),
            (
                ThresholdBucketConstraint(["k:T", "k:B1", "k:B2"]),
                {
                    "k:T": book("k:T", bid=60, ask=62),
                    "k:B1": book("k:B1", bid=23, ask=25),
                    "k:B2": book("k:B2", bid=28, ask=30),
                },
            ),
        ],
    )
    def test_reported_profit_holds_in_every_feasible_outcome(self, constraint, books):
        opp = constraint.scan(books, fee_models=FREE)
        assert opp is not None

        independent = brute_force_worst_case(constraint, opp.legs, opp.total_fees_pips)
        assert independent == opp.worst_case_profit_pips
        assert independent > 0, "reported arbitrage must profit in EVERY outcome"

    def test_every_scenario_is_enumerated(self):
        """A missing scenario is how a losing case hides from the worst case."""
        con = PartitionConstraint(["a", "b", "c", "d"])
        opp = con.scan(
            {
                "a": book("a", bid=20, ask=22),
                "b": book("b", bid=20, ask=22),
                "c": book("c", bid=20, ask=22),
                "d": book("d", bid=20, ask=22),
            },
            fee_models=FREE,
        )
        assert len(opp.scenarios) == 4

    def test_a_leg_that_cannot_fill_is_not_an_opportunity(self):
        con = MonotoneConstraint(["k:A", "k:B"])
        books = {
            "k:A": book("k:A", bid=28, ask=30, size=0),
            "k:B": book("k:B", bid=35, ask=37),
        }
        assert con.scan(books, fee_models=FREE) is None

    def test_missing_book_is_not_an_opportunity(self):
        con = MonotoneConstraint(["k:A", "k:B"])
        assert con.scan({"k:A": book("k:A", 28, 30)}, fee_models=FREE) is None

    def test_one_sided_book_is_not_an_opportunity(self):
        con = MonotoneConstraint(["k:A", "k:B"])
        books = {
            "k:A": book("k:A", bid=28, ask=None),
            "k:B": book("k:B", bid=35, ask=37),
        }
        assert con.scan(books, fee_models=FREE) is None


class TestScanner:
    def test_ranks_by_return_on_capital_not_absolute_profit(self):
        """With a small account, capital is the binding resource."""
        scanner = ConstraintScanner(fee_models=FREE, min_profit_pips=0)
        scanner.add(ComplementConstraint(["k:SMALL"]))
        scanner.add(ComplementConstraint(["k:BIG"]))
        books = {
            # 3c profit on ~52c of capital -> high return
            "k:SMALL": book("k:SMALL", bid=55, ask=52, size=100),
            # 4c profit on ~5c*... much larger capital -> lower return
            "k:BIG": book("k:BIG", bid=54, ask=50, size=100),
        }
        results = scanner.scan(books)
        assert len(results) == 2
        rors = [o.return_on_capital for o in results]
        assert rors == sorted(rors, reverse=True)

    def test_min_profit_filters_noise(self):
        scanner = ConstraintScanner(fee_models=FREE, min_profit_pips=10_000_000)
        scanner.add(ComplementConstraint(["k:A"]))
        assert scanner.scan({"k:A": book("k:A", bid=55, ask=52)}) == []

    def test_empty_registry_is_safe(self):
        assert ConstraintScanner(fee_models=FREE).scan({}) == []

    def test_execution_risk_is_reported(self):
        con = PartitionConstraint(["a", "b", "c"])
        opp = con.scan(
            {
                "a": book("a", bid=28, ask=30),
                "b": book("b", bid=28, ask=30),
                "c": book("c", bid=30, ask=32),
            },
            fee_models=FREE,
        )
        assert "3 legs" in opp.execution_risk

    def test_passive_legs_are_flagged_as_risky(self):
        legs = [
            ArbLeg("k:A", Side.BUY, 10, c(30), taker=False),
            ArbLeg("k:B", Side.SELL, 10, c(35), taker=True),
        ]
        opp = MonotoneConstraint(["k:A", "k:B"]).evaluate(legs, fee_models=FREE)
        assert "passive" in opp.execution_risk
