"""Return-target feasibility.

Answers the question every trading plan starts with - *what would it actually
take to make X% per month?* - and, more importantly, what that configuration
costs in risk of ruin.

The arithmetic that makes high monthly returns conceivable at small size is
**turnover**. Kalshi's daily-settling markets recycle capital roughly 21 times
a month, so

    monthly return ~= cycles * deployment * edge_per_cycle

A 1% edge per cycle at 50% deployment across 21 cycles is ~10%/month. The same
1% edge applied twice a month is 1%. This is why a $5,000 account can target
returns that no large fund can: not because it is smarter, but because it can
recycle its entire balance through opportunities too small for anyone else to
bother pricing.

Two hard limits keep that from being a licence to print money, and both are
modelled here:

**Capacity.** Deployment is bounded by how much size the book will actually
absorb. Weather brackets run $5-15k per side with a $25,000 position cap, so
the strategy that returns 10%/month on $5,000 returns far less on $50,000. The
high-return path and the grow-to-serious-capital path are in tension, and
:func:`capacity_limited_return` makes that explicit.

**Estimation error.** Every figure above assumes the edge is *known*. It is
estimated, and aggressive deployment against an estimated edge is how accounts
die - the simulation prices that directly rather than assuming it away.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetRequirement:
    """What a monthly return target demands of edge, deployment and turnover."""

    monthly_target: float
    cycles_per_month: float
    deployment: float
    required_edge_per_cycle: float

    @property
    def required_edge_pp(self) -> float:
        """Edge expressed in percentage points of probability."""
        return self.required_edge_per_cycle * 100

    @property
    def is_plausible(self) -> bool:
        """Whether the required edge is within documented reality.

        Roughly 2pp is the ceiling of what has been measured on these venues by
        credible operators; beyond that the requirement is not a trading plan,
        it is a wish.
        """
        return self.required_edge_pp <= 2.0


def required_edge(
    *, monthly_target: float, cycles_per_month: float = 21.0, deployment: float = 0.5
) -> TargetRequirement:
    """Edge per cycle needed to hit a monthly return target.

    Uses the geometric relation ``(1 + d*e)^n = 1 + target`` rather than the
    naive ``n*d*e``, because returns compound within the month and the naive
    version overstates the required edge at high turnover.
    """
    if cycles_per_month <= 0 or deployment <= 0:
        raise ValueError("cycles and deployment must be positive")
    growth = (1.0 + monthly_target) ** (1.0 / cycles_per_month) - 1.0
    return TargetRequirement(
        monthly_target=monthly_target,
        cycles_per_month=cycles_per_month,
        deployment=deployment,
        required_edge_per_cycle=growth / deployment,
    )


@dataclass(frozen=True)
class CapacityResult:
    """Monthly return after the book's depth caps deployment."""

    bankroll: float
    deployed_per_cycle: float
    effective_deployment: float
    monthly_return: float
    monthly_dollars: float
    capacity_bound: bool


def capacity_limited_return(
    *,
    bankroll: float,
    edge_per_cycle: float,
    cycles_per_month: float = 21.0,
    max_deployment: float = 1.0,
    capacity_per_cycle: float = 2_000.0,
) -> CapacityResult:
    """Monthly return once book depth caps how much can be deployed.

    ``capacity_per_cycle`` is the dollar size the available opportunities can
    absorb in one settlement cycle. Below that, deployment is a choice; above
    it, deployment is capped and the *percentage* return decays as ``1/bankroll``
    even though the dollar profit stays flat.

    This is the mechanism that makes a high monthly percentage a small-account
    phenomenon rather than a scalable business.
    """
    wanted = bankroll * max_deployment
    deployed = min(wanted, capacity_per_cycle)
    effective_deployment = deployed / bankroll if bankroll > 0 else 0.0
    per_cycle = effective_deployment * edge_per_cycle
    monthly = (1.0 + per_cycle) ** cycles_per_month - 1.0
    return CapacityResult(
        bankroll=bankroll,
        deployed_per_cycle=deployed,
        effective_deployment=effective_deployment,
        monthly_return=monthly,
        monthly_dollars=bankroll * monthly,
        capacity_bound=deployed < wanted,
    )


@dataclass(frozen=True)
class RuinEstimate:
    """Outcome distribution for a sizing configuration."""

    trials: int
    median_final: float
    p05_final: float
    p95_final: float
    prob_ruin: float
    prob_hit_target: float
    prob_loss: float

    def summary(self) -> str:
        return (
            f"median ${self.median_final:,.0f}  "
            f"5-95% ${self.p05_final:,.0f}-${self.p95_final:,.0f}  "
            f"P(ruin) {self.prob_ruin:.1%}  "
            f"P(target) {self.prob_hit_target:.1%}  "
            f"P(down) {self.prob_loss:.1%}"
        )


