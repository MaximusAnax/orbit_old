"""Measuring the weather edge against history.

The central claim of :mod:`orbit.strategies.weather` is that a daily maximum is
a running maximum, so by mid-afternoon the outcome is frequently already
*determined* while the market may still be pricing uncertainty. That claim is
either true or it is not, and it can be settled **today** — it depends only on
historical station observations, which go back decades, not on recorded market
prices.

That makes this the one experiment in the whole project that does not require
waiting. It answers, per station and per hour of the day:

    Of all the days in the sample, on what fraction had the day's maximum
    *already been reached* by this hour?

If the answer at 3pm local is 70%, then on 70% of days a bot reading live
observations at 3pm knows the settlement value with certainty, and every
threshold below the observed maximum is a settled contract. Whether that is
*profitable* additionally requires that the market has not already priced it —
which needs recorded prices — but if the certainty curve is flat and late, the
strategy is dead and no amount of price data will revive it.

Run it before committing capital, and before believing anything in the
strategy docs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from orbit.data.weather import Observation


@dataclass
class HourStats:
    """How determined the day's outcome is, by a given local hour."""

    local_hour: int
    days: int = 0
    #: Days where the running maximum already equals the final daily maximum.
    max_already_reached: int = 0
    #: Mean gap in degrees between the running max and the final max.
    mean_remaining_rise: float = 0.0
    #: 90th percentile of that gap — the tail that decides how wide a model
    #: must be when the outcome is *not* yet locked.
    p90_remaining_rise: float = 0.0

    @property
    def settled_fraction(self) -> float:
        return self.max_already_reached / self.days if self.days else 0.0


@dataclass
class CertaintyCurve:
    """The result of the study for one station."""

    station_id: str
    days_analysed: int
    hours: list[HourStats] = field(default_factory=list)

    def settled_fraction_at(self, local_hour: int) -> float:
        for h in self.hours:
            if h.local_hour == local_hour:
                return h.settled_fraction
        return 0.0

    def first_hour_above(self, threshold: float) -> int | None:
        """Earliest local hour at which the outcome is settled this often."""
        for h in sorted(self.hours, key=lambda x: x.local_hour):
            if h.settled_fraction >= threshold:
                return h.local_hour
        return None

    def summary(self) -> dict[str, object]:
        return {
            "station": self.station_id,
            "days_analysed": self.days_analysed,
            "settled_by_hour": {
                h.local_hour: round(h.settled_fraction, 3)
                for h in sorted(self.hours, key=lambda x: x.local_hour)
            },
            "half_settled_by": self.first_hour_above(0.5),
            "mostly_settled_by": self.first_hour_above(0.8),
        }

    def format_table(self) -> str:
        lines = [
            f"Station {self.station_id} — {self.days_analysed} days",
            "",
            f"{'local hour':>10}  {'settled':>8}  {'mean rise':>10}  {'p90 rise':>9}",
        ]
        for h in sorted(self.hours, key=lambda x: x.local_hour):
            if h.days == 0:
                continue
            lines.append(
                f"{h.local_hour:>10}  {h.settled_fraction:>7.1%}  "
                f"{h.mean_remaining_rise:>9.1f}F  {h.p90_remaining_rise:>8.1f}F"
            )
        half = self.first_hour_above(0.5)
        most = self.first_hour_above(0.8)
        lines += [
            "",
            f"50% of days settled by: {half if half is not None else 'never'}:00 local",
            f"80% of days settled by: {most if most is not None else 'never'}:00 local",
        ]
        return "\n".join(lines)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def build_certainty_curve(
    observations: Sequence[Observation],
    *,
    timezone_offset_h: float,
    station_id: str = "",
    min_observations_per_day: int = 12,
) -> CertaintyCurve:
    """Measure how early the daily maximum is typically locked in.

    Days with sparse observation coverage are excluded rather than treated as
    settled early: a station that stopped reporting at noon would otherwise
    look like its maximum was reached by noon, which would manufacture exactly
    the result the study is meant to test.
    """
    offset = timedelta(hours=timezone_offset_h)
    by_day: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for obs in observations:
        local = obs.timestamp + offset
        by_day[local.strftime("%Y-%m-%d")].append((local.hour, obs.temperature_f))

    per_hour_reached: dict[int, int] = defaultdict(int)
    per_hour_days: dict[int, int] = defaultdict(int)
    per_hour_gaps: dict[int, list[float]] = defaultdict(list)
    days_used = 0

    for readings in by_day.values():
        if len(readings) < min_observations_per_day:
            continue
        days_used += 1
        daily_max = max(t for _, t in readings)

        for hour in range(24):
            so_far = [t for h, t in readings if h <= hour]
            if not so_far:
                # No observation yet this day at this hour; the outcome is
                # certainly not determined, and there is no running max.
                per_hour_days[hour] += 1
                per_hour_gaps[hour].append(daily_max - min(t for _, t in readings))
                continue
            running = max(so_far)
            per_hour_days[hour] += 1
            if running >= daily_max:
                per_hour_reached[hour] += 1
            per_hour_gaps[hour].append(daily_max - running)

    hours = [
        HourStats(
            local_hour=hour,
            days=per_hour_days[hour],
            max_already_reached=per_hour_reached[hour],
            mean_remaining_rise=(
                sum(per_hour_gaps[hour]) / len(per_hour_gaps[hour])
                if per_hour_gaps[hour]
                else 0.0
            ),
            p90_remaining_rise=_percentile(per_hour_gaps[hour], 0.9),
        )
        for hour in range(24)
        if per_hour_days[hour]
    ]
    return CertaintyCurve(
        station_id=station_id, days_analysed=days_used, hours=hours
    )


