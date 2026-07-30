"""Alerting: Telegram push and daily email.

Alerting exists to answer one question without opening a laptop: *is anything
wrong?* It is therefore tuned against noise. A bot that messages on every fill
trains you to ignore it, and the message you then ignore is the kill-switch
notification.

Rules:
* Critical events (kill switch, reconciliation mismatch, venue down) always
  send.
* Routine events are rate-limited and deduplicated.
* Daily summary sends once, whether or not anything happened, so silence is
  never ambiguous — no summary means the *process* is down.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    CRITICAL = 30


@dataclass
class Alert:
    severity: Severity
    title: str
    body: str
    #: Events sharing a key are deduplicated within the cooldown window.
    dedup_key: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def format(self) -> str:
        icon = {
            Severity.INFO: "•",
            Severity.WARNING: "!",
            Severity.CRITICAL: "!!",
        }[self.severity]
        return f"{icon} *{self.title}*\n{self.body}"


class AlertManager:
    """Fans alerts out to configured channels, with deduplication."""

    def __init__(
        self,
        *,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        min_severity: Severity = Severity.WARNING,
        dedup_window_s: float = 900.0,
    ) -> None:
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.min_severity = min_severity
        self.dedup_window = timedelta(seconds=dedup_window_s)
        self._last_sent: dict[str, datetime] = {}
        self.history: list[Alert] = []

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    def _should_send(self, alert: Alert) -> bool:
        if alert.severity < self.min_severity:
            return False
        # Critical alerts bypass deduplication: if the kill switch trips twice
        # for different reasons, both matter.
        if alert.severity is Severity.CRITICAL:
            return True
        key = alert.dedup_key or alert.title
        last = self._last_sent.get(key)
        return not (last and alert.timestamp - last < self.dedup_window)

    async def send(self, alert: Alert) -> bool:
        """Deliver an alert. Never raises — alerting must not break trading."""
        self.history.append(alert)
        del self.history[:-500]
        if not self._should_send(alert):
            return False
        self._last_sent[alert.dedup_key or alert.title] = alert.timestamp

        log.info("alert", severity=alert.severity.name, title=alert.title)
        if self.telegram_enabled:
            with contextlib.suppress(Exception):
                await self._send_telegram(alert.format())
        return True

    async def _send_telegram(self, text: str) -> None:
        import aiohttp

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
            url, json=payload
        ) as resp:
            if resp.status >= 400:
                log.warning("alert.telegram_failed", status=resp.status)

    # -- convenience --------------------------------------------------------

    async def kill_switch_tripped(self, reason: str) -> None:
        await self.send(
            Alert(
                Severity.CRITICAL,
                "TRADING HALTED",
                f"Kill switch tripped: {reason}\n\n"
                "Trading will not resume until you reset it from the dashboard.",
                dedup_key="kill",
            )
        )

    async def reconciliation_failed(self, problems: list[str]) -> None:
        await self.send(
            Alert(
                Severity.CRITICAL,
                "POSITION MISMATCH",
                "Local state disagrees with the venue:\n"
                + "\n".join(f"  {p}" for p in problems[:10]),
                dedup_key="reconcile",
            )
        )

    async def venue_down(self, venue: str, error: str) -> None:
        await self.send(
            Alert(
                Severity.WARNING,
                f"{venue} unreachable",
                f"Recorder is retrying. Last error: {error}",
                dedup_key=f"venue_down:{venue}",
            )
        )

    async def drawdown_warning(self, fraction: float, limit: float) -> None:
        await self.send(
            Alert(
                Severity.WARNING,
                "Drawdown approaching limit",
                f"Currently {fraction:.1%} against a {limit:.1%} limit. "
                "Trading halts automatically if it is reached.",
                dedup_key="drawdown",
            )
        )

    async def daily_summary(self, status: dict[str, Any]) -> None:
        """Sent every day regardless, so silence unambiguously means down."""
        strat = status.get("strategy", {})
        risk = status.get("risk", {})
        promo = status.get("promotion", {})
        net = strat.get("net_pnl_usd", 0.0)
        lines = [
            f"Net PnL: ${net:,.2f}",
            f"Bankroll: ${risk.get('bankroll_usd', 0):,.2f}",
            f"Trades: {strat.get('trades_completed', 0)} of "
            f"{strat.get('trades_attempted', 0)} attempted",
            f"Fill rate: {strat.get('fill_rate', 0):.0%}",
            f"Fees: ${strat.get('fees_usd', 0):,.2f}",
            f"Drawdown: {risk.get('drawdown_fraction', 0):.1%}",
            f"Mode: {strat.get('mode', '?')}",
        ]
        if promo.get("ready_for_live"):
            lines.append("\nReady for live promotion — all gates cleared.")
        elif promo.get("blockers"):
            lines.append("\nPaper gates outstanding:")
            lines += [f"  {b}" for b in promo["blockers"]]

        await self.send(
            Alert(
                Severity.INFO,
                f"Daily summary {datetime.now(UTC):%Y-%m-%d}",
                "\n".join(lines),
                dedup_key=f"daily:{datetime.now(UTC):%Y-%m-%d}",
            )
        )


class DailyReporter:
    """Fires the daily summary once per UTC day."""

    def __init__(self, alerts: AlertManager, hour_utc: int = 23) -> None:
        self.alerts = alerts
        self.hour_utc = hour_utc
        self._last_sent_date: str | None = None

    async def maybe_send(self, status: dict[str, Any]) -> bool:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        if self._last_sent_date == today or now.hour < self.hour_utc:
            return False
        self._last_sent_date = today
        await self.alerts.daily_summary(status)
        return True

    async def run(self, status_fn: Any, *, interval_s: float = 300.0) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.maybe_send(status_fn())
            await asyncio.sleep(interval_s)
