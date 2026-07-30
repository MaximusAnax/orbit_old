"""Risk engine and kill switch.

Every order in the system passes through :meth:`RiskEngine.check`. Strategies
propose; risk disposes. That separation exists so no strategy — including one
written later, in a hurry, at 2am — can bypass a limit by constructing an
order directly.

The design assumption is that **something will go wrong**: a model will be
miscalibrated, a feed will go stale while looking healthy, a venue will report
a fill twice, a loop will fire a thousand orders. The engine's job is to bound
the damage from failures nobody predicted, which is why the checks are mostly
about *state* (how much is deployed, how fast are we trading, how old is the
data) rather than about whether a given trade looks smart.

The kill switch is deliberately one-way. Automatic re-enabling after a
cooldown is how a bug that lost money once loses it repeatedly overnight.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from orbit.core.money import PIPS_PER_DOLLAR, format_usd
from orbit.core.types import Fill, OrderRequest, Position, Signal
from orbit.risk.sizing import correlated_kelly_scale

log = structlog.get_logger(__name__)


class RiskDecision(StrEnum):
    ALLOW = "allow"
    REDUCE = "reduce"
    REJECT = "reject"


@dataclass(frozen=True)
class RiskVerdict:
    """The engine's answer, always with a reason attached."""

    decision: RiskDecision
    approved_size: int
    reason: str
    checks_failed: tuple[str, ...] = ()

    @property
    def is_allowed(self) -> bool:
        return self.decision is not RiskDecision.REJECT and self.approved_size > 0


@dataclass
class RiskLimits:
    """Hard bounds. Defaults are tuned for a $5k account.

    These are intentionally tight. The cost of limits that are too tight is
    foregone profit that shows up in the logs as a ``binding_constraint``; the
    cost of limits that are too loose is discovered only once.
    """

    #: Total capital the system may deploy, as a fraction of bankroll. The
    #: remainder is the buffer that keeps a settlement surprise from
    #: cascading into forced liquidation.
    max_deployed_fraction: float = 0.60
    #: Most capital in any single market.
    max_market_fraction: float = 0.10
    #: Most capital across all markets sharing an ``event_key``. This is the
    #: limit that actually protects the account: ten "independent" positions
    #: on one election are one position.
    max_event_fraction: float = 0.20
    #: Most capital on one venue. Bounds venue-specific failure — a frozen
    #: withdrawal or a resolution dispute — not just market risk.
    max_venue_fraction: float = 0.70
    #: Daily realised loss that halts trading, as a fraction of day-start equity.
    max_daily_loss_fraction: float = 0.05
    #: Peak-to-trough drawdown that trips the kill switch permanently.
    max_drawdown_fraction: float = 0.15
    #: Order rate ceiling. A runaway loop is bounded by this, not by hope.
    max_orders_per_minute: int = 60
    #: Refuse to act on market data older than this. Trading a stale book is
    #: how a bot buys into news it has not seen yet.
    max_data_staleness_s: float = 10.0
    #: Assumed pairwise correlation between markets in one event.
    intra_event_correlation: float = 0.7
    #: Minimum order size. Kalshi's per-order fee ceiling makes one-lots a
    #: guaranteed loss at mid-book.
    min_order_size: int = 5


