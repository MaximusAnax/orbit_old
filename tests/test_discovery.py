"""Constraint discovery.

Discovery is where a false arbitrage would be born, so these tests are mostly
about what it *refuses* to infer. A missed relationship costs nothing; an
invented one costs the position.
"""

from __future__ import annotations

from orbit.core.types import Market, MarketStatus, Venue
from orbit.strategies.constraints import (
    ComplementConstraint,
    MonotoneConstraint,
    PartitionConstraint,
)
from orbit.strategies.discovery import (
    Confidence,
    build_constraints_for,
    discover,
    explain,
    parse_strike,
)


def mkt(ticker: str, title: str = "", event: str = "EVT") -> Market:
    return Market(
        venue=Venue.KALSHI,
        venue_id=ticker,
        title=title or ticker,
        event_key=event,
        status=MarketStatus.ACTIVE,
    )


class TestStrikeParsing:
    def test_parses_threshold_ticker(self):
        s = parse_strike(mkt("KXHIGHNY-25JUL30-T75.5"))
        assert s is not None and s.value == 75.5 and s.kind == "T"

    def test_parses_bucket_ticker(self):
        s = parse_strike(mkt("KXHIGHNY-25JUL30-B72"))
        assert s is not None and s.value == 72 and s.kind == "B"

    def test_parses_negative_strike(self):
        s = parse_strike(mkt("KXTEMP-25JAN01-T-10"))
        assert s is not None and s.value == -10

    def test_falls_back_to_title_language(self):
        s = parse_strike(mkt("OPAQUE", title="Will the high be above 80 degrees?"))
        assert s is not None and s.value == 80 and s.ascending_is_narrower

    def test_below_language_inverts_the_direction(self):
        s = parse_strike(mkt("OPAQUE", title="Will the high be below 80 degrees?"))
        assert s is not None and not s.ascending_is_narrower

    def test_refuses_ambiguous_range_titles(self):
        """'between 70 and 75' has two numbers and is not a threshold."""
        assert parse_strike(mkt("X", title="Will the high be between 70 and 75?")) is None

    def test_refuses_contradictory_titles(self):
        assert parse_strike(
            mkt("X", title="Will it be above 70 but below 80?")
        ) is None

    def test_refuses_titles_with_no_direction(self):
        assert parse_strike(mkt("X", title="Who wins the election?")) is None

    def test_refuses_when_nothing_is_parseable(self):
        assert parse_strike(mkt("RANDOMTICKER", title="Some question")) is None


class TestCertainConstraints:
    def test_every_market_gets_a_parity_constraint(self):
        markets = [mkt("A"), mkt("B"), mkt("C")]
        parity = [
            d for d in discover(markets)
            if isinstance(d.constraint, ComplementConstraint)
        ]
        assert len(parity) == 3
        assert all(d.confidence is Confidence.CERTAIN for d in parity)
        assert all(d.auto_enabled for d in parity)

    def test_parity_needs_no_metadata(self):
        """It is true by construction, so it works on opaque tickers too."""
        assert discover([mkt("???", title="")])[0].auto_enabled


