"""The trading loop.

Wires market data to opportunity detection to risk to execution, and records
everything. One loop serves paper, live and backtest, so the only difference
between a paper run and a live run is where fills come from.

The promotion gate lives here too. A strategy does not go live because it
looked good; it goes live because it accumulated a statistically meaningful
paper record. :class:`PromotionGate` encodes that as a rule rather than a
judgement call, which matters most on the day the temptation is strongest.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from orbit.core.money import format_usd
from orbit.core.types import Fill, OrderBook
from orbit.data.store import TickStore
from orbit.engine.executor import ExecutionMode, Executor
from orbit.risk.engine import RiskEngine
from orbit.strategies.constraints import ArbOpportunity, ConstraintScanner

log = structlog.get_logger(__name__)


@dataclass
class StrategyStats:
    """Running performance record for one strategy."""

    strategy_id: str
    mode: str = "paper"
    opportunities_seen: int = 0
    trades_attempted: int = 0
    trades_completed: int = 0
    trades_failed: int = 0
    gross_pnl_pips: int = 0
    fees_pips: int = 0
    unwind_cost_pips: int = 0
    first_trade_at: datetime | None = None
    last_trade_at: datetime | None = None

    @property
    def net_pnl_pips(self) -> int:
        return self.gross_pnl_pips - self.fees_pips - self.unwind_cost_pips

    @property
    def fill_rate(self) -> float:
        """Completed / attempted.

        The number that decides whether constraint arbitrage is real. A high
        detection rate with a low fill rate means the violations are stale
        quotes that vanish when touched, not tradable edges.
        """
        if self.trades_attempted == 0:
            return 0.0
        return self.trades_completed / self.trades_attempted

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "mode": self.mode,
            "opportunities_seen": self.opportunities_seen,
            "trades_attempted": self.trades_attempted,
            "trades_completed": self.trades_completed,
            "trades_failed": self.trades_failed,
            "fill_rate": self.fill_rate,
            "net_pnl_usd": self.net_pnl_pips / 10_000,
            "gross_pnl_usd": self.gross_pnl_pips / 10_000,
            "fees_usd": self.fees_pips / 10_000,
            "unwind_cost_usd": self.unwind_cost_pips / 10_000,
            "first_trade_at": (
                self.first_trade_at.isoformat() if self.first_trade_at else None
            ),
            "last_trade_at": (
                self.last_trade_at.isoformat() if self.last_trade_at else None
            ),
        }


@dataclass
class PromotionGate:
    """Criteria a strategy must clear on paper before risking real money.

    Every threshold is here to block a specific way of fooling yourself:

    * ``min_trades`` — three lucky trades are not evidence.
    * ``min_days`` — a strategy that only saw one market regime saw nothing.
    * ``min_net_pnl_pips`` — profitable *after* modelled fees, which is where
      most prediction-market strategies actually die.
    * ``min_fill_rate`` — detected opportunities that cannot be filled are not
      opportunities. This is the criterion most likely to block constraint
      arbitrage, and it should.
    """

    min_trades: int = 50
    min_days: float = 14.0
    min_net_pnl_pips: int = 0
    min_fill_rate: float = 0.5

    def evaluate(self, stats: StrategyStats) -> tuple[bool, list[str]]:
        """Return whether the strategy may go live, and why not if it may not."""
        blockers: list[str] = []
        if stats.trades_completed < self.min_trades:
            blockers.append(
                f"only {stats.trades_completed}/{self.min_trades} completed trades"
            )
        days = 0.0
        if stats.first_trade_at and stats.last_trade_at:
            days = (stats.last_trade_at - stats.first_trade_at).total_seconds() / 86_400
        if days < self.min_days:
            blockers.append(f"only {days:.1f}/{self.min_days} days of history")
        if stats.net_pnl_pips <= self.min_net_pnl_pips:
            blockers.append(
                f"net PnL {format_usd(stats.net_pnl_pips)} does not clear the bar"
            )
        if stats.fill_rate < self.min_fill_rate:
            blockers.append(
                f"fill rate {stats.fill_rate:.0%} below {self.min_fill_rate:.0%} — "
                "opportunities may be stale quotes"
            )
        return (not blockers), blockers


class TradingRunner:
    """Scan, risk-check, execute, record. Repeat."""

    def __init__(
        self,
        *,
        scanner: ConstraintScanner,
        risk: RiskEngine,
        executor: Executor,
        store: TickStore | None = None,
        strategy_id: str = "constraint_arb",
        scan_interval_s: float = 2.0,
        promotion_gate: PromotionGate | None = None,
    ) -> None:
        self.scanner = scanner
        self.risk = risk
        self.executor = executor
        self.store = store
        self.strategy_id = strategy_id
        self.scan_interval_s = scan_interval_s
        self.gate = promotion_gate or PromotionGate()
        self.stats = StrategyStats(
            strategy_id=strategy_id, mode=executor.mode.value
        )
        self.books: dict[str, OrderBook] = {}
        self.recent_opportunities: list[ArbOpportunity] = []
        self.trade_log: list[dict[str, Any]] = []
        self._stop = asyncio.Event()

    # -- data ---------------------------------------------------------------

    def observe(self, book: OrderBook) -> None:
        self.books[book.market_key] = book
        self.executor.observe(book)
        if self.store is not None:
            self.store.record_book(book)

    # -- one iteration ------------------------------------------------------

    async def scan_once(self, *, now: datetime | None = None) -> list[ArbOpportunity]:
        """Detect, filter and act on opportunities exactly once.

        Split out from the loop so it can be driven by recorded data in a
        backtest and by live data in production, with no behavioural fork.
        """
        now = now or datetime.now(UTC)
        if self.risk.kill.is_tripped:
            return []

        opportunities = self.scanner.scan(self.books)
        self.stats.opportunities_seen += len(opportunities)
        self.recent_opportunities = opportunities[:20]

        acted: list[ArbOpportunity] = []
        for opp in opportunities:
            if not await self._try_execute(opp, now=now):
                continue
            acted.append(opp)
        return acted

    async def _try_execute(self, opp: ArbOpportunity, *, now: datetime) -> bool:
        # Risk-check every leg before touching any of them. A multi-leg trade
        # that is only partly permitted is not a smaller version of the same
        # trade — it is a different, unhedged one.
        staleness = max(
            (
                (now - self.books[leg.market_key].timestamp).total_seconds()
                for leg in opp.legs
                if leg.market_key in self.books
            ),
            default=0.0,
        )
        for leg in opp.legs:
            from orbit.core.types import OrderRequest

            verdict = self.risk.check(
                OrderRequest(
                    market_key=leg.market_key,
                    side=leg.side,
                    size=leg.size,
                    price_pips=leg.limit_pips,
                    strategy_id=self.strategy_id,
                ),
                event_key=opp.event_key or None,
                data_age_s=staleness,
            )
            if not verdict.is_allowed or verdict.approved_size < leg.size:
                log.info(
                    "arb.skipped",
                    constraint=opp.constraint_name,
                    reason=verdict.reason,
                )
                return False

        self.stats.trades_attempted += 1
        result = await self.executor.execute_arbitrage(
            opp, strategy_id=self.strategy_id
        )

        for fill in result.fills:
            self.risk.record_fill(fill, event_key=opp.event_key or None)
        for req in result.requested:
            self.risk.record_order(req)

        if result.error:
            self.stats.trades_failed += 1
            self.stats.unwind_cost_pips -= min(0, result.net_pnl_pips)
        else:
            self.stats.trades_completed += 1
            # ``worst_case_profit_pips`` is already net of the modelled fees,
            # so the pre-fee figure is recovered before booking it. Adding it
            # as-is and then subtracting actual fees would charge fees twice
            # and turn a profitable arb into a reported loss. Keeping gross and
            # fees separate also exposes the gap between modelled and actual
            # fees, which is a useful early warning that a schedule changed.
            self.stats.gross_pnl_pips += (
                opp.worst_case_profit_pips + opp.total_fees_pips
            )
        self.stats.fees_pips += result.total_fees_pips
        self.stats.last_trade_at = now
        if self.stats.first_trade_at is None:
            self.stats.first_trade_at = now

        self.trade_log.append(
            {
                "timestamp": now.isoformat(),
                "constraint": opp.constraint_name,
                "legs": len(opp.legs),
                "expected_profit_usd": opp.worst_case_profit_pips / 10_000,
                "capital_usd": opp.capital_pips / 10_000,
                "completed": not result.error,
                "error": result.error,
                "rationale": opp.rationale,
            }
        )
        return not result.error

    # -- loop ---------------------------------------------------------------

    async def run(self) -> None:
        log.info(
            "runner.starting", strategy=self.strategy_id, mode=self.executor.mode.value
        )
        try:
            while not self._stop.is_set():
                try:
                    await self.scan_once()
                except Exception as exc:
                    # A strategy bug must not kill the process; it must be
                    # visible and bounded.
                    log.error("runner.scan_failed", error=str(exc), exc_info=True)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.scan_interval_s
                    )
        finally:
            log.info("runner.stopped", stats=self.stats.as_dict())

    async def stop(self) -> None:
        self._stop.set()
        if self.executor.mode is ExecutionMode.LIVE:
            await self.executor.cancel_all()

    # -- reporting ----------------------------------------------------------

    def promotion_status(self) -> dict[str, Any]:
        ready, blockers = self.gate.evaluate(self.stats)
        return {
            "strategy_id": self.strategy_id,
            "mode": self.executor.mode.value,
            "ready_for_live": ready,
            "blockers": blockers,
            "stats": self.stats.as_dict(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "strategy": self.stats.as_dict(),
            "promotion": self.promotion_status(),
            "risk": self.risk.snapshot(),
            "markets_tracked": len(self.books),
            "recent_opportunities": [
                {
                    "constraint": o.constraint_name,
                    "profit_usd": o.worst_case_profit_pips / 10_000,
                    "capital_usd": o.capital_pips / 10_000,
                    "return_on_capital": (
                        None if o.return_on_capital == float("inf")
                        else o.return_on_capital
                    ),
                    "legs": len(o.legs),
                    "execution_risk": o.execution_risk,
                }
                for o in self.recent_opportunities
            ],
            "recent_trades": self.trade_log[-25:],
        }


class Backtester:
    """Replays recorded books through the live trading loop.

    Uses the same :class:`TradingRunner` and the same fill model as paper
    trading. The only substitution is the source of books, which is what makes
    a backtest result meaningful rather than a separate simulator's opinion.
    """

    def __init__(self, runner: TradingRunner) -> None:
        self.runner = runner

    async def run(
        self, books: list[OrderBook], *, batch_by_timestamp: bool = True
    ) -> dict[str, Any]:
        """Replay in timestamp order.

        Books at the same instant are applied together before scanning, since
        a constraint spanning several markets can only be evaluated once every
        leg has been observed. Scanning after each individual update would
        detect violations against a half-updated view of the world.
        """
        ordered = sorted(books, key=lambda b: b.timestamp)
        i = 0
        while i < len(ordered):
            stamp = ordered[i].timestamp
            batch = [ordered[i]]
            i += 1
            if batch_by_timestamp:
                while i < len(ordered) and ordered[i].timestamp == stamp:
                    batch.append(ordered[i])
                    i += 1
            for book in batch:
                self.runner.observe(book)
            await self.runner.scan_once(now=stamp)

        return {
            "books_replayed": len(ordered),
            "window": (
                [ordered[0].timestamp.isoformat(), ordered[-1].timestamp.isoformat()]
                if ordered
                else None
            ),
            **self.runner.status(),
        }


def fills_to_pnl_pips(fills: list[Fill]) -> int:
    """Net cash effect of a fill list. Used by reports and tests."""
    return sum(f.cash_delta_pips for f in fills)