@dataclass
class RiskState:
    """Live risk state, rebuilt from fills and reconciled against the venue."""

    bankroll_pips: int
    day_start_equity_pips: int
    peak_equity_pips: int
    realized_pnl_today_pips: int = 0
    positions: dict[str, Position] = field(default_factory=dict)
    #: market_key -> event_key, for correlation grouping.
    event_of: dict[str, str] = field(default_factory=dict)
    order_times: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    seen_client_ids: set[str] = field(default_factory=set)
    day: datetime = field(default_factory=lambda: datetime.now(UTC))

    def deployed_pips(self) -> int:
        return sum(p.collateral_pips() for p in self.positions.values())

    def market_exposure_pips(self, market_key: str) -> int:
        pos = self.positions.get(market_key)
        return pos.collateral_pips() if pos else 0

    def event_exposure_pips(self, event_key: str) -> int:
        return sum(
            p.collateral_pips()
            for k, p in self.positions.items()
            if self.event_of.get(k) == event_key
        )

    def venue_exposure_pips(self, venue: str) -> int:
        return sum(
            p.collateral_pips()
            for k, p in self.positions.items()
            if k.split(":", 1)[0] == venue
        )

    def positions_in_event(self, event_key: str) -> int:
        return sum(
            1
            for k, p in self.positions.items()
            if self.event_of.get(k) == event_key and not p.is_flat
        )

    def equity_pips(self) -> int:
        """Cash plus the cost basis of open positions.

        Positions are valued **at cost, not at market**. Marking a thin
        prediction-market book to its own mid makes equity jump on a single
        stale quote, and a drawdown limit keyed to that would trip on noise
        rather than on losses.

        Including the cost basis is what makes deploying capital
        equity-neutral, and it is not optional. Cash alone falls by the price
        paid when opening a long and rises by the premium when opening a
        short, so an equity figure of cash alone treats *every* new position as
        an instant profit or loss. With cash-only equity, deploying 30% of the
        account registered as a 30% drawdown and tripped the kill switch on the
        first normal-sized trade.

        Adding the basis cancels that exactly: a long costs cash and adds a
        positive basis, a short receives cash and adds a negative one, so only
        realised PnL and fees move equity — which is precisely what the
        drawdown and daily-loss limits are meant to measure.
        """
        return self.bankroll_pips + sum(
            p.cost_basis_pips for p in self.positions.values()
        )

    def drawdown_fraction(self) -> float:
        if self.peak_equity_pips <= 0:
            return 0.0
        return max(
            0.0,
            (self.peak_equity_pips - self.equity_pips()) / self.peak_equity_pips,
        )

    def daily_loss_fraction(self) -> float:
        if self.day_start_equity_pips <= 0:
            return 0.0
        return max(
            0.0, -self.realized_pnl_today_pips / self.day_start_equity_pips
        )


class KillSwitch:
    """One-way trading halt.

    Tripping is cheap and reversible by a human; not tripping when you should
    have is neither. Re-arming is intentionally manual.
    """

    def __init__(self) -> None:
        self._tripped = False
        self._reason: str | None = None
        self._tripped_at: datetime | None = None

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def reason(self) -> str | None:
        return self._reason

    def trip(self, reason: str) -> None:
        if self._tripped:
            return
        self._tripped = True
        self._reason = reason
        self._tripped_at = datetime.now(UTC)
        log.critical("killswitch.tripped", reason=reason)

    def reset(self, *, acknowledged_by: str) -> None:
        """Re-arm trading. Requires a named human, recorded in the log."""
        log.warning(
            "killswitch.reset", by=acknowledged_by, previous_reason=self._reason
        )
        self._tripped = False
        self._reason = None
        self._tripped_at = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tripped": self._tripped,
            "reason": self._reason,
            "tripped_at": self._tripped_at.isoformat() if self._tripped_at else None,
        }


