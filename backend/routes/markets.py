"""Routes for browsing markets and a single market's detail/model breakdown."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Market, Opportunity
from backend.schemas import MarketDetailOut, MarketOut, ModelBreakdown, OpportunityOut
from backend.services.edge_calculator import (
    compute_edges,
    confidence_level,
    suggested_action,
)
from backend.services.fair_probability import MarketAsPriorModel
from backend.services.orderbook_collector import (
    build_market_view,
    fetch_yes_orderbook,
    market_mid_yes,
)
from backend.services.polymarket_client import PolymarketClient
from backend.services.risk_manager import RiskManager
from backend.services.scanner import _asks_from_market, _open_exposures
from backend.services.settings_store import get_effective_settings

router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get("", response_model=list[MarketOut])
def list_markets(
    db: Session = Depends(get_db),
    category: str | None = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(200, le=1000),
) -> list[Market]:
    """List stored markets, most liquid first."""
    q = db.query(Market)
    if active_only:
        q = q.filter(Market.active.is_(True), Market.closed.is_(False))
    if category:
        q = q.filter(Market.category == category)
    return q.order_by(Market.liquidity.desc()).limit(limit).all()


@router.get("/{market_id}", response_model=MarketDetailOut)
def market_detail(market_id: str, db: Session = Depends(get_db)) -> MarketDetailOut:
    """Return a market with a live order-book pull and full model breakdown."""
    market = db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="market not found")

    eff = get_effective_settings(db)
    book = None
    try:
        with PolymarketClient() as client:
            book = fetch_yes_orderbook(client, market)
    except Exception:  # detail page must still render without live depth
        book = None

    # Re-run the model with depth (microstructure imbalance) when available.
    raw_book = None
    if book and book.get("levels"):
        raw_book = {
            "bids": list(reversed(book["levels"]["bids"])),
            "asks": list(reversed(book["levels"]["asks"])),
        }
    view = build_market_view(market, raw_book)
    fair = MarketAsPriorModel().fair_probability(view)
    mid = market_mid_yes(market)
    ask_yes, ask_no = _asks_from_market(market, mid)
    edges = compute_edges(
        fair.fair_prob_yes, ask_yes, ask_no,
        spread=market.spread, fee=eff.estimated_fee, safety_margin=eff.safety_margin,
    )
    act = suggested_action(
        edges, spread=market.spread, liquidity=market.liquidity,
        min_edge_to_trade=eff.min_edge_to_trade, max_spread=eff.max_spread,
        min_liquidity=eff.min_liquidity,
    )

    breakdown = ModelBreakdown(
        implied_prob_yes=round(fair.implied_prob_yes, 4),
        calibrated_market_prob=round(fair.calibrated_market_prob, 4),
        external_prob=fair.external_prob,
        micro_prob=fair.micro_prob,
        news_prob=fair.news_prob,
        weights=fair.weights,
        signals_available=fair.signals_available,
        fair_prob_yes=round(fair.fair_prob_yes, 4),
        notes=[n for n in fair.notes if n],
    )

    opp_row = db.get(Opportunity, market_id)
    opportunity = OpportunityOut.model_validate(opp_row) if opp_row else None

    # Risk notes: exposures vs caps and gating state.
    rm = RiskManager(
        bankroll=eff.paper_bankroll,
        max_market_exposure_pct=eff.max_market_exposure_pct,
        max_category_exposure_pct=eff.max_category_exposure_pct,
    )
    exposures = _open_exposures(db)
    mkt_exp = rm.market_exposure(exposures, market_id)
    cat_exp = rm.category_exposure(exposures, market.category)
    risk_notes = [
        f"Suggested action: {act.action} ({act.reason}).",
        f"Market exposure ${mkt_exp:,.2f} / cap "
        f"${eff.paper_bankroll * eff.max_market_exposure_pct:,.2f}.",
        f"Category '{market.category}' exposure ${cat_exp:,.2f} / cap "
        f"${eff.paper_bankroll * eff.max_category_exposure_pct:,.2f}.",
        f"Confidence basis: edge {act.best_edge:+.3f}, spread "
        f"{(market.spread or 0):.3f}, liquidity ${market.liquidity:,.0f}.",
        "Paper trading is "
        + ("ENABLED" if eff.paper_trading_enabled else "DISABLED")
        + " — no real orders are ever placed.",
    ]

    return MarketDetailOut(
        market=MarketOut.model_validate(market),
        opportunity=opportunity,
        model_breakdown=breakdown,
        orderbook=book,
        risk_notes=risk_notes,
    )
