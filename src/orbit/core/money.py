"""Money and price representation.

Every price in Orbit is an integer number of **pips**, where 1 pip = $0.0001.
A binary event contract settles at either $0.00 or $1.00, so a valid contract
price lives in ``[0, 10_000]`` pips.

Why integers: a trading system that represents money as ``float`` will
eventually book a fill at 0.30000000000000004 and reconcile against the
exchange incorrectly. Integer pips make every price, fee and PnL computation
exact, and they divide cleanly into both venues' tick sizes:

    Kalshi tick      $0.01   = 100 pips
    Polymarket tick  $0.01   = 100 pips  (some markets $0.001 = 10 pips)

Model *fair values* are a different animal: they are probabilities and want
full floating-point precision. Those stay as ``float`` in ``[0.0, 1.0]`` and
are only converted to a tradable price at order-construction time, where the
rounding direction is an explicit, deliberate choice (see :func:`prob_to_price`).
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Scale constants
# ---------------------------------------------------------------------------

#: Pips per US dollar. 1 pip = $0.0001.
PIPS_PER_DOLLAR: Final[int] = 10_000

#: Pips per cent. Kalshi quotes in whole cents.
PIPS_PER_CENT: Final[int] = 100

#: A contract that resolves YES pays out this much.
CONTRACT_PAYOUT_PIPS: Final[int] = PIPS_PER_DOLLAR

#: Valid price bounds for a binary contract, in pips.
MIN_PRICE_PIPS: Final[int] = 0
MAX_PRICE_PIPS: Final[int] = PIPS_PER_DOLLAR

#: Prices strictly inside the book — you cannot rest an order at 0 or $1.
MIN_TRADABLE_PIPS: Final[int] = PIPS_PER_CENT  # 1c
MAX_TRADABLE_PIPS: Final[int] = PIPS_PER_DOLLAR - PIPS_PER_CENT  # 99c


class PriceError(ValueError):
    """Raised when a price is outside the valid range for a binary contract."""


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------


def cents_to_pips(cents: int) -> int:
    """Convert a whole-cent price (Kalshi's native unit) to pips."""
    return cents * PIPS_PER_CENT


def pips_to_cents(pips: int) -> float:
    """Convert pips to cents. May be fractional; use only for display."""
    return pips / PIPS_PER_CENT


def dollars_to_pips(dollars: float) -> int:
    """Convert a dollar amount to pips, rounding half away from zero.

    Used to ingest venue payloads that quote decimal dollars (Polymarket).
    """
    return round(dollars * PIPS_PER_DOLLAR)


def pips_to_dollars(pips: int) -> float:
    """Convert pips to a dollar float. Display and reporting only."""
    return pips / PIPS_PER_DOLLAR


def prob_to_price(prob: float, *, tick_pips: int, round_up: bool) -> int:
    """Convert a model probability to a tradable integer price on the tick grid.

    ``round_up`` must be chosen deliberately by the caller, because rounding
    direction is a trading decision, not a formatting one:

    * Buying: round **down** so you never pay more than your fair value.
    * Selling: round **up** so you never sell below your fair value.

    The result is clamped into ``[MIN_TRADABLE_PIPS, MAX_TRADABLE_PIPS]``,
    since no venue accepts a resting order at 0 or $1.
    """
    if not 0.0 <= prob <= 1.0:
        raise PriceError(f"probability out of range: {prob}")
    raw = prob * PIPS_PER_DOLLAR
    ticks = -(-raw // tick_pips) if round_up else raw // tick_pips
    pips = int(ticks) * tick_pips
    return max(MIN_TRADABLE_PIPS, min(MAX_TRADABLE_PIPS, pips))


def price_to_prob(pips: int) -> float:
    """Convert an integer price to the probability it implies."""
    return pips / PIPS_PER_DOLLAR


def validate_price(pips: int, *, tradable: bool = True) -> int:
    """Validate a price and return it unchanged, for use in constructors."""
    lo = MIN_TRADABLE_PIPS if tradable else MIN_PRICE_PIPS
    hi = MAX_TRADABLE_PIPS if tradable else MAX_PRICE_PIPS
    if not lo <= pips <= hi:
        raise PriceError(f"price {pips} pips outside [{lo}, {hi}]")
    return pips


def round_to_tick(pips: int, *, tick_pips: int, round_up: bool) -> int:
    """Snap an arbitrary pip price onto the venue's tick grid."""
    if tick_pips <= 0:
        raise PriceError(f"tick must be positive, got {tick_pips}")
    ticks = -(-pips // tick_pips) if round_up else pips // tick_pips
    return int(ticks) * tick_pips


# ---------------------------------------------------------------------------
# Binary-contract algebra
# ---------------------------------------------------------------------------


def complement(pips: int) -> int:
    """The price of the opposite side.

    A YES at ``p`` and a NO at ``$1 - p`` are economically identical positions,
    which is the single most useful identity in binary markets: it lets the
    whole system reason in YES-space and translate NO quotes on the way in.
    """
    return PIPS_PER_DOLLAR - pips


def notional_pips(price_pips: int, size: int) -> int:
    """Capital required to buy ``size`` contracts at ``price_pips``.

    Prediction-market contracts are fully collateralised: buying costs the
    price, and *selling* (writing) costs the complement. There is no leverage,
    so this is also the maximum possible loss on the position.
    """
    return price_pips * size


def format_price(pips: int) -> str:
    """Human-readable price, e.g. ``'47.5c'``."""
    cents = pips / PIPS_PER_CENT
    return f"{cents:.0f}c" if cents == int(cents) else f"{cents:.2f}c"


def format_usd(pips: int) -> str:
    """Human-readable dollar amount from a pip quantity, e.g. ``'$12.34'``."""
    return f"${pips / PIPS_PER_DOLLAR:,.2f}"
