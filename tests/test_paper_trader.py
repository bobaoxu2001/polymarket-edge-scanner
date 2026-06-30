"""Unit tests for the paper-trading engine and account accounting."""
from __future__ import annotations

import pytest

from backend.models import Market, SettingKV
from backend.services import paper_trader as pt


def _pin_bankroll(session, amount=1000.0):
    session.add(SettingKV(key="paper_bankroll", value=amount))
    session.flush()


def _make_market(session, **over) -> Market:
    fields = dict(
        id="m1", question="Will X happen?", category="Crypto",
        active=True, closed=False, enable_order_book=True,
        best_bid=0.5, best_ask=0.6, spread=0.1,
        outcomes=["Yes", "No"], outcome_prices=[0.55, 0.45],
        clob_token_ids=["t0", "t1"], liquidity=20000.0, volume=1000.0, volume_24h=1000.0,
    )
    fields.update(over)
    m = Market(**fields)
    session.add(m)
    session.flush()
    return m


def test_open_trade_and_account_marks_to_market(session):
    _pin_bankroll(session)
    m = _make_market(session)
    pt.open_paper_trade(
        session, market=m, outcome="Yes", price=0.5, fair_prob=0.6,
        edge=0.08, confidence=0.7, size_usd=10.0, shares=20.0, reason="test",
    )
    acct = pt.compute_account(session)
    assert acct.initial_bankroll == pytest.approx(1000.0)
    assert acct.cash == pytest.approx(990.0)             # 1000 - 10 cost
    assert acct.open_position_value == pytest.approx(11.0)  # 20 sh * mid 0.55
    assert acct.unrealized_pnl == pytest.approx(1.0)
    assert acct.equity == pytest.approx(1001.0)
    assert acct.open_trades == 1


def test_resolve_win_pays_out(session):
    _pin_bankroll(session)
    m = _make_market(session)
    pt.open_paper_trade(
        session, market=m, outcome="Yes", price=0.5, fair_prob=0.6,
        edge=0.08, confidence=0.7, size_usd=10.0, shares=20.0, reason="test",
    )
    m.closed = True
    m.winning_outcome = "Yes"
    settled = pt.resolve_market_trades(session, m)
    assert settled == 1
    trade = session.query(pt.PaperTrade).first()
    assert trade.status == pt.RESOLVED_WIN
    assert trade.realized_pnl == pytest.approx(10.0)     # 20*1 - 10
    acct = pt.compute_account(session)
    assert acct.realized_pnl == pytest.approx(10.0)
    assert acct.cash == pytest.approx(1010.0)
    assert acct.open_trades == 0


def test_resolve_loss_costs_stake(session):
    _pin_bankroll(session)
    m = _make_market(session)
    pt.open_paper_trade(
        session, market=m, outcome="Yes", price=0.5, fair_prob=0.6,
        edge=0.08, confidence=0.7, size_usd=10.0, shares=20.0, reason="test",
    )
    m.closed = True
    m.winning_outcome = "No"
    pt.resolve_market_trades(session, m)
    trade = session.query(pt.PaperTrade).first()
    assert trade.status == pt.RESOLVED_LOSS
    assert trade.realized_pnl == pytest.approx(-10.0)
    acct = pt.compute_account(session)
    assert acct.cash == pytest.approx(990.0)
    assert acct.realized_pnl == pytest.approx(-10.0)


def test_outcome_price_helper():
    assert pt.outcome_price(0.55, "Yes") == pytest.approx(0.55)
    assert pt.outcome_price(0.55, "No") == pytest.approx(0.45)


def test_mark_to_market_for_no_side(session):
    _pin_bankroll(session)
    m = _make_market(session)
    t = pt.open_paper_trade(
        session, market=m, outcome="No", price=0.4, fair_prob=0.6,
        edge=0.06, confidence=0.6, size_usd=8.0, shares=20.0, reason="test",
    )
    px, value, unreal = pt.mark_to_market(t, mid_yes=0.55)
    assert px == pytest.approx(0.45)          # NO price = 1 - 0.55
    assert value == pytest.approx(9.0)         # 20 * 0.45
    assert unreal == pytest.approx(1.0)        # 9 - 8


def test_close_trade_realizes_pnl(session):
    _pin_bankroll(session)
    m = _make_market(session)
    t = pt.open_paper_trade(
        session, market=m, outcome="Yes", price=0.5, fair_prob=0.6,
        edge=0.08, confidence=0.7, size_usd=10.0, shares=20.0, reason="test",
    )
    closed = pt.close_trade(session, t.id)
    assert closed.status == pt.CLOSED
    assert closed.exit_price == pytest.approx(0.55)   # current mid
    assert closed.realized_pnl == pytest.approx(1.0)  # 20*0.55 - 10
