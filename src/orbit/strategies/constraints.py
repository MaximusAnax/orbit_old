"""Logical-consistency arbitrage.

Prediction markets price *propositions*, and propositions have logical
structure that prices must respect. "Fed cuts by at least 50bp" cannot be more
likely than "Fed cuts by at least 25bp". "BTC above $100k by March" cannot
exceed "BTC above $100k by June". The individual buckets of a temperature
market must sum to exactly $1. When these relationships break — and on thin,
independently-quoted books they break regularly — the violation is a trade
whose profit does not depend on being right about anything.

That last property is what makes this family the correct place to start:

* **No model risk.** The edge is arithmetic, not a forecast. There is no
  probability estimate to be wrong about.
* **Small capital works.** Profit comes from the size of the violation, not
  from scale.
* **Fully backtestable.** Constraint violations are visible in recorded book
  data, so a strategy can be validated against the archive rather than
  forward-tested on hope.

Rather than write one strategy per relationship, the relationships are modelled
as :class:`Constraint` objects. Each declares which outcome combinations are
logically *feasible*, and profit is then evaluated the same way for all of
them: enumerate every feasible resolution, compute PnL in each, and take the
minimum. If that minimum is positive after fees, the trade cannot lose.

The rigour matters. It is easy to spot "these prices look inconsistent" and
construct a position that is merely *probably* profitable. Taking the worst
case over feasible outcomes is what separates arbitrage from a directional bet
wearing its clothes.
"""

from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from orbit.core.fees import FeeModel, Liquidity
from orbit.core.money import PIPS_PER_DOLLAR, format_usd
from orbit.core.types import OrderBook, Side

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


@dataclass(frozen=True, slots=True)
class ArbLeg:
    """One leg of a multi-leg arbitrage."""

    market_key: str
    side: Side
    size: int
    limit_pips: int
    #: Whether this leg must cross the spread (taker) or can rest (maker).
    #: Passive legs are far cheaper on Kalshi but may never fill, which turns
    #: a "risk-free" trade into a naked position.
    taker: bool = True

    def payoff_pips(self, settled_yes: bool) -> int:
        """PnL for this leg if the market settles as given, excluding fees."""
        payout = PIPS_PER_DOLLAR if settled_yes else 0
        return self.side.sign * (payout - self.limit_pips) * self.size

    def collateral_pips(self) -> int:
        unit = (
            self.limit_pips
            if self.side is Side.BUY
            else PIPS_PER_DOLLAR - self.limit_pips
        )
        return unit * self.size


@dataclass(frozen=True, slots=True)
class ArbOpportunity:
    """A detected violation, priced and sized.

    ``worst_case_profit_pips`` is the guaranteed minimum across every feasible
    resolution, net of fees. If it is positive the position cannot lose money
    — assuming every leg fills, which is precisely the assumption
    :attr:`execution_risk` exists to flag.
    """

    constraint_name: str
    legs: tuple[ArbLeg, ...]
    worst_case_profit_pips: int
    best_case_profit_pips: int
    capital_pips: int
    total_fees_pips: int
    rationale: str
    #: Markets involved, for correlation accounting.
    event_key: str = ""
    scenarios: tuple[tuple[bool, ...], ...] = ()

    @property
    def is_profitable(self) -> bool:
        return self.worst_case_profit_pips > 0

    @property
    def return_on_capital(self) -> float:
        """Return on capital *deployed*, not on capital at risk.

        The honest denominator at small account sizes: a 2% risk-free return
        that locks capital for three months is worse than it sounds, and this
        is the number that reveals it.

        Zero capital with positive profit is infinite return, not zero — it
        happens when a short field's proceeds already exceed the $1 obligation
        under venue netting, so the position funds itself. Reporting it as
        ``inf`` keeps such trades sorted first, which is where they belong.
        """
        if self.capital_pips <= 0:
            return float("inf") if self.worst_case_profit_pips > 0 else 0.0
        return self.worst_case_profit_pips / self.capital_pips

    @property
    def execution_risk(self) -> str:
        """How the trade fails in practice.

        Multi-leg arbitrage does not lose money because the arithmetic is
        wrong; it loses money because one leg fills and another does not,
        leaving a naked directional position nobody intended to hold.
        """
        passive = sum(1 for leg in self.legs if not leg.taker)
        if passive:
            return f"{passive}/{len(self.legs)} legs passive — may not fill"
        if len(self.legs) > 2:
            return f"{len(self.legs)} legs must fill together"
        return "low"

    def __str__(self) -> str:
        return (
            f"{self.constraint_name}: {len(self.legs)} legs, "
            f"guaranteed {format_usd(self.worst_case_profit_pips)} on "
            f"{format_usd(self.capital_pips)} ({self.return_on_capital:.2%})"
        )


