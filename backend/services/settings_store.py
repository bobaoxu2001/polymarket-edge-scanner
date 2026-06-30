"""Runtime-adjustable settings, layered on top of :mod:`backend.config`.

Defaults come from environment/config. The dashboard Settings panel can override
a subset of them; overrides are persisted in the ``settings_kv`` table so they
survive restarts. Anything not overridden falls back to the config default.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from sqlalchemy.orm import Session

from backend.config import settings as cfg
from backend.models import SettingKV

# Keys exposed to the dashboard Settings panel.
_OVERRIDABLE = {
    "paper_trading_enabled",
    "paper_bankroll",
    "min_liquidity",
    "min_volume_24h",
    "max_spread",
    "min_edge_to_trade",
    "safety_margin",
    "estimated_fee",
    "max_days_to_resolution",
    "allow_extreme_prices",
    "categories_filter",
}


@dataclass
class EffectiveSettings:
    """The settings actually used by a scan run (defaults + DB overrides)."""

    paper_trading_enabled: bool = cfg.paper_trading_enabled
    paper_bankroll: float = cfg.paper_bankroll
    min_liquidity: float = cfg.min_liquidity
    min_volume_24h: float = cfg.min_volume_24h
    max_spread: float = cfg.max_spread
    min_edge_to_trade: float = cfg.min_edge_to_trade
    safety_margin: float = cfg.safety_margin
    estimated_fee: float = cfg.estimated_fee
    max_days_to_resolution: int = cfg.max_days_to_resolution
    allow_extreme_prices: bool = cfg.allow_extreme_prices
    # Empty list == include every category.
    categories_filter: list[str] = field(default_factory=list)

    # Non-overridable but commonly needed downstream.
    max_position_pct: float = cfg.max_position_pct
    max_market_exposure_pct: float = cfg.max_market_exposure_pct
    max_category_exposure_pct: float = cfg.max_category_exposure_pct
    allow_averaging: bool = cfg.allow_averaging
    strong_liquidity_override: float = cfg.strong_liquidity_override
    extreme_price_band: float = cfg.extreme_price_band

    def as_public_dict(self) -> dict:
        """Only the overridable keys (what the Settings API exposes)."""
        return {k: v for k, v in asdict(self).items() if k in _OVERRIDABLE}


def get_effective_settings(session: Session) -> EffectiveSettings:
    """Build the effective settings by applying DB overrides over defaults."""
    eff = EffectiveSettings()
    rows = {row.key: row.value for row in session.query(SettingKV).all()}
    valid = {f.name for f in fields(EffectiveSettings)}
    for key, val in rows.items():
        if key in valid and val is not None:
            setattr(eff, key, val)
    return eff


def update_settings(session: Session, updates: dict) -> EffectiveSettings:
    """Persist a partial settings update; ignores unknown / non-overridable keys."""
    for key, val in updates.items():
        if key not in _OVERRIDABLE or val is None:
            continue
        row = session.get(SettingKV, key)
        if row is None:
            session.add(SettingKV(key=key, value=val))
        else:
            row.value = val
    session.flush()
    return get_effective_settings(session)
