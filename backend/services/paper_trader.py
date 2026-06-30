r"""Paper trading engine — simulated positions only. No real orders, ever.

Accounting model (per outcome share priced in [0, 1], paying $1 if it wins):

* Opening a position costs ``size_usd`` and buys ``shares = size_usd / price``.
* Marking to market: ``value = shares * current_outcome_price``.
* Resolution: win => each share pays $1; loss => shares expire worthless.

Cash and equity are *derived* from the trade ledger (no separate balance row),
which keeps the books internally consistent by construction.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Market, PaperTrade, SettingKV, utcnow

OPEN = "OPEN"
CLOSED = "CLOSED"
RESOLVED_WIN = "RESOLVED_WIN"
RESOLVED_LOSS = "RESOLVED_LOSS"
CANCELLED = "CANCELLED"
_TERMINAL = {CLOSED, RESOLVED_WIN, RESOLVED_LOSS, CANCELLED}


def outcome_price(mid_yes: float, outcome: str) -> float:
    """Current price of a specific outcome given the YES mid price."""
    return mid_yes if outcome.strip().lower() == "yes" else 1.0 - mid_yes


def get_initial_bankroll(session: Session) -> float:
    """Initial paper bankroll (settings override, else config default)."""
    row = session.get(SettingKV, "paper_bankroll")
    if row is not None and row.value is not None:
        try:
            return float(row.value)
        except (TypeError, ValueError):
            pass
    return float(settings.paper_bankroll)


def open_paper_trade(
    session: Session,
    *,
    market: Market,
    outcome: str,
    price: float,
    fair_prob: float,
    edge: float,
    confidence: float,
    size_usd: float,
    shares: float,
    reason: str,
) -> PaperTrade:
    """Record a new OPEN paper trade. Caller is responsible for risk checks."""
    trade = PaperTrade(
        market_id=market.id,
        slug=market.slug,
        market_title=market.question,
        category=market.category,
        outcome=outcome,
        side="BUY",
        entry_price=round(price, 4),
        shares=round(shares, 4),
        size_usd=round(size_usd, 2),
        fair_prob=round(fair_prob, 4),
        edge=round(edge, 4),
        confidence=round(confidence, 4),
        reason=reason,
        status=OPEN,
        opened_at=utcnow(),
    )
    session.add(trade)
    session.flush()
    return trade


def resolve_market_trades(session: Session, market: Market) -> int:
    """Settle all OPEN trades on a resolved market. Returns count settled."""
    if not market.closed or not market.winning_outcome:
        return 0
    winner = market.winning_outcome.strip().lower()
    open_trades = (
        session.query(PaperTrade)
        .filter(PaperTrade.market_id == market.id, PaperTrade.status == OPEN)
        .all()
    )
    settled = 0
    for t in open_trades:
        won = t.outcome.strip().lower() == winner
        t.status = RESOLVED_WIN if won else RESOLVED_LOSS
        t.exit_price = 1.0 if won else 0.0
        t.realized_pnl = round((t.shares * t.exit_price) - t.size_usd, 2)
        t.resolved_outcome = market.winning_outcome
        t.closed_at = utcnow()
        settled += 1
    return settled


def close_trade(session: Session, trade_id: int) -> PaperTrade | None:
    """Manually close an OPEN trade at the current market price."""
    t = session.get(PaperTrade, trade_id)
    if t is None or t.status != OPEN:
        return t
    market = session.get(Market, t.market_id)
    mid = _market_mid(market) if market else t.entry_price
    px = outcome_price(mid, t.outcome)
    t.status = CLOSED
    t.exit_price = round(px, 4)
    t.realized_pnl = round((t.shares * px) - t.size_usd, 2)
    t.closed_at = utcnow()
    return t


def cancel_trade(session: Session, trade_id: int) -> PaperTrade | None:
    """Cancel an OPEN trade (no PnL impact; treated as never executed)."""
    t = session.get(PaperTrade, trade_id)
    if t is None or t.status != OPEN:
        return t
    t.status = CANCELLED
    t.exit_price = None
    t.realized_pnl = 0.0
    t.closed_at = utcnow()
    return t


# --------------------------------------------------------------------------- #
# Account / mark-to-market
# --------------------------------------------------------------------------- #
@dataclass
class Account:
    initial_bankroll: float
    cash: float
    open_position_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    roi: float
    open_trades: int


def _market_mid(market: Market | None) -> float:
    if market is None:
        return 0.5
    if market.best_bid is not None and market.best_ask is not None:
        return (market.best_bid + market.best_ask) / 2.0
    if market.outcome_prices:
        try:
            return float(market.outcome_prices[0])
        except (TypeError, ValueError, IndexError):
            return 0.5
    return market.last_trade_price if market.last_trade_price is not None else 0.5


def _mids_by_market(session: Session) -> dict[str, float]:
    return {m.id: _market_mid(m) for m in session.query(Market).all()}


def mark_to_market(trade: PaperTrade, mid_yes: float) -> tuple[float, float, float]:
    """Return (current_outcome_price, current_value, unrealized_pnl)."""
    px = outcome_price(mid_yes, trade.outcome)
    value = trade.shares * px
    return round(px, 4), round(value, 2), round(value - trade.size_usd, 2)


def compute_account(session: Session) -> Account:
    """Derive cash, equity, and PnL from the full paper-trade ledger."""
    initial = get_initial_bankroll(session)
    mids = _mids_by_market(session)
    trades = session.query(PaperTrade).all()

    realized = 0.0
    open_cost = 0.0
    open_value = 0.0
    open_count = 0
    for t in trades:
        if t.status in _TERMINAL:
            realized += t.realized_pnl or 0.0
        elif t.status == OPEN:
            open_count += 1
            open_cost += t.size_usd
            mid = mids.get(t.market_id, t.entry_price)
            _, value, _ = mark_to_market(t, mid)
            open_value += value

    cash = initial + realized - open_cost
    equity = cash + open_value
    unrealized = open_value - open_cost
    total = realized + unrealized
    roi = (total / initial) if initial else 0.0
    return Account(
        initial_bankroll=round(initial, 2),
        cash=round(cash, 2),
        open_position_value=round(open_value, 2),
        equity=round(equity, 2),
        realized_pnl=round(realized, 2),
        unrealized_pnl=round(unrealized, 2),
        total_pnl=round(total, 2),
        roi=round(roi, 4),
        open_trades=open_count,
    )