@dataclass
class ThresholdOpportunity:
    """How many settled contracts a given hour would expose, per day.

    A threshold strictly below the running maximum is already settled YES; one
    strictly above the highest still-attainable value is settled NO. Both are
    tradable certainties if the market has not priced them.
    """

    local_hour: int
    mean_settled_yes_thresholds: float
    mean_settled_no_thresholds: float

    @property
    def mean_total(self) -> float:
        return self.mean_settled_yes_thresholds + self.mean_settled_no_thresholds


def count_settled_thresholds(
    observations: Sequence[Observation],
    *,
    timezone_offset_h: float,
    thresholds: Sequence[float],
    at_local_hour: int,
    plausible_remaining_rise: float = 6.0,
    min_observations_per_day: int = 12,
) -> ThresholdOpportunity:
    """Count contracts already decided at a given hour, averaged over days.

    ``plausible_remaining_rise`` bounds how much warmer it could still get,
    which is what makes a *NO* settlement claimable before the day ends. Set it
    from the p90 gap in :func:`build_certainty_curve` rather than by intuition;
    too small a value invents certainty that does not exist, which is the one
    error this whole approach cannot tolerate.
    """
    offset = timedelta(hours=timezone_offset_h)
    by_day: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for obs in observations:
        local = obs.timestamp + offset
        by_day[local.strftime("%Y-%m-%d")].append((local.hour, obs.temperature_f))

    yes_counts: list[int] = []
    no_counts: list[int] = []
    for readings in by_day.values():
        if len(readings) < min_observations_per_day:
            continue
        so_far = [t for h, t in readings if h <= at_local_hour]
        if not so_far:
            continue
        running = max(so_far)
        ceiling = running + plausible_remaining_rise
        yes_counts.append(sum(1 for t in thresholds if t <= running))
        no_counts.append(sum(1 for t in thresholds if t > ceiling))

    n = max(1, len(yes_counts))
    return ThresholdOpportunity(
        local_hour=at_local_hour,
        mean_settled_yes_thresholds=sum(yes_counts) / n,
        mean_settled_no_thresholds=sum(no_counts) / n,
    )


def estimate_monthly_dollars(
    *,
    settled_contracts_per_day: float,
    stations: int,
    capture_rate: float,
    edge_cents: float,
    contracts_per_trade: int,
) -> dict[str, float]:
    """Translate the study into a dollar figure, with the assumptions exposed.

    Every input except the first is a *guess* until measured against recorded
    prices, and the output is only as good as ``capture_rate`` — the fraction
    of settled contracts still mispriced by the time the bot sees them. If the
    market is efficient here, that number is near zero and so is the profit,
    however impressive the certainty curve looks.

    This function exists to make the sensitivity explicit rather than to
    produce a forecast. Vary ``capture_rate`` and ``edge_cents`` and see how
    fast the answer collapses.
    """
    trades_per_month = settled_contracts_per_day * stations * capture_rate * 30
    gross = trades_per_month * contracts_per_trade * edge_cents / 100.0
    return {
        "trades_per_month": round(trades_per_month, 1),
        "gross_dollars_per_month": round(gross, 2),
        "assumed_capture_rate": capture_rate,
        "assumed_edge_cents": edge_cents,
        "contracts_per_trade": contracts_per_trade,
    }
