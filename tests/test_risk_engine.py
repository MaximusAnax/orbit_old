"""Risk engine behaviour.

These tests encode the failures the engine exists to survive: a runaway order
loop, a stale feed, a duplicated retry, a correlated book that looks
diversified, and a drawdown that should stop trading permanently rather than
politely.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from orbit.core.money import cents_to_pips
from orbit.core.types import Fill, OrderRequest, Position, Side
from orbit.risk.engine import (
    KillSwitch,
    RiskDecision,
    RiskEngine,
    RiskLimits,
)

BANKROLL = 50_000_000  # $5,000


def c(cents: int) -> int:
    return cents_to_pips(cents)


def req(market="kalshi:A", side=Side.BUY, size=100, cents=50, **kw) -> OrderRequest:
    return OrderRequest(
        market_key=market, side=side, size=size, price_pips=c(cents), **kw
    )


def fill(market="kalshi:A", side=Side.BUY, size=100, cents=50, fee=0) -> Fill:
    return Fill(
        market_key=market,
        timestamp=datetime.now(UTC),
        side=side,
        size=size,
        price_pips=c(cents),
        fee_pips=fee,
        liquidity="taker",
        order_id="o",
        client_order_id="c",
    )


@pytest.fixture
def engine():
    return RiskEngine(bankroll_pips=BANKROLL)


class TestKillSwitch:
    def test_blocks_everything_once_tripped(self, engine):
        engine.kill.trip("manual")
        v = engine.check(req())
        assert v.decision is RiskDecision.REJECT
        assert "kill switch" in v.reason

    def test_is_one_way_until_a_human_resets_it(self, engine):
        """No timer re-arms it. A bug that lost money once must not repeat."""
        engine.kill.trip("bad model")
        assert engine.kill.is_tripped
        engine.kill.trip("something else")
        assert engine.kill.reason == "bad model", "first reason is preserved"
        engine.kill.reset(acknowledged_by="operator")
        assert not engine.kill.is_tripped
        assert engine.check(req()).is_allowed

    def test_trips_on_drawdown(self, engine):
        engine.state.peak_equity_pips = BANKROLL
        engine.state.bankroll_pips = int(BANKROLL * 0.80)  # -20%
        engine._check_automatic_halts()
        assert engine.kill.is_tripped
        assert "drawdown" in engine.kill.reason

    def test_trips_on_daily_loss(self, engine):
        engine.state.realized_pnl_today_pips = -int(BANKROLL * 0.06)
        engine._check_automatic_halts()
        assert engine.kill.is_tripped
        assert "daily loss" in engine.kill.reason

    def test_does_not_trip_below_the_limits(self, engine):
        engine.state.realized_pnl_today_pips = -int(BANKROLL * 0.01)
        engine.state.bankroll_pips = int(BANKROLL * 0.99)
        engine._check_automatic_halts()
        assert not engine.kill.is_tripped


class TestIdempotency:
    def test_duplicate_client_order_id_is_rejected(self, engine):
        """A retry after a network timeout must never double-fill."""
        order = req()
        assert engine.check(order).is_allowed
        engine.record_order(order)
        v = engine.check(order)
        assert v.decision is RiskDecision.REJECT
        assert "duplicate" in v.reason


class TestStaleData:
    def test_rejects_stale_books(self, engine):
        v = engine.check(req(), data_age_s=30.0)
        assert v.decision is RiskDecision.REJECT
        assert "stale" in v.reason

    def test_allows_fresh_books(self, engine):
        assert engine.check(req(), data_age_s=0.5).is_allowed


class TestOrderRate:
    def test_runaway_loop_is_bounded(self, engine):
        limits = RiskLimits(max_orders_per_minute=10)
        eng = RiskEngine(limits, bankroll_pips=BANKROLL)
        for i in range(10):
            order = req(size=5, client_order_id=f"id-{i}")
            assert eng.check(order).is_allowed
            eng.record_order(order)
        v = eng.check(req(size=5, client_order_id="id-overflow"))
        assert v.decision is RiskDecision.REJECT
        assert "order rate" in v.reason


class TestExposureLimits:
    def test_reduces_rather_than_rejects_when_near_a_limit(self, engine):
        """Partial capacity should trade smaller, not refuse."""
        engine.state.positions["kalshi:A"] = Position(
            market_key="kalshi:A", size=800, cost_basis_pips=800 * c(50)
        )
        v = engine.check(req(size=1000))
        assert v.decision is RiskDecision.REDUCE
        assert 0 < v.approved_size < 1000
        assert "market_limit" in v.checks_failed

    def test_market_limit_caps_single_market_exposure(self, engine):
        # 10% of $5,000 = $500 -> 1000 contracts at 50c.
        v = engine.check(req(size=5000))
        assert v.approved_size <= 1000

    def test_total_deployed_limit(self, engine):
        engine.state.positions["kalshi:OTHER"] = Position(
            market_key="kalshi:OTHER", size=6000, cost_basis_pips=6000 * c(50)
        )
        v = engine.check(req(market="kalshi:A", size=1000))
        assert v.decision is RiskDecision.REJECT
        assert "total_deployed" in v.checks_failed

    def test_event_limit_treats_correlated_markets_as_one_bet(self, engine):
        """Ten markets on one election must not each get a full allocation."""
        for i in range(4):
            key = f"kalshi:ELECTION-{i}"
            engine.state.positions[key] = Position(
                market_key=key, size=200, cost_basis_pips=200 * c(50)
            )
            engine.state.event_of[key] = "ELECTION"
        v = engine.check(req(market="kalshi:ELECTION-9", size=1000),
                         event_key="ELECTION")
        assert v.approved_size < 1000
        assert "event_limit" in v.checks_failed

    def test_correlation_penalty_tightens_as_positions_accumulate(self, engine):
        """Each additional position on one event shrinks the event budget.

        The per-market limit is relaxed here so the *event* limit is the
        binding one; otherwise the market cap masks the effect being tested.
        """
        limits = RiskLimits(max_market_fraction=1.0, max_deployed_fraction=1.0)

        def room_with(n: int) -> int:
            eng = RiskEngine(limits, bankroll_pips=BANKROLL)
            for i in range(n):
                key = f"kalshi:E-{i}"
                # Negligible existing exposure, so the difference measured is
                # the correlation scale rather than capital already used.
                eng.state.positions[key] = Position(market_key=key, size=1,
                                                    cost_basis_pips=c(50))
                eng.state.event_of[key] = "E"
            return eng.check(req(market="kalshi:E-new", size=100_000),
                             event_key="E").approved_size

        assert room_with(1) > room_with(4) > room_with(9)

    def test_market_cap_binds_before_the_event_cap_by_default(self, engine):
        """With default limits, no single market can consume the event budget."""
        v = engine.check(req(market="kalshi:E-0", size=100_000), event_key="E")
        assert "market_limit" in v.checks_failed

    def test_venue_limit(self, engine):
        engine.state.positions["kalshi:X"] = Position(
            market_key="kalshi:X", size=7000, cost_basis_pips=7000 * c(50)
        )
        v = engine.check(req(market="kalshi:A", size=500))
        assert not v.is_allowed or "venue_limit" in v.checks_failed

    def test_rejects_when_room_is_below_min_order_size(self, engine):
        """Tiny remaining room is worse than nothing: fees exceed the edge."""
        limits = RiskLimits(min_order_size=50)
        eng = RiskEngine(limits, bankroll_pips=BANKROLL)
        eng.state.positions["kalshi:A"] = Position(
            market_key="kalshi:A", size=990, cost_basis_pips=990 * c(50)
        )
        v = eng.check(req(size=1000))
        assert v.decision is RiskDecision.REJECT
        assert "min_size" in v.checks_failed


class TestStateTracking:
    def test_fill_updates_bankroll_and_exposure(self, engine):
        start = engine.state.bankroll_pips
        engine.record_fill(fill(size=100, cents=50, fee=17_500))
        assert engine.state.bankroll_pips == start - 100 * c(50) - 17_500
        assert engine.state.market_exposure_pips("kalshi:A") == 100 * c(50)

    def test_settlement_returns_collateral_and_profit(self, engine):
        start = engine.state.bankroll_pips
        engine.record_fill(fill(size=100, cents=40))
        assert engine.state.bankroll_pips == start - 100 * c(40)
        pnl = engine.record_settlement("kalshi:A", settled_yes=True)
        assert pnl == 100 * c(60)  # paid 40c, received $1
        assert engine.state.bankroll_pips == start + 100 * c(60)
        assert engine.state.deployed_pips() == 0

    def test_losing_settlement(self, engine):
        start = engine.state.bankroll_pips
        engine.record_fill(fill(size=100, cents=40))
        pnl = engine.record_settlement("kalshi:A", settled_yes=False)
        assert pnl == -100 * c(40)
        assert engine.state.bankroll_pips == start - 100 * c(40)

    def test_day_roll_clears_daily_loss_but_keeps_drawdown(self, engine):
        engine.state.realized_pnl_today_pips = -1_000_000
        engine.state.peak_equity_pips = BANKROLL * 2
        engine.roll_day()
        assert engine.state.realized_pnl_today_pips == 0
        assert engine.state.drawdown_fraction() > 0, "drawdown must survive the roll"


class TestReconciliation:
    def test_detects_a_size_mismatch(self, engine):
        engine.state.positions["kalshi:A"] = Position(market_key="kalshi:A", size=100)
        problems = engine.reconcile([Position(market_key="kalshi:A", size=90)])
        assert len(problems) == 1
        assert "local 100 != venue 90" in problems[0]

    def test_detects_a_position_we_do_not_know_about(self, engine):
        problems = engine.reconcile([Position(market_key="kalshi:GHOST", size=50)])
        assert len(problems) == 1
        assert "GHOST" in problems[0]

    def test_clean_when_state_agrees(self, engine):
        engine.state.positions["kalshi:A"] = Position(market_key="kalshi:A", size=100)
        assert engine.reconcile([Position(market_key="kalshi:A", size=100)]) == []


class TestReporting:
    def test_snapshot_has_what_the_dashboard_needs(self, engine):
        engine.record_fill(fill(size=100, cents=50))
        snap = engine.snapshot()
        for key in (
            "bankroll_usd", "deployed_usd", "deployed_fraction",
            "daily_loss_fraction", "drawdown_fraction", "open_positions",
            "kill_switch",
        ):
            assert key in snap
        assert snap["open_positions"] == 1

    def test_utilisation_is_a_fraction_of_each_limit(self, engine):
        engine.record_fill(fill(size=100, cents=50))
        util = engine.utilisation()
        assert all(v >= 0 for v in util.values())
        assert util["deployed"] > 0

    def test_kill_switch_state_is_serialisable(self):
        ks = KillSwitch()
        assert ks.as_dict()["tripped"] is False
        ks.trip("test")
        d = ks.as_dict()
        assert d["tripped"] is True and d["reason"] == "test"
        assert d["tripped_at"] is not None
