"""Unit tests for position sizing and exposure limits."""
from __future__ import annotations

import pytest

from backend.services.risk_manager import (
    OpenExposure,
    RiskManager,
    base_position_size,
    classify_edge_strength,
)


def test_classify_edge_strength():
    assert classify_edge_strength(0.08, 0.025) == "strong"
    assert classify_edge_strength(0.05, 0.025) == "medium"
    assert classify_edge_strength(0.03, 0.025) == "weak"


def test_base_position_size_tiers_and_cap():
    bankroll = 1000.0
    weak, s1 = base_position_size(0.03, bankroll, min_edge_to_trade=0.025, max_position_pct=0.01)
    med, s2 = base_position_size(0.05, bankroll, min_edge_to_trade=0.025, max_position_pct=0.01)
    strong, s3 = base_position_size(0.09, bankroll, min_edge_to_trade=0.025, max_position_pct=0.01)
    assert (s1, s2, s3) == ("weak", "medium", "strong")
    assert weak == pytest.approx(2.5)    # 0.25%
    assert med == pytest.approx(5.0)     # 0.5%
    assert strong == pytest.approx(10.0)  # 1.0% (== per-trade cap)
    # Per-trade cap clamps strong size.
    capped, _ = base_position_size(0.09, bankroll, min_edge_to_trade=0.025, max_position_pct=0.005)
    assert capped == pytest.approx(5.0)


def _rm(**kw):
    return RiskManager(
        bankroll=1000.0,
        max_position_pct=0.01,
        max_market_exposure_pct=0.05,
        max_category_exposure_pct=0.15,
        min_edge_to_trade=0.025,
        **kw,
    )


def test_evaluate_approves_and_sizes_strong_edge():
    d = _rm().evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=[],
    )
    assert d.approved
    assert d.size_usd == pytest.approx(10.0)  # 1% of 1000
    assert d.shares == pytest.approx(20.0)    # 10 / 0.5


def test_evaluate_rejects_below_min_edge():
    d = _rm().evaluate(
        edge=0.01, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=[],
    )
    assert not d.approved


def test_evaluate_rejects_duplicate_without_averaging():
    existing = [OpenExposure("m1", "Crypto", "Yes", 10.0)]
    d = _rm().evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=existing,
    )
    assert not d.approved
    assert "duplicate" in d.reasons[0]


def test_evaluate_allows_averaging_when_enabled():
    existing = [OpenExposure("m1", "Crypto", "Yes", 10.0)]
    d = _rm(allow_averaging=True).evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=existing,
    )
    # per-market cap is 5% = $50; $10 already used -> $40 room, target $10 fits.
    assert d.approved


def test_evaluate_caps_by_market_exposure():
    # Already $48 in market m1 (cap $50). Target strong = $10, but only $2 room.
    existing = [OpenExposure("m1", "Crypto", "No", 48.0)]
    d = _rm(allow_averaging=True).evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=existing,
    )
    assert d.approved
    assert d.size_usd == pytest.approx(2.0)
    assert "per-market" in d.reasons[0]


def test_evaluate_caps_by_category_exposure():
    # $148 already in Crypto (cap 15% = $150) -> only $2 room.
    existing = [OpenExposure("mX", "Crypto", "No", 148.0)]
    d = _rm().evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=existing,
    )
    assert d.approved
    assert d.size_usd == pytest.approx(2.0)
    assert "per-category" in d.reasons[0]


def test_evaluate_never_exceeds_cash():
    d = _rm().evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=3.0, open_positions=[],
    )
    assert d.approved
    assert d.size_usd == pytest.approx(3.0)
    assert "cash" in d.reasons[0]


def test_evaluate_rejects_when_no_capacity():
    d = _rm().evaluate(
        edge=0.09, price=0.5, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=0.5, open_positions=[],
    )
    assert not d.approved


def test_evaluate_rejects_invalid_price():
    d = _rm().evaluate(
        edge=0.09, price=1.0, market_id="m1", category="Crypto",
        outcome="Yes", cash_available=1000.0, open_positions=[],
    )
    assert not d.approved