class RiskEngine:
    """Pre-trade checks, exposure tracking and automatic halts."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        *,
        bankroll_pips: int,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.kill = kill_switch or KillSwitch()
        self.state = RiskState(
            bankroll_pips=bankroll_pips,
            day_start_equity_pips=bankroll_pips,
            peak_equity_pips=bankroll_pips,
        )

    # -- pre-trade ----------------------------------------------------------

    def check(
        self,
        request: OrderRequest,
        *,
        event_key: str | None = None,
        data_age_s: float | None = None,
    ) -> RiskVerdict:
        """Approve, shrink, or reject an order.

        Checks run in order of severity: absolute halts first, then
        idempotency, then exposure limits which may merely reduce size.
        """
        failed: list[str] = []

        if self.kill.is_tripped:
            return RiskVerdict(
                RiskDecision.REJECT, 0, f"kill switch: {self.kill.reason}",
                ("kill_switch",),
            )

        # Idempotency. A retry after a network timeout must never double-fill.
        if request.client_order_id in self.state.seen_client_ids:
            return RiskVerdict(
                RiskDecision.REJECT, 0,
                f"duplicate client_order_id {request.client_order_id}",
                ("duplicate_order",),
            )

        if data_age_s is not None and data_age_s > self.limits.max_data_staleness_s:
            return RiskVerdict(
                RiskDecision.REJECT, 0,
                f"market data {data_age_s:.1f}s stale "
                f"(limit {self.limits.max_data_staleness_s}s)",
                ("stale_data",),
            )

        if self._order_rate_exceeded():
            return RiskVerdict(
                RiskDecision.REJECT, 0,
                f"order rate above {self.limits.max_orders_per_minute}/min",
                ("order_rate",),
            )

        if self.state.daily_loss_fraction() >= self.limits.max_daily_loss_fraction:
            self.kill.trip(
                f"daily loss {self.state.daily_loss_fraction():.1%} hit limit"
            )
            return RiskVerdict(
                RiskDecision.REJECT, 0, "daily loss limit", ("daily_loss",)
            )

        if self.state.drawdown_fraction() >= self.limits.max_drawdown_fraction:
            self.kill.trip(
                f"drawdown {self.state.drawdown_fraction():.1%} hit limit"
            )
            return RiskVerdict(
                RiskDecision.REJECT, 0, "max drawdown", ("drawdown",)
            )

        # -- exposure limits: these reduce rather than reject ---------------
        bankroll = self.state.bankroll_pips
        if bankroll <= 0:
            return RiskVerdict(RiskDecision.REJECT, 0, "no bankroll", ("bankroll",))

        per_contract = request.max_cost_pips // max(1, request.size)
        if per_contract <= 0:
            return RiskVerdict(
                RiskDecision.REJECT, 0, "degenerate price", ("price",)
            )

        allowed = request.size

        def cap(budget_pips: int, name: str) -> int:
            nonlocal allowed
            room = max(0, budget_pips) // per_contract
            if room < allowed:
                failed.append(name)
                allowed = room
            return allowed

        cap(
            int(bankroll * self.limits.max_deployed_fraction)
            - self.state.deployed_pips(),
            "total_deployed",
        )
        cap(
            int(bankroll * self.limits.max_market_fraction)
            - self.state.market_exposure_pips(request.market_key),
            "market_limit",
        )
        venue = request.market_key.split(":", 1)[0]
        cap(
            int(bankroll * self.limits.max_venue_fraction)
            - self.state.venue_exposure_pips(venue),
            "venue_limit",
        )

        if event_key:
            event_budget = int(bankroll * self.limits.max_event_fraction)
            # Shrink the event budget by the correlation penalty: N positions
            # on one event behave like far fewer independent bets.
            n = self.state.positions_in_event(event_key) + 1
            scale = correlated_kelly_scale(
                n, rho=self.limits.intra_event_correlation
            )
            cap(
                int(event_budget * scale) - self.state.event_exposure_pips(event_key),
                "event_limit",
            )

        if allowed <= 0:
            return RiskVerdict(
                RiskDecision.REJECT, 0,
                f"no room under {failed[0] if failed else 'limits'}",
                tuple(failed),
            )

        if allowed < self.limits.min_order_size:
            return RiskVerdict(
                RiskDecision.REJECT, 0,
                f"remaining room ({allowed}) below min order size "
                f"({self.limits.min_order_size}); fees would exceed the edge",
                (*failed, "min_size"),
            )

        if allowed < request.size:
            return RiskVerdict(
                RiskDecision.REDUCE, allowed,
                f"reduced {request.size}->{allowed} by {failed[0]}",
                tuple(failed),
            )
        return RiskVerdict(RiskDecision.ALLOW, allowed, "ok")

    def check_signal(
        self, signal: Signal, *, event_key: str | None = None,
        data_age_s: float | None = None,
    ) -> RiskVerdict:
        """Convenience wrapper for the strategy path."""
        request = OrderRequest(
            market_key=signal.market_key,
            side=signal.side,
            size=signal.desired_size,
            price_pips=signal.limit_pips,
            strategy_id=signal.strategy_id,
            rationale=signal.rationale,
        )
        return self.check(request, event_key=event_key, data_age_s=data_age_s)

    def _order_rate_exceeded(self) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        while self.state.order_times and self.state.order_times[0] < cutoff:
            self.state.order_times.popleft()
        return len(self.state.order_times) >= self.limits.max_orders_per_minute

    # -- state updates ------------------------------------------------------

    def record_order(self, request: OrderRequest) -> None:
        """Note that an order was sent. Feeds rate limiting and idempotency."""
        self.state.order_times.append(time.monotonic())
        self.state.seen_client_ids.add(request.client_order_id)

    def record_fill(self, fill: Fill, *, event_key: str | None = None) -> None:
        """Apply a fill to risk state and re-evaluate the automatic halts."""
        pos = self.state.positions.setdefault(
            fill.market_key, Position(market_key=fill.market_key)
        )
        before = pos.realized_pnl_pips
        pos.apply_fill(fill)
        self.state.realized_pnl_today_pips += pos.realized_pnl_pips - before
        self.state.bankroll_pips += fill.cash_delta_pips
        if event_key:
            self.state.event_of[fill.market_key] = event_key

        self.state.peak_equity_pips = max(
            self.state.peak_equity_pips, self.state.equity_pips()
        )
        self._check_automatic_halts()

    def record_settlement(self, market_key: str, *, settled_yes: bool) -> int:
        """Settle a position and fold the result into today's PnL."""
        pos = self.state.positions.get(market_key)
        if pos is None or pos.is_flat:
            return 0
        # Cash moves by the settlement payout only. The premium or price paid
        # already moved cash when the position opened, so adding collateral
        # back on top would double-count it — and would be wrong in opposite
        # directions for longs and shorts. Equity still changes by exactly the
        # PnL, because the position's cost basis leaves the book at the same
        # time.
        payout_pips = pos.size * (PIPS_PER_DOLLAR if settled_yes else 0)
        pnl = pos.settle(settled_yes=settled_yes)
        self.state.realized_pnl_today_pips += pnl
        self.state.bankroll_pips += payout_pips
        self.state.positions.pop(market_key, None)
        self.state.peak_equity_pips = max(
            self.state.peak_equity_pips, self.state.equity_pips()
        )
        self._check_automatic_halts()
        return pnl

    def _check_automatic_halts(self) -> None:
        dd = self.state.drawdown_fraction()
        if dd >= self.limits.max_drawdown_fraction:
            self.kill.trip(f"drawdown {dd:.1%} exceeded limit")
        loss = self.state.daily_loss_fraction()
        if loss >= self.limits.max_daily_loss_fraction:
            self.kill.trip(f"daily loss {loss:.1%} exceeded limit")

    def roll_day(self) -> None:
        """Reset daily counters. Drawdown deliberately survives the roll."""
        self.state.day_start_equity_pips = self.state.equity_pips()
        self.state.realized_pnl_today_pips = 0
        self.state.day = datetime.now(UTC)
        self.state.seen_client_ids.clear()
        log.info(
            "risk.day_rolled", equity=format_usd(self.state.equity_pips())
        )

    def reconcile(self, venue_positions: list[Position]) -> list[str]:
        """Compare internal state to the venue's and report every mismatch.

        Divergence between what we think we hold and what the exchange thinks
        we hold is the precondition for every large unexplained loss. This is
        run on a schedule, and a non-empty result should page a human.
        """
        problems: list[str] = []
        venue_by_key = {p.market_key: p for p in venue_positions}
        for key in set(venue_by_key) | set(self.state.positions):
            ours = self.state.positions.get(key)
            theirs = venue_by_key.get(key)
            our_size = ours.size if ours else 0
            their_size = theirs.size if theirs else 0
            if our_size != their_size:
                problems.append(
                    f"{key}: local {our_size} != venue {their_size}"
                )
        if problems:
            log.error("risk.reconciliation_failed", problems=problems)
        return problems

    # -- reporting ----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Everything the dashboard needs to show current risk utilisation."""
        s, lim = self.state, self.limits
        bankroll = max(1, s.bankroll_pips)
        return {
            "bankroll_usd": s.bankroll_pips / 10_000,
            "deployed_usd": s.deployed_pips() / 10_000,
            "deployed_fraction": s.deployed_pips() / bankroll,
            "deployed_limit": lim.max_deployed_fraction,
            "realized_pnl_today_usd": s.realized_pnl_today_pips / 10_000,
            "daily_loss_fraction": s.daily_loss_fraction(),
            "daily_loss_limit": lim.max_daily_loss_fraction,
            "drawdown_fraction": s.drawdown_fraction(),
            "drawdown_limit": lim.max_drawdown_fraction,
            "peak_equity_usd": s.peak_equity_pips / 10_000,
            "open_positions": sum(1 for p in s.positions.values() if not p.is_flat),
            "orders_last_minute": len(s.order_times),
            "kill_switch": self.kill.as_dict(),
        }

    def utilisation(self) -> dict[str, float]:
        """Each limit as a fraction of itself, for dashboard gauges."""
        s, lim = self.state, self.limits
        bankroll = max(1, s.bankroll_pips)
        return {
            "deployed": (s.deployed_pips() / bankroll) / lim.max_deployed_fraction,
            "daily_loss": s.daily_loss_fraction() / lim.max_daily_loss_fraction,
            "drawdown": s.drawdown_fraction() / lim.max_drawdown_fraction,
            "order_rate": len(s.order_times) / lim.max_orders_per_minute,
        }