class TestStructuralLadders:
    def test_builds_a_ladder_from_thresholds(self):
        markets = [
            mkt("K-T70", event="E"),
            mkt("K-T75", event="E"),
            mkt("K-T80", event="E"),
        ]
        ladders = [
            d for d in discover(markets)
            if isinstance(d.constraint, MonotoneConstraint)
        ]
        assert len(ladders) == 3  # C(3,2): all pairs, not just neighbours
        assert all(d.confidence is Confidence.STRUCTURAL for d in ladders)

    def test_implication_direction_is_higher_implies_lower(self):
        """'Above 80' implies 'above 70', so 80 is the narrow leg."""
        markets = [mkt("K-T70", event="E"), mkt("K-T80", event="E")]
        ladder = next(
            d.constraint for d in discover(markets)
            if isinstance(d.constraint, MonotoneConstraint)
        )
        narrow, broad = ladder.market_keys
        assert narrow.endswith("T80")
        assert broad.endswith("T70")

    def test_below_style_markets_ladder_the_other_way(self):
        markets = [
            mkt("A", title="Will it be below 70?", event="E"),
            mkt("B", title="Will it be below 80?", event="E"),
        ]
        ladder = next(
            d.constraint for d in discover(markets)
            if isinstance(d.constraint, MonotoneConstraint)
        )
        narrow, broad = ladder.market_keys
        # "below 70" implies "below 80".
        assert narrow.endswith(":A")
        assert broad.endswith(":B")

    def test_mixed_direction_markets_are_never_laddered_together(self):
        """Mixing above-style and below-style inverts the implication."""
        markets = [
            mkt("A", title="Will it be above 70?", event="E"),
            mkt("B", title="Will it be below 80?", event="E"),
        ]
        assert not [
            d for d in discover(markets)
            if isinstance(d.constraint, MonotoneConstraint)
        ]

    def test_markets_in_different_events_are_not_related(self):
        markets = [mkt("K-T70", event="E1"), mkt("K-T80", event="E2")]
        assert not [
            d for d in discover(markets)
            if isinstance(d.constraint, MonotoneConstraint)
        ]

    def test_equal_strikes_produce_no_constraint(self):
        markets = [mkt("A-T70", event="E"), mkt("B-T70", event="E")]
        assert not [
            d for d in discover(markets)
            if isinstance(d.constraint, MonotoneConstraint)
        ]


class TestInferredPartitions:
    def test_partitions_are_off_by_default(self):
        """Assuming exhaustiveness is how a false arbitrage gets invented."""
        markets = [mkt(f"K-B{i}", event="E") for i in (70, 72, 74)]
        assert not [
            d for d in discover(markets)
            if isinstance(d.constraint, PartitionConstraint)
        ]

    def test_partitions_appear_only_when_explicitly_requested(self):
        markets = [mkt(f"K-B{i}", event="E") for i in (70, 72, 74)]
        found = [
            d for d in discover(markets, include_inferred=True)
            if isinstance(d.constraint, PartitionConstraint)
        ]
        assert len(found) == 1
        assert found[0].confidence is Confidence.INFERRED
        assert not found[0].auto_enabled
        assert "verify" in found[0].explanation.lower()

    def test_a_mixed_group_is_not_treated_as_a_partition(self):
        """One non-bucket member means the set is not known to be exhaustive."""
        markets = [
            mkt("K-B70", event="E"),
            mkt("K-B72", event="E"),
            mkt("K-OTHER", event="E"),
        ]
        assert not [
            d for d in discover(markets, include_inferred=True)
            if isinstance(d.constraint, PartitionConstraint)
        ]

    def test_two_market_groups_are_not_partitions(self):
        markets = [mkt("K-B70", event="E"), mkt("K-B72", event="E")]
        assert not [
            d for d in discover(markets, include_inferred=True)
            if isinstance(d.constraint, PartitionConstraint)
        ]


class TestBuildAndExplain:
    def test_build_returns_only_auto_enabled_constraints(self):
        markets = [mkt(f"K-B{i}", event="E") for i in (70, 72, 74)]
        constraints = build_constraints_for(markets)
        assert all(not isinstance(c, PartitionConstraint) for c in constraints)
        assert len(constraints) == 3  # parity only

    def test_build_from_recorded_keys_yields_parity_only(self):
        """Documented limitation: keys alone cannot reconstruct ladders."""
        constraints = build_constraints_for([], market_keys=["kalshi:A", "kalshi:B"])
        assert len(constraints) == 2
        assert all(isinstance(c, ComplementConstraint) for c in constraints)

    def test_explain_reports_review_status(self):
        markets = [mkt("K-B70", event="E"), mkt("K-B72", event="E"),
                   mkt("K-B74", event="E")]
        text = explain(markets)
        assert "NEEDS REVIEW" in text
        assert "auto-enabled" in text

    def test_empty_input_is_safe(self):
        assert discover([]) == []
        assert build_constraints_for([]) == []
