"""Return-target feasibility.

The properties that matter are the uncomfortable ones: that a high monthly
percentage is a small-account phenomenon, that the dollar profit stops growing
once capacity binds, and that estimation error hollows out the downside without
moving the median.
"""

from __future__ import annotations

import pytest

from orbit.risk.targets import (
    capacity_limited_return,
    feasibility_report,
    growth_to_income,
    required_edge,
    simulate,
)


class TestRequiredEdge:
    def test_turnover_is_what_makes_high_returns_conceivable(self):
        """The same target needs far less edge when capital recycles often."""
        daily = required_edge(monthly_target=0.10, cycles_per_month=21, deployment=0.5)
        twice = required_edge(monthly_target=0.10, cycles_per_month=2, deployment=0.5)
        assert daily.required_edge_pp < twice.required_edge_pp / 5

    def test_ten_percent_a_month_is_arithmetically_plausible(self):
        """Under 2pp at ordinary deployment — demanding, not absurd."""
        r = required_edge(monthly_target=0.10, deployment=0.5)
        assert r.required_edge_pp < 1.0
        assert r.is_plausible

    def test_twenty_percent_a_month_stops_being_plausible(self):
        """At modest deployment it needs an edge nobody has documented."""
        r = required_edge(monthly_target=0.20, deployment=0.25)
        assert r.required_edge_pp > 2.0
        assert not r.is_plausible

    def test_more_deployment_lowers_the_required_edge(self):
        edges = [
            required_edge(monthly_target=0.10, deployment=d).required_edge_pp
            for d in (0.1, 0.25, 0.5, 1.0)
        ]
        assert edges == sorted(edges, reverse=True)

    def test_uses_geometric_not_naive_compounding(self):
        """Naive n*d*e overstates the requirement at high turnover."""
        r = required_edge(monthly_target=0.10, cycles_per_month=21, deployment=1.0)
        naive = 0.10 / 21
        assert r.required_edge_per_cycle < naive

    def test_rejects_degenerate_inputs(self):
        with pytest.raises(ValueError, match="must be positive"):
            required_edge(monthly_target=0.1, deployment=0.0)


class TestCapacityCeiling:
    def test_percentage_return_collapses_as_the_account_grows(self):
        """The core tension: high percentages are a small-account phenomenon."""
        returns = [
            capacity_limited_return(
                bankroll=float(b), edge_per_cycle=0.01, capacity_per_cycle=2_500.0
            ).monthly_return
            for b in (5_000, 25_000, 100_000)
        ]
        assert returns == sorted(returns, reverse=True)
        assert returns[0] > returns[-1] * 10

    def test_dollar_profit_goes_flat_once_capacity_binds(self):
        """A bigger account buys a smaller percentage, not more money.

        This is the finding that reframes the whole plan: past the capacity
        ceiling, growing the account does not grow the income.
        """
        small = capacity_limited_return(
            bankroll=25_000.0, edge_per_cycle=0.01, capacity_per_cycle=2_500.0
        )
        large = capacity_limited_return(
            bankroll=100_000.0, edge_per_cycle=0.01, capacity_per_cycle=2_500.0
        )
        assert small.capacity_bound and large.capacity_bound
        assert large.monthly_dollars == pytest.approx(small.monthly_dollars, rel=0.05)

    def test_below_capacity_deployment_is_a_choice(self):
        result = capacity_limited_return(
            bankroll=1_000.0, edge_per_cycle=0.01, capacity_per_cycle=10_000.0
        )
        assert not result.capacity_bound
        assert result.effective_deployment == pytest.approx(1.0)

    def test_more_capacity_raises_the_ceiling(self):
        """Which is why the path to real income runs through breadth."""
        narrow = capacity_limited_return(
            bankroll=50_000.0, edge_per_cycle=0.01, capacity_per_cycle=2_500.0
        )
        broad = capacity_limited_return(
            bankroll=50_000.0, edge_per_cycle=0.01, capacity_per_cycle=25_000.0
        )
        assert broad.monthly_dollars > narrow.monthly_dollars * 5


class TestRuinSimulation:
    def test_heavier_deployment_raises_ruin_risk(self):
        probs = [
            simulate(deployment=d, trials=1500).prob_ruin
            for d in (0.10, 0.25, 0.50)
        ]
        assert probs == sorted(probs)

    def test_estimation_error_hollows_out_the_downside(self):
        """The median barely moves; the 5th percentile collapses.

        Being wrong about your edge does not cost you the average outcome. It
        costs you the bad ones, which is exactly where ruin lives.
        """
        known = simulate(true_edge_sd=0.0, deployment=0.25, trials=2000)
        unsure = simulate(true_edge_sd=0.02, deployment=0.25, trials=2000)
        assert unsure.median_final == pytest.approx(known.median_final, rel=0.05)
        assert unsure.p05_final < known.p05_final / 2
        assert unsure.prob_ruin > known.prob_ruin

    def test_full_deployment_risks_ruin_even_with_a_known_edge(self):
        """At 97c the payoff is ~32:1 against; a losing streak is fatal."""
        assert simulate(true_edge_sd=0.0, deployment=1.0, trials=1500).prob_ruin > 0.5

    def test_a_genuinely_negative_edge_reliably_loses(self):
        r = simulate(believed_edge=-0.02, true_edge_sd=0.0, deployment=0.25,
                     trials=1500)
        assert r.prob_loss > 0.9

    def test_results_are_deterministic_for_a_given_seed(self):
        a = simulate(trials=500, seed=42)
        b = simulate(trials=500, seed=42)
        assert a.median_final == b.median_final


class TestGrowthToIncome:
    def test_higher_returns_reach_the_income_target_sooner(self):
        months = [
            growth_to_income(monthly_rate=r)["months"] for r in (0.01, 0.02, 0.03, 0.05)
        ]
        assert months == sorted(months, reverse=True)

    def test_contributions_dominate_early(self):
        """The practical point: for the first stretch, savings beat edge."""
        alone = growth_to_income(monthly_rate=0.02)["months"]
        with_savings = growth_to_income(monthly_rate=0.02, monthly_contribution=500)[
            "months"
        ]
        assert with_savings < alone / 2

    def test_target_balance_is_income_over_rate(self):
        out = growth_to_income(monthly_income_target=1000.0, monthly_rate=0.02)
        assert out["target_balance"] == pytest.approx(50_000.0)

    def test_reports_when_returns_overtake_contributions(self):
        out = growth_to_income(monthly_rate=0.03, monthly_contribution=500.0)
        assert out["crossover_month"] > 0


class TestReport:
    def test_report_flags_implausible_targets(self):
        text = feasibility_report()
        assert "implausible" in text
        assert "2pp" in text
