"""The scan orchestrator: collect → model → edge → risk → (paper) trade.

A single :func:`run_scan` call performs one full cycle and is safe to invoke
both from the background scheduler and from an HTTP request. Opportunities are
fully rebuilt each cycle (one current row per qualifying market), so the table
never shows stale signals.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models import Market, Opportunity, PaperTrade, SettingKV, utcnow
from backend.schemas import ScanResult
from backend.services import paper_trader as pt
from backend.services.edge_calculator import (
    ACTION_BUY_NO,
    ACTION_BUY_YES,
    compute_edges,
    confidence_score,
    suggested_action,
)
from backend.services.fair_probability import MarketAsPriorModel
from backend.services.market_collector import collect_markets, refresh_market_by_id
from backend.services.orderbook_collector import build_market_view, market_mid_yes
from backend.services.polymarket_client import PolymarketClient
from backend.services.risk_manager import OpenExposure, RiskManager
from backend.services.settings_store import get_effective_settings

LAST_SCAN_KEY = "_last_scan_at"


def _asks_from_market(market: Market, mid: float) -> tuple[float, float]:
    """Derive (ask_yes, ask_no) — the cost to *buy* each outcome.

    On a binary market, buying NO is equivalent to selling YES, so
    ``ask_no = 1 - best_bid_yes``. Falls back to the mid when quotes are missing.
    """
    ask_yes = market.best_ask if market.best_ask is not None else mid
    ask_no = (1.0 - market.best_bid) if market.best_bid is not None else (1.0 - mid)
    return ask_yes, ask_no


def _open_exposures(session: Session) -> list[OpenExposure]:
    rows = session.query(PaperTrade).filter(PaperTrade.status == pt.OPEN).all()
    return [
        OpenExposure(r.market_id, r.category, r.outcome, r.size_usd) for r in rows
    ]


def _settle_closed_markets(session: Session, client: PolymarketClient) -> int:
    """Re-fetch markets we hold open positions in and settle any that resolved."""
    market_ids = [
        mid
        for (mid,) in session.query(PaperTrade.market_id)
        .filter(PaperTrade.status == pt.OPEN)
        .distinct()
        .all()
    ]
    settled = 0
    for mid in market_ids:
        m = refresh_market_by_id(session, client, mid)
        if m and m.closed:
            settled += pt.resolve_market_trades(session, m)
    return settled


def run_scan(session: Session) -> ScanResult:
    """Run one full scan cycle and persist its results. Returns a summary."""
    started = time.monotonic()
    eff = get_effective_settings(session)
    model = MarketAsPriorModel()

    paper_opened = 0
    settled = 0
    actionable = 0

    with PolymarketClient() as client:
        qualifying, fetched = collect_markets(session, client, eff)

        # Rebuild the opportunities snapshot from scratch.
        session.query(Opportunity).delete()

        # Risk/bankroll context for any paper trades opened this cycle.
        account = pt.compute_account(session)
        rm = RiskManager(
            bankroll=account.initial_bankroll,
            max_position_pct=eff.max_position_pct,
            max_market_exposure_pct=eff.max_market_exposure_pct,
            max_category_exposure_pct=eff.max_category_exposure_pct,
            min_edge_to_trade=eff.min_edge_to_trade,
            allow_averaging=eff.allow_averaging,
        )
        cash = account.cash
        exposures = _open_exposures(session)

        for market in qualifying:
            view = build_market_view(market)  # momentum-only (no per-market book)
            fair = model.fair_probability(view)
            mid = view.mid_yes
            ask_yes, ask_no = _asks_from_market(market, mid)

            edges = compute_edges(
                fair.fair_prob_yes,
                ask_yes,
                ask_no,
                spread=market.spread,
                fee=eff.estimated_fee,
                safety_margin=eff.safety_margin,
            )
            act = suggested_action(
                edges,
                spread=market.spread,
                liquidity=market.liquidity,
                min_edge_to_trade=eff.min_edge_to_trade,
                max_spread=eff.max_spread,
                min_liquidity=eff.min_liquidity,
            )
            conf = confidence_score(
                act.best_edge,
                spread=market.spread,
                liquidity=market.liquidity,
                volume_24h=market.volume_24h,
                signals_available=fair.signals_available,
                max_spread=eff.max_spread,
            )

            session.add(
                Opportunity(
                    market_id=market.id,
                    slug=market.slug,
                    question=market.question,
                    category=market.category,
                    implied_prob_yes=round(mid, 4),
                    fair_prob_yes=round(fair.fair_prob_yes, 4),
                    calibrated_market_prob=round(fair.calibrated_market_prob, 4),
                    external_prob=fair.external_prob,
                    micro_prob=fair.micro_prob,
                    news_prob=fair.news_prob,
                    signals_available=fair.signals_available,
                    ask_yes=round(ask_yes, 4),
                    ask_no=round(ask_no, 4),
                    spread=round(market.spread or 0.0, 4),
                    liquidity=market.liquidity,
                    volume_24h=market.volume_24h,
                    edge_yes=round(edges.edge_yes, 4),
                    edge_no=round(edges.edge_no, 4),
                    best_side=act.best_side,
                    best_edge=round(act.best_edge, 4),
                    confidence=conf,
                    action=act.action,
                    reason=act.reason,
                    scanned_at=utcnow(),
                )
            )

            if act.action not in (ACTION_BUY_YES, ACTION_BUY_NO):
                continue
            actionable += 1

            if not eff.paper_trading_enabled:
                continue

            outcome = "Yes" if act.best_side == "YES" else "No"
            price = ask_yes if act.best_side == "YES" else ask_no
            fair_side = (
                fair.fair_prob_yes if act.best_side == "YES" else 1.0 - fair.fair_prob_yes
            )
            decision = rm.evaluate(
                edge=act.best_edge,
                price=price,
                market_id=market.id,
                category=market.category,
                outcome=outcome,
                cash_available=cash,
                open_positions=exposures,
            )
            if decision.approved:
                pt.open_paper_trade(
                    session,
                    market=market,
                    outcome=outcome,
                    price=price,
                    fair_prob=fair_side,
                    edge=act.best_edge,
                    confidence=conf,
                    size_usd=decision.size_usd,
                    shares=decision.shares,
                    reason=f"{act.reason}; {'; '.join(decision.reasons)}",
                )
                cash -= decision.size_usd
                exposures.append(
                    OpenExposure(market.id, market.category, outcome, decision.size_usd)
                )
                paper_opened += 1

        settled = _settle_closed_markets(session, client)

    # Record last scan time.
    row = session.get(SettingKV, LAST_SCAN_KEY)
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    if row is None:
        session.add(SettingKV(key=LAST_SCAN_KEY, value=now_iso))
    else:
        row.value = now_iso
    session.flush()

    duration = round(time.monotonic() - started, 2)
    return ScanResult(
        scanned_markets=fetched,
        opportunities=len(qualifying),
        actionable=actionable,
        paper_trades_opened=paper_opened,
        paper_trades_resolved=settled,
        duration_seconds=duration,
        message=(
            f"Scanned {fetched} markets, {len(qualifying)} qualified, "
            f"{actionable} actionable, {paper_opened} paper trades opened, "
            f"{settled} resolved."
        ),
    )
