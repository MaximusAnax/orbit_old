"""Venue adapter protocol.

Every venue is reduced to this interface so that strategies, risk and the
backtester are written once. The adapter's job is translation and nothing
else: it owns the venue's dialect (Kalshi's cent prices and YES/NO order
actions, Polymarket's decimal prices and signed orders) and hands the rest of
the system normalised :mod:`orbit.core.types` objects.

Two rules keep this boundary honest:

1. **Everything leaves the adapter in YES-space.** See
   :func:`normalize_binary_book` — a venue that quotes both sides as bids
   (Kalshi does) is converted here, once, rather than in every strategy.
2. **Adapters never decide.** No sizing, no risk checks, no "helpfully"
   retrying a rejected order. They report what the venue said, including
   failures, so the engine can react with full information.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from orbit.core.money import complement
from orbit.core.types import (
    Balance,
    Fill,
    Market,
    Order,
    OrderBook,
    OrderRequest,
    Position,
    PriceLevel,
    Trade,
    Venue,
)


class VenueError(Exception):
    """Base class for venue failures."""

    def __init__(self, message: str, *, venue: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.venue = venue
        self.retryable = retryable


class AuthError(VenueError):
    """Credentials missing, malformed, or rejected."""


class RateLimitError(VenueError):
    """Venue asked us to slow down. Always retryable, after a delay."""

    def __init__(self, message: str, *, venue: str, retry_after_s: float = 1.0) -> None:
        super().__init__(message, venue=venue, retryable=True)
        self.retry_after_s = retry_after_s


class OrderRejectedError(VenueError):
    """The venue refused an order. Never retried blindly."""


class InsufficientFundsError(OrderRejectedError):
    """Not enough collateral. Signals the risk engine to recompute balances."""


@dataclass(frozen=True, slots=True)
class VenueCapabilities:
    """What a venue actually supports.

    Strategies query this instead of hardcoding assumptions, so a strategy
    that needs post-only quoting can decline to run on a venue without it
    rather than silently paying taker fees on every fill.
    """

    supports_post_only: bool
    supports_batch_orders: bool
    supports_order_amend: bool
    #: Whether the venue nets collateral across mutually exclusive outcomes.
    #: Determines whether dutch-book trades tie up one leg's capital or all legs'.
    nets_multi_outcome_margin: bool
    #: Whether YES and NO can be minted/redeemed as a pair against $1.
    #: Polymarket's split/merge; enforces a hard arbitrage bound.
    supports_split_merge: bool
    min_order_size: int
    max_order_size: int | None
    #: Typical round-trip latency budget in milliseconds, for strategy gating.
    typical_latency_ms: int


@runtime_checkable
class MarketDataFeed(Protocol):
    """Streaming market data. Implementations must be reconnect-safe."""

    async def subscribe_books(
        self, market_keys: Sequence[str]
    ) -> AsyncIterator[OrderBook]: ...

    async def subscribe_trades(
        self, market_keys: Sequence[str]
    ) -> AsyncIterator[Trade]: ...


class VenueAdapter(ABC):
    """Abstract venue. Concrete adapters live in sibling modules."""

    venue: Venue
    capabilities: VenueCapabilities

    # -- reference data -----------------------------------------------------

    @abstractmethod
    async def list_markets(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[Market]:
        """Enumerate markets. Used by the scanner to find tradable universe."""

    @abstractmethod
    async def get_market(self, venue_id: str) -> Market: ...

    # -- market data --------------------------------------------------------

    @abstractmethod
    async def get_book(self, venue_id: str, *, depth: int = 10) -> OrderBook:
        """Fetch a single book, normalised to YES-space."""

    @abstractmethod
    async def stream_books(
        self, venue_ids: Sequence[str]
    ) -> AsyncIterator[OrderBook]:
        """Stream book updates. Must resubscribe transparently on reconnect."""

    # -- trading ------------------------------------------------------------

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def get_open_orders(self) -> list[Order]: ...

    @abstractmethod
    async def get_fills(self, *, since: datetime | None = None) -> list[Fill]: ...

    # -- account ------------------------------------------------------------

    @abstractmethod
    async def get_balance(self) -> Balance: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    # -- lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        """Release sockets and sessions."""
        return None

    def market_key(self, venue_id: str) -> str:
        return f"{self.venue.value}:{venue_id}"


# ---------------------------------------------------------------------------
# Book normalisation
# ---------------------------------------------------------------------------


def normalize_binary_book(
    *,
    market_key: str,
    timestamp: datetime,
    yes_bids: Sequence[tuple[int, int]],
    no_bids: Sequence[tuple[int, int]],
    sequence: int | None = None,
    depth: int | None = None,
) -> OrderBook:
    """Convert a two-sided *bid-only* binary book into a YES-space book.

    Kalshi (and any venue modelling a binary market as two opposing books)
    publishes **bids on both sides**: a list of bids to buy YES, and a list of
    bids to buy NO. There are no explicit asks. The conversion is the central
    identity of binary markets:

        a bid to buy NO at price ``p``
          == an offer to sell YES at ``$1 - p``

    So YES asks are the NO bids reflected through $1. Getting this wrong
    inverts the book, which does not raise an error — it silently produces a
    strategy that buys every time it means to sell. Hence the dedicated
    function and its tests.

    Args:
        yes_bids: ``(price_pips, size)`` bids to buy YES.
        no_bids: ``(price_pips, size)`` bids to buy NO.
        depth: Truncate each side to this many levels.

    Returns:
        A book whose ``bids`` descend and ``asks`` ascend, both in YES-space.
    """
    bids = sorted(
        (PriceLevel(price_pips=p, size=s) for p, s in yes_bids if s > 0),
        key=lambda lvl: -lvl.price_pips,
    )
    asks = sorted(
        (PriceLevel(price_pips=complement(p), size=s) for p, s in no_bids if s > 0),
        key=lambda lvl: lvl.price_pips,
    )
    if depth is not None:
        bids, asks = bids[:depth], asks[:depth]
    return OrderBook(
        market_key=market_key,
        timestamp=timestamp,
        bids=tuple(bids),
        asks=tuple(asks),
        sequence=sequence,
    )


def normalize_two_sided_book(
    *,
    market_key: str,
    timestamp: datetime,
    bids: Sequence[tuple[int, int]],
    asks: Sequence[tuple[int, int]],
    sequence: int | None = None,
    depth: int | None = None,
) -> OrderBook:
    """Normalise a venue that already publishes explicit bids and asks.

    Polymarket's CLOB returns a conventional book per outcome token, so this
    is a sort-and-truncate rather than a reflection.
    """
    b = sorted(
        (PriceLevel(price_pips=p, size=s) for p, s in bids if s > 0),
        key=lambda lvl: -lvl.price_pips,
    )
    a = sorted(
        (PriceLevel(price_pips=p, size=s) for p, s in asks if s > 0),
        key=lambda lvl: lvl.price_pips,
    )
    if depth is not None:
        b, a = b[:depth], a[:depth]
    return OrderBook(
        market_key=market_key,
        timestamp=timestamp,
        bids=tuple(b),
        asks=tuple(a),
        sequence=sequence,
    )
