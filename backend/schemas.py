"""Pydantic v2 schemas for API request/response payloads."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MarketOut(_ORM):
    id: str
    slug: str | None = None
    question: str
    category: str
    description: str | None = None
    resolution_source: str | None = None
    end_date: datetime | None = None
    active: bool
    closed: bool
    enable_order_book: bool
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    last_trade_price: float | None = None
    one_day_price_change: float | None = None
    one_week_price_change: float | None = None
    liquidity: float
    volume: float
    volume_24h: float
    outcomes: list[str] = Field(default_factory=list)
    outcome_prices: list[float] = Field(default_factory=list)
    winning_outcome: str | None = None
    updated_at: datetime | None = None


class OpportunityOut(_ORM):
    market_id: str
    slug: str | None = None
    question: str
    category: str
    implied_prob_yes: float
    fair_prob_yes: float
    calibrated_market_prob: float
    external_prob: float | None = None
    micro_prob: float | None = None
    news_prob: float | None = None
    signals_available: dict[str, Any] = Field(default_factory=dict)
    ask_yes: float
    ask_no: float
    spread: float
    liquidity: float
    volume_24h: float
    edge_yes: float
    edge_no: float
    best_side: str | None = None
    best_edge: float
    confidence: float
    action: str
    reason: str
    scanned_at: datetime | None = None


class PaperTradeOut(_ORM):
    id: int
    market_id: str
    slug: str | None = None
    market_title: str
    category: str
    outcome: str
    side: str
    entry_price: float
    shares: float
    size_usd: float
    fair_prob: float
    edge: float
    confidence: float
    reason: str
    status: str
    opened_at: datetime
    closed_at: datetime | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None
    resolved_outcome: str | None = None
    # Computed, not stored:
    current_price: float | None = None
    current_value: float | None = None
    unrealized_pnl: float | None = None


class ModelBreakdown(BaseModel):
    """Transparent decomposition of how a fair probability was produced."""

    implied_prob_yes: float
    calibrated_market_prob: float
    external_prob: float | None
    micro_prob: float | None
    news_prob: float | None
    weights: dict[str, float]
    signals_available: dict[str, bool]
    fair_prob_yes: float
    notes: list[str] = Field(default_factory=list)


class MarketDetailOut(BaseModel):
    market: MarketOut
    opportunity: OpportunityOut | None = None
    model_breakdown: ModelBreakdown | None = None
    orderbook: dict[str, Any] | None = None
    risk_notes: list[str] = Field(default_factory=list)


class OverviewMetrics(BaseModel):
    active_markets_scanned: int
    opportunities_found: int
    open_paper_trades: int
    paper_bankroll: float
    cash: float
    open_position_value: float
    equity: float
    paper_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    roi: float
    average_edge: float
    last_scan_at: datetime | None = None


class CalibrationBucket(BaseModel):
    bucket: str
    predicted_prob: float
    actual_win_rate: float
    count: int


class CategoryPnL(BaseModel):
    category: str
    realized_pnl: float
    trades: int


class ConfidencePnL(BaseModel):
    confidence_level: str
    realized_pnl: float
    trades: int
    win_rate: float


class EvaluationMetrics(BaseModel):
    num_signals: int
    num_paper_trades: int
    num_resolved: int
    win_rate: float
    average_edge: float
    average_realized_return: float
    roi: float
    brier_score: float | None
    calibration: list[CalibrationBucket]
    profit_by_category: list[CategoryPnL]
    profit_by_confidence: list[ConfidencePnL]


class SettingsOut(BaseModel):
    paper_trading_enabled: bool
    paper_bankroll: float
    min_liquidity: float
    min_volume_24h: float
    max_spread: float
    min_edge_to_trade: float
    safety_margin: float
    estimated_fee: float
    max_days_to_resolution: int
    allow_extreme_prices: bool
    categories_filter: list[str] = Field(default_factory=list)


class SettingsUpdate(BaseModel):
    paper_trading_enabled: bool | None = None
    paper_bankroll: float | None = None
    min_liquidity: float | None = None
    min_volume_24h: float | None = None
    max_spread: float | None = None
    min_edge_to_trade: float | None = None
    safety_margin: float | None = None
    estimated_fee: float | None = None
    max_days_to_resolution: int | None = None
    allow_extreme_prices: bool | None = None
    categories_filter: list[str] | None = None


class ArbitrageOpportunity(BaseModel):
    """A single-market (rebalancing/bundle) arbitrage check result."""

    market_id: str
    slug: str | None = None
    question: str
    category: str
    liquidity: float
    ask_yes: float | None = None
    ask_no: float | None = None
    cost: float | None = None
    overround: float | None = None
    arb_edge: float | None = None
    executable_shares: float | None = None
    is_arbitrage: bool
    note: str


class ScanResult(BaseModel):
    scanned_markets: int
    opportunities: int
    actionable: int
    paper_trades_opened: int
    paper_trades_resolved: int
    duration_seconds: float
    message: str
