"""End-to-end integration.

Exercises the real path a deployment takes — discover constraints from a market
universe, record ticks, detect a violation, risk-check it, execute it, and
serve the result to the dashboard — with only the venue replaced by a fake.

The purpose is to catch the failures that unit tests structurally cannot: a
component whose contract changed underneath its neighbour, state that does not
survive the round trip, or a status payload the dashboard cannot render.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from orbit.api.server import create_app, state
from orbit.config import Settings
from orbit.core.fees import KalshiFees, PolymarketFees
from orbit.core.money import cents_to_pips
from orbit.core.types import Market, MarketStatus, Venue
from orbit.data.store import TickStore
from orbit.engine.executor import ExecutionMode, Executor
from orbit.engine.runner import Backtester, TradingRunner
from orbit.risk.engine import RiskEngine, RiskLimits
from orbit.strategies.constraints import ConstraintScanner
from orbit.strategies.discovery import build_constraints_for
from orbit.venues.base import normalize_two_sided_book

FEES = {"kalshi": KalshiFees(), "polymarket": PolymarketFees()}
TS = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
BANKROLL = 50_000_000  # $5,000


def c(cents: int) -> int:
    return cents_to_pips(cents)


def ladder_markets() -> list[Market]:
    """A three-rung temperature threshold ladder, as Kalshi lists them."""
    return [
        Market(
            venue=Venue.KALSHI,
            venue_id=f"KXHIGHNY-26JUL30-T{strike}",
            title=f"NYC high above {strike}F",
            event_key="KXHIGHNY-26JUL30",
            status=MarketStatus.ACTIVE,
            close_time=TS + timedelta(hours=6),
        )
        for strike in (70, 75, 80)
    ]


def book(key, bid, ask, size=200, ts=TS):
    return normalize_two_sided_book(
        market_key=key,
        timestamp=ts,
        bids=[(c(bid), size)],
        asks=[(c(ask), size)],
    )


def build_runner(mode=ExecutionMode.PAPER, store=None, limits=None):
    scanner = ConstraintScanner(
        fee_models=FEES, min_profit_pips=100, max_size=500
    )
    for constraint in build_constraints_for(ladder_markets()):
        scanner.add(constraint)
    return TradingRunner(
        scanner=scanner,
        risk=RiskEngine(limits or RiskLimits(), bankroll_pips=BANKROLL),
        executor=Executor({}, mode=mode),
        store=store,
    )


class TestDiscoveryToExecution:
    def test_discovery_produces_a_working_constraint_set(self):
        """Three rungs: 3 parity + C(3,2)=3 ladder constraints."""
        constraints = build_constraints_for(ladder_markets())
        assert len(constraints) == 6

    async def test_consistent_prices_produce_no_trades(self):
        """A well-behaved ladder must be left alone."""
        runner = build_runner()
        # Higher strike = less likely = cheaper. Correct ordering.
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T80", 20, 22))
        assert await runner.scan_once(now=TS) == []
        assert runner.stats.trades_attempted == 0

    async def test_an_inverted_rung_is_detected_and_traded(self):
        """T80 bidding above T70's ask is logically impossible."""
        runner = build_runner()
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T80", 70, 72))

        # Both T80/T75 (28c) and T80/T70 (8c) are violated. The scanner ranks
        # by return on capital, so the richer pair is taken first; the second
        # is then correctly declined because T80 exposure is already at its
        # per-market limit.
        found = runner.scanner.scan(runner.books)
        assert len(found) == 2
        assert found[0].return_on_capital > found[1].return_on_capital

        acted = await runner.scan_once(now=TS)
        assert acted, "an inverted ladder must be detected"
        assert runner.stats.trades_completed >= 1
        assert runner.stats.net_pnl_pips > 0

        # Whatever pair is chosen, T80 is the overpriced narrow leg and must
        # be sold, with a broader rung bought against it.
        legs = {leg.market_key: leg.side.value for leg in acted[0].legs}
        assert legs["kalshi:KXHIGHNY-26JUL30-T80"] == "sell"
        assert set(legs.values()) == {"sell", "buy"}

    async def test_profit_is_guaranteed_across_every_resolution(self):
        """Independently verify the executed position cannot lose."""
        runner = build_runner()
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T80", 70, 72))
        acted = await runner.scan_once(now=TS)

        opp = acted[0]
        narrow, broad = (leg for leg in opp.legs)
        if narrow.side.value != "sell":
            narrow, broad = broad, narrow

        # A implies B, so (narrow=True, broad=False) is impossible. Check the
        # three states that are, from first principles rather than via the
        # class under test.
        for narrow_yes, broad_yes in ((False, False), (False, True), (True, True)):
            total = (
                narrow.payoff_pips(narrow_yes)
                + broad.payoff_pips(broad_yes)
                - opp.total_fees_pips
            )
            assert total > 0, f"loses when narrow={narrow_yes} broad={broad_yes}"

    async def test_risk_limits_bind_end_to_end(self):
        """A tiny account must decline a trade it cannot collateralise."""
        runner = build_runner(limits=RiskLimits(max_market_fraction=0.0001))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T80", 70, 72))
        assert await runner.scan_once(now=TS) == []
        assert runner.stats.trades_completed == 0


