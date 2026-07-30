"""Core domain types shared by every layer of the system.

These types are deliberately venue-neutral. Kalshi speaks in "YES/NO contracts
at a cent price"; Polymarket speaks in "outcome tokens at a decimal price".
Both collapse to the same object: a claim that pays $1 if a condition holds.
Adapters translate at the boundary so strategies, risk and backtesting never
learn a venue's dialect.

One normalisation is load-bearing: **everything is expressed in YES-space.**
A NO order at price ``p`` is recorded as the equivalent YES order at
``1 - p`` on the opposite side. Without this, every strategy would have to
handle four combinations of side and outcome, and one of them would be wrong.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Self

from orbit.core.money import (
    PIPS_PER_DOLLAR,
    complement,
    format_price,
    format_usd,
    price_to_prob,
)


class Venue(str, Enum):
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class Side(str, Enum):
    """Direction in YES-space."""

    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        """+1 for buy, -1 for sell. Lets position math stay branch-free."""
        return 1 if self is Side.BUY else -1


class Outcome(str, Enum):
    """Which leg of a binary market a venue quote refers to."""

    YES = "yes"
    NO = "no"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class TimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    #: Rest only; reject if the order would cross and take. Essential for any
    #: strategy whose edge depends on earning the maker side of the spread.
    POST_ONLY = "post_only"


class OrderStatus(str, Enum):
    PENDING = "pending"  # created locally, not yet acknowledged
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES

    @property
    def is_live(self) -> bool:
        """Still working on the exchange and therefore still consuming risk."""
        return self in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)


_TERMINAL_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


class MarketStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"  # trading halted, awaiting resolution
    SETTLED = "settled"
    UNKNOWN = "unknown"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Market:
    """A single binary contract that settles to $1 (YES) or $0 (NO)."""

    venue: Venue
    #: Venue-native identifier used for order placement (Kalshi ticker,
    #: Polymarket token id).
    venue_id: str
    title: str
    #: Groups markets that belong to one real-world event. Two markets sharing
    #: an ``event_key`` may be mutually exclusive, which is what makes
    #: dutch-book and logical-consistency checks possible.
    event_key: str
    status: MarketStatus = MarketStatus.UNKNOWN
    tick_pips: int = 100
    close_time: datetime | None = None
    expected_settle_time: datetime | None = None
    #: Venue-imposed cap on contracts held, if any.
    position_limit: int | None = None
    #: Free-form venue metadata, kept for debugging and strategy heuristics.
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Globally unique key across venues."""
        return f"{self.venue.value}:{self.venue_id}"

    @property
    def is_tradable(self) -> bool:
        return self.status is MarketStatus.ACTIVE

    def time_to_close(self, now: datetime | None = None) -> float | None:
        """Seconds until trading closes, or ``None`` if unknown."""
        if self.close_time is None:
            return None
        return (self.close_time - (now or _now())).total_seconds()


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price_pips: int
    size: int

    @property
    def notional_pips(self) -> int:
        return self.price_pips * self.size


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Top-of-book plus depth for one market, normalised to YES-space.

    ``bids`` are descending by price, ``asks`` ascending — the conventional
    order, so ``bids[0]`` and ``asks[0]`` are always the inside market.
    """

    market_key: str
    timestamp: datetime
    bids: tuple[PriceLevel, ...] = ()
    asks: tuple[PriceLevel, ...] = ()
    #: Exchange sequence number where available; used to detect dropped
    #: websocket messages, which otherwise corrupt the book silently.
    sequence: int | None = None

    @property
    def best_bid(self) -> PriceLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> PriceLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def best_bid_pips(self) -> int | None:
        return self.bids[0].price_pips if self.bids else None

    @property
    def best_ask_pips(self) -> int | None:
        return self.asks[0].price_pips if self.asks else None

    @property
    def spread_pips(self) -> int | None:
        if not self.bids or not self.asks:
            return None
        return self.asks[0].price_pips - self.bids[0].price_pips

    @property
    def mid_pips(self) -> int | None:
        """Arithmetic mid. ``None`` if either side is empty."""
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price_pips + self.asks[0].price_pips) // 2

    @property
    def microprice_pips(self) -> int | None:
        """Size-weighted mid — a better fair-value proxy than the plain mid.

        Leans toward the side with less resting size, which is the side price
        is more likely to move toward. On thin prediction-market books this
        difference is frequently larger than the edge being hunted.
        """
        if not self.bids or not self.asks:
            return None
        bid, ask = self.bids[0], self.asks[0]
        total = bid.size + ask.size
        if total == 0:
            return self.mid_pips
        return (bid.price_pips * ask.size + ask.price_pips * bid.size) // total

    @property
    def is_crossed(self) -> bool:
        """A crossed book means stale or corrupt data — never a free lunch."""
        if not self.bids or not self.asks:
            return False
        return self.bids[0].price_pips >= self.asks[0].price_pips

    def depth_within(self, *, side: Side, limit_pips: int) -> int:
        """Total size available no worse than ``limit_pips``.

        Used to answer "can I actually get filled for the size I want?" before
        committing to a trade — the question that separates a backtested edge
        from a real one.
        """
        if side is Side.BUY:
            return sum(lvl.size for lvl in self.asks if lvl.price_pips <= limit_pips)
        return sum(lvl.size for lvl in self.bids if lvl.price_pips >= limit_pips)

    def sweep_cost_pips(self, *, side: Side, size: int) -> tuple[int, int] | None:
        """Cost of taking ``size`` contracts immediately.

        Returns ``(total_pips, filled_size)``. Returns ``None`` if the book is
        empty on the relevant side. If the book is too thin, ``filled_size``
        is less than ``size`` — callers must check, because assuming full fills
        is the most common way a backtest lies.
        """
        levels = self.asks if side is Side.BUY else self.bids
        if not levels:
            return None
        remaining, total = size, 0
        for lvl in levels:
            if remaining <= 0:
                break
            take = min(remaining, lvl.size)
            total += take * lvl.price_pips
            remaining -= take
        return total, size - remaining

    def staleness_seconds(self, now: datetime | None = None) -> float:
        return ((now or _now()) - self.timestamp).total_seconds()


@dataclass(frozen=True, slots=True)
class Trade:
    """A public print on the tape."""

    market_key: str
    timestamp: datetime
    price_pips: int
    size: int
    #: Side of the aggressor, when the venue discloses it.
    taker_side: Side | None = None


# ---------------------------------------------------------------------------
# Orders and fills
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """An intent to trade, before the venue has seen it.

    Immutable and free of venue identifiers so it can be risk-checked,
    logged and replayed identically in backtest, paper and live.
    """

    market_key: str
    side: Side
    size: int
    price_pips: int | None = None  # None => market order
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.GTC
    #: Idempotency key. Sent to the venue where supported so a retry after a
    #: network timeout cannot double-fill.
    client_order_id: str = field(default_factory=_new_id)
    strategy_id: str = "unknown"
    #: Why this order exists — carried into the trade log so every fill can be
    #: traced back to a decision.
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError(f"size must be positive, got {self.size}")
        if self.order_type is OrderType.LIMIT and self.price_pips is None:
            raise ValueError("limit order requires price_pips")
        if self.price_pips is not None and not 0 < self.price_pips < PIPS_PER_DOLLAR:
            raise ValueError(f"price {self.price_pips} outside tradable range")

    @property
    def max_cost_pips(self) -> int:
        """Worst-case collateral this order can consume.

        Buying costs ``price``; selling a binary contract is writing it, which
        costs the complement. Market orders have no bound, so we assume the
        worst case of $1 — the risk engine must not be optimistic.
        """
        if self.price_pips is None:
            return PIPS_PER_DOLLAR * self.size
        unit = self.price_pips if self.side is Side.BUY else complement(self.price_pips)
        return unit * self.size


@dataclass(frozen=True, slots=True)
class Fill:
    """An execution. The only event that changes real money."""

    market_key: str
    timestamp: datetime
    side: Side
    size: int
    price_pips: int
    fee_pips: int
    liquidity: str  # "maker" | "taker"
    order_id: str
    client_order_id: str
    strategy_id: str = "unknown"
    venue_fill_id: str | None = None

    @property
    def signed_size(self) -> int:
        return self.side.sign * self.size

    @property
    def cash_delta_pips(self) -> int:
        """Change in cash. Negative when buying, positive when selling.

        Fees always reduce cash regardless of direction.
        """
        return -self.side.sign * self.price_pips * self.size - self.fee_pips


@dataclass(slots=True)
class Order:
    """Live order state, mirrored from the venue.

    Mutable by design: this is the one place the system tracks reality as the
    exchange reports it. Every mutation goes through :meth:`apply_fill` or
    :meth:`with_status` so ``filled_size`` and ``status`` cannot disagree.
    """

    request: OrderRequest
    venue_order_id: str | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: int = 0
    avg_fill_pips: int = 0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    reject_reason: str | None = None

    @property
    def client_order_id(self) -> str:
        return self.request.client_order_id

    @property
    def market_key(self) -> str:
        return self.request.market_key

    @property
    def remaining_size(self) -> int:
        return max(0, self.request.size - self.filled_size)

    @property
    def is_live(self) -> bool:
        return self.status.is_live

    def apply_fill(self, fill: Fill) -> None:
        """Fold a fill into this order, keeping the average price exact."""
        if fill.size <= 0:
            return
        new_filled = self.filled_size + fill.size
        if new_filled > self.request.size:
            raise ValueError(
                f"overfill on {self.client_order_id}: "
                f"{new_filled} > requested {self.request.size}"
            )
        total_pips = self.avg_fill_pips * self.filled_size + fill.price_pips * fill.size
        self.filled_size = new_filled
        self.avg_fill_pips = total_pips // new_filled
        self.status = (
            OrderStatus.FILLED
            if self.remaining_size == 0
            else OrderStatus.PARTIALLY_FILLED
        )
        self.updated_at = fill.timestamp

    def with_status(self, status: OrderStatus, *, reason: str | None = None) -> Self:
        self.status = status
        self.reject_reason = reason
        self.updated_at = _now()
        return self


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Position:
    """Net position in one market, in YES-space.

    ``size`` is signed: positive is long YES, negative is short YES (which is
    long NO). ``cost_basis_pips`` is the *net cash paid* including fees, so
    realised PnL falls out of settlement without a separate ledger.
    """

    market_key: str
    size: int = 0
    cost_basis_pips: int = 0
    realized_pnl_pips: int = 0
    fees_paid_pips: int = 0
    last_update: datetime = field(default_factory=_now)

    @property
    def is_flat(self) -> bool:
        return self.size == 0

    @property
    def avg_price_pips(self) -> int | None:
        """Average entry price per contract, or ``None`` when flat."""
        if self.size == 0:
            return None
        return abs(self.cost_basis_pips) // abs(self.size)

    def apply_fill(self, fill: Fill) -> None:
        """Update the position, realising PnL when a fill reduces exposure.

        Handles all four transitions — open, add, reduce, and flip through
        flat — and keeps the ledger exact. Integer division of the cost basis
        can leave a sub-pip residual; rather than discard it (which would let
        the books drift by a fraction of a cent per round trip, forever) the
        residual is folded into realised PnL whenever the position goes flat.
        """
        signed = fill.signed_size
        self.fees_paid_pips += fill.fee_pips
        self.realized_pnl_pips -= fill.fee_pips

        reducing = self.size != 0 and (self.size > 0) != (signed > 0)
        if reducing:
            closed = min(abs(signed), abs(self.size))
            entry = abs(self.cost_basis_pips) // abs(self.size)
            # Selling a long realises (exit - entry); covering a short realises
            # (entry - exit). The sign of the existing position gives both.
            direction = 1 if self.size > 0 else -1
            self.realized_pnl_pips += direction * (fill.price_pips - entry) * closed
            self.cost_basis_pips -= direction * entry * closed
            after = self.size + signed
            if after != 0 and (after > 0) == (signed > 0):
                # Flipped clean through flat. The old position is fully closed,
                # so whatever basis remains is truncation residual and belongs
                # to realised PnL — dropping it here would leak a fraction of a
                # cent on every flip, permanently.
                self.realized_pnl_pips -= self.cost_basis_pips
                self.cost_basis_pips = after * fill.price_pips
            self.size = after
        else:
            self.cost_basis_pips += signed * fill.price_pips
            self.size += signed

        if self.size == 0 and self.cost_basis_pips != 0:
            # Flat: any leftover basis is a rounding residual, not exposure.
            self.realized_pnl_pips -= self.cost_basis_pips
            self.cost_basis_pips = 0
        self.last_update = fill.timestamp

    def unrealized_pnl_pips(self, mark_pips: int) -> int:
        if self.size == 0:
            return 0
        return self.size * mark_pips - self.cost_basis_pips

    def collateral_pips(self) -> int:
        """Capital locked by this position.

        Fully collateralised venues lock ``price`` for a long and
        ``1 - price`` for a short. Return on *deployed* capital — the number
        that actually matters at small account sizes — is computed against this.
        """
        if self.size == 0:
            return 0
        if self.size > 0:
            return abs(self.cost_basis_pips)
        entry = abs(self.cost_basis_pips) // abs(self.size)
        return complement(entry) * abs(self.size)

    def settle(self, *, settled_yes: bool, settlement_fee_pips: int = 0) -> int:
        """Settle to $1 or $0 and return realised PnL in pips."""
        payout = PIPS_PER_DOLLAR if settled_yes else 0
        pnl = self.size * payout - self.cost_basis_pips - settlement_fee_pips
        self.realized_pnl_pips += pnl
        self.fees_paid_pips += settlement_fee_pips
        self.size = 0
        self.cost_basis_pips = 0
        self.last_update = _now()
        return pnl


@dataclass(frozen=True, slots=True)
class Balance:
    """Account balance on one venue, as the venue reports it."""

    venue: Venue
    cash_pips: int
    #: Capital locked in open positions and resting orders.
    reserved_pips: int = 0
    timestamp: datetime = field(default_factory=_now)

    @property
    def available_pips(self) -> int:
        return self.cash_pips - self.reserved_pips

    @property
    def total_pips(self) -> int:
        return self.cash_pips

    def __str__(self) -> str:
        return (
            f"{self.venue.value}: {format_usd(self.available_pips)} available "
            f"of {format_usd(self.cash_pips)}"
        )


# ---------------------------------------------------------------------------
# Quotes / fair values
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FairValue:
    """A model's opinion about a market, with its own uncertainty.

    ``confidence`` is not decoration: position sizing shrinks with it, so a
    model that is honest about being unsure automatically trades smaller. A
    strategy that always claims 1.0 will be sized as if it were certain, which
    is exactly how estimation error turns into ruin.
    """

    market_key: str
    probability: float
    confidence: float
    source: str
    timestamp: datetime = field(default_factory=_now)
    #: Half-width of the model's uncertainty band, in probability units.
    stderr: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability out of range: {self.probability}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    @property
    def price_pips(self) -> int:
        return int(round(self.probability * PIPS_PER_DOLLAR))

    def edge_pips(self, market_pips: int, *, side: Side) -> int:
        """Gross edge in pips, before fees, for trading ``side`` here."""
        if side is Side.BUY:
            return self.price_pips - market_pips
        return market_pips - self.price_pips

    def with_haircut(self, factor: float) -> FairValue:
        """Shrink the estimate toward 50c.

        The correct reflex when a model is being trusted for the first time:
        it preserves the direction of the signal while shrinking the size of
        the bet, so a wrong model loses slowly instead of quickly.
        """
        shrunk = 0.5 + (self.probability - 0.5) * factor
        return replace(self, probability=shrunk, confidence=self.confidence * factor)


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's decision to act, before risk sizing.

    Strategies emit signals; the risk engine converts them into orders. Keeping
    these separate means no strategy can bypass position limits, and every
    rejected trade is attributable.
    """

    strategy_id: str
    market_key: str
    side: Side
    #: Price the strategy is willing to pay/receive. The risk engine may
    #: reduce size but must never improve this price.
    limit_pips: int
    #: Size the strategy wants, before risk scaling.
    desired_size: int
    fair_value: FairValue | None = None
    urgency: float = 0.5  # 0 = patient/passive, 1 = must execute now
    rationale: str = ""
    timestamp: datetime = field(default_factory=_now)
    #: Signals that must execute together or not at all — arbitrage legs.
    #: A partially executed arb is not an arb, it is a naked position.
    group_id: str | None = None
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def expected_edge_pips(self) -> int | None:
        if self.fair_value is None:
            return None
        return self.fair_value.edge_pips(self.limit_pips, side=self.side)

    def __str__(self) -> str:
        return (
            f"{self.strategy_id} {self.side.value} {self.desired_size} "
            f"{self.market_key} @ {format_price(self.limit_pips)}"
            f"{f' (fv {price_to_prob(self.fair_value.price_pips):.1%})' if self.fair_value else ''}"
        )