class Constraint(ABC):
    """A logical relationship that market prices must satisfy."""

    name: str = "constraint"

    def __init__(self, market_keys: Sequence[str], *, event_key: str = "") -> None:
        self.market_keys = tuple(market_keys)
        self.event_key = event_key

    @abstractmethod
    def feasible_outcomes(self) -> Iterator[tuple[bool, ...]]:
        """Every resolution combination the logic permits.

        Ordered to match :attr:`market_keys`. This is the heart of the module:
        an incorrect feasible set produces confident, wrong "arbitrage".
        """

    @abstractmethod
    def find_violation(
        self, books: dict[str, OrderBook], *, max_size: int
    ) -> tuple[ArbLeg, ...] | None:
        """Return legs that exploit a violation, or ``None`` if prices are consistent."""

    def evaluate(
        self,
        legs: Sequence[ArbLeg],
        *,
        fee_models: dict[str, FeeModel],
    ) -> ArbOpportunity:
        """Price a candidate position across every feasible outcome."""
        index = {key: i for i, key in enumerate(self.market_keys)}
        scenarios = tuple(self.feasible_outcomes())

        fees = 0
        for leg in legs:
            venue = leg.market_key.split(":", 1)[0]
            model = fee_models.get(venue)
            if model is not None:
                fees += model.trade_fee_pips(
                    price_pips=leg.limit_pips,
                    size=leg.size,
                    liquidity=Liquidity.TAKER if leg.taker else Liquidity.MAKER,
                )

        payoffs = []
        for scenario in scenarios:
            total = 0
            for leg in legs:
                i = index.get(leg.market_key)
                if i is None:
                    continue
                total += leg.payoff_pips(scenario[i])
            payoffs.append(total - fees)

        return ArbOpportunity(
            constraint_name=self.name,
            legs=tuple(legs),
            worst_case_profit_pips=min(payoffs) if payoffs else 0,
            best_case_profit_pips=max(payoffs) if payoffs else 0,
            capital_pips=sum(leg.collateral_pips() for leg in legs),
            total_fees_pips=fees,
            rationale=self._describe(legs),
            event_key=self.event_key,
            scenarios=scenarios,
        )

    def _describe(self, legs: Sequence[ArbLeg]) -> str:
        parts = [
            f"{leg.side.value} {leg.size} {leg.market_key}@{leg.limit_pips / 100:.0f}c"
            for leg in legs
        ]
        return f"{self.name}: " + " + ".join(parts)

    def scan(
        self,
        books: dict[str, OrderBook],
        *,
        fee_models: dict[str, FeeModel],
        max_size: int = 1000,
        min_profit_pips: int = 0,
    ) -> ArbOpportunity | None:
        """Find and price a violation in one call. ``None`` if nothing worth doing."""
        if not all(key in books for key in self.market_keys):
            return None
        legs = self.find_violation(books, max_size=max_size)
        if not legs:
            return None
        opp = self.evaluate(legs, fee_models=fee_models)
        return opp if opp.worst_case_profit_pips > min_profit_pips else None


# ---------------------------------------------------------------------------
# Concrete constraints
# ---------------------------------------------------------------------------


class ComplementConstraint(Constraint):
    """YES and NO of the same event must price to exactly $1.

    Within one Kalshi market this is the parity trade: if the YES ask plus the
    NO ask is below $1, buying both is a guaranteed dollar for less than a
    dollar. Across the two Polymarket tokens of one condition, split/merge
    enforces the same bound structurally.

    Expressed in YES-space, buying NO at price ``n`` is selling YES at
    ``1 - n``, so the opportunity appears as a *crossed book*: bid >= ask.
    """

    name = "yes_no_parity"

    def feasible_outcomes(self) -> Iterator[tuple[bool, ...]]:
        yield (True,)
        yield (False,)

    def find_violation(
        self, books: dict[str, OrderBook], *, max_size: int
    ) -> tuple[ArbLeg, ...] | None:
        book = books[self.market_keys[0]]
        bid, ask = book.best_bid, book.best_ask
        if bid is None or ask is None or bid.price_pips <= ask.price_pips:
            return None
        # Buy at the ask, sell at the (higher) bid: locked in regardless of
        # how the market resolves.
        size = min(bid.size, ask.size, max_size)
        if size <= 0:
            return None
        return (
            ArbLeg(book.market_key, Side.BUY, size, ask.price_pips),
            ArbLeg(book.market_key, Side.SELL, size, bid.price_pips),
        )


