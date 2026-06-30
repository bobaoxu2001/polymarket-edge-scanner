"""Order-book collection and microstructure summaries (CLOB).

Fetching a full book per market on every scan would be heavy and rate-limit
unfriendly, so the scanner relies on Gamma's best bid/ask for breadth. Books are
fetched on demand (e.g. the market detail page) to enrich a single market with
real depth and a microstructure signal.
"""
from __future__ import annotations

from typing import Any

from backend.models import Market
from backend.services.fair_probability import MarketView
from backend.services.polymarket_client import PolymarketClient


def _best(levels: list[dict]) -> tuple[float | None, float | None]:
    """CLOB lists the best quote last; return (price, size) of that level."""
    if not levels:
        return None, None
    try:
        return float(levels[-1]["price"]), float(levels[-1]["size"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None, None


def _depth(levels: list[dict], n: int = 5) -> float:
    total = 0.0
    for lvl in levels[-n:]:
        try:
            total += float(lvl["size"])
        except (KeyError, ValueError, TypeError):
            continue
    return round(total, 2)


def orderbook_summary(book: dict | None) -> dict[str, Any] | None:
    """Summarize a raw CLOB book: best quotes, spread, depth, and imbalance."""
    if not book:
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    best_bid, bid_sz = _best(bids)
    best_ask, ask_sz = _best(asks)
    bid_depth = _depth(bids)
    ask_depth = _depth(asks)
    spread = (
        round(best_ask - best_bid, 4)
        if best_bid is not None and best_ask is not None
        else None
    )
    imbalance = None
    if bid_depth + ask_depth > 0:
        imbalance = round((bid_depth - ask_depth) / (bid_depth + ask_depth), 4)
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_size": bid_sz,
        "best_ask_size": ask_sz,
        "spread": spread,
        "bid_depth_top5": bid_depth,
        "ask_depth_top5": ask_depth,
        "imbalance": imbalance,
        "tick_size": book.get("tick_size"),
        "levels": {
            "bids": bids[-5:][::-1],  # best-first for display
            "asks": asks[-5:][::-1],
        },
    }


def fetch_yes_orderbook(
    client: PolymarketClient, market: Market
) -> dict[str, Any] | None:
    """Fetch + summarize the YES-token order book for a market, if available."""
    tokens = market.clob_token_ids or []
    if not tokens:
        return None
    return orderbook_summary(client.fetch_orderbook(tokens[0]))


def market_mid_yes(market: Market) -> float:
    """YES implied probability for a stored market row."""
    if market.best_bid is not None and market.best_ask is not None:
        return (market.best_bid + market.best_ask) / 2.0
    if market.outcome_prices:
        try:
            return float(market.outcome_prices[0])
        except (TypeError, ValueError, IndexError):
            pass
    return market.last_trade_price if market.last_trade_price is not None else 0.5


def build_market_view(market: Market, book: dict | None = None) -> MarketView:
    """Assemble a :class:`MarketView` for the fair-probability model.

    ``book`` may be a raw CLOB book (with ``bids``/``asks``) to enable the
    depth-imbalance microstructure signal; when omitted only momentum is used.
    """
    return MarketView(
        slug=market.slug,
        mid_yes=market_mid_yes(market),
        best_bid=market.best_bid,
        best_ask=market.best_ask,
        spread=market.spread,
        liquidity=market.liquidity,
        volume_24h=market.volume_24h,
        one_day_price_change=market.one_day_price_change,
        one_week_price_change=market.one_week_price_change,
        orderbook=book,
    )
