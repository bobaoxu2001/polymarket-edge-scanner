"""Unit tests for model-free single-market rebalancing arbitrage math."""
from __future__ import annotations

import pytest

from backend.services.arbitrage import rebalancing_edge


def test_rebalancing_edge_detects_arbitrage():
    # Buying YES@0.48 + NO@0.49 costs 0.97 < 1.0 -> 0.03 risk-free edge.
    edge, is_arb = rebalancing_edge(0.48, 0.49)
    assert edge == pytest.approx(0.03)
    assert is_arb is True


def test_rebalancing_edge_no_arbitrage_when_overround():
    # Typical market: asks sum to > 1 (the overround) -> no arbitrage.
    edge, is_arb = rebalancing_edge(0.52, 0.50)
    assert edge == pytest.approx(-0.02)
    assert is_arb is False


def test_rebalancing_edge_accounts_for_fees():
    # 0.03 gross edge wiped out by 2x0.02 fees -> negative, not arbitrage.
    edge, is_arb = rebalancing_edge(0.48, 0.49, total_fee=0.04)
    assert edge == pytest.approx(-0.01)
    assert is_arb is False


def test_rebalancing_edge_handles_missing_quotes():
    assert rebalancing_edge(None, 0.5) == (None, False)
    assert rebalancing_edge(0.5, None) == (None, False)


def test_rebalancing_edge_breakeven_is_not_arbitrage():
    edge, is_arb = rebalancing_edge(0.50, 0.50)
    assert edge == pytest.approx(0.0)
    assert is_arb is False  # strictly positive required