class MonotoneConstraint(Constraint):
    """If A implies B then P(A) <= P(B).

    Covers the two most common ladders on these venues:

    * **Date ladders** — "X happens by March" implies "X happens by June".
    * **Strike ladders** — "Fed cuts at least 50bp" implies "at least 25bp";
      "BTC above $110k" implies "BTC above $100k".

    Markets are given in implication order: ``market_keys[0]`` (narrow)
    implies ``market_keys[1]`` (broad). The infeasible combination is
    ``(True, False)`` — the narrow event happening while the broad one does
    not.

    **The direction of the trade is the whole game.** A violation means the
    narrow contract is trading *too expensively* relative to the broad one, so
    the trade is to **sell the narrow and buy the broad**. The opposite pairing
    is not merely worse, it is unbounded-loss: buying narrow and selling broad
    loses the full spread in the ``(False, True)`` state, where the broad event
    happens and the narrow one does not — which is precisely the state that
    makes the broad contract worth more in the first place. Working the payoff
    through all three feasible outcomes at narrow_bid=40c, broad_ask=35c::

        (F, F):  +40  -35          = +5c
        (F, T):  +40  +65          = +105c
        (T, T):  -60  +65          = +5c

    Every outcome profits, with the minimum being the size of the violation.
    """

    name = "monotone_implication"

    def feasible_outcomes(self) -> Iterator[tuple[bool, ...]]:
        yield (False, False)
        yield (False, True)
        yield (True, True)
        # (True, False) is logically impossible: A implies B.

    def find_violation(
        self, books: dict[str, OrderBook], *, max_size: int
    ) -> tuple[ArbLeg, ...] | None:
        narrow, broad = (books[k] for k in self.market_keys)
        narrow_bid, broad_ask = narrow.best_bid, broad.best_ask
        if narrow_bid is None or broad_ask is None:
            return None
        # Violation: the narrow event can be sold for more than the broad
        # event costs, despite being logically less likely.
        if narrow_bid.price_pips <= broad_ask.price_pips:
            return None
        size = min(narrow_bid.size, broad_ask.size, max_size)
        if size <= 0:
            return None
        return (
            ArbLeg(narrow.market_key, Side.SELL, size, narrow_bid.price_pips),
            ArbLeg(broad.market_key, Side.BUY, size, broad_ask.price_pips),
        )


