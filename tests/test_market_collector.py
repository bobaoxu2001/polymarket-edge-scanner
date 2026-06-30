"""Tests for market parsing, quality filters, and duplicate-safe collection."""
from __future__ import annotations

from backend.services.market_collector import (
    categorize,
    collect_markets,
    parse_market,
    quality_filter,
)
from backend.services.settings_store import EffectiveSettings


def _raw(market_id: str = "123") -> dict:
    """A Gamma-style raw market that passes the default quality filters."""
    return {
        "id": market_id,
        "question": "Will the example event happen?",
        "slug": f"will-example-{market_id}",
        "description": "Resolves YES if the example event occurs by the end date.",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.5", "0.5"]',
        "clobTokenIds": '["tok0", "tok1"]',
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "bestBid": 0.49,
        "bestAsk": 0.51,
        "spread": 0.02,
        "liquidity": "20000",
        "volume24hr": "1500",
        "volume": "5000",
        "endDate": "2026-09-01T00:00:00Z",
        "events": [],
    }


class _StubClient:
    """Minimal duck-typed client returning a fixed raw market list."""

    def __init__(self, markets: list[dict]) -> None:
        self._markets = markets

    def fetch_active_markets(self, **_kw) -> list[dict]:
        return self._markets


def test_parse_market_normalizes_json_string_fields():
    parsed = parse_market(_raw())
    assert parsed is not None
    f = parsed.fields
    assert f["outcomes"] == ["Yes", "No"]
    assert f["outcome_prices"] == [0.5, 0.5]
    assert f["clob_token_ids"] == ["tok0", "tok1"]
    assert f["liquidity"] == 20000.0


def test_quality_filter_passes_good_market_and_rejects_extremes():
    f = parse_market(_raw()).fields
    ok, _ = quality_filter(f, EffectiveSettings())
    assert ok is True

    # Price near 0/1 is rejected unless explicitly enabled.
    extreme = parse_market(_raw()).fields
    extreme["best_bid"], extreme["best_ask"] = 0.0, 0.02
    rejected, reason = quality_filter(extreme, EffectiveSettings())
    assert rejected is False
    assert "near 0/1" in reason


def test_categorize_keywords():
    assert categorize("Will Bitcoin hit $100k?", "", []) == "Crypto"
    assert categorize("Will Trump win the election?", "", []) == "Politics"


def test_collect_markets_deduplicates_repeated_ids(session):
    # The same market returned twice (e.g. Gamma pagination overlap) must not
    # produce duplicate rows or crash on the opportunities unique constraint.
    client = _StubClient([_raw("123"), _raw("123"), _raw("456")])
    qualifying, scanned = collect_markets(session, client, EffectiveSettings())
    ids = [m.id for m in qualifying]
    assert sorted(ids) == ["123", "456"]   # 123 deduped
    assert scanned == 2                     # unique markets scanned
