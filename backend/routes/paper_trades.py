"""Routes for viewing and managing simulated (paper) trades."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Market, PaperTrade
from backend.schemas import PaperTradeOut
from backend.services import paper_trader as pt

router = APIRouter(prefix="/api/paper-trades", tags=["paper-trades"])


def _to_out(trade: PaperTrade, market: Market | None) -> PaperTradeOut:
    """Serialize a trade, marking OPEN positions to market."""
    out = PaperTradeOut.model_validate(trade)
    if trade.status == pt.OPEN and market is not None:
        mid = pt._market_mid(market)
        px, value, unreal = pt.mark_to_market(trade, mid)
        out.current_price = px
        out.current_value = value
        out.unrealized_pnl = unreal
    elif trade.status != pt.OPEN:
        out.current_price = trade.exit_price
        out.current_value = round((trade.shares * (trade.exit_price or 0.0)), 2)
        out.unrealized_pnl = 0.0
    return out


@router.get("", response_model=list[PaperTradeOut])
def list_paper_trades(
    db: Session = Depends(get_db),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(500, le=2000),
) -> list[PaperTradeOut]:
    """List paper trades (newest first), with mark-to-market for open ones."""
    q = db.query(PaperTrade)
    if status:
        q = q.filter(PaperTrade.status == status.upper())
    trades = q.order_by(PaperTrade.opened_at.desc()).limit(limit).all()
    markets = {m.id: m for m in db.query(Market).all()}
    return [_to_out(t, markets.get(t.market_id)) for t in trades]


@router.post("/{trade_id}/close", response_model=PaperTradeOut)
def close_paper_trade(trade_id: int, db: Session = Depends(get_db)) -> PaperTradeOut:
    """Manually close an OPEN paper trade at the current market price."""
    trade = pt.close_trade(db, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="trade not found")
    db.commit()
    return _to_out(trade, db.get(Market, trade.market_id))


@router.post("/{trade_id}/cancel", response_model=PaperTradeOut)
def cancel_paper_trade(trade_id: int, db: Session = Depends(get_db)) -> PaperTradeOut:
    """Cancel an OPEN paper trade (treated as never executed; no PnL)."""
    trade = pt.cancel_trade(db, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="trade not found")
    db.commit()
    return _to_out(trade, db.get(Market, trade.market_id))
