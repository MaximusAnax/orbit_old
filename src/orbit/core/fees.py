"""Exact fee models.

Fees are the single most important number in prediction-market trading. A
1-cent spread on a $1 contract is a 1% gross edge; Kalshi's taker fee at
mid-book is 1.75 cents. Most strategies that look profitable on paper are
simply fee-negative, so the backtester and the live engine must share one
implementation of the fee math — this module — and it must be exact.

All fee functions take integer pip prices and return integer pips.

.. warning::
   Fee schedules change. Every schedule here carries an ``effective_date`` and
   a ``source`` URL. Re-verify before trusting a backtest that spans a change,
   and see ``docs/fees.md`` for the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol

from orbit.core.money import PIPS_PER_CENT, PIPS_PER_DOLLAR


class Liquidity(str, Enum):
    """Whether an execution added or removed liquidity.

    This distinction is worth real money: on Kalshi the general fee schedule
    charges takers and (on most series) leaves makers free, which is the entire
    economic basis for a passive quoting strategy.
    """

    MAKER = "maker"
    TAKER = "taker"


class FeeModel(Protocol):
    """Common interface so backtest and live paths cannot diverge."""

    def trade_fee_pips(self, *, price_pips: int, size: int, liquidity: Liquidity) -> int:
        """Fee in pips for executing ``size`` contracts at ``price_pips``."""
        ...

    def settlement_fee_pips(self, *, size: int, settled_yes: bool) -> int:
        """Fee in pips charged when a held position settles."""
        ...


# ---------------------------------------------------------------------------
# Kalshi
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KalshiFeeSchedule:
    """Parameters of Kalshi's published trading-fee formula.

    The general schedule is::

        fee = ceil_to_cent( rate * C * P * (1 - P) )

    where ``C`` is the contract count and ``P`` the price in dollars. The
    ``P * (1 - P)`` term makes the fee a parabola that peaks at 50c and
    collapses toward the wings:

        price      fee per contract (rate = 0.07)
        -----      -----------------------------
         50c        1.750c
         75c        1.313c
         90c        0.630c
         95c        0.333c
         99c        0.069c

    That shape is a strategic fact, not trivia. Trading at 95c costs about a
    fifth of what trading at 50c costs, which is why deep-in-the-money carry
    trades survive fees when mid-book scalping does not.

    The ceiling is applied **per order, to the next whole cent** — so small
    orders are penalised. A single contract at 50c owes ceil(1.75c) = 2c, a
    4% tax; a hundred contracts owe 175c, a 3.5% tax. Order sizing therefore
    interacts with fees directly, and :meth:`KalshiFees.min_profitable_size`
    exists to make that explicit.
    """

    #: Multiplier in the taker fee formula.
    taker_rate: float = 0.07
    #: Maker fee rate. Kalshi's general schedule has historically been
    #: maker-free; some series introduced a maker fee. Verify per series.
    maker_rate: float = 0.0
    #: Per-contract settlement fee in pips (0 on the general schedule).
    settlement_fee_pips_per_contract: int = 0
    effective_date: date = date(2025, 1, 1)
    source: str = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"


class KalshiFees:
    """Kalshi fee model using exact integer arithmetic.

    The formula is evaluated as a rational number and only then rounded, so
    results are bit-identical between backtest and live and never drift with
    floating point.
    """

    def __init__(self, schedule: KalshiFeeSchedule | None = None) -> None:
        self.schedule = schedule or KalshiFeeSchedule()

    def trade_fee_pips(self, *, price_pips: int, size: int, liquidity: Liquidity) -> int:
        if size <= 0:
            return 0
        rate = (
            self.schedule.taker_rate
            if liquidity is Liquidity.TAKER
            else self.schedule.maker_rate
        )
        if rate == 0.0:
            return 0
        return self._formula_pips(rate=rate, price_pips=price_pips, size=size)

    @staticmethod
    def _formula_pips(*, rate: float, price_pips: int, size: int) -> int:
        """``ceil_to_cent(rate * C * P * (1 - P))`` in pips, exactly.

        Working in pips, ``P = p / 10_000`` and ``1 - P = (10_000 - p) / 10_000``,
        so the fee in cents is::

            rate * 100 * C * p * (10_000 - p) / 10_000**2

        We scale ``rate`` by 10**6 to an integer to keep the whole computation
        in exact integer arithmetic before taking the ceiling.
        """
        rate_scaled = int(round(rate * 1_000_000))
        numerator = rate_scaled * size * price_pips * (PIPS_PER_DOLLAR - price_pips)
        denominator = 1_000_000 * PIPS_PER_DOLLAR * 100  # -> cents
        fee_cents = -(-numerator // denominator)  # ceiling division
        return fee_cents * PIPS_PER_CENT

    def settlement_fee_pips(self, *, size: int, settled_yes: bool) -> int:
        del settled_yes  # Kalshi's general schedule does not vary by outcome.
        return self.schedule.settlement_fee_pips_per_contract * max(0, size)

    # -- analysis helpers ---------------------------------------------------

    def fee_per_contract_pips(self, price_pips: int, *, size: int = 1000) -> float:
        """Amortised per-contract taker fee, for strategy screening.

        Uses a large default ``size`` so the per-order cent-rounding does not
        dominate; pass the real size when sizing an actual order.
        """
        total = self.trade_fee_pips(
            price_pips=price_pips, size=size, liquidity=Liquidity.TAKER
        )
        return total / size

    def round_trip_cost_pips(self, entry_pips: int, exit_pips: int, *, size: int) -> int:
        """Total fee to open at ``entry_pips`` and close at ``exit_pips``.

        The number a strategy must beat before it makes a cent.
        """
        return self.trade_fee_pips(
            price_pips=entry_pips, size=size, liquidity=Liquidity.TAKER
        ) + self.trade_fee_pips(price_pips=exit_pips, size=size, liquidity=Liquidity.TAKER)

    def min_profitable_size(self, *, price_pips: int, edge_pips_per_contract: int) -> int:
        """Smallest order size whose gross edge exceeds fees.

        Because the fee ceiling is per-order, very small orders can be
        unprofitable at an edge that is comfortably profitable in size. Returns
        ``0`` when no size clears the fee — i.e. the trade is never worth doing.
        """
        if edge_pips_per_contract <= 0:
            return 0
        asymptotic = self.fee_per_contract_pips(price_pips)
        if asymptotic >= edge_pips_per_contract:
            return 0  # fee-negative at any size
        for size in range(1, 10_001):
            fee = self.trade_fee_pips(
                price_pips=price_pips, size=size, liquidity=Liquidity.TAKER
            )
            if edge_pips_per_contract * size > fee:
                return size
        return 0


# ---------------------------------------------------------------------------
# Polymarket
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolymarketFeeSchedule:
    """Polymarket CLOB fee parameters.

    Polymarket has historically charged **zero** trading fees, which is its
    structural advantage over Kalshi and the reason cross-venue pricing is not
    symmetric. Order placement is gasless (a relayer submits on your behalf),
    so the marginal cost of a CLOB trade is genuinely ~0.

    The costs that *do* exist live elsewhere and are modelled separately:
    bridging USDC in and out, and the opportunity cost of collateral parked on
    Polygon. Fees here are parameterised so a future fee introduction is a
    one-line change rather than an audit of every strategy.
    """

    taker_fee_bps: int = 0
    maker_fee_bps: int = 0
    #: Gas is paid by the relayer for CLOB orders; non-zero only for direct
    #: on-chain actions such as split/merge or neg-risk conversion.
    onchain_action_gas_pips: int = 0
    effective_date: date = date(2025, 1, 1)
    source: str = "https://docs.polymarket.com/"


class PolymarketFees:
    """Polymarket fee model.

    Fees are charged in basis points of *notional* when non-zero. Notional for
    a binary contract is ``price * size``, so a taker fee applies asymmetrically
    across the price range — unlike Kalshi's symmetric parabola.
    """

    def __init__(self, schedule: PolymarketFeeSchedule | None = None) -> None:
        self.schedule = schedule or PolymarketFeeSchedule()

    def trade_fee_pips(self, *, price_pips: int, size: int, liquidity: Liquidity) -> int:
        if size <= 0:
            return 0
        bps = (
            self.schedule.taker_fee_bps
            if liquidity is Liquidity.TAKER
            else self.schedule.maker_fee_bps
        )
        if bps == 0:
            return 0
        notional = price_pips * size
        return -(-notional * bps // 10_000)  # ceiling

    def settlement_fee_pips(self, *, size: int, settled_yes: bool) -> int:
        del size, settled_yes
        return 0

    def onchain_action_cost_pips(self, n_actions: int = 1) -> int:
        """Cost of a direct on-chain action (split, merge, neg-risk convert)."""
        return self.schedule.onchain_action_gas_pips * n_actions


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FEE_MODELS: dict[str, FeeModel] = {
    "kalshi": KalshiFees(),
    "polymarket": PolymarketFees(),
}


def fee_model_for(venue: str) -> FeeModel:
    """Look up the fee model for a venue id, failing loudly on typos."""
    try:
        return FEE_MODELS[venue]
    except KeyError:
        raise KeyError(
            f"no fee model registered for venue {venue!r}; "
            f"known venues: {sorted(FEE_MODELS)}"
        ) from None
