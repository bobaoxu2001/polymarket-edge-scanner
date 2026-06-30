"""News signal — *placeholder only*.

Important policy: an LLM / news pipeline is **never** allowed to make the final
trading decision. At most it may contribute a small, bounded adjustment to the
fair-probability estimate plus a human-readable explanation. This module returns
a neutral signal by default and exists to make that boundary explicit and to
provide a wiring point for a future, carefully-gated implementation.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.config import settings

# Hard cap on how far news may ever move a probability estimate.
MAX_NEWS_ADJUSTMENT = 0.03


@dataclass
class SignalResult:
    """A probability signal plus whether it was actually available."""

    probability: float
    available: bool
    note: str


def news_signal_probability(market_mid: float, slug: str | None = None) -> SignalResult:
    """Return a bounded news-derived probability for the YES outcome.

    In the MVP this is disabled and simply echoes the market mid (a neutral
    signal). Even when enabled in the future, the adjustment is clamped to
    ``±MAX_NEWS_ADJUSTMENT`` and is advisory only — see module docstring.
    """
    if not settings.news_signal_enabled:
        return SignalResult(
            probability=market_mid,
            available=False,
            note="news signal disabled (placeholder, never authoritative)",
        )

    # Placeholder for a future bounded news/LLM adjustment. No live source is
    # wired up, so we return neutral but flag it as 'enabled but no data'.
    return SignalResult(
        probability=market_mid,
        available=False,
        note="news signal enabled but no news source configured",
    )
