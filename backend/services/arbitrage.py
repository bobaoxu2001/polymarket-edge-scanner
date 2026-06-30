"""Model-free single-market (rebalancing / bundle) arbitrage detection.

Motivation: the academic literature on Polymarket (e.g. *Arbitrage Analysis in
Polymarket NBA Markets*, arXiv:2605.00864; *Unravelling the Probabilistic
Forest*, arXiv:2508.03474) finds that the bulk of genuinely risk-free profit is
**combinatorial / rebalancing arbitrage**, not directional mispricing — but it is
*rare*, *short-lived* (median ~3.6s), and *liquidity-bounded* (often only ~15
shares). This module measures it honestly rather than promising to capture it.

For a binary market, YES and NO are **separate CLOB tokens with separate books**.
Buying one YES share + one NO share guarantees a $1 payout (exactly one resolves
to $1). So if ``ask_yes + ask_no < 1`` (after fees), the pair is a risk-free buy:

    arb_edge = 1 - ask_yes - ask_no - total_fee

The executable size is bounded by the *thinner* of the two best-ask levels, which
is exactly why these opportunities rarely scale. This is read-only / research
output — no auto-execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.models import Market
from backend.services.orderbook_collector import _best  # best (price,size) of a level
from backend.services.polymarket_client import PolymarketClient


@dataclass
class ArbResult:
    """Result of checking one market for single-market rebalancing arbitrage."""

    ask_yes: float | None
    ask_no: float | None
    cost: float | None          # ask_yes + ask_no
    overround: float | None     # cost - 1 (negative => arbitrage)
    arb_edge: float | None      # 1 - cost - fees (positive => risk-free profit)
    executable_shares: float | None  # min of the two best-ask sizes
    is_arbitrage: bool
    note: str


def rebalancing_edge(
    ask_yes: float | None, ask_no: float | None, *, total_fee: float = 0.0
) -> tuple[float | None, bool]:
    """Return (arb_edge, is_arbitrage) for buying YES+NO at the given asks.

    ``arb_edge = 1 - ask_yes - ask_no - total_fee``. Positive means a risk-free
    profit per matched share pair (before liquidity/slippage limits).
    """
    if ask_yes is None or ask_no is None:
        return None, False
    edge = 1.0 - ask_yes - ask_no - total_fee
    return edge, edge > 0.0


def check_market_arbitrage(
    client: PolymarketClient, market: Market, *, fee_per_leg: float = 0.0
) -> ArbResult:
    """Fetch both token books for a market and check for rebalancing arbitrage.

    Costs up to two CLOB calls (one per outcome token). Degrades gracefully to a
    non-arbitrage result if either book is missing.
    """
    tokens = market.clob_token_ids or []
    if len(tokens) < 2:
        return ArbResult(None, None, None, None, None, None, False,
                         "market is not a two-token binary")

    book_yes = client.fetch_orderbook(tokens[0])
    book_no = client.fetch_orderbook(tokens[1])
    ask_yes, size_yes = _best((book_yes or {}).get("asks") or [])
    ask_no, size_no = _best((book_no or {}).get("asks") or [])

    if ask_yes is None or ask_no is None:
        return ArbResult(ask_yes, ask_no, None, None, None, None, False,
                         "order book unavailable for one or both legs")

    cost = ask_yes + ask_no
    edge, is_arb = rebalancing_edge(ask_yes, ask_no, total_fee=2 * fee_per_leg)
    exec_shares = None
    if size_yes is not None and size_no is not None:
        exec_shares = round(min(size_yes, size_no), 2)

    note = (
        f"buy YES@{ask_yes:.3f} + NO@{ask_no:.3f} = {cost:.3f}; "
        + ("RISK-FREE EDGE" if is_arb else "no arbitrage")
        + (f"; size-bound {exec_shares} sh" if exec_shares is not None else "")
    )
    return ArbResult(
        ask_yes=round(ask_yes, 4),
        ask_no=round(ask_no, 4),
        cost=round(cost, 4),
        overround=round(cost - 1.0, 4),
        arb_edge=round(edge, 4),
        executable_shares=exec_shares,
        is_arbitrage=is_arb,
        note=note,
    )
