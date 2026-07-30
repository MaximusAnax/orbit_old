"""Position sizing.

Binary contracts make Kelly unusually clean — there are exactly two outcomes
and the price *is* the breakeven probability — which makes it tempting to use
full Kelly. That temptation is the fastest route to ruin in this system, for
one reason: Kelly assumes you know the true probability. You do not. You have
an estimate, and Kelly is brutally sensitive to error in it.

Overbetting is not symmetric with underbetting. Growth as a function of
stake is a downward parabola that peaks at full Kelly and returns to zero at
roughly *twice* it, so betting 2x Kelly earns nothing even when the edge is
completely real, and betting more loses money on a winning strategy. Staking
a fraction ``c`` of Kelly retains about ``c(2 - c)`` of the optimal growth
rate: half Kelly keeps ~75%, quarter Kelly ~44%. Giving up half the
theoretical growth to survive a materially wrong ``q`` is a good trade when
``q`` is an estimate, so this module defaults to a *quarter* Kelly and treats
it as a ceiling rather than a target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from orbit.core.fees import FeeModel, Liquidity
from orbit.core.money import PIPS_PER_DOLLAR, complement
from orbit.core.types import Side

#: Default Kelly multiplier. Quarter Kelly retains ~44% of the theoretical
#: growth rate for a large reduction in drawdown, and stays profitable even
#: when the probability estimate is well off.
DEFAULT_KELLY_FRACTION = 0.25


def kelly_fraction(*, price_pips: int, true_prob: float, side: Side) -> float:
    """Full-Kelly stake as a fraction of bankroll. May be negative.

    For a *buy* at price ``p`` with true probability ``q``, the contract stakes
    ``p`` to win ``1 - p``, giving odds ``b = (1 - p) / p``. Substituting into
    ``f* = (q·b - (1 - q)) / b`` collapses to::

        f* = (q - p) / (1 - p)

    For a *sell*, the position is symmetrically a purchase of the complement
    at ``1 - p`` with probability ``1 - q``::

        f* = (p - q) / p

    A negative result means the trade is on the wrong side of fair value; the
    caller should not "flip it" automatically, because a model confident enough
    to be wrong by that much is a model to distrust, not invert.
    """
    p = price_pips / PIPS_PER_DOLLAR
    q = max(0.0, min(1.0, true_prob))
    if side is Side.BUY:
        if p >= 1.0:
            return 0.0
        return (q - p) / (1.0 - p)
    if p <= 0.0:
        return 0.0
    return (p - q) / p


@dataclass(frozen=True)
class SizingResult:
    """A sizing decision and, importantly, why it came out that way."""

    size: int
    kelly_full: float
    kelly_applied: float
    capital_at_risk_pips: int
    expected_value_pips: int
    binding_constraint: str

    @property
    def is_actionable(self) -> bool:
        return self.size > 0


class PositionSizer:
    """Turns an edge into a contract count, or into an explanation of zero.

    Every reduction is attributed. When a strategy that backtested well trades
    tiny in production, the answer to "why" is in ``binding_constraint`` rather
    than in a debugging session.
    """

    def __init__(
        self,
        *,
        kelly_fraction_cap: float = DEFAULT_KELLY_FRACTION,
        max_fraction_per_trade: float = 0.05,
        min_edge_pips: int = 50,  # 0.5c of edge after fees, or don't bother
        confidence_floor: float = 0.2,
    ) -> None:
        if not 0 < kelly_fraction_cap <= 1.0:
            raise ValueError("kelly_fraction_cap must be in (0, 1]")
        self.kelly_fraction_cap = kelly_fraction_cap
        self.max_fraction_per_trade = max_fraction_per_trade
        self.min_edge_pips = min_edge_pips
        self.confidence_floor = confidence_floor

    def size(
        self,
        *,
        bankroll_pips: int,
        price_pips: int,
        true_prob: float,
        side: Side,
        confidence: float = 1.0,
        available_liquidity: int | None = None,
        max_contracts: int | None = None,
        fee_model: FeeModel | None = None,
    ) -> SizingResult:
        """Compute a contract count under every constraint at once."""
        collateral_per_contract = (
            price_pips if side is Side.BUY else complement(price_pips)
        )
        if collateral_per_contract <= 0 or bankroll_pips <= 0:
            return self._zero("no capital or degenerate price", price_pips, true_prob, side)

        full = kelly_fraction(price_pips=price_pips, true_prob=true_prob, side=side)
        if full <= 0:
            return self._zero("no edge at this price", price_pips, true_prob, side)

        # Confidence scales the bet *before* the Kelly cap, so an unsure model
        # is sized down rather than merely capped.
        scaled_confidence = max(0.0, min(1.0, confidence))
        if scaled_confidence < self.confidence_floor:
            return self._zero("confidence below floor", price_pips, true_prob, side)

        applied = min(full * self.kelly_fraction_cap * scaled_confidence,
                      self.max_fraction_per_trade)
        constraint = (
            "per-trade cap"
            if applied == self.max_fraction_per_trade
            else "fractional kelly"
        )

        budget_pips = int(bankroll_pips * applied)
        size = budget_pips // collateral_per_contract

        if available_liquidity is not None and size > available_liquidity:
            size, constraint = available_liquidity, "available liquidity"
        if max_contracts is not None and size > max_contracts:
            size, constraint = max_contracts, "position limit"
        if size <= 0:
            return self._zero("bankroll too small for one contract", price_pips, true_prob, side)

        # Gross edge per contract, then net of the fee actually charged at
        # this size — the per-order fee ceiling means small orders can be
        # fee-negative at an edge that is fine in size.
        edge_pips = self._edge_pips(price_pips, true_prob, side)
        gross = edge_pips * size
        fee = (
            fee_model.trade_fee_pips(
                price_pips=price_pips, size=size, liquidity=Liquidity.TAKER
            )
            if fee_model
            else 0
        )
        net = gross - fee
        if net <= 0 or edge_pips < self.min_edge_pips:
            return self._zero(
                "edge does not clear fees at any workable size",
                price_pips,
                true_prob,
                side,
            )

        return SizingResult(
            size=size,
            kelly_full=full,
            kelly_applied=applied,
            capital_at_risk_pips=size * collateral_per_contract,
            expected_value_pips=net,
            binding_constraint=constraint,
        )

    @staticmethod
    def _edge_pips(price_pips: int, true_prob: float, side: Side) -> int:
        fair = round(true_prob * PIPS_PER_DOLLAR)
        return fair - price_pips if side is Side.BUY else price_pips - fair

    def _zero(
        self, reason: str, price_pips: int, true_prob: float, side: Side
    ) -> SizingResult:
        return SizingResult(
            size=0,
            kelly_full=kelly_fraction(
                price_pips=price_pips, true_prob=true_prob, side=side
            ),
            kelly_applied=0.0,
            capital_at_risk_pips=0,
            expected_value_pips=0,
            binding_constraint=reason,
        )


def correlated_kelly_scale(n_correlated: int, *, rho: float = 0.7) -> float:
    """Shrink factor for ``n`` positions that share a risk driver.

    Prediction market books are far more correlated than they look. Ten
    contracts on the same election, or every temperature market on the same
    weather front, are close to one bet with ten names. Sizing each at
    "quarter Kelly" independently is really betting 2.5x Kelly on the
    underlying driver.

    For ``n`` equally-weighted bets with pairwise correlation ``rho``, the
    variance of the sum scales as ``n + n(n-1)rho`` rather than ``n``, so the
    per-position stake is divided by ``sqrt(1 + (n-1)rho)``. At rho=0.7 and n=5
    that is a 0.5x haircut — the difference between a bad week and a blown
    account.
    """
    if n_correlated <= 1:
        return 1.0
    rho = max(0.0, min(1.0, rho))
    return 1.0 / math.sqrt(1.0 + (n_correlated - 1) * rho)


def expected_growth_rate(*, price_pips: int, true_prob: float, side: Side,
                         fraction: float) -> float:
    """Long-run log growth rate for staking ``fraction`` of bankroll.

    Exposes the asymmetry that justifies fractional Kelly: this function
    peaks at full Kelly, returns to zero at *twice* full Kelly, and goes
    negative beyond. Underbetting costs a little growth; overbetting costs
    everything.
    """
    p = price_pips / PIPS_PER_DOLLAR
    q = max(0.0, min(1.0, true_prob))
    if side is Side.SELL:
        p, q = 1.0 - p, 1.0 - q
    if not 0.0 < p < 1.0 or fraction <= 0:
        return 0.0
    win_mult = 1.0 + fraction * (1.0 - p) / p
    lose_mult = 1.0 - fraction
    if win_mult <= 0 or lose_mult <= 0:
        return float("-inf")  # ruin is possible on a single loss
    return q * math.log(win_mult) + (1.0 - q) * math.log(lose_mult)
