"""Evaluation / backtesting metrics over recorded paper trades.

Pure-Python (no pandas at runtime) so the dashboard stays lightweight. Metrics
include win rate, realized return, ROI, Brier score, probability-bucket
calibration, and PnL broken down by category and confidence level.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from backend.models import Opportunity, PaperTrade
from backend.schemas import (
    CalibrationBucket,
    CategoryPnL,
    ConfidencePnL,
    EvaluationMetrics,
)
from backend.services import paper_trader as pt
from backend.services.edge_calculator import (
    ACTION_BUY_NO,
    ACTION_BUY_YES,
    confidence_level,
)

_RESOLVED = {pt.RESOLVED_WIN, pt.RESOLVED_LOSS}
_REALIZED = {pt.RESOLVED_WIN, pt.RESOLVED_LOSS, pt.CLOSED}


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_metrics(session: Session) -> EvaluationMetrics:
    """Aggregate evaluation metrics across all paper trades and opportunities."""
    trades = session.query(PaperTrade).all()
    account = pt.compute_account(session)

    num_signals = (
        session.query(Opportunity)
        .filter(Opportunity.action.in_([ACTION_BUY_YES, ACTION_BUY_NO]))
        .count()
    )

    resolved = [t for t in trades if t.status in _RESOLVED]
    realized = [t for t in trades if t.status in _REALIZED]
    wins = [t for t in resolved if t.status == pt.RESOLVED_WIN]

    avg_edge = _safe_div(sum(t.edge for t in trades), len(trades)) if trades else 0.0
    avg_return = (
        _safe_div(sum(_safe_div(t.realized_pnl or 0.0, t.size_usd) for t in realized),
                  len(realized))
        if realized
        else 0.0
    )

    # Brier score over resolved trades: (predicted P(win) - outcome)^2.
    brier = None
    if resolved:
        brier = _safe_div(
            sum((t.fair_prob - (1.0 if t.status == pt.RESOLVED_WIN else 0.0)) ** 2
                for t in resolved),
            len(resolved),
        )

    return EvaluationMetrics(
        num_signals=num_signals,
        num_paper_trades=len(trades),
        num_resolved=len(resolved),
        win_rate=round(_safe_div(len(wins), len(resolved)), 4),
        average_edge=round(avg_edge, 4),
        average_realized_return=round(avg_return, 4),
        roi=account.roi,
        brier_score=round(brier, 4) if brier is not None else None,
        calibration=_calibration(resolved),
        profit_by_category=_profit_by_category(realized),
        profit_by_confidence=_profit_by_confidence(resolved),
    )


def _calibration(resolved: list[PaperTrade]) -> list[CalibrationBucket]:
    """Decile calibration: predicted P(win) vs actual win rate per bucket."""
    buckets: dict[int, list[PaperTrade]] = defaultdict(list)
    for t in resolved:
        idx = min(int(t.fair_prob * 10), 9)
        buckets[idx].append(t)

    out: list[CalibrationBucket] = []
    for idx in sorted(buckets):
        group = buckets[idx]
        predicted = _safe_div(sum(t.fair_prob for t in group), len(group))
        actual = _safe_div(
            sum(1 for t in group if t.status == pt.RESOLVED_WIN), len(group)
        )
        out.append(
            CalibrationBucket(
                bucket=f"{idx / 10:.1f}-{(idx + 1) / 10:.1f}",
                predicted_prob=round(predicted, 4),
                actual_win_rate=round(actual, 4),
                count=len(group),
            )
        )
    return out


def _profit_by_category(realized: list[PaperTrade]) -> list[CategoryPnL]:
    agg: dict[str, list[float]] = defaultdict(list)
    for t in realized:
        agg[t.category].append(t.realized_pnl or 0.0)
    return [
        CategoryPnL(category=cat, realized_pnl=round(sum(v), 2), trades=len(v))
        for cat, v in sorted(agg.items(), key=lambda kv: -sum(kv[1]))
    ]


def _profit_by_confidence(resolved: list[PaperTrade]) -> list[ConfidencePnL]:
    agg: dict[str, list[PaperTrade]] = defaultdict(list)
    for t in resolved:
        agg[confidence_level(t.confidence)].append(t)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out: list[ConfidencePnL] = []
    for level, group in agg.items():
        wins = sum(1 for t in group if t.status == pt.RESOLVED_WIN)
        out.append(
            ConfidencePnL(
                confidence_level=level,
                realized_pnl=round(sum(t.realized_pnl or 0.0 for t in group), 2),
                trades=len(group),
                win_rate=round(_safe_div(wins, len(group)), 4),
            )
        )
    return sorted(out, key=lambda c: order.get(c.confidence_level, 9))
