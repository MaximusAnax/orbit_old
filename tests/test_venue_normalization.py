"""Order-book normalisation.

The Kalshi conversion is the highest-risk pure function in the codebase: if
YES asks are derived from NO bids incorrectly, the book comes out *inverted*.
Nothing raises. The system simply believes it can buy at 3c what actually
costs 97c, and every strategy trades backwards into a wall.

These tests exist so that failure mode is impossible.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from orbit.core.money import cents_to_pips, complement
from orbit.core.types import Side
from orbit.venues.base import normalize_binary_book, normalize_two_sided_book
from orbit.venues.kalshi import parse_orderbook

TS = datetime(2026, 1, 1, tzinfo=UTC)


def c(cents: int) -> int:
    return cents_to_pips(cents)


class TestKalshiBookReflection:
    def test_no_bids_become_yes_asks_at_the_complement(self):
        """The identity: a 40c bid for NO is a 60c offer of YES."""
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(55), 10)],
            no_bids=[(c(40), 7)],
        )
        assert book.best_bid_pips == c(55)
        assert book.best_ask_pips == c(60)
        assert book.best_ask.size == 7
        assert book.spread_pips == c(5)

    def test_book_is_not_inverted(self):
        """The canary. A realistic book must have bid < ask, never the reverse."""
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(30), 100), (c(29), 50)],
            no_bids=[(c(68), 80), (c(67), 40)],
        )
        assert book.best_bid_pips == c(30)
        assert book.best_ask_pips == c(32)  # 100 - 68
        assert book.best_bid_pips < book.best_ask_pips
        assert not book.is_crossed

    def test_ordering_is_canonical(self):
        """Bids descend, asks ascend, regardless of input order."""
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(20), 1), (c(35), 1), (c(28), 1)],
            no_bids=[(c(50), 1), (c(61), 1), (c(55), 1)],
        )
        bids = [lvl.price_pips for lvl in book.bids]
        asks = [lvl.price_pips for lvl in book.asks]
        assert bids == sorted(bids, reverse=True)
        assert asks == sorted(asks)
        assert asks[0] == c(39)  # complement of the best NO bid, 61c

    def test_zero_size_levels_are_dropped(self):
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(30), 0), (c(29), 5)],
            no_bids=[(c(60), 0)],
        )
        assert [lvl.price_pips for lvl in book.bids] == [c(29)]
        assert book.asks == ()
        assert book.best_ask is None
        assert book.spread_pips is None

    def test_depth_truncation_keeps_the_best_levels(self):
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(x), 1) for x in range(10, 40)],
            no_bids=[(c(x), 1) for x in range(50, 80)],
            depth=3,
        )
        assert len(book.bids) == 3
        assert len(book.asks) == 3
        assert [lvl.price_pips for lvl in book.bids] == [c(39), c(38), c(37)]
        # Best ask = complement of the *highest* NO bid (79c) = 21c.
        assert [lvl.price_pips for lvl in book.asks] == [c(21), c(22), c(23)]

    def test_empty_book(self):
        book = normalize_binary_book(
            market_key="kalshi:X", timestamp=TS, yes_bids=[], no_bids=[]
        )
        assert book.best_bid is None and book.best_ask is None
        assert book.mid_pips is None and book.microprice_pips is None
        assert not book.is_crossed

    @given(
        yes=st.integers(min_value=1, max_value=98),
        no=st.integers(min_value=1, max_value=98),
    )
    def test_reflection_is_always_the_complement(self, yes, no):
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(yes), 1)],
            no_bids=[(c(no), 1)],
        )
        assert book.best_bid_pips == c(yes)
        assert book.best_ask_pips == complement(c(no))

    @given(
        yes=st.integers(min_value=1, max_value=98),
        no=st.integers(min_value=1, max_value=98),
    )
    def test_crossed_only_when_the_venue_book_is_genuinely_crossed(self, yes, no):
        """bid >= ask iff yes_bid + no_bid >= $1 — i.e. a real free lunch.

        This is the YES/NO parity arbitrage condition. It should be flagged as
        crossed, because that is exactly what it is: buy YES and NO together
        for less than the $1 they are jointly guaranteed to pay.
        """
        book = normalize_binary_book(
            market_key="kalshi:X",
            timestamp=TS,
            yes_bids=[(c(yes), 1)],
            no_bids=[(c(no), 1)],
        )
        assert book.is_crossed == (yes + no >= 100)


class TestKalshiPayloadParsing:
    def test_parses_list_of_pairs(self):
        raw = {"orderbook": {"yes": [[45, 100], [44, 50]], "no": [[52, 30]]}}
        book = parse_orderbook("kalshi:X", raw)
        assert book.best_bid_pips == c(45)
        assert book.best_ask_pips == c(48)

    def test_parses_dict_levels(self):
        raw = {
            "orderbook": {
                "yes": [{"price": 45, "count": 100}],
                "no": [{"price": 52, "count": 30}],
            }
        }
        book = parse_orderbook("kalshi:X", raw)
        assert book.best_bid_pips == c(45)
        assert book.best_ask_pips == c(48)

    def test_accepts_true_false_aliases(self):
        """kalshi-python 2.1.0 aliases the arrays to 'true'/'false'."""
        raw = {"orderbook": {"true": [[45, 100]], "false": [[52, 30]]}}
        book = parse_orderbook("kalshi:X", raw)
        assert book.best_bid_pips == c(45)
        assert book.best_ask_pips == c(48)

    def test_handles_null_sides(self):
        """Kalshi returns null, not [], for an empty side of a one-sided book."""
        book = parse_orderbook("kalshi:X", {"orderbook": {"yes": None, "no": None}})
        assert book.bids == () and book.asks == ()

    def test_unwrapped_payload(self):
        book = parse_orderbook("kalshi:X", {"yes": [[45, 1]], "no": [[52, 1]]})
        assert book.best_bid_pips == c(45)

    def test_malformed_rows_are_skipped_not_fatal(self):
        raw = {"orderbook": {"yes": [[45, 100], "garbage", [None, 5], [44, 2]], "no": []}}
        book = parse_orderbook("kalshi:X", raw)
        assert [lvl.price_pips for lvl in book.bids] == [c(45), c(44)]


class TestTwoSidedBook:
    def test_polymarket_style_book_is_sorted_not_reflected(self):
        book = normalize_two_sided_book(
            market_key="polymarket:X",
            timestamp=TS,
            bids=[(c(40), 5), (c(42), 9)],
            asks=[(c(47), 3), (c(45), 8)],
        )
        assert book.best_bid_pips == c(42)
        assert book.best_ask_pips == c(45)
        assert book.spread_pips == c(3)


class TestBookAnalytics:
    @pytest.fixture
    def book(self):
        return normalize_two_sided_book(
            market_key="k:X",
            timestamp=TS,
            bids=[(c(40), 100), (c(39), 200)],
            asks=[(c(44), 50), (c(45), 300)],
        )

    def test_mid_and_microprice(self, book):
        assert book.mid_pips == c(42)
        # Ask side is thinner (50 vs 100), so the microprice leans toward the ask.
        assert book.microprice_pips > book.mid_pips

    def test_depth_within_limit(self, book):
        assert book.depth_within(side=Side.BUY, limit_pips=c(44)) == 50
        assert book.depth_within(side=Side.BUY, limit_pips=c(45)) == 350
        assert book.depth_within(side=Side.SELL, limit_pips=c(40)) == 100
        assert book.depth_within(side=Side.SELL, limit_pips=c(39)) == 300

    def test_sweep_cost_reports_partial_fills(self, book):
        """A backtest that assumes full fills is lying; the API forces the check."""
        total, filled = book.sweep_cost_pips(side=Side.BUY, size=60)
        assert filled == 60
        assert total == 50 * c(44) + 10 * c(45)

        total, filled = book.sweep_cost_pips(side=Side.BUY, size=1000)
        assert filled == 350, "book is too thin for 1000; must report the shortfall"

    def test_sweep_on_empty_side_returns_none(self):
        empty = normalize_two_sided_book(
            market_key="k:X", timestamp=TS, bids=[], asks=[]
        )
        assert empty.sweep_cost_pips(side=Side.BUY, size=10) is None
