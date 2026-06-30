"""Collect Polymarket markets, normalize them, categorize, and quality-filter.

Raw Gamma payloads are messy (numbers-as-strings, JSON-encoded list fields,
optional keys). This module turns them into clean :class:`backend.models.Market`
rows and applies the documented quality filters before a market is considered
for scoring.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.models import Market, utcnow
from backend.services.polymarket_client import PolymarketClient
from backend.services.settings_store import EffectiveSettings

# Keyword -> category. First match wins; checked against question + event title.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Crypto", ("bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "doge", "xrp")),
    ("Politics", ("election", "president", "senate", "congress", "governor",
                  "trump", "biden", "democrat", "republican", "primary", "poll", "vote")),
    ("Sports", ("nba", "nfl", "soccer", "premier league", "champions league", "world cup",
                "super bowl", "mlb", "nhl", "ufc", "tennis", "golf", "f1", "olympic",
                "win the", "vs", " beat ")),
    ("Economics", ("fed", "interest rate", "inflation", "cpi", "gdp", "recession",
                   "rate cut", "jobs report", "unemployment", "tariff")),
    ("Science & Tech", ("ai ", "openai", "gpt", "spacex", "nasa", "launch", "iphone",
                        "apple", "google", "tesla", "nvidia")),
    ("Pop Culture", ("album", "movie", "oscar", "grammy", "box office", "netflix",
                     "spotify", "celebrity", "taylor swift", "rihanna")),
    ("World", ("ukraine", "russia", "china", "israel", "gaza", "war", "ceasefire",
               "nato", "united nations")),
]


@dataclass
class ParsedMarket:
    raw: dict
    fields: dict[str, Any]


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_list(value: Any) -> list:
    """Parse a possibly JSON-encoded list field (Gamma encodes these as strings)."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def categorize(question: str, event_title: str, tags: list[str]) -> str:
    """Infer a coarse category from the question, event title, and any tags."""
    hay = " ".join([question or "", event_title or "", " ".join(tags or [])]).lower()
    for label in tags or []:
        for cat, kws in _CATEGORY_KEYWORDS:
            if label.lower() in kws or label.lower() == cat.lower():
                return cat
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(kw in hay for kw in kws):
            return cat
    return "Other"


def parse_market(raw: dict) -> ParsedMarket | None:
    """Normalize a raw Gamma market dict into model-ready fields."""
    mid = str(raw.get("id") or "").strip()
    question = (raw.get("question") or "").strip()
    if not mid or not question:
        return None

    outcomes = [str(o) for o in _json_list(raw.get("outcomes"))]
    prices = [p for p in (_to_float(x) for x in _json_list(raw.get("outcomePrices"))) if p is not None]
    token_ids = [str(t) for t in _json_list(raw.get("clobTokenIds"))]

    events = raw.get("events") or []
    event_title = events[0].get("title", "") if events else ""
    tags: list[str] = []
    for ev in events:
        for t in ev.get("tags") or []:
            lbl = t.get("label") if isinstance(t, dict) else None
            if lbl:
                tags.append(lbl)

    fields = {
        "id": mid,
        "condition_id": raw.get("conditionId"),
        "slug": raw.get("slug"),
        "question": question,
        "category": categorize(question, event_title, tags),
        "description": raw.get("description"),
        "resolution_source": raw.get("resolutionSource") or None,
        "end_date": _parse_dt(raw.get("endDate")),
        "active": bool(raw.get("active", True)),
        "closed": bool(raw.get("closed", False)),
        "enable_order_book": bool(raw.get("enableOrderBook", True)),
        "best_bid": _to_float(raw.get("bestBid")),
        "best_ask": _to_float(raw.get("bestAsk")),
        "spread": _to_float(raw.get("spread")),
        "last_trade_price": _to_float(raw.get("lastTradePrice")),
        "one_day_price_change": _to_float(raw.get("oneDayPriceChange")),
        "one_week_price_change": _to_float(raw.get("oneWeekPriceChange")),
        "liquidity": _to_float(raw.get("liquidityNum") or raw.get("liquidity"), 0.0) or 0.0,
        "volume": _to_float(raw.get("volumeNum") or raw.get("volume"), 0.0) or 0.0,
        "volume_24h": _to_float(raw.get("volume24hr"), 0.0) or 0.0,
        "outcomes": outcomes,
        "outcome_prices": prices,
        "clob_token_ids": token_ids,
    }
    return ParsedMarket(raw=raw, fields=fields)


