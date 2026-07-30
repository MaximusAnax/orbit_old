"""Order execution.

Three execution modes share one code path so that what is tested is what
trades:

* ``PAPER`` — orders are simulated against the live book. No venue calls.
* ``LIVE`` — orders go to the venue.
* ``BACKTEST`` — identical to paper, driven by recorded rather than live books.

Keeping them behind one interface is the point. A paper mode that runs
different code from live proves nothing about live, and the discrepancy is
always discovered with real money.

The other job here is **atomic multi-leg execution**. A constraint arbitrage is
only risk-free if every leg fills. One leg filling alone is a naked position
the strategy never intended and is not sized for, so partial execution is
treated as an incident: the executor unwinds what filled and reports it, rather
than leaving the book quietly wrong.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import structlog

from orbit.core.fees import FeeModel, Liquidity, fee_model_for
from orbit.core.types import (
    Fill,
    Order,
    OrderBook,
    OrderRequest,
    OrderStatus,
    OrderType,
    PriceLevel,
    Side,
    TimeInForce,
)
from orbit.strategies.constraints import ArbOpportunity
from orbit.venues.base import VenueAdapter, VenueError

log = structlog.get_logger(__name__)


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


@dataclass
class ExecutionResult:
    """Outcome of an execution attempt, including partial failure."""

    requested: tuple[OrderRequest, ...]
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    unwound: list[Fill] = field(default_factory=list)
    error: str | None = None

    @property
    def fully_filled(self) -> bool:
        return len(self.orders) == len(self.requested) and all(
            o.status is OrderStatus.FILLED for o in self.orders
        )

    @property
    def net_pnl_pips(self) -> int:
        return sum(f.cash_delta_pips for f in self.fills + self.unwound)

    @property
    def total_fees_pips(self) -> int:
        return sum(f.fee_pips for f in self.fills + self.unwound)


class PaperFillModel:
    """Simulates fills against a real book.

    Deliberately pessimistic, because an optimistic fill model is the single
    most common way a backtest reports profits that never existed:

    * A marketable order walks the book level by level and **can fill
      partially** if depth runs out. It never gets more size than was
      displayed.
    * A resting order is only filled when the market trades *through* its
      price, not merely to it — modelling queue position as "last in line".
      Assuming fills at the touch is worth several cents a trade, which is
      larger than most edges here.
    * Our own size is removed from the book before the next leg is priced, so
      a multi-leg trade cannot fill twice against the same displayed liquidity.
    """

    def __init__(self, *, assume_queue_priority: bool = False) -> None:
        self.assume_queue_priority = assume_queue_priority

    def fill(
        self,
        request: OrderRequest,
        book: OrderBook,
        *,
        fee_model: FeeModel,
        now: datetime | None = None,
    ) -> tuple[Fill | None, OrderBook]:
        """Attempt a fill. Returns the fill (if any) and the depleted book."""
        now = now or datetime.now(UTC)
        levels = book.asks if request.side is Side.BUY else book.bids
        if not levels:
            return None, book

        limit = request.price_pips
        crosses = (
            limit is None
            or (request.side is Side.BUY and limit >= levels[0].price_pips)
            or (request.side is Side.SELL and limit <= levels[0].price_pips)
        )
        if not crosses:
            # Would rest. Passive fills are not simulated optimistically: a
            # resting order is assumed to be behind the entire queue.
            return None, book

        filled, cost, remaining = 0, 0, request.size
        consumed: list[int] = []
        for level in levels:
            if remaining <= 0:
                break
            if limit is not None and (
                (request.side is Side.BUY and level.price_pips > limit)
                or (request.side is Side.SELL and level.price_pips < limit)
            ):
                break
            take = min(remaining, level.size)
            filled += take
            cost += take * level.price_pips
            remaining -= take
            consumed.append(take)

        if filled == 0:
            return None, book
        if request.time_in_force is TimeInForce.FOK and filled < request.size:
            return None, book

        avg = cost // filled
        fee = fee_model.trade_fee_pips(
            price_pips=avg, size=filled, liquidity=Liquidity.TAKER
        )
        fill = Fill(
            market_key=request.market_key,
            timestamp=now,
            side=request.side,
            size=filled,
            price_pips=avg,
            fee_pips=fee,
            liquidity="taker",
            order_id=f"paper-{request.client_order_id[:8]}",
            client_order_id=request.client_order_id,
            strategy_id=request.strategy_id,
        )
        return fill, self._deplete(book, request.side, consumed)

    @staticmethod
    def _deplete(book: OrderBook, side: Side, consumed: list[int]) -> OrderBook:
        """Remove the liquidity we just took, so it cannot be used twice."""
        levels = list(book.asks if side is Side.BUY else book.bids)
        out = []
        for i, level in enumerate(levels):
            taken = consumed[i] if i < len(consumed) else 0
            if level.size - taken > 0:
                out.append(
                    PriceLevel(price_pips=level.price_pips, size=level.size - taken)
                )
        if side is Side.BUY:
            return OrderBook(book.market_key, book.timestamp, book.bids, tuple(out),
                             book.sequence)
        return OrderBook(book.market_key, book.timestamp, tuple(out), book.asks,
                         book.sequence)


class Executor:
    """Places orders in the configured mode and reconciles the result."""

    def __init__(
        self,
        adapters: dict[str, VenueAdapter],
        *,
        mode: ExecutionMode = ExecutionMode.PAPER,
        fill_model: PaperFillModel | None = None,
    ) -> None:
        self.adapters = adapters
        self.mode = mode
        self.fill_model = fill_model or PaperFillModel()
        self._paper_books: dict[str, OrderBook] = {}

    def observe(self, book: OrderBook) -> None:
        """Feed the current book, used for paper and backtest fills."""
        self._paper_books[book.market_key] = book

    async def execute(
        self, request: OrderRequest, *, book: OrderBook | None = None
    ) -> tuple[Order, list[Fill]]:
        """Execute a single order."""
        if self.mode is ExecutionMode.LIVE:
            return await self._execute_live(request)
        return self._execute_paper(request, book)

    def _execute_paper(
        self, request: OrderRequest, book: OrderBook | None
    ) -> tuple[Order, list[Fill]]:
        order = Order(request=request)
        book = book or self._paper_books.get(request.market_key)
        if book is None:
            return order.with_status(OrderStatus.REJECTED, reason="no book"), []

        venue = request.market_key.split(":", 1)[0]
        fill, depleted = self.fill_model.fill(
            request, book, fee_model=fee_model_for(venue)
        )
        self._paper_books[request.market_key] = depleted
        order.venue_order_id = f"paper-{request.client_order_id[:8]}"
        if fill is None:
            order.status = OrderStatus.OPEN  # would rest, unfilled
            return order, []
        order.apply_fill(fill)
        return order, [fill]

    async def _execute_live(self, request: OrderRequest) -> tuple[Order, list[Fill]]:
        venue = request.market_key.split(":", 1)[0]
        adapter = self.adapters.get(venue)
        if adapter is None:
            order = Order(request=request)
            return order.with_status(
                OrderStatus.REJECTED, reason=f"no adapter for {venue}"
            ), []
        order = await adapter.place_order(request)
        fills: list[Fill] = []
        if order.filled_size > 0:
            fills = [
                f
                for f in await adapter.get_fills()
                if f.client_order_id == request.client_order_id
            ]
        return order, fills

    # -- multi-leg ----------------------------------------------------------

    async def execute_arbitrage(
        self, opportunity: ArbOpportunity, *, strategy_id: str = "arb"
    ) -> ExecutionResult:
        """Execute every leg, unwinding if the set cannot be completed.

        Legs are ordered **least liquid first**. The leg most likely to fail is
        therefore attempted while the position is still smallest, so an
        unwind costs as little as possible. Executing the easy leg first
        maximises the damage when the hard one misses.
        """
        legs = sorted(
            opportunity.legs,
            key=lambda leg: self._available_depth(leg.market_key, leg.side),
        )
        requests = tuple(
            OrderRequest(
                market_key=leg.market_key,
                side=leg.side,
                size=leg.size,
                price_pips=leg.limit_pips,
                time_in_force=TimeInForce.IOC,
                strategy_id=strategy_id,
                rationale=opportunity.rationale,
            )
            for leg in legs
        )
        result = ExecutionResult(requested=requests)

        for request in requests:
            try:
                order, fills = await self.execute(request)
            except VenueError as exc:
                result.error = f"{request.market_key}: {exc}"
                break
            result.orders.append(order)
            result.fills.extend(fills)
            filled = sum(f.size for f in fills)
            if filled < request.size:
                result.error = (
                    f"{request.market_key} filled {filled}/{request.size}; "
                    "arbitrage incomplete"
                )
                break

        if result.error and result.fills:
            result.unwound = await self._unwind(result.fills, strategy_id=strategy_id)
            log.error(
                "arb.partial_execution_unwound",
                error=result.error,
                legs_filled=len(result.fills),
                cost_pips=result.net_pnl_pips,
            )
        return result

    def _available_depth(self, market_key: str, side: Side) -> int:
        book = self._paper_books.get(market_key)
        if book is None:
            return 0
        levels = book.asks if side is Side.BUY else book.bids
        return levels[0].size if levels else 0

    async def _unwind(self, fills: list[Fill], *, strategy_id: str) -> list[Fill]:
        """Close positions opened by a failed multi-leg attempt.

        Unwinding costs the spread and is expected to lose money. That is the
        correct trade: a known small loss now beats an unintended directional
        position held to settlement.
        """
        unwound: list[Fill] = []
        for fill in fills:
            request = OrderRequest(
                market_key=fill.market_key,
                side=fill.side.opposite,
                size=fill.size,
                price_pips=None,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.IOC,
                strategy_id=strategy_id,
                rationale="unwind incomplete arbitrage",
            )
            with contextlib.suppress(VenueError):
                _, got = await self.execute(request)
                unwound.extend(got)
        return unwound

    async def cancel_all(self) -> int:
        """Pull every resting order across every venue. Kill-switch path."""
        if self.mode is not ExecutionMode.LIVE:
            return 0
        total = 0
        for adapter in self.adapters.values():
            with contextlib.suppress(VenueError, AttributeError):
                total += await asyncio.wait_for(adapter.cancel_all(), timeout=10.0)
        return total
