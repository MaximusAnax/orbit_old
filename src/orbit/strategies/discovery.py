"""Constraint discovery.

Turns a list of markets into the logical relationships between them. This is
the step that makes constraint arbitrage work on a live venue rather than on
hand-written pairs — and it is also the most dangerous code in the project,
because **a wrong relationship produces a confident false arbitrage.**

If two markets are grouped as a mutually exclusive partition when they are not,
the scanner will happily report a guaranteed profit for a position that can
lose in full. The worst-case-over-scenarios machinery in
:mod:`orbit.strategies.constraints` is only as sound as the scenarios it is
given, and those come from here.

So discovery is graded by how much can be *proved* rather than inferred:

``CERTAIN``
    True by construction, independent of any metadata. Only YES/NO parity
    qualifies: a single market's own two sides must price to $1. Enabled
    automatically.

``STRUCTURAL``
    Follows from parsed strike values within one series and expiry, where the
    implication is a mathematical fact about the numbers ("above 80" implies
    "above 75"). Enabled automatically when parsing succeeds on both sides.

``INFERRED``
    Depends on a venue grouping meaning what it appears to mean — chiefly that
    an event's markets are mutually exclusive *and* exhaustive. Disabled by
    default. These are surfaced for a human to confirm, because the failure
    mode is not a missed trade but a fabricated one.

The asymmetry is deliberate. Missing an opportunity costs nothing; inventing
one costs the position.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import structlog

from orbit.core.types import Market
from orbit.strategies.constraints import (
    ComplementConstraint,
    Constraint,
    MonotoneConstraint,
    PartitionConstraint,
)

log = structlog.get_logger(__name__)


class Confidence(StrEnum):
    CERTAIN = "certain"
    STRUCTURAL = "structural"
    INFERRED = "inferred"


@dataclass(frozen=True)
class DiscoveredConstraint:
    constraint: Constraint
    confidence: Confidence
    explanation: str

    @property
    def auto_enabled(self) -> bool:
        return self.confidence in (Confidence.CERTAIN, Confidence.STRUCTURAL)


# Kalshi encodes the strike in the ticker's final segment. ``-T`` marks a
# threshold ("at or above"), ``-B`` a bucket (a range). Both carry a number.
_STRIKE_RE = re.compile(r"-(?P<kind>[TB])(?P<value>-?\d+(?:\.\d+)?)$")

# Threshold language in titles, used as a fallback when the ticker is opaque.
_ABOVE_RE = re.compile(
    r"\b(above|over|greater than|at least|higher than|more than|≥|>=?)\b",
    re.IGNORECASE,
)
_BELOW_RE = re.compile(
    r"\b(below|under|less than|at most|lower than|fewer than|≤|<=?)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Strike:
    value: float
    kind: str  # "T" threshold, "B" bucket
    #: True when a *higher* strike is a *less likely* event ("above X").
    ascending_is_narrower: bool = True


def parse_strike(market: Market) -> Strike | None:
    """Extract a strike from a market, or ``None`` when it cannot be proved.

    Returning ``None`` is the safe answer and is preferred over a guess: an
    unparsed market simply yields no constraint, whereas a misparsed one yields
    a false relationship.
    """
    match = _STRIKE_RE.search(market.venue_id)
    if match:
        return Strike(
            value=float(match.group("value")),
            kind=match.group("kind"),
            ascending_is_narrower=True,
        )

    # Fall back to the title, but only when the direction is unambiguous:
    # exactly one of "above"/"below" present, and exactly one number.
    title = market.title
    above, below = bool(_ABOVE_RE.search(title)), bool(_BELOW_RE.search(title))
    if above == below:
        return None  # neither, or contradictory
    numbers = _NUMBER_RE.findall(title.replace(",", ""))
    if len(numbers) != 1:
        return None  # ambiguous: "between 70 and 75" is not a threshold
    return Strike(
        value=float(numbers[0]), kind="T", ascending_is_narrower=above
    )


def discover(
    markets: Sequence[Market], *, include_inferred: bool = False
) -> list[DiscoveredConstraint]:
    """Derive every relationship supportable from this market list."""
    found: list[DiscoveredConstraint] = []

    # -- CERTAIN: YES/NO parity, one per market -----------------------------
    # Needs no metadata at all: a market's own bid and ask crossing is a
    # risk-free trade by definition.
    for market in markets:
        found.append(
            DiscoveredConstraint(
                ComplementConstraint([market.key], event_key=market.event_key),
                Confidence.CERTAIN,
                f"{market.venue_id}: YES and NO must price to $1",
            )
        )

    by_event: dict[str, list[Market]] = defaultdict(list)
    for market in markets:
        by_event[market.event_key].append(market)

    for event_key, group in by_event.items():
        if len(group) < 2:
            continue

        # -- STRUCTURAL: strike ladders -------------------------------------
        strikes: list[tuple[Market, Strike]] = []
        for market in group:
            strike = parse_strike(market)
            if strike is not None and strike.kind == "T":
                strikes.append((market, strike))

        if len(strikes) >= 2:
            # Only compare markets whose direction convention agrees; mixing
            # "above X" with "below Y" in one ladder inverts the implication.
            for narrower_first in (True, False):
                rungs = [
                    (m, s)
                    for m, s in strikes
                    if s.ascending_is_narrower is narrower_first
                ]
                if len(rungs) < 2:
                    continue
                rungs.sort(key=lambda pair: pair[1].value, reverse=narrower_first)
                # After sorting, rungs[i] implies rungs[j] for every j > i.
                for i in range(len(rungs)):
                    for j in range(i + 1, len(rungs)):
                        narrow, broad = rungs[i][0], rungs[j][0]
                        if rungs[i][1].value == rungs[j][1].value:
                            continue
                        found.append(
                            DiscoveredConstraint(
                                MonotoneConstraint(
                                    [narrow.key, broad.key], event_key=event_key
                                ),
                                Confidence.STRUCTURAL,
                                f"{narrow.venue_id} (strike {rungs[i][1].value}) "
                                f"implies {broad.venue_id} "
                                f"(strike {rungs[j][1].value})",
                            )
                        )

        # -- INFERRED: the event's markets partition the outcome space ------
        # Requires that the group be both mutually exclusive and exhaustive,
        # which the venue does not reliably state. Off unless asked for.
        if include_inferred and len(group) >= 3:
            buckets = [
                m for m in group if (s := parse_strike(m)) and s.kind == "B"
            ]
            if len(buckets) == len(group):
                found.append(
                    DiscoveredConstraint(
                        PartitionConstraint(
                            [m.key for m in buckets], event_key=event_key
                        ),
                        Confidence.INFERRED,
                        f"{event_key}: {len(buckets)} buckets ASSUMED mutually "
                        "exclusive and exhaustive — verify before enabling",
                    )
                )

    return found


def build_constraints_for(
    markets: Sequence[Market],
    *,
    market_keys: Sequence[str] | None = None,
    include_inferred: bool = False,
) -> list[Constraint]:
    """Convenience wrapper returning only auto-enabled constraints.

    ``market_keys`` lets the backtester rebuild a constraint set from recorded
    keys alone, where full market metadata is no longer available. Only parity
    constraints can be recovered that way, which is a limitation worth stating
    plainly rather than papering over: **a backtest driven purely by recorded
    keys tests parity, not ladders.** Record the market universe alongside the
    ticks (the recorder does) to reconstruct the rest.
    """
    if market_keys is not None and not markets:
        return [ComplementConstraint([key]) for key in market_keys]

    discovered = discover(markets, include_inferred=include_inferred)
    enabled = [d for d in discovered if d.auto_enabled or include_inferred]
    by_confidence: dict[str, int] = defaultdict(int)
    for d in discovered:
        by_confidence[d.confidence.value] += 1
    log.info(
        "constraints.discovered",
        total=len(discovered),
        enabled=len(enabled),
        **by_confidence,
    )
    return [d.constraint for d in enabled]


def explain(markets: Sequence[Market], *, include_inferred: bool = True) -> str:
    """Human-readable report of what was discovered, for review before enabling."""
    discovered = discover(markets, include_inferred=include_inferred)
    lines = [f"{len(discovered)} relationships across {len(markets)} markets", ""]
    for level in Confidence:
        subset = [d for d in discovered if d.confidence is level]
        if not subset:
            continue
        status = "auto-enabled" if subset[0].auto_enabled else "NEEDS REVIEW"
        lines.append(f"{level.value.upper()} ({len(subset)}) — {status}")
        lines.extend(f"    {d.explanation}" for d in subset[:20])
        if len(subset) > 20:
            lines.append(f"    ... and {len(subset) - 20} more")
        lines.append("")
    return "\n".join(lines)