def detect_winning_outcome(fields: dict[str, Any]) -> str | None:
    """If a market is closed, infer the winning outcome from its prices."""
    if not fields.get("closed"):
        return None
    outcomes = fields.get("outcomes") or []
    prices = fields.get("outcome_prices") or []
    if len(outcomes) != len(prices) or not outcomes:
        return None
    best_i = max(range(len(prices)), key=lambda i: prices[i])
    return outcomes[best_i] if prices[best_i] >= 0.9 else None


def market_mid_yes(fields: dict[str, Any]) -> float | None:
    """YES implied probability (mid of best bid/ask, else first outcome price)."""
    bb, ba = fields.get("best_bid"), fields.get("best_ask")
    if bb is not None and ba is not None and ba >= bb:
        return (bb + ba) / 2.0
    prices = fields.get("outcome_prices") or []
    return prices[0] if prices else fields.get("last_trade_price")


def quality_filter(fields: dict[str, Any], eff: EffectiveSettings) -> tuple[bool, str]:
    """Apply documented quality filters. Returns (passed, reason-if-rejected)."""
    if not fields["active"] or fields["closed"]:
        return False, "inactive or resolved"
    if not fields["enable_order_book"]:
        return False, "order book disabled"
    outcomes = [o.lower() for o in fields["outcomes"]]
    if sorted(outcomes) != ["no", "yes"]:
        return False, "non-binary or unclear outcomes"
    if not fields.get("description"):
        return False, "missing resolution rules"
    if fields["liquidity"] < eff.min_liquidity:
        return False, f"liquidity ${fields['liquidity']:,.0f} < ${eff.min_liquidity:,.0f}"
    if fields["volume_24h"] < eff.min_volume_24h:
        return False, f"24h volume ${fields['volume_24h']:,.0f} < ${eff.min_volume_24h:,.0f}"
    spread = fields.get("spread")
    if spread is not None and spread > eff.max_spread:
        return False, f"spread {spread:.3f} > {eff.max_spread:.3f}"

    mid = market_mid_yes(fields)
    if mid is None:
        return False, "no price available"
    band = eff.extreme_price_band
    if not eff.allow_extreme_prices and (mid < band or mid > 1 - band):
        return False, f"price {mid:.3f} near 0/1 (extreme disabled)"

    end = fields.get("end_date")
    if end is not None:
        days = (end - datetime.utcnow()).total_seconds() / 86400.0
        if days > eff.max_days_to_resolution and fields["liquidity"] < eff.strong_liquidity_override:
            return False, f"resolves in {days:.0f}d (> {eff.max_days_to_resolution}d) w/o strong liquidity"

    if eff.categories_filter and fields["category"] not in eff.categories_filter:
        return False, f"category {fields['category']} not in filter"

    return True, "ok"


def upsert_market(session: Session, fields: dict[str, Any]) -> Market:
    """Insert or update a market row from normalized fields."""
    m = session.get(Market, fields["id"])
    if m is None:
        m = Market(id=fields["id"], first_seen_at=utcnow())
        session.add(m)
    for k, v in fields.items():
        if k == "id":
            continue
        setattr(m, k, v)
    m.winning_outcome = detect_winning_outcome(fields) or m.winning_outcome
    m.updated_at = utcnow()
    session.flush()
    return m


def collect_markets(
    session: Session, client: PolymarketClient, eff: EffectiveSettings
) -> tuple[list[Market], int]:
    """Fetch active markets, upsert them all, and return (qualifying, fetched).

    Every fetched market is upserted so detail pages work, but only markets that
    pass :func:`quality_filter` are returned for scoring.
    """
    raw_markets = client.fetch_active_markets(min_liquidity=eff.min_liquidity)
    qualifying: list[Market] = []
    for raw in raw_markets:
        parsed = parse_market(raw)
        if parsed is None:
            continue
        m = upsert_market(session, parsed.fields)
        passed, _ = quality_filter(parsed.fields, eff)
        if passed:
            qualifying.append(m)
    session.flush()
    return qualifying, len(raw_markets)


def refresh_market_by_id(
    session: Session, client: PolymarketClient, market_id: str
) -> Market | None:
    """Re-fetch a single market by id and upsert it (used to detect resolution)."""
    raw = client.fetch_market(market_id)
    if not raw:
        return session.get(Market, market_id)
    parsed = parse_market(raw)
    if parsed is None:
        return session.get(Market, market_id)
    return upsert_market(session, parsed.fields)