class PartitionConstraint(Constraint):
    """Mutually exclusive, exhaustive outcomes must sum to exactly $1.

    The field-sum or "dutch book" case: every candidate in an election, every
    temperature bucket, every Fed decision size. If the YES asks across all
    outcomes total less than $1, buying the complete set pays $1 for certain.

    Capital efficiency depends entirely on venue mechanics. Both Kalshi's
    mutually-exclusive market groups and Polymarket's neg-risk adapter net
    collateral across legs; without that netting the trade ties up the full
    sum of every leg and the return on deployed capital collapses.
    """

    name = "partition_sum"

    def __init__(
        self,
        market_keys: Sequence[str],
        *,
        event_key: str = "",
        nets_collateral: bool = True,
    ) -> None:
        super().__init__(market_keys, event_key=event_key)
        self.nets_collateral = nets_collateral

    def feasible_outcomes(self) -> Iterator[tuple[bool, ...]]:
        n = len(self.market_keys)
        for i in range(n):
            yield tuple(j == i for j in range(n))

    def find_violation(
        self, books: dict[str, OrderBook], *, max_size: int
    ) -> tuple[ArbLeg, ...] | None:
        raw_asks = [books[k].best_ask for k in self.market_keys]
        raw_bids = [books[k].best_bid for k in self.market_keys]

        # Buy the field: the complete set costs less than the $1 it must pay.
        if all(a is not None for a in raw_asks):
            asks = [a for a in raw_asks if a is not None]
            if sum(a.price_pips for a in asks) < PIPS_PER_DOLLAR:
                size = min(min(a.size for a in asks), max_size)
                if size > 0:
                    return tuple(
                        ArbLeg(key, Side.BUY, size, a.price_pips)
                        for key, a in zip(self.market_keys, asks, strict=True)
                    )

        # Sell the field: the set can be sold for more than the $1 it can cost.
        if all(b is not None for b in raw_bids):
            bids = [b for b in raw_bids if b is not None]
            if sum(b.price_pips for b in bids) > PIPS_PER_DOLLAR:
                size = min(min(b.size for b in bids), max_size)
                if size > 0:
                    return tuple(
                        ArbLeg(key, Side.SELL, size, b.price_pips)
                        for key, b in zip(self.market_keys, bids, strict=True)
                    )
        return None

    def evaluate(
        self, legs: Sequence[ArbLeg], *, fee_models: dict[str, FeeModel]
    ) -> ArbOpportunity:
        opp = super().evaluate(legs, fee_models=fee_models)
        capital = opp.capital_pips

        if self.nets_collateral and legs and all(leg.side is Side.SELL for leg in legs):
            # Shorting a complete partition is where netting actually matters.
            # Exactly one outcome can pay, so the true obligation is $1 per set
            # rather than the complement of every leg summed. Without netting a
            # 5-way field ties up roughly 4x the capital for the same profit,
            # which is usually the difference between a live trade and a dead
            # one. (Buying the field needs no adjustment: its cost is already
            # the minimum possible outlay.)
            size = min(leg.size for leg in legs)
            proceeds = sum(leg.limit_pips * leg.size for leg in legs)
            capital = max(0, size * PIPS_PER_DOLLAR - proceeds)

        return ArbOpportunity(
            constraint_name=opp.constraint_name,
            legs=opp.legs,
            worst_case_profit_pips=opp.worst_case_profit_pips,
            best_case_profit_pips=opp.best_case_profit_pips,
            capital_pips=capital,
            total_fees_pips=opp.total_fees_pips,
            rationale=opp.rationale,
            event_key=opp.event_key,
            scenarios=opp.scenarios,
        )


class ThresholdBucketConstraint(Constraint):
    """A threshold contract must equal the sum of the buckets above it.

    Kalshi frequently lists the same underlying twice: as ranges ("high temp
    75-76°F") and as thresholds ("high temp above 74°F"). The threshold is
    definitionally the sum of every bucket above the cut, so the two
    representations must agree. They are quoted by different participants and
    routinely do not.

    ``market_keys`` is ``(threshold, *buckets_above)``.
    """

    name = "threshold_bucket_consistency"

    def feasible_outcomes(self) -> Iterator[tuple[bool, ...]]:
        n_buckets = len(self.market_keys) - 1
        # Exactly one bucket resolves YES, and the threshold resolves YES
        # precisely when one of its buckets does. Also allow the case where no
        # listed bucket hits (outcome fell below the threshold).
        yield (False, *(False,) * n_buckets)
        for i in range(n_buckets):
            yield (True, *(j == i for j in range(n_buckets)))

    def find_violation(
        self, books: dict[str, OrderBook], *, max_size: int
    ) -> tuple[ArbLeg, ...] | None:
        threshold_key, *bucket_keys = self.market_keys
        threshold = books[threshold_key]
        buckets = [books[k] for k in bucket_keys]

        t_bid, t_ask = threshold.best_bid, threshold.best_ask
        # Drop Nones once so the rest of the function works on concrete levels;
        # a short list means some bucket has no quote and the leg is untradable.
        bucket_asks = [lvl for b in buckets if (lvl := b.best_ask) is not None]
        bucket_bids = [lvl for b in buckets if (lvl := b.best_bid) is not None]
        complete = len(buckets)

        # Case 1: buckets are collectively cheaper than the threshold bid.
        # Buy every bucket, sell the threshold.
        if t_bid is not None and len(bucket_asks) == complete:
            cost = sum(a.price_pips for a in bucket_asks)
            if cost < t_bid.price_pips:
                size = min(t_bid.size, min(a.size for a in bucket_asks), max_size)
                if size > 0:
                    return (
                        ArbLeg(threshold_key, Side.SELL, size, t_bid.price_pips),
                        *(
                            ArbLeg(k, Side.BUY, size, a.price_pips)
                            for k, a in zip(bucket_keys, bucket_asks, strict=True)
                        ),
                    )

        # Case 2: the threshold is cheaper than selling every bucket.
        if t_ask is not None and len(bucket_bids) == complete:
            proceeds = sum(b.price_pips for b in bucket_bids)
            if t_ask.price_pips < proceeds:
                size = min(t_ask.size, min(b.size for b in bucket_bids), max_size)
                if size > 0:
                    return (
                        ArbLeg(threshold_key, Side.BUY, size, t_ask.price_pips),
                        *(
                            ArbLeg(k, Side.SELL, size, b.price_pips)
                            for k, b in zip(bucket_keys, bucket_bids, strict=True)
                        ),
                    )
        return None


