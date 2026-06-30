"""Application configuration.

Defaults live here; they can be overridden via environment variables or a
``.env`` file (see ``.env.example``). A small subset of these values is also
*runtime-adjustable* from the dashboard Settings panel — those overrides are
persisted in the database and layered on top of these defaults at scan time
(see :mod:`backend.services.settings_store`).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = the directory that contains this `backend/` package's parent.
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from env / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Safety switches ---------------------------------------------------
    paper_trading_enabled: bool = True
    live_trading_enabled: bool = False  # never honored by the MVP; see README

    # ---- Polymarket public API --------------------------------------------
    polymarket_gamma_base: str = "https://gamma-api.polymarket.com"
    polymarket_clob_base: str = "https://clob.polymarket.com"
    http_min_interval_seconds: float = 0.25
    http_timeout_seconds: float = 20.0
    http_cache_ttl_seconds: float = 30.0

    # ---- Scanner / scheduler ----------------------------------------------
    scan_interval_seconds: int = 300
    scan_on_startup: bool = True
    market_fetch_limit: int = 200

    # ---- Bankroll & risk (paper) ------------------------------------------
    paper_bankroll: float = 1000.0
    max_position_pct: float = 0.01
    max_market_exposure_pct: float = 0.05
    max_category_exposure_pct: float = 0.15
    allow_averaging: bool = False

    # ---- Quality filters ---------------------------------------------------
    min_liquidity: float = 5000.0
    min_volume_24h: float = 500.0
    max_spread: float = 0.05
    max_days_to_resolution: int = 400
    strong_liquidity_override: float = 50000.0
    allow_extreme_prices: bool = False
    extreme_price_band: float = 0.05

    # ---- Edge / fee model --------------------------------------------------
    estimated_fee: float = 0.0
    safety_margin: float = 0.015
    min_edge_to_trade: float = 0.025

    # ---- External signals / news ------------------------------------------
    external_signals_csv: str = "data/external_signals.csv"
    news_signal_enabled: bool = False
    anthropic_api_key: str | None = None

    # ---- Derived paths -----------------------------------------------------
    @property
    def database_url(self) -> str:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(DATA_DIR / 'scanner.sqlite3').as_posix()}"

    @property
    def external_signals_path(self) -> Path:
        p = Path(self.external_signals_csv)
        return p if p.is_absolute() else ROOT_DIR / p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()


# Convenient module-level handle.
settings = get_settings()
