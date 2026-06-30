"""Route for on-demand single-market (rebalancing/bundle) arbitrage scanning.

This is read-only research output. It fetches both outcome-token order books for
the most liquid stored markets and reports where ``ask_yes + ask_no < 1``. Per
the literature these are rare, short-lived, and liquidity-bounded, so this view
exists to *measure* them honestly — not to auto-execute.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import Market
from backend.schemas import ArbitrageOpportunity
from backend.services.arbitrage import check_market_arbitrage
from backend.services.polymarket_client import PolymarketClient
from backend.services.settings_store import get_effective_settings

router = APIRouter(prefix="/api/arbitrage", tags=["arbitrage"])


@router.get("", response_model=list[ArbitrageOpportunity])
def scan_arbitrage(
    db: Session = Depends(get_db),
    limit: int = Query(20, le=60, description="How many top-liquidity markets to check"),
    arb_only: bool = Query(False, description="Return only positive-edge arbitrage"),
) -> list[ArbitrageOpportunity]:
    """Scan top-liquidity markets for single-market rebalancing arbitrage.

    Costs up to ``2 * limit`` CLOB calls, so it is on-demand (not in the periodic
    scan). Results are sorted by arbitrage edge (best first).
    """
    eff = get_effective_settings(db)
    markets = (
        db.query(Market)
        .filter(Market.active.is_(True), Market.closed.is_(False))
        .filter(Market.enable_order_book.is_(True))
        .order_by(Market.liquidity.desc())
        .limit(limit)
        .all()
    )

    out: list[ArbitrageOpportunity] = []
    with PolymarketClient() as client:
        for m in markets:
            if len(m.clob_token_ids or []) < 2:
                continue
            res = check_market_arbitrage(client, m, fee_per_leg=eff.estimated_fee)
            if arb_only and not res.is_arbitrage:
                continue
            out.append(
                ArbitrageOpportunity(
                    market_id=m.id,
                    slug=m.slug,
                    question=m.question,
                    category=m.category,
                    liquidity=m.liquidity,
                    ask_yes=res.ask_yes,
                    ask_no=res.ask_no,
                    cost=res.cost,
                    overround=res.overround,
                    arb_edge=res.arb_edge,
                    executable_shares=res.executable_shares,
                    is_arbitrage=res.is_arbitrage,
                    note=res.note,
                )
            )
    out.sort(key=lambda o: (o.arb_edge if o.arb_edge is not None else -9), reverse=True)
    return out
