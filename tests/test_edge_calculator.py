"""Unit tests for edge calculation, suggested actions, and confidence scoring."""
from __future__ import annotations

import pytest

from backend.services.edge_calculator import (
    ACTION_AVOID,
    ACTION_BUY_NO,
    ACTION_BUY_YES,
    ACTION_WATCH,
    compute_edges,
    confidence_level,
    confidence_score,
    estimated_slippage,
    suggested_action,
)


def test_estimated_slippage_floor_and_scaling():
    assert estimated_slippage(0.0) == 0.005          # floor
    assert estimated_slippage(None) == 0.005
    assert estimated_slippage(0.02) == pytest.approx(0.005)  # 0.02*0.25 = 0.005
    assert estimated_slippage(0.08) == pytest.approx(0.02)   # 0.08*0.25 = 0.02


def test_compute_edges_basic_math():
    # fair=0.60, ask_yes=0.50, ask_no=0.45, no spread -> slippage floor 0.005
    e = compute_edges(0.60, 0.50, 0.45, spread=0.0, fee=0.0, safety_margin=0.015)
    friction = 0.0 + 0.005 + 0.015
    assert e.edge_yes == pytest.approx(0.60 - 0.50 - friction)   # 0.08
    assert e.edge_no == pytest.approx(0.40 - 0.45 - friction)    # -0.07
    assert e.best_side == "YES"
    assert e.best_edge == pytest.approx(e.edge_yes)


def test_compute_edges_includes_fee():
    e = compute_edges(0.7, 0.6, 0.3, spread=0.0, fee=0.02, safety_margin=0.0)
    # friction = 0.02 + 0.005 + 0.0 = 0.025
    assert e.edge_yes == pytest.approx(0.7 - 0.6 - 0.025)


def test_suggested_action_buy_yes():
    e = compute_edges(0.62, 0.50, 0.46, spread=0.01, fee=0.0, safety_margin=0.015)
    a = suggested_action(e, spread=0.01, liquidity=20000, min_edge_to_trade=0.025,
                         max_spread=0.05, min_liquidity=5000)
    assert a.action == ACTION_BUY_YES
    assert a.best_side == "YES"


def test_suggested_action_buy_no():
    e = compute_edges(0.30, 0.62, 0.55, spread=0.01, fee=0.0, safety_margin=0.0)
    a = suggested_action(e, spread=0.01, liquidity=20000, min_edge_to_trade=0.025,
                         max_spread=0.05, min_liquidity=5000)
    assert a.action == ACTION_BUY_NO
    assert a.best_side == "NO"


def test_suggested_action_watch_when_edge_too_small():
    e = compute_edges(0.51, 0.50, 0.50, spread=0.01, fee=0.0, safety_margin=0.015)
    a = suggested_action(e, spread=0.01, liquidity=20000, min_edge_to_trade=0.025,
                         max_spread=0.05, min_liquidity=5000)
    assert a.action == ACTION_WATCH


def test_suggested_action_avoid_wide_spread_overrides_edge():
    e = compute_edges(0.70, 0.50, 0.40, spread=0.10, fee=0.0, safety_margin=0.0)
    a = suggested_action(e, spread=0.10, liquidity=50000, min_edge_to_trade=0.025,
                         max_spread=0.05, min_liquidity=5000)
    assert a.action == ACTION_AVOID
    assert "spread" in a.reason


def test_suggested_action_avoid_low_liquidity():
    e = compute_edges(0.70, 0.50, 0.40, spread=0.01, fee=0.0, safety_margin=0.0)
    a = suggested_action(e, spread=0.01, liquidity=100, min_edge_to_trade=0.025,
                         max_spread=0.05, min_liquidity=5000)
    assert a.action == ACTION_AVOID
    assert "liquidity" in a.reason


def test_confidence_score_bounds_and_levels():
    low = confidence_score(0.0, spread=0.05, liquidity=0, volume_24h=0)
    high = confidence_score(0.10, spread=0.0, liquidity=100000, volume_24h=100000,
                            signals_available={"external": True, "microstructure": True, "news": True})
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low
    assert confidence_level(0.9) == "HIGH"
    assert confidence_level(0.5) == "MEDIUM"
    assert confidence_level(0.1) == "LOW"