def simulate(
    *,
    bankroll: float = 5_000.0,
    believed_edge: float = 0.02,
    true_edge_sd: float = 0.02,
    deployment: float = 0.5,
    cycles: int = 252,
    contract_price: float = 0.97,
    target_multiple: float = 2.0,
    ruin_fraction: float = 0.3,
    trials: int = 4_000,
    seed: int = 7,
) -> RuinEstimate:
    """Monte-Carlo a sizing plan, with the edge itself uncertain.

    ``true_edge_sd`` is the crux and the reason this function exists. Setting it
    to zero models a trader who *knows* their edge, which nobody does; the
    default draws the true edge from a distribution centred on the believed
    value, so the simulation prices being confidently wrong as well as unlucky.

    Trading at ``contract_price`` near 1.0 wins small and loses large - the
    payoff geometry at 97c is roughly 32:1 against - so a modest overestimate of
    the edge flips the sign of the whole plan. That asymmetry does not show up
    in an expected-value calculation and is the main thing this simulation is
    for.
    """
    rng = random.Random(seed)
    finals: list[float] = []
    ruined = hit_target = lost = 0

    for _ in range(trials):
        # The edge you actually have, not the one you believe you have.
        true_edge = rng.gauss(believed_edge, true_edge_sd)
        win_prob = min(0.9999, max(0.0001, contract_price + true_edge))

        balance = bankroll
        for _ in range(cycles):
            stake = balance * deployment
            if stake < 1.0:
                break
            # Buying at `contract_price`: win (1-p)/p per unit staked, else -1.
            if rng.random() < win_prob:
                balance += stake * (1.0 - contract_price) / contract_price
            else:
                balance -= stake
            if balance <= bankroll * ruin_fraction:
                break

        finals.append(balance)
        if balance <= bankroll * ruin_fraction:
            ruined += 1
        if balance >= bankroll * target_multiple:
            hit_target += 1
        if balance < bankroll:
            lost += 1

    finals.sort()
    n = len(finals)
    return RuinEstimate(
        trials=trials,
        median_final=finals[n // 2],
        p05_final=finals[int(n * 0.05)],
        p95_final=finals[int(n * 0.95)],
        prob_ruin=ruined / trials,
        prob_hit_target=hit_target / trials,
        prob_loss=lost / trials,
    )


def feasibility_report(
    *,
    monthly_targets: tuple[float, ...] = (0.02, 0.05, 0.10, 0.20),
    cycles_per_month: float = 21.0,
    deployments: tuple[float, ...] = (0.25, 0.50, 1.00),
) -> str:
    """Table of what each monthly target demands, for a plan document."""
    lines = [
        f"Required edge per cycle ({cycles_per_month:.0f} settlement cycles/month)",
        "",
        f"{'target/mo':>10} " + " ".join(f"{d:>13.0%} deployed" for d in deployments),
    ]
    for target in monthly_targets:
        cells = []
        for dep in deployments:
            req = required_edge(
                monthly_target=target,
                cycles_per_month=cycles_per_month,
                deployment=dep,
            )
            mark = "" if req.is_plausible else "  <-- implausible"
            cells.append(f"{req.required_edge_pp:>12.2f}pp{mark}")
        lines.append(f"{target:>10.0%} " + " ".join(cells))
    lines += [
        "",
        "Roughly 2pp is the ceiling credibly measured on these venues.",
        "Anything above it is a wish, not a plan.",
    ]
    return "\n".join(lines)


def growth_to_income(
    *,
    monthly_income_target: float = 1_000.0,
    start: float = 5_000.0,
    monthly_rate: float = 0.03,
    monthly_contribution: float = 0.0,
    max_months: int = 600,
) -> dict[str, float]:
    """Months until returns alone reach a monthly income target.

    Separates the two engines — trading return and outside contribution — and
    reports where they cross over, because early on the contribution usually
    does far more work than the edge does.
    """
    target_balance = monthly_income_target / monthly_rate
    balance, months, crossover = start, 0, None
    while balance < target_balance and months < max_months:
        if crossover is None and balance * monthly_rate >= monthly_contribution > 0:
            crossover = months
        balance = balance * (1.0 + monthly_rate) + monthly_contribution
        months += 1
    return {
        "target_balance": target_balance,
        "months": months,
        "years": months / 12.0,
        "final_balance": balance,
        "crossover_month": crossover if crossover is not None else math.nan,
    }
