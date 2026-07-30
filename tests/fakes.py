"""In-memory venue used by tests, paper trading and the backtester.

A fake that is merely "not real" is useless; a fake that reproduces the
venue's *awkward* behaviour is where the value is. This one can be told to
rate-limit, drop connections, reject orders and partially fill, because those
are the paths that break unattended systems at 3am and they are otherwise
impossible to exercise offline.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from orbit.core.fees import KalshiFees, Liquidity
from orbit.core.types import (
    Balance,
    Fill,
    Market,
    MarketStatus,
    Order,
    OrderBook,
    OrderRequest,
    OrderStatus,
    Position,
    Side,
    Venue,
)
from orbit.venues.base import (
    RateLimitError,
    VenueAdapter,
    VenueCapabilities,
    VenueError,
    normalize_two_sided_book,
)


class FakeAdapter(VenueAdapter):
    """Deterministic venue with injectable failures."""

    capabilities = VenueCapabilities(
        supports_post_only=True,
        supports_batch_orders=True,
        supports_order_amend=False,
        nets_multi_outcome_margin=False,
        supports_split_merge=False,
        min_order_size=1,
        max_order_size=None,
        typical_latency_ms=0,
    )

    def __init__(
        self,
        venue: Venue = Venue.KALSHI,
        *,
        markets: Sequence[Market] | None = None,
        books: dict[str, OrderBook] | None = None,
        balance_pips: int = 50_000_000,  # $5,000
    ) -> None:
        self.venue = venue
        self._markets = list(markets or self._default_markets())
        self._books = dict(books or {})
        self._balance_pips = balance_pips
        self._orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._positions: dict[str, Position] = {}
        self._ids = itertools.count(1)
        self.fees = KalshiFees()

        # -- failure injection ---------------------------------------------
        self.fail_next_n = 0
        self.rate_limit_next_n = 0
        self.reject_orders = False
        self.partial_fill_ratio: float | None = None
        self.stream_drops_after: int | None = None
        self.call_counts: dict[str, int] = {}

    def _default_markets(self) -> list[Market]:
        now = datetime.now(UTC)
        return [
            Market(
                venue=self.venue,
                venue_id=f"TEST-{i}",
                title=f"Test market {i}",
                event_key=f"EVENT-{i // 2}",
                status=MarketStatus.ACTIVE,
                tick_pips=100,
                close_time=now + timedelta(days=1 + i),
            )
            for i in range(4)
        ]

    def _tick(self, name: str) -> None:
        self.call_counts[name] = self.call_counts.get(name, 0) + 1
        if self.rate_limit_next_n > 0:
            self.rate_limit_next_n -= 1
            raise RateLimitError("slow down", venue=self.venue.value, retry_after_s=0.01)
        if self.fail_next_n > 0:
            self.fail_next_n -= 1
            raise VenueError("injected failure", venue=self.venue.value, retryable=True)

    # -- reference data -----------------------------------------------------

    async def list_markets(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[Market]:
        self._tick("list_markets")
        return self._markets[:limit]

    async def get_market(self, venue_id: str) -> Market:
        self._tick("get_market")
        for m in self._markets:
            if m.venue_id == venue_id:
                return m
        raise VenueError(f"unknown market {venue_id}", venue=self.venue.value)

    # -- market data --------------------------------------------------------

    def set_book(
        self, venue_id: str, bids: Sequence[tuple[int, int]], asks: Sequence[tuple[int, int]]
    ) -> OrderBook:
        book = normalize_two_sided_book(
            market_key=self.market_key(venue_id),
            timestamp=datetime.now(UTC),
            bids=list(bids),
            asks=list(asks),
        )
        self._books[venue_id] = book
        return book

    async def get_book(self, venue_id: str, *, depth: int = 10) -> OrderBook:
        self._tick("get_book")
        if venue_id in self._books:
            return self._books[venue_id]
        return self.set_book(venue_id, [(4500, 100), (4400, 200)], [(4700, 100)])

    async def get_books(self, venue_ids: Sequence[str]) -> list[OrderBook]:
        self._tick("get_books")
        return [await self.get_book(v) for v in venue_ids]

    async def stream_books(self, venue_ids: Sequence[str]) -> AsyncIterator[OrderBook]:
        self._tick("stream_books")
        emitted = 0
        for i in itertools.count():
            for vid in venue_ids:
                if self.stream_drops_after is not None and emitted >= self.stream_drops_after:
                    raise VenueError(
                        "stream dropped", venue=self.venue.value, retryable=True
                    )
                book = self.set_book(
                    vid, [(4500 + (i % 5) * 100, 100)], [(4700 + (i % 5) * 100, 100)]
                )
                emitted += 1
                yield book
            await asyncio.sleep(0)

    # -- trading ------------------------------------------------------------

    async def place_order(self, request: OrderRequest) -> Order:
        self._tick("place_order")
        order = Order(request=request)
        if self.reject_orders:
            return order.with_status(OrderStatus.REJECTED, reason="injected rejection")

        order.venue_order_id = f"ord-{next(self._ids)}"
        order.status = OrderStatus.OPEN
        self._orders[order.venue_order_id] = order

        venue_id = request.market_key.split(":", 1)[1]
        book = await self.get_book(venue_id)
        crossing = (
            request.price_pips is not None
            and book.best_ask_pips is not None
            and request.side is Side.BUY
            and request.price_pips >= book.best_ask_pips
        ) or (
            request.price_pips is not None
            and book.best_bid_pips is not None
            and request.side is Side.SELL
            and request.price_pips <= book.best_bid_pips
        )
        if crossing:
            size = request.size
            if self.partial_fill_ratio is not None:
                size = max(1, int(size * self.partial_fill_ratio))
            price = (
                book.best_ask_pips if request.side is Side.BUY else book.best_bid_pips
            )
            assert price is not None
            self._execute(order, size=size, price_pips=price, liquidity=Liquidity.TAKER)
        return order

    def _execute(
        self, order: Order, *, size: int, price_pips: int, liquidity: Liquidity
    ) -> Fill:
        fee = self.fees.trade_fee_pips(
            price_pips=price_pips, size=size, liquidity=liquidity
        )
        fill = Fill(
            market_key=order.market_key,
            timestamp=datetime.now(UTC),
            side=order.request.side,
            size=size,
            price_pips=price_pips,
            fee_pips=fee,
            liquidity=liquidity.value,
            order_id=order.venue_order_id or "",
            client_order_id=order.client_order_id,
            strategy_id=order.request.strategy_id,
        )
        order.apply_fill(fill)
        self._fills.append(fill)
        pos = self._positions.setdefault(
            order.market_key, Position(market_key=order.market_key)
        )
        pos.apply_fill(fill)
        self._balance_pips += fill.cash_delta_pips
        return fill

    async def cancel_order(self, order: Order) -> Order:
        self._tick("cancel_order")
        if order.venue_order_id in self._orders:
            self._orders.pop(order.venue_order_id, None)
        return order.with_status(OrderStatus.CANCELED)

    async def cancel_all(self) -> int:
        n = len(self._orders)
        self._orders.clear()
        return n

    async def get_open_orders(self) -> list[Order]:
        self._tick("get_open_orders")
        return [o for o in self._orders.values() if o.is_live]

    async def get_fills(self, *, since: datetime | None = None) -> list[Fill]:
        self._tick("get_fills")
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    # -- account ------------------------------------------------------------

    async def get_balance(self) -> Balance:
        self._tick("get_balance")
        return Balance(venue=self.venue, cash_pips=self._balance_pips)

    async def get_positions(self) -> list[Position]:
        self._tick("get_positions")
        return [p for p in self._positions.values() if not p.is_flat]

    def status(self) -> dict[str, Any]:
        return {
            "balance_pips": self._balance_pips,
            "orders": len(self._orders),
            "fills": len(self._fills),
            "calls": dict(self.call_counts),
        }
