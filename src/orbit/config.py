"""Configuration.

Everything is environment-driven so that secrets never enter the repository
and a deployment is reproducible from a single ``.env``. Defaults are chosen
for the safest possible posture: **paper mode, demo endpoints, trading
disabled**. Turning on real money must be an explicit act in three separate
places, because every accidental-live-trading story starts with a default that
was convenient.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orbit.risk.engine import RiskLimits


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ORBIT_", extra="ignore"
    )

    # -- mode ---------------------------------------------------------------

    mode: Literal["paper", "live", "backtest"] = "paper"
    #: Second switch. Even in live mode nothing trades unless this is true, so
    #: a stray ORBIT_MODE=live cannot by itself put money at risk.
    trading_enabled: bool = False
    #: Third switch: Kalshi's demo environment. Must be turned off explicitly.
    use_demo_endpoints: bool = True

    # -- capital ------------------------------------------------------------

    bankroll_usd: float = Field(default=5_000.0, gt=0)

    # -- Kalshi -------------------------------------------------------------

    kalshi_key_id: str = ""
    kalshi_private_key_path: str = ""

    # -- Polymarket ---------------------------------------------------------

    polymarket_private_key: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_api_passphrase: str = ""
    polymarket_funder_address: str = ""
    polymarket_signature_type: int = 1

    # -- data ---------------------------------------------------------------

    data_dir: Path = Path("data")
    record_interval_s: float = 5.0
    max_markets_per_venue: int = 250

    # -- risk ---------------------------------------------------------------

    max_deployed_fraction: float = 0.60
    max_market_fraction: float = 0.10
    max_event_fraction: float = 0.20
    max_daily_loss_fraction: float = 0.05
    max_drawdown_fraction: float = 0.15
    max_orders_per_minute: int = 60
    kelly_fraction: float = 0.25
    min_order_size: int = 5

    # -- strategy -----------------------------------------------------------

    scan_interval_s: float = 2.0
    #: Minimum guaranteed profit per trade. One cent is a deliberate floor:
    #: below that, fee-model error and a single tick of slippage dominate.
    min_profit_cents: float = 1.0
    max_contracts_per_trade: int = 500

    # -- interface ----------------------------------------------------------

    api_host: str = "127.0.0.1"
    api_port: int = 8080
    #: Required to reach the dashboard. Empty disables the API entirely rather
    #: than serving an unauthenticated control surface for a live account.
    api_token: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_email: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    log_level: str = "INFO"
    log_json: bool = False

    # -- validation ---------------------------------------------------------

    @field_validator("kelly_fraction")
    @classmethod
    def _kelly_must_be_fractional(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError("kelly_fraction must be in (0, 1]")
        if v > 0.5:
            raise ValueError(
                "kelly_fraction above 0.5 is not supported: growth peaks at full "
                "Kelly and reaches zero near 2x, so estimation error at this "
                "level risks ruin rather than under-performance"
            )
        return v

    @model_validator(mode="after")
    def _live_mode_requires_explicit_intent(self) -> Settings:
        """Refuse to start in a half-configured live state.

        Failing loudly at startup is much cheaper than discovering at 3am that
        the system was pointed at production with demo credentials, or was
        quietly paper-trading while believed to be live.
        """
        if self.mode == "live" and self.trading_enabled:
            if self.use_demo_endpoints:
                raise ValueError(
                    "live trading with use_demo_endpoints=True: set "
                    "ORBIT_USE_DEMO_ENDPOINTS=false to trade real money, or "
                    "ORBIT_TRADING_ENABLED=false to stay in simulation"
                )
            if not (self.kalshi_key_id or self.polymarket_private_key):
                raise ValueError("live trading enabled but no venue credentials set")
            if not self.api_token:
                raise ValueError(
                    "live trading requires ORBIT_API_TOKEN so the dashboard and "
                    "kill switch are not exposed unauthenticated"
                )
        return self

    # -- derived ------------------------------------------------------------

    @property
    def bankroll_pips(self) -> int:
        return int(self.bankroll_usd * 10_000)

    @property
    def min_profit_pips(self) -> int:
        return int(self.min_profit_cents * 100)

    @property
    def is_live(self) -> bool:
        """True only when all three independent switches agree."""
        return (
            self.mode == "live"
            and self.trading_enabled
            and not self.use_demo_endpoints
        )

    @property
    def has_kalshi(self) -> bool:
        return bool(self.kalshi_key_id and self.kalshi_private_key_path)

    @property
    def has_polymarket(self) -> bool:
        return bool(self.polymarket_private_key)

    def risk_limits(self) -> RiskLimits:
        return RiskLimits(
            max_deployed_fraction=self.max_deployed_fraction,
            max_market_fraction=self.max_market_fraction,
            max_event_fraction=self.max_event_fraction,
            max_daily_loss_fraction=self.max_daily_loss_fraction,
            max_drawdown_fraction=self.max_drawdown_fraction,
            max_orders_per_minute=self.max_orders_per_minute,
            min_order_size=self.min_order_size,
        )

    def describe(self) -> dict[str, object]:
        """Startup banner. Never includes secrets."""
        return {
            "mode": self.mode,
            "trading_enabled": self.trading_enabled,
            "endpoints": "demo" if self.use_demo_endpoints else "PRODUCTION",
            "effective": "LIVE — REAL MONEY" if self.is_live else "simulation only",
            "bankroll_usd": self.bankroll_usd,
            "venues": [
                v
                for v, on in (
                    ("kalshi", self.has_kalshi),
                    ("polymarket", self.has_polymarket),
                )
                if on
            ],
            "data_dir": str(self.data_dir),
            "api": f"{self.api_host}:{self.api_port}" if self.api_token else "disabled",
            "alerts": [
                name
                for name, on in (
                    ("telegram", bool(self.telegram_bot_token and self.telegram_chat_id)),
                    ("email", bool(self.alert_email and self.smtp_host)),
                )
                if on
            ],
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