class CrossVenueConstraint(Constraint):
    """The same proposition on two venues must price the same.

    The most-discussed prediction-market trade and the one most often
    mis-implemented, because the arithmetic is trivial and the hard part is
    entirely in the premise. Two markets that *look* identical routinely
    differ in resolution source, resolution date, or edge-case handling — and
    a pair that resolves differently is not an arbitrage, it is two opposing
    naked positions with the losses realised simultaneously.

    ``resolution_verified`` therefore defaults to ``False`` and gates the
    strategy: a pair is only traded once a human has read both rulebooks. The
    fee asymmetry matters too — the Kalshi leg pays taker fees while the
    Polymarket leg historically pays none, so the breakeven gap is not
    symmetric.
    """

    name = "cross_venue"

    def __init__(
        self,
        market_keys: Sequence[str],
        *,
        event_key: str = "",
        resolution_verified: bool = False,
    ) -> None:
        if len(market_keys) != 2:
            raise ValueError("cross-venue constraint compares exactly two markets")
        super().__init__(market_keys, event_key=event_key)
        self.resolution_verified = resolution_verified

    def feasible_outcomes(self) -> Iterator[tuple[bool, ...]]:
        # Identical propositions resolve identically — which is exactly the
        # assumption `resolution_verified` exists to protect.
        yield (True, True)
        yield (False, False)

    def find_violation(
        self, books: dict[str, OrderBook], *, max_size: int
    ) -> tuple[ArbLeg, ...] | None:
        if not self.resolution_verified:
            return None
        a_key, b_key = self.market_keys
        a, b = books[a_key], books[b_key]
        for buy_book, sell_book, buy_key, sell_key in (
            (a, b, a_key, b_key),
            (b, a, b_key, a_key),
        ):
            ask, bid = buy_book.best_ask, sell_book.best_bid
            if ask is None or bid is None or ask.price_pips >= bid.price_pips:
                continue
            size = min(ask.size, bid.size, max_size)
            if size > 0:
                return (
                    ArbLeg(buy_key, Side.BUY, size, ask.price_pips),
                    ArbLeg(sell_key, Side.SELL, size, bid.price_pips),
                )
        return None


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


@dataclass
class ConstraintScanner:
    """Evaluates a registry of constraints against current books."""

    constraints: list[Constraint] = field(default_factory=list)
    fee_models: dict[str, FeeModel] = field(default_factory=dict)
    min_profit_pips: int = 100  # 1 cent of guaranteed profit, or skip
    max_size: int = 1000

    def add(self, constraint: Constraint) -> None:
        self.constraints.append(constraint)

    def scan(self, books: dict[str, OrderBook]) -> list[ArbOpportunity]:
        """Return every profitable violation, richest first.

        Ranked by return on capital rather than absolute profit: with a small
        account the binding resource is capital, so a $2 profit that ties up
        $20 beats a $5 profit that ties up $500.
        """
        found = [
            opp
            for constraint in self.constraints
            if (
                opp := constraint.scan(
                    books,
                    fee_models=self.fee_models,
                    max_size=self.max_size,
                    min_profit_pips=self.min_profit_pips,
                )
            )
            is not None
        ]
        found.sort(key=lambda o: o.return_on_capital, reverse=True)
        return found


def build_monotone_ladder(
    market_keys: Sequence[str], *, event_key: str = ""
) -> list[MonotoneConstraint]:
    """Every ordered pair in a ladder, from narrowest to broadest.

    A five-rung ladder yields ten constraints rather than four, because
    non-adjacent rungs can be inconsistent while every adjacent pair looks
    fine. Checking only neighbours misses most real violations.
    """
    return [
        MonotoneConstraint((narrow, broad), event_key=event_key)
        for narrow, broad in itertools.combinations(market_keys, 2)
    ]
