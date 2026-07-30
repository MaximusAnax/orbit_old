"""Weather forecast edge.

Kalshi lists daily high/low temperature markets that settle on official NWS
station observations. Public numerical weather prediction is excellent and
free. That combination is the most promising *model* edge available to a small
account, because unlike constraint arbitrage it does not wait for someone else
to misprice — it produces an opinion on every market, every day, on roughly
20 cities x 2 series x 365 days.

The central insight is not the forecast. It is this:

    **The daily maximum is a running maximum, so observations already taken
    are a hard floor that cannot be undone.**

By mid-afternoon a station has usually already recorded the day's high. If the
observed high so far is 76°F, then "high above 75°F" is not likely — it is
*settled*, and any price below 100c is free money. More generally, every
observation truncates the distribution from below and collapses uncertainty
long before expiry. A model that treats the day's high as a symmetric forecast
error around a point estimate throws this away entirely.

:func:`daily_max_distribution` encodes it: the distribution of the final
maximum is the distribution of the remaining hours, censored from below at
what has already been observed.

.. warning::
   **Settlement rounding decides these markets.** A threshold at 75°F against
   an observation of 75.4°F depends entirely on whether the venue settles on
   the rounded integer or the raw value, and on whether the source is the
   hourly METAR or the daily climate report. This module exposes the rule as
   configuration rather than assuming one, and it is the first item to confirm
   in ``docs/VERIFICATION.md``. Getting it wrong inverts the edge on exactly
   the contracts where the edge is largest.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from orbit.core.fees import KalshiFees, Liquidity
from orbit.core.money import PIPS_PER_DOLLAR
from orbit.core.types import FairValue, OrderBook, Side


class SettlementRounding(StrEnum):
    """How the venue converts an observation into a settlement value."""

    #: Round to the nearest whole degree (75.4 -> 75, 75.5 -> 76).
    NEAREST_INTEGER = "nearest_integer"
    #: Truncate toward zero (75.9 -> 75). Used by some climate products.
    TRUNCATE = "truncate"
    #: Compare the raw value directly, no rounding.
    RAW = "raw"


def apply_rounding(value: float, rule: SettlementRounding) -> float:
    if rule is SettlementRounding.NEAREST_INTEGER:
        # Half-up, matching how observation products round, rather than
        # Python's banker's rounding which would send 74.5 to 74.
        return math.floor(value + 0.5)
    if rule is SettlementRounding.TRUNCATE:
        return math.floor(value)
    return value


# ---------------------------------------------------------------------------
# Forecast error model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForecastSkill:
    """Forecast error as a function of lead time.

    Defaults approximate published NWS/NBM station-level max-temperature
    verification: mean absolute error around 2-3degF at 24 hours, improving as
    the forecast valid time approaches. These are **placeholders to be replaced
    with error measured from your own archive** — the recorder stores forecasts
    alongside outcomes precisely so this can be fitted rather than assumed.

    Sizing is proportional to the edge, and the edge is a function of this
    number, so an optimistic sigma here becomes systematic overbetting. When
    unsure, set it too wide.
    """

    #: Standard deviation of forecast error in °F at zero lead time. Not zero:
    #: even a "current" observation can be revised or corrected.
    sigma_at_zero_h: float = 0.5
    #: Standard deviation at 24 hours lead.
    sigma_at_24h: float = 2.5
    #: Standard deviation at 72 hours lead.
    sigma_at_72h: float = 4.5

    def sigma(self, lead_hours: float) -> float:
        """Interpolate the error standard deviation for a lead time.

        Error grows roughly with the square root of lead time, so
        interpolation is done in sqrt-space rather than linearly.
        """
        h = max(0.0, lead_hours)
        if h <= 24.0:
            t = math.sqrt(h / 24.0)
            return self.sigma_at_zero_h + t * (self.sigma_at_24h - self.sigma_at_zero_h)
        t = min(1.0, math.sqrt((h - 24.0) / 48.0))
        return self.sigma_at_24h + t * (self.sigma_at_72h - self.sigma_at_24h)


def _normal_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Distribution of the day's maximum
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyMaxDistribution:
    """Distribution over the settling value of a daily max/min market.

    ``observed_floor`` is what makes this different from a plain forecast: the
    running maximum already recorded. The final value cannot come in below it,
    so all probability mass below the floor collapses onto the floor itself.
    """

    #: Best estimate of the maximum over the *remaining* hours.
    remaining_forecast: float
    #: Uncertainty on that estimate.
    sigma: float
    #: Highest value already observed today. ``None`` before any observation.
    observed_floor: float | None = None
    #: True for a daily-minimum market, where observations cap from above.
    is_minimum: bool = False
    rounding: SettlementRounding = SettlementRounding.NEAREST_INTEGER

    @property
    def is_settled(self) -> bool:
        """Whether observations alone have already determined the outcome.

        Only meaningful relative to a threshold; see :meth:`prob_at_or_above`.
        """
        return self.sigma <= 0.0

    def prob_at_or_above(self, threshold: float) -> float:
        """P(settlement value >= threshold).

        The floor is applied first and is absolute. If the day has already
        recorded 76°F, then P(high >= 75) is exactly 1.0 — not 0.98, not
        "very likely". That certainty is the whole edge, and treating it as
        merely probable is what leaves it on the table.
        """
        # Compare on the venue's own settlement scale, not the raw one.
        floor = self.observed_floor
        if floor is not None:
            settled_floor = apply_rounding(floor, self.rounding)
            if not self.is_minimum and settled_floor >= threshold:
                return 1.0
            if self.is_minimum and settled_floor <= threshold:
                # A daily *minimum* already at or below the threshold means
                # "min <= threshold" is certain, so "min >= threshold" is
                # impossible.
                return 0.0 if settled_floor < threshold else 1.0

        if self.sigma <= 0.0:
            return 1.0 if self.remaining_forecast >= threshold else 0.0

        # Rounding shifts the effective cutoff: with round-half-up, settling
        # at or above 75 requires a raw value of at least 74.5.
        cutoff = threshold
        if self.rounding is SettlementRounding.NEAREST_INTEGER:
            cutoff = threshold - 0.5
        elif self.rounding is SettlementRounding.TRUNCATE:
            cutoff = threshold

        z = (self.remaining_forecast - cutoff) / self.sigma
        return _normal_cdf(z)

    def prob_in_bucket(self, low: float, high: float) -> float:
        """P(low <= settlement < high), for range markets."""
        return max(0.0, self.prob_at_or_above(low) - self.prob_at_or_above(high))

    def confidence(self) -> float:
        """How much to trust this estimate, in [0, 1].

        Tightens as uncertainty collapses, so an outright settled market is
        sized at full confidence and a three-day-out forecast is sized small.
        """
        if self.sigma <= 0.0:
            return 1.0
        return max(0.0, min(1.0, 1.0 / (1.0 + self.sigma / 2.0)))


def daily_max_distribution(
    *,
    observations: Sequence[float],
    remaining_forecast: float,
    lead_hours: float,
    skill: ForecastSkill | None = None,
    is_minimum: bool = False,
    rounding: SettlementRounding = SettlementRounding.NEAREST_INTEGER,
) -> DailyMaxDistribution:
    """Build the distribution of today's settling value.

    Args:
        observations: Values observed so far today, in any order.
        remaining_forecast: Forecast extreme over the hours still to come.
        lead_hours: Hours until the market's observation window closes. Drives
            the error width, and reaching zero is what turns a forecast into a
            fact.
    """
    skill = skill or ForecastSkill()
    floor: float | None = None
    if observations:
        floor = min(observations) if is_minimum else max(observations)

    return DailyMaxDistribution(
        remaining_forecast=remaining_forecast,
        sigma=skill.sigma(lead_hours),
        observed_floor=floor,
        is_minimum=is_minimum,
        rounding=rounding,
    )


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


@dataclass
class WeatherMarket:
    """A Kalshi weather contract, parsed into what the model needs."""

    market_key: str
    station: str
    #: Threshold in °F for a threshold market.
    threshold: float | None = None
    #: Inclusive-exclusive bounds for a bucket market.
    bucket: tuple[float, float] | None = None
    is_minimum: bool = False
    close_time: datetime | None = None

    def probability(self, dist: DailyMaxDistribution) -> float:
        if self.bucket is not None:
            return dist.prob_in_bucket(*self.bucket)
        if self.threshold is not None:
            return dist.prob_at_or_above(self.threshold)
        raise ValueError(f"{self.market_key}: neither threshold nor bucket set")


@dataclass
class WeatherEdgeStrategy:
    """Prices weather markets from forecasts and live observations.

    Emits a :class:`FairValue` per market; sizing and risk are handled
    downstream, as with every other strategy — this only forms an opinion.
    """

    skill: ForecastSkill = field(default_factory=ForecastSkill)
    rounding: SettlementRounding = SettlementRounding.NEAREST_INTEGER
    #: Multiple of the fee that the edge must clear. The *threshold itself is
    #: price-dependent*, which is the single most important design decision in
    #: this class.
    #:
    #: Kalshi's fee is parabolic in price, so the break-even forecasting edge
    #: is 1.75 percentage points at 50c but only 0.20pp at 97c — the same
    #: skill is worth roughly nine times more in the wings than at mid-book.
    #: A flat cents threshold inverts this: it waves through mid-book trades
    #: that need a huge edge to break even, and rejects wing trades that need
    #: almost none. Deriving the hurdle from the fee at the actual price
    #: points the strategy where the hurdle is lowest, automatically.
    edge_safety_multiple: float = 2.0
    #: Absolute floor regardless of price, so a near-zero fee at 99c cannot
    #: justify trading on model noise.
    min_edge_floor_pips: int = 20  # 0.2 cents
    #: Shrink applied to every estimate until the model has been validated
    #: against realised outcomes. Starting below 1.0 is deliberate: a new
    #: model's first job is to be measured, not to be trusted.
    haircut: float = 0.5
    #: Fee model used to derive the price-dependent hurdle.
    fees: KalshiFees = field(default_factory=KalshiFees)

    def required_edge_pips(self, price_pips: int, *, size: int = 100) -> int:
        """Minimum edge worth acting on at this price.

        Falls steeply toward the wings because the fee does, which is what
        makes deep-in-the-money weather contracts the right place to trade a
        small forecasting edge and mid-book contracts the wrong one.
        """
        fee_per_contract = self.fees.trade_fee_pips(
            price_pips=price_pips, size=size, liquidity=Liquidity.TAKER
        ) / max(1, size)
        return max(
            self.min_edge_floor_pips,
            int(fee_per_contract * self.edge_safety_multiple),
        )

    def fair_value(
        self,
        market: WeatherMarket,
        *,
        observations: Sequence[float],
        remaining_forecast: float,
        now: datetime | None = None,
    ) -> FairValue:
        now = now or datetime.now(UTC)
        lead_hours = 24.0
        if market.close_time is not None:
            lead_hours = max(
                0.0, (market.close_time - now).total_seconds() / 3600.0
            )

        dist = daily_max_distribution(
            observations=observations,
            remaining_forecast=remaining_forecast,
            lead_hours=lead_hours,
            skill=self.skill,
            is_minimum=market.is_minimum,
            rounding=self.rounding,
        )
        prob = market.probability(dist)
        fv = FairValue(
            market_key=market.market_key,
            probability=prob,
            confidence=dist.confidence(),
            source="weather_model",
            timestamp=now,
            stderr=dist.sigma,
        )
        # A settled market needs no haircut — the floor is a fact, not an
        # estimate — so shrinking it would only discard the best trade
        # available.
        if prob in (0.0, 1.0) and dist.observed_floor is not None:
            return fv
        return fv.with_haircut(self.haircut)

    def evaluate(
        self,
        market: WeatherMarket,
        book: OrderBook,
        *,
        observations: Sequence[float],
        remaining_forecast: float,
        now: datetime | None = None,
    ) -> tuple[FairValue, Side, int] | None:
        """Return ``(fair_value, side, edge_pips)`` when the market is mispriced."""
        fv = self.fair_value(
            market,
            observations=observations,
            remaining_forecast=remaining_forecast,
            now=now,
        )
        ask, bid = book.best_ask_pips, book.best_bid_pips

        # The hurdle is evaluated at the price actually being traded, not as a
        # flat constant, so the same model edge qualifies in the wings and is
        # correctly rejected at mid-book.
        if ask is not None:
            edge = fv.edge_pips(ask, side=Side.BUY)
            if edge >= self.required_edge_pips(ask):
                return fv, Side.BUY, edge
        if bid is not None:
            edge = fv.edge_pips(bid, side=Side.SELL)
            if edge >= self.required_edge_pips(bid):
                return fv, Side.SELL, edge
        return None


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@dataclass
class CalibrationRecord:
    """One (forecast, outcome) pair, for measuring whether the model is honest."""

    market_key: str
    predicted_prob: float
    settled_yes: bool
    market_price_pips: int
    timestamp: datetime


class CalibrationTracker:
    """Measures whether the model's probabilities mean anything.

    A model claiming 70% must resolve YES about 70% of the time. Without this,
    a confident and wrong model is indistinguishable from a confident and right
    one until the account is gone.

    Also tracks whether the model beats the *market*, which is the only
    comparison that pays: being well-calibrated while the market is equally
    well-calibrated is a strategy with no edge and real fees.
    """

    def __init__(self, n_bins: int = 10) -> None:
        self.n_bins = n_bins
        self.records: list[CalibrationRecord] = []

    def add(self, record: CalibrationRecord) -> None:
        self.records.append(record)

    def reliability(self) -> list[tuple[float, float, int]]:
        """``(mean predicted, observed frequency, count)`` per probability bin."""
        edges = [i / self.n_bins for i in range(self.n_bins + 1)]
        buckets: list[list[CalibrationRecord]] = [[] for _ in range(self.n_bins)]
        for r in self.records:
            idx = min(self.n_bins - 1, max(0, bisect_left(edges, r.predicted_prob) - 1))
            buckets[idx].append(r)
        out = []
        for bucket in buckets:
            if not bucket:
                continue
            mean_pred = sum(r.predicted_prob for r in bucket) / len(bucket)
            observed = sum(1 for r in bucket if r.settled_yes) / len(bucket)
            out.append((mean_pred, observed, len(bucket)))
        return out

    def brier_score(self) -> float | None:
        """Mean squared error of the probabilities. Lower is better."""
        if not self.records:
            return None
        return sum(
            (r.predicted_prob - (1.0 if r.settled_yes else 0.0)) ** 2
            for r in self.records
        ) / len(self.records)

    def market_brier_score(self) -> float | None:
        """The same score for the market's own price — the bar to beat."""
        if not self.records:
            return None
        return sum(
            (r.market_price_pips / PIPS_PER_DOLLAR - (1.0 if r.settled_yes else 0.0))
            ** 2
            for r in self.records
        ) / len(self.records)

    def beats_market(self) -> bool | None:
        """Whether the model is more accurate than the price it trades against.

        The single number that decides whether this strategy should run at all.
        ``None`` until there is enough data to say.
        """
        if len(self.records) < 100:
            return None
        mine, theirs = self.brier_score(), self.market_brier_score()
        if mine is None or theirs is None:
            return None
        return mine < theirs

    def summary(self) -> dict[str, object]:
        return {
            "samples": len(self.records),
            "model_brier": self.brier_score(),
            "market_brier": self.market_brier_score(),
            "beats_market": self.beats_market(),
            "reliability": self.reliability(),
        }