class TestRecordThenBacktest:
    async def test_recorded_ticks_replay_through_the_strategy(self):
        """The full archive loop: record to Parquet, read back, replay, profit."""
        with tempfile.TemporaryDirectory() as tmp:
            store = TickStore(tmp, flush_rows=10_000, flush_seconds=1e9)

            # Record 20 ticks; the ladder inverts on tick 10.
            for i in range(20):
                ts = TS + timedelta(seconds=i)
                t80_bid = 70 if i == 10 else 20
                store.record_book(book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62, ts=ts))
                store.record_book(book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42, ts=ts))
                store.record_book(
                    book("kalshi:KXHIGHNY-26JUL30-T80", t80_bid, t80_bid + 2, ts=ts)
                )
            store.flush()

            replayed = list(store.read_books())
            assert len(replayed) == 60

            runner = build_runner(mode=ExecutionMode.BACKTEST)
            report = await Backtester(runner).run(replayed)

            assert report["books_replayed"] == 60
            assert report["strategy"]["trades_completed"] == 1, (
                "exactly one violation existed in the recorded window"
            )
            assert report["strategy"]["net_pnl_usd"] > 0

    async def test_backtest_and_paper_agree_on_the_same_data(self):
        """Same books, same fill model, same result — the point of one code path."""
        books = [
            book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62),
            book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42),
            book("kalshi:KXHIGHNY-26JUL30-T80", 70, 72),
        ]
        bt = build_runner(mode=ExecutionMode.BACKTEST)
        report = await Backtester(bt).run(books)

        paper = build_runner(mode=ExecutionMode.PAPER)
        for b in books:
            paper.observe(b)
        await paper.scan_once(now=TS)

        assert (
            report["strategy"]["net_pnl_usd"] == paper.stats.net_pnl_pips / 10_000
        )


class TestDashboardIntegration:
    @pytest.fixture
    def client(self):
        settings = Settings(api_token="test-token", _env_file=None)
        runner = build_runner()
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T70", 60, 62))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T75", 40, 42))
        runner.observe(book("kalshi:KXHIGHNY-26JUL30-T80", 70, 72))
        state.runner = runner
        state.settings = settings
        state.recorder = None
        yield TestClient(create_app())
        state.runner = None
        state.settings = None

    def test_health_needs_no_token(self):
        client = TestClient(create_app())
        assert client.get("/health").status_code == 200

    def test_every_data_route_rejects_a_missing_token(self, client):
        for path in ("/api/status", "/api/positions", "/api/trades",
                     "/api/opportunities", "/api/funding"):
            assert client.get(path).status_code == 401, path

    def test_wrong_token_is_rejected(self, client):
        r = client.get("/api/status", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_status_payload_is_json_serialisable(self, client):
        r = client.get("/api/status", headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200
        json.dumps(r.json())  # the dashboard has to render this
        assert "risk" in r.json()

    def test_opportunities_are_visible_before_any_trade(self, client):
        """Day-one signal: is the strategy finding anything at all?"""
        r = client.get(
            "/api/opportunities", headers={"Authorization": "Bearer test-token"}
        )
        assert r.status_code == 200
        assert r.json()["opportunities"], "the inverted ladder should be listed"

    async def test_kill_switch_halts_trading_through_the_api(self, client):
        headers = {"Authorization": "Bearer test-token"}
        r = client.post("/api/kill?reason=test", headers=headers)
        assert r.status_code == 200 and r.json()["killed"]

        runner = state.runner
        assert runner.risk.kill.is_tripped
        assert await runner.scan_once(now=TS) == []

        # Resume requires naming a human.
        assert client.post("/api/resume", headers=headers).status_code == 422
        r = client.post("/api/resume?acknowledged_by=tester", headers=headers)
        assert r.status_code == 200
        assert not runner.risk.kill.is_tripped

    def test_funding_reports_balances_and_manual_instructions(self, client):
        r = client.get("/api/funding", headers={"Authorization": "Bearer test-token"})
        body = r.json()
        assert "deposit" in body["instructions"]
        assert "withdraw" in body["instructions"]
        assert body["configured_bankroll_usd"] == 5000.0

    def test_dashboard_page_renders(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Orbit" in r.text
        assert "KILL SWITCH" in r.text

    def test_openapi_is_not_exposed(self, client):
        """The route list includes the kill switch; it is not public."""
        assert client.get("/openapi.json").status_code == 404


class TestSafetyDefaults:
    def test_default_configuration_cannot_trade_real_money(self):
        settings = Settings(_env_file=None)
        assert not settings.is_live
        assert settings.mode == "paper"
        assert not settings.trading_enabled
        assert settings.use_demo_endpoints

    def test_live_mode_rejects_demo_endpoints(self):
        with pytest.raises(ValueError, match="use_demo_endpoints"):
            Settings(
                _env_file=None,
                mode="live",
                trading_enabled=True,
                use_demo_endpoints=True,
                kalshi_key_id="k",
                api_token="t",
            )

    def test_live_mode_requires_credentials(self):
        with pytest.raises(ValueError, match="no venue credentials"):
            Settings(
                _env_file=None,
                mode="live",
                trading_enabled=True,
                use_demo_endpoints=False,
                api_token="t",
            )

    def test_live_mode_requires_an_api_token(self):
        """Otherwise the kill switch would be unauthenticated."""
        with pytest.raises(ValueError, match="API_TOKEN"):
            Settings(
                _env_file=None,
                mode="live",
                trading_enabled=True,
                use_demo_endpoints=False,
                kalshi_key_id="k",
                kalshi_private_key_path="/tmp/k.pem",
            )

    def test_reckless_kelly_is_rejected(self):
        with pytest.raises(ValueError, match="risks ruin"):
            Settings(_env_file=None, kelly_fraction=0.9)
