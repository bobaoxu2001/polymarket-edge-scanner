"""Routes for ranked opportunities (the current model snapshot)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Opportunity
from backend.schemas import OpportunityOut

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

_SORTS = {
    "edge": Opportunity.best_edge.desc(),
    "confidence": Opportunity.confidence.desc(),
    "liquidity": Opportunity.liquidity.desc(),
    "volume": Opportunity.volume_24h.desc(),
}


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(
    db: Session = Depends(get_db),
    category: str | None = Query(None),
    action: str | None = Query(None, description="Filter by suggested action"),
    actionable_only: bool = Query(False, description="Only PAPER BUY signals"),
    sort: str = Query("edge", description="edge|confidence|liquidity|volume"),
    limit: int = Query(200, le=1000),
) -> list[Opportunity]:
    """Return ranked opportunities with optional filters."""
    q = db.query(Opportunity)
    if category:
        q = q.filter(Opportunity.category == category)
    if action:
        q = q.filter(Opportunity.action == action)
    if actionable_only:
        q = q.filter(Opportunity.action.in_(["PAPER BUY YES", "PAPER BUY NO"]))
    q = q.order_by(_SORTS.get(sort, Opportunity.best_edge.desc()))
    return q.limit(limit).all()


@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)) -> list[str]:
    """Distinct categories present in the current opportunity snapshot."""
    rows = db.query(Opportunity.category).distinct().all()
    return sorted({r[0] for r in rows if r[0]})
