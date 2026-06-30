"""Routes for overview cards and evaluation/calibration metrics."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Market, Opportunity, PaperTrade, SettingKV
from backend.schemas import EvaluationMetrics, OverviewMetrics
from backend.services import paper_trader as pt
from backend.services.backtester import compute_metrics
from backend.services.edge_calculator import ACTION_BUY_NO, ACTION_BUY_YES
from backend.services.scanner import LAST_SCAN_KEY

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

_ACTIONABLE = [ACTION_BUY_YES, ACTION_BUY_NO]


@router.get("/overview", response_model=OverviewMetrics)
def overview(db: Session = Depends(get_db)) -> OverviewMetrics:
    """Headline cards: scanned markets, opportunities, bankroll, and PnL."""
    active_markets = (
        db.query(Market)
        .filter(Market.active.is_(True), Market.closed.is_(False))
        .count()
    )
    actionable = db.query(Opportunity).filter(Opportunity.action.in_(_ACTIONABLE))
    opportunities_found = actionable.count()
    avg_edge = (
        db.query(func.avg(Opportunity.best_edge))
        .filter(Opportunity.action.in_(_ACTIONABLE))
        .scalar()
    )

    account = pt.compute_account(db)
    open_trades = (
        db.query(PaperTrade).filter(PaperTrade.status == pt.OPEN).count()
    )

    last_row = db.get(SettingKV, LAST_SCAN_KEY)
    last_scan = None
    if last_row and last_row.value:
        try:
            last_scan = datetime.fromisoformat(str(last_row.value))
        except ValueError:
            last_scan = None

    return OverviewMetrics(
        active_markets_scanned=active_markets,
        opportunities_found=opportunities_found,
        open_paper_trades=open_trades,
        paper_bankroll=account.initial_bankroll,
        cash=account.cash,
        open_position_value=account.open_position_value,
        equity=account.equity,
        paper_pnl=account.total_pnl,
        realized_pnl=account.realized_pnl,
        unrealized_pnl=account.unrealized_pnl,
        roi=account.roi,
        average_edge=round(avg_edge or 0.0, 4),
        last_scan_at=last_scan,
    )


@router.get("/evaluation", response_model=EvaluationMetrics)
def evaluation(db: Session = Depends(get_db)) -> EvaluationMetrics:
    """Win rate, realized return, ROI, Brier score, and calibration buckets."""
    return compute_metrics(db)
