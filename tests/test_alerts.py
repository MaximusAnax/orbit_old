"""Alert routing and deduplication.

The failure mode being defended against is not "an alert did not send" but
"so many alerts sent that the operator stopped reading them". These tests pin
the noise controls, and equally that the noise controls never suppress a
critical message.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from orbit.alerts import Alert, AlertManager, DailyReporter, Severity


@pytest.fixture
def alerts():
    # No Telegram configured: send() still records and returns its decision,
    # so routing logic is testable without any network.
    return AlertManager(min_severity=Severity.WARNING, dedup_window_s=600)


class TestSeverityFiltering:
    async def test_info_is_suppressed_below_the_threshold(self, alerts):
        assert not await alerts.send(Alert(Severity.INFO, "routine", "body"))

    async def test_warning_sends(self, alerts):
        assert await alerts.send(Alert(Severity.WARNING, "problem", "body"))

    async def test_critical_sends(self, alerts):
        assert await alerts.send(Alert(Severity.CRITICAL, "very bad", "body"))

    async def test_lowering_the_threshold_admits_info(self):
        mgr = AlertManager(min_severity=Severity.INFO)
        assert await mgr.send(Alert(Severity.INFO, "routine", "body"))


class TestDeduplication:
    async def test_repeat_warnings_are_suppressed_within_the_window(self, alerts):
        first = Alert(Severity.WARNING, "venue down", "x", dedup_key="v")
        assert await alerts.send(first)
        assert not await alerts.send(
            Alert(Severity.WARNING, "venue down", "x", dedup_key="v")
        )

    async def test_the_window_expires(self, alerts):
        await alerts.send(Alert(Severity.WARNING, "venue down", "x", dedup_key="v"))
        later = Alert(
            Severity.WARNING, "venue down", "x", dedup_key="v",
            timestamp=datetime.now(UTC) + timedelta(seconds=700),
        )
        assert await alerts.send(later)

    async def test_different_keys_are_independent(self, alerts):
        assert await alerts.send(Alert(Severity.WARNING, "a", "x", dedup_key="a"))
        assert await alerts.send(Alert(Severity.WARNING, "b", "x", dedup_key="b"))

    async def test_critical_alerts_bypass_deduplication(self, alerts):
        """Two kill-switch trips for different reasons both matter."""
        assert await alerts.send(
            Alert(Severity.CRITICAL, "halted", "drawdown", dedup_key="kill")
        )
        assert await alerts.send(
            Alert(Severity.CRITICAL, "halted", "reconciliation", dedup_key="kill")
        )

    async def test_history_is_recorded_even_when_suppressed(self, alerts):
        """Suppressed is not lost: the dashboard should still show it."""
        await alerts.send(Alert(Severity.INFO, "routine", "body"))
        assert len(alerts.history) == 1

    async def test_history_is_bounded(self, alerts):
        for i in range(600):
            await alerts.send(Alert(Severity.INFO, f"n{i}", "body"))
        assert len(alerts.history) == 500


class TestConvenienceAlerts:
    async def test_kill_switch_is_critical(self, alerts):
        await alerts.kill_switch_tripped("drawdown 15%")
        assert alerts.history[-1].severity is Severity.CRITICAL
        assert "drawdown" in alerts.history[-1].body

    async def test_reconciliation_mismatch_is_critical(self, alerts):
        await alerts.reconciliation_failed(["kalshi:A: local 10 != venue 5"])
        last = alerts.history[-1]
        assert last.severity is Severity.CRITICAL
        assert "kalshi:A" in last.body

    async def test_reconciliation_body_is_truncated(self, alerts):
        await alerts.reconciliation_failed([f"m{i}: mismatch" for i in range(50)])
        assert alerts.history[-1].body.count("\n") <= 11

    async def test_venue_down_is_a_warning_not_a_page(self, alerts):
        await alerts.venue_down("kalshi", "connection reset")
        assert alerts.history[-1].severity is Severity.WARNING


class TestDailySummary:
    def _status(self, **over):
        base = {
            "strategy": {
                "net_pnl_usd": 12.34, "trades_completed": 10,
                "trades_attempted": 12, "fill_rate": 0.83,
                "fees_usd": 3.2, "mode": "paper",
            },
            "risk": {"bankroll_usd": 5012.34, "drawdown_fraction": 0.01},
            "promotion": {"ready_for_live": False, "blockers": ["only 10/50 trades"]},
        }
        base.update(over)
        return base

    async def test_summary_includes_the_headline_numbers(self, alerts):
        await alerts.daily_summary(self._status())
        body = alerts.history[-1].body
        assert "$12.34" in body
        assert "10 of 12" in body
        assert "83%" in body

    async def test_summary_surfaces_promotion_blockers(self, alerts):
        await alerts.daily_summary(self._status())
        assert "only 10/50 trades" in alerts.history[-1].body

    async def test_summary_announces_readiness(self, alerts):
        await alerts.daily_summary(
            self._status(promotion={"ready_for_live": True, "blockers": []})
        )
        assert "Ready for live" in alerts.history[-1].body

    async def test_summary_survives_a_partial_status_payload(self, alerts):
        """A reporting bug must not take out the alerting path."""
        await alerts.daily_summary({})
        assert alerts.history

    async def test_reporter_fires_once_per_day(self, alerts):
        reporter = DailyReporter(alerts, hour_utc=0)  # always past the hour
        assert await reporter.maybe_send(self._status())
        assert not await reporter.maybe_send(self._status())

    async def test_reporter_waits_for_its_hour(self, alerts):
        reporter = DailyReporter(alerts, hour_utc=23)
        if datetime.now(UTC).hour < 23:
            assert not await reporter.maybe_send(self._status())


class TestFormatting:
    def test_severity_prefixes_are_distinct(self):
        rendered = {
            Alert(sev, "t", "b").format()[:2]
            for sev in (Severity.INFO, Severity.WARNING, Severity.CRITICAL)
        }
        assert len(rendered) == 3

    def test_title_and_body_both_appear(self):
        text = Alert(Severity.WARNING, "Title here", "Body here").format()
        assert "Title here" in text and "Body here" in text
