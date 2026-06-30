"""SQLAlchemy ORM models for markets, opportunities, paper trades, and settings."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (stored naive-UTC in SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Market(Base):
    """A snapshot of a single Polymarket binary market.

    One row per market id; updated in place on each scan (upsert).
    """

    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # gamma market id
    condition_id: Mapped[str | None] = mapped_column(String, index=True)
    slug: Mapped[str | None] = mapped_column(String, index=True)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, default="Other", index=True)
    description: Mapped[str | None] = mapped_column(Text)
    resolution_source: Mapped[str | None] = mapped_column(Text)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)

    active: Mapped[bool] = mapped_column(default=True)
    closed: Mapped[bool] = mapped_column(default=False)
    enable_order_book: Mapped[bool] = mapped_column(default=True)

    # Prices are for the YES outcome token (outcome index 0).
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    last_trade_price: Mapped[float | None] = mapped_column(Float)
    one_day_price_change: Mapped[float | None] = mapped_column(Float)
    one_week_price_change: Mapped[float | None] = mapped_column(Float)

    liquidity: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    volume_24h: Mapped[float] = mapped_column(Float, default=0.0)

    outcomes: Mapped[list[str]] = mapped_column(JSON, default=list)
    outcome_prices: Mapped[list[float]] = mapped_column(JSON, default=list)
    clob_token_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Populated once the market resolves.
    winning_outcome: Mapped[str | None] = mapped_column(String)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class Opportunity(Base):
    """Current model output for a market (one row per market, upserted)."""

    __tablename__ = "opportunities"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str | None] = mapped_column(String)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, index=True)

    implied_prob_yes: Mapped[float] = mapped_column(Float)
    fair_prob_yes: Mapped[float] = mapped_column(Float)
    calibrated_market_prob: Mapped[float] = mapped_column(Float)
    external_prob: Mapped[float | None] = mapped_column(Float)
    micro_prob: Mapped[float | None] = mapped_column(Float)
    news_prob: Mapped[float | None] = mapped_column(Float)
    signals_available: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    ask_yes: Mapped[float] = mapped_column(Float)
    ask_no: Mapped[float] = mapped_column(Float)
    spread: Mapped[float] = mapped_column(Float)
    liquidity: Mapped[float] = mapped_column(Float)
    volume_24h: Mapped[float] = mapped_column(Float)

    edge_yes: Mapped[float] = mapped_column(Float)
    edge_no: Mapped[float] = mapped_column(Float)
    best_side: Mapped[str | None] = mapped_column(String)  # YES / NO / None
    best_edge: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)  # 0..1
    action: Mapped[str] = mapped_column(String, index=True)
    reason: Mapped[str] = mapped_column(Text)

    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaperTrade(Base):
    """A simulated (paper) position. No real funds are ever involved."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, index=True)
    slug: Mapped[str | None] = mapped_column(String)
    market_title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, index=True)

    outcome: Mapped[str] = mapped_column(String)  # "Yes" / "No"
    side: Mapped[str] = mapped_column(String, default="BUY")

    entry_price: Mapped[float] = mapped_column(Float)
    shares: Mapped[float] = mapped_column(Float)
    size_usd: Mapped[float] = mapped_column(Float)
    fair_prob: Mapped[float] = mapped_column(Float)  # P(our side wins) at entry
    edge: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    exit_price: Mapped[float | None] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    resolved_outcome: Mapped[str | None] = mapped_column(String)


class SettingKV(Base):
    """Runtime-adjustable settings as a small key/value store (JSON values)."""

    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )
