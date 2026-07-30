"""Execution, the trading loop, and the promotion gate.

The tests that matter most here concern *failure*: a multi-leg arbitrage where
one leg misses must not leave a naked position, and a paper fill model must not
be generous, because a generous fill model is how a backtest invents profit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from orbit.core.fees import KalshiFees, PolymarketFees
from orbit.core.money import cents_to_pips
from orbit.core.types import OrderRequest, Side, TimeInForce
from orbit.engine.executor import ExecutionMode, Executor, PaperFillModel
from orbit.engine.runner import (
    Backtester,
    PromotionGate,
    StrategyStats,
    TradingRunner,
)
from orbit.risk.engine import RiskEngine, RiskLimits
from orbit.strategies.constraints import (
    ComplementConstraint,
    ConstraintScanner,
    MonotoneConstraint,
)
from orbit.venues.base import normalize_two_sided_book

TS = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
FEES = {"kalshi": KalshiFees(), "polymarket": PolymarketFees()}
BANKROLL = 50_000_000  # $5,000


def c(cents: int) -> int:
    return cents_to_pips(cents)


def book(key, bid=None, ask=None, size=1000, ts=TS, bid2=None, ask2=None):
    bids = [(c(bid), size)] if bid is not None else []
    asks = [(c(ask), size)] if ask is not None else []
    if bid2 is not None:
        bids.append((c(bid2), size))
    if ask2 is not None:
        asks.append((c(ask2), size))
    return normalize_two_sided_book(
        market_key=key, timestamp=ts, bids=bids, asks=asks
    )


class TestPaperFillModel:
    def test_marketable_order_fills_at_the_book(self):
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 100, c(50))
        fill, _ = model.fill(req, book("kalshi:A", bid=45, ask=48),
                             fee_model=KalshiFees())
        assert fill is not None
        assert fill.price_pips == c(48)
        assert fill.size == 100

    def test_resting_order_does_not_fill(self):
        """A limit inside the spread would rest; it must not fill for free."""
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 100, c(46))
        fill, _ = model.fill(req, book("kalshi:A", bid=45, ask=48),
                             fee_model=KalshiFees())
        assert fill is None

    def test_partial_fill_when_the_book_is_thin(self):
        """The most important pessimism: you cannot get more than is shown."""
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 500, c(50))
        fill, _ = model.fill(req, book("kalshi:A", bid=45, ask=48, size=100),
                             fee_model=KalshiFees())
        assert fill is not None
        assert fill.size == 100, "must not invent liquidity"

    def test_walks_multiple_levels_and_averages(self):
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 150, c(50))
        b = book("kalshi:A", bid=45, ask=48, size=100, ask2=49)
        fill, _ = model.fill(req, b, fee_model=KalshiFees())
        assert fill.size == 150
        # 100 at 48c + 50 at 49c -> average 48.33c
        assert c(48) < fill.price_pips < c(49)

    def test_fok_rejects_a_partial(self):
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 500, c(50),
                           time_in_force=TimeInForce.FOK)
        fill, _ = model.fill(req, book("kalshi:A", bid=45, ask=48, size=100),
                             fee_model=KalshiFees())
        assert fill is None

    def test_liquidity_is_consumed_and_cannot_be_reused(self):
        """Otherwise a multi-leg trade fills twice against the same size."""
        model = PaperFillModel()
        b = book("kalshi:A", bid=45, ask=48, size=100)
        req = OrderRequest("kalshi:A", Side.BUY, 60, c(50))
        fill1, b = model.fill(req, b, fee_model=KalshiFees())
        assert fill1.size == 60
        fill2, b = model.fill(
            OrderRequest("kalshi:A", Side.BUY, 60, c(50)), b, fee_model=KalshiFees()
        )
        assert fill2.size == 40, "only the remaining 40 should be available"

    def test_empty_book_does_not_fill(self):
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 100, c(50))
        fill, _ = model.fill(req, book("kalshi:A"), fee_model=KalshiFees())
        assert fill is None

    def test_fees_are_charged_on_paper_fills(self):
        """Paper trading that ignores fees is worse than no paper trading."""
        model = PaperFillModel()
        req = OrderRequest("kalshi:A", Side.BUY, 100, c(50))
        fill, _ = model.fill(req, book("kalshi:A", bid=45, ask=50),
                             fee_model=KalshiFees())
        assert fill.fee_pips > 0


class TestMultiLegExecution:
    @pytest.fixture
    def executor(self):
        return Executor({}, mode=ExecutionMode.PAPER)

    async def test_both_legs_fill_on_a_clean_arb(self, executor):
        books = {
            "kalshi:MAR": book("kalshi:MAR", bid=40, ask=42),
            "kalshi:JUN": book("kalshi:JUN", bid=33, ask=35),
        }
        for b in books.values():
            executor.observe(b)
        opp = MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"]).scan(
            books, fee_models=FEES
        )
        assert opp is not None
        result = await executor.execute_arbitrage(opp)
        assert result.error is None
        assert len(result.fills) == 2
        assert not result.unwound

    async def test_partial_execution_is_unwound(self, executor):
        """One leg filling alone is a naked position, not a smaller arb."""
        books = {
            # JUN has only 10 contracts available, so the second leg misses.
            "kalshi:MAR": book("kalshi:MAR", bid=40, ask=42, size=1000),
            "kalshi:JUN": book("kalshi:JUN", bid=33, ask=35, size=10),
        }
        for b in books.values():
            executor.observe(b)
        opp = MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"]).scan(
            books, fee_models=FEES, max_size=1000
        )
        # Force an oversized second leg by rebuilding at full size.
        from orbit.strategies.constraints import ArbLeg

        opp = MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"]).evaluate(
            [
                ArbLeg("kalshi:MAR", Side.SELL, 1000, c(40)),
                ArbLeg("kalshi:JUN", Side.BUY, 1000, c(35)),
            ],
            fee_models=FEES,
        )
        result = await executor.execute_arbitrage(opp)
        assert result.error is not None
        assert "incomplete" in result.error
        assert result.unwound, "the filled leg must be closed out"

    async def test_least_liquid_leg_is_attempted_first(self, executor):
        """Fail early, while the position is still smallest."""
        executor.observe(book("kalshi:THIN", bid=40, ask=42, size=5))
        executor.observe(book("kalshi:DEEP", bid=33, ask=35, size=5000))
        from orbit.strategies.constraints import ArbLeg

        opp = MonotoneConstraint(["kalshi:THIN", "kalshi:DEEP"]).evaluate(
            [
                ArbLeg("kalshi:THIN", Side.SELL, 100, c(40)),
                ArbLeg("kalshi:DEEP", Side.BUY, 100, c(35)),
            ],
            fee_models=FEES,
        )
        result = await executor.execute_arbitrage(opp)
        assert result.requested[0].market_key == "kalshi:THIN"


class TestTradingRunner:
    def make_runner(self, *, limits=None, mode=ExecutionMode.PAPER):
        scanner = ConstraintScanner(fee_models=FEES, min_profit_pips=0)
        scanner.add(MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"]))
        scanner.add(ComplementConstraint(["kalshi:X"]))
        risk = RiskEngine(limits or RiskLimits(), bankroll_pips=BANKROLL)
        return TradingRunner(
            scanner=scanner,
            risk=risk,
            executor=Executor({}, mode=mode),
            scan_interval_s=0.01,
        )

    async def test_detects_and_trades_a_violation(self):
        runner = self.make_runner()
        runner.observe(book("kalshi:MAR", bid=40, ask=42, size=100))
        runner.observe(book("kalshi:JUN", bid=33, ask=35, size=100))
        acted = await runner.scan_once(now=TS)
        assert acted
        assert runner.stats.trades_completed == 1
        assert runner.stats.net_pnl_pips > 0

    async def test_does_nothing_when_prices_are_consistent(self):
        runner = self.make_runner()
        runner.observe(book("kalshi:MAR", bid=28, ask=30))
        runner.observe(book("kalshi:JUN", bid=40, ask=42))
        assert await runner.scan_once(now=TS) == []
        assert runner.stats.trades_attempted == 0

    async def test_kill_switch_stops_all_trading(self):
        runner = self.make_runner()
        runner.observe(book("kalshi:MAR", bid=40, ask=42))
        runner.observe(book("kalshi:JUN", bid=33, ask=35))
        runner.risk.kill.trip("test")
        assert await runner.scan_once(now=TS) == []
        assert runner.stats.trades_attempted == 0

    async def test_stale_data_blocks_execution(self):
        """An old book is not evidence about the present."""
        runner = self.make_runner()
        old = TS - timedelta(minutes=5)
        runner.observe(book("kalshi:MAR", bid=40, ask=42, ts=old))
        runner.observe(book("kalshi:JUN", bid=33, ask=35, ts=old))
        assert await runner.scan_once(now=TS) == []
        assert runner.stats.trades_completed == 0

    async def test_risk_rejection_prevents_a_partial_multi_leg_trade(self):
        """If any leg is disallowed, no leg trades."""
        limits = RiskLimits(max_market_fraction=0.000001, min_order_size=1)
        runner = self.make_runner(limits=limits)
        runner.observe(book("kalshi:MAR", bid=40, ask=42))
        runner.observe(book("kalshi:JUN", bid=33, ask=35))
        assert await runner.scan_once(now=TS) == []
        assert runner.stats.trades_attempted == 0

    async def test_records_a_trade_log(self):
        runner = self.make_runner()
        runner.observe(book("kalshi:MAR", bid=40, ask=42, size=100))
        runner.observe(book("kalshi:JUN", bid=33, ask=35, size=100))
        await runner.scan_once(now=TS)
        assert len(runner.trade_log) == 1
        entry = runner.trade_log[0]
        assert entry["constraint"] == "monotone_implication"
        assert entry["completed"] is True
        assert entry["expected_profit_usd"] > 0

    async def test_status_is_serialisable_for_the_dashboard(self):
        runner = self.make_runner()
        runner.observe(book("kalshi:MAR", bid=40, ask=42, size=100))
        runner.observe(book("kalshi:JUN", bid=33, ask=35, size=100))
        await runner.scan_once(now=TS)
        status = runner.status()
        import json

        json.dumps(status)  # must not raise
        assert status["strategy"]["trades_completed"] == 1
        assert "promotion" in status and "risk" in status


class TestPromotionGate:
    def test_blocks_a_strategy_with_too_few_trades(self):
        stats = StrategyStats("s", trades_completed=5, gross_pnl_pips=100_000)
        stats.first_trade_at = TS - timedelta(days=30)
        stats.last_trade_at = TS
        ready, blockers = PromotionGate().evaluate(stats)
        assert not ready
        assert any("completed trades" in b for b in blockers)

    def test_blocks_a_strategy_with_too_little_history(self):
        stats = StrategyStats("s", trades_completed=100, gross_pnl_pips=100_000,
                              trades_attempted=100)
        stats.first_trade_at = TS - timedelta(days=2)
        stats.last_trade_at = TS
        ready, blockers = PromotionGate().evaluate(stats)
        assert not ready
        assert any("days of history" in b for b in blockers)

    def test_blocks_a_strategy_that_is_not_profitable_after_fees(self):
        stats = StrategyStats("s", trades_completed=100, trades_attempted=100,
                              gross_pnl_pips=100_000, fees_pips=200_000)
        stats.first_trade_at = TS - timedelta(days=30)
        stats.last_trade_at = TS
        ready, blockers = PromotionGate().evaluate(stats)
        assert not ready
        assert any("net PnL" in b for b in blockers)

    def test_blocks_on_a_low_fill_rate(self):
        """Detected-but-unfillable opportunities are stale quotes, not edges."""
        stats = StrategyStats("s", trades_completed=60, trades_attempted=1000,
                              gross_pnl_pips=500_000)
        stats.first_trade_at = TS - timedelta(days=30)
        stats.last_trade_at = TS
        ready, blockers = PromotionGate().evaluate(stats)
        assert not ready
        assert any("fill rate" in b for b in blockers)

    def test_promotes_a_strategy_that_clears_every_bar(self):
        stats = StrategyStats("s", trades_completed=100, trades_attempted=120,
                              gross_pnl_pips=500_000, fees_pips=50_000)
        stats.first_trade_at = TS - timedelta(days=30)
        stats.last_trade_at = TS
        ready, blockers = PromotionGate().evaluate(stats)
        assert ready and blockers == []


class TestBacktester:
    async def test_replays_recorded_books_through_the_same_loop(self):
        scanner = ConstraintScanner(fee_models=FEES, min_profit_pips=0)
        scanner.add(MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"]))
        runner = TradingRunner(
            scanner=scanner,
            risk=RiskEngine(bankroll_pips=BANKROLL),
            executor=Executor({}, mode=ExecutionMode.BACKTEST),
        )
        books = []
        for i in range(10):
            ts = TS + timedelta(seconds=i)
            # A violation appears only on the fifth tick.
            mar_bid = 40 if i == 5 else 28
            books.append(book("kalshi:MAR", bid=mar_bid, ask=mar_bid + 2,
                              size=100, ts=ts))
            books.append(book("kalshi:JUN", bid=33, ask=35, size=100, ts=ts))

        report = await Backtester(runner).run(books)
        assert report["books_replayed"] == 20
        assert report["strategy"]["trades_completed"] == 1

    async def test_batches_same_timestamp_books_before_scanning(self):
        """A constraint spanning markets cannot be judged on a half-updated view."""
        scanner = ConstraintScanner(fee_models=FEES, min_profit_pips=0)
        scanner.add(MonotoneConstraint(["kalshi:MAR", "kalshi:JUN"]))
        runner = TradingRunner(
            scanner=scanner,
            risk=RiskEngine(bankroll_pips=BANKROLL),
            executor=Executor({}, mode=ExecutionMode.BACKTEST),
        )
        books = [
            book("kalshi:MAR", bid=40, ask=42, size=100, ts=TS),
            book("kalshi:JUN", bid=33, ask=35, size=100, ts=TS),
        ]
        report = await Backtester(runner).run(books)
        assert report["strategy"]["trades_completed"] == 1

    async def test_empty_replay_is_safe(self):
        runner = TradingRunner(
            scanner=ConstraintScanner(fee_models=FEES),
            risk=RiskEngine(bankroll_pips=BANKROLL),
            executor=Executor({}, mode=ExecutionMode.BACKTEST),
        )
        report = await Backtester(runner).run([])
        assert report["books_replayed"] == 0
        assert report["window"] is None
