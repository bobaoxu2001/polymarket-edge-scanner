"""Fair-probability model (``MarketAsPriorModel``) and its signal components.

The philosophy is deliberately conservative: **start from the market price** and
apply small, transparent adjustments. With no external data configured, the fair
probability collapses back to (a lightly calibrated) market-implied probability,
so the system never invents an edge out of thin air.

    p_fair = 0.70 * calibrated_market_probability
           + 0.15 * external_signal_probability
           + 0.10 * microstructure_signal_probability
           + 0.05 * news_signal_probability

Any signal that is unavailable contributes a *neutral* value (the market mid),
so it does not push the estimate away from the market.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.services.news_signal import SignalResult, news_signal_probability

# Component weights — must sum to 1.0.
WEIGHTS = {"market": 0.70, "external": 0.15, "microstructure": 0.10, "news": 0.05}

# Calibration placeholder: shrink probabilities slightly toward 0.5 and clamp,
# so we never act overconfident near 0 or 1. Replace with an empirically fit
# isotonic / Platt calibration once enough resolved history exists.
_CALIBRATION_SHRINK = 0.96
_CLAMP_LO, _CLAMP_HI = 0.02, 0.98


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class MarketView:
    """Parsed, model-ready view of one market (YES-outcome oriented)."""

    slug: str | None
    mid_yes: float  # implied market probability of YES
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    liquidity: float
    volume_24h: float
    one_day_price_change: float | None = None
    one_week_price_change: float | None = None
    # Optional CLOB book for the YES token: {"bids":[{price,size}], "asks":[...]}
    orderbook: dict[str, Any] | None = None


@dataclass
class FairProbabilityResult:
    """Output of the model with a full, auditable breakdown."""

    fair_prob_yes: float
    implied_prob_yes: float
    calibrated_market_prob: float
    external_prob: float | None
    micro_prob: float | None
    news_prob: float | None
    signals_available: dict[str, bool]
    weights: dict[str, float]
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 1) Calibrated market probability
# --------------------------------------------------------------------------- #
def calibrated_market_probability(price: float) -> float:
    """Convert a market price into a calibrated implied probability.

    Applies a mild shrink toward 0.5 and clamps away from the extremes so the
    model does not become overconfident near 0 or 1. This is an explicit
    placeholder for a data-driven calibration curve.
    """
    p = _clamp(price, 0.0001, 0.9999)
    shrunk = 0.5 + (p - 0.5) * _CALIBRATION_SHRINK
    return _clamp(shrunk, _CLAMP_LO, _CLAMP_HI)


# --------------------------------------------------------------------------- #
# 2) External signal probability (optional CSV)
# --------------------------------------------------------------------------- #
_external_cache: dict[str, Any] = {"mtime": None, "rows": {}}


def _load_external_signals() -> dict[tuple[str, str], dict]:
    """Load + cache ``external_signals.csv`` keyed by (slug, outcome-lowercased).

    Columns: ``market_slug, outcome, external_probability, source, timestamp``.
    Re-reads only when the file's mtime changes.
    """
    path: Path = settings.external_signals_path
    if not path.exists():
        _external_cache.update(mtime=None, rows={})
        return {}
    mtime = path.stat().st_mtime
    if _external_cache["mtime"] == mtime:
        return _external_cache["rows"]

    rows: dict[tuple[str, str], dict] = {}
    try:
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                slug = (r.get("market_slug") or "").strip()
                outcome = (r.get("outcome") or "").strip().lower()
                if not slug or not outcome:
                    continue
                try:
                    prob = float(r.get("external_probability", ""))
                except (TypeError, ValueError):
                    continue
                rows[(slug, outcome)] = {
                    "probability": _clamp(prob, 0.0, 1.0),
                    "source": (r.get("source") or "").strip(),
                    "timestamp": (r.get("timestamp") or "").strip(),
                }
    except OSError:
        rows = {}
    _external_cache.update(mtime=mtime, rows=rows)
    return rows


def external_signal_probability(slug: str | None, market_mid: float) -> SignalResult:
    """Return an external probability of YES from the optional CSV, else neutral.

    A row for outcome ``Yes`` is used directly; a ``No`` row is converted to
    ``1 - p``. If no row matches, the signal is neutral (market mid) and flagged
    unavailable.
    """
    if not slug:
        return SignalResult(market_mid, False, "no slug to match external signal")
    rows = _load_external_signals()
    if not rows:
        return SignalResult(market_mid, False, "no external_signals.csv configured")

    yes = rows.get((slug, "yes"))
    no = rows.get((slug, "no"))
    if yes is not None:
        p = yes["probability"]
        return SignalResult(p, True, f"external YES={p:.3f} ({yes['source'] or 'csv'})")
    if no is not None:
        p = 1.0 - no["probability"]
        return SignalResult(p, True, f"external (from NO) YES={p:.3f} ({no['source'] or 'csv'})")
    return SignalResult(market_mid, False, "no external row for this market")


# --------------------------------------------------------------------------- #
# 3) Microstructure signal probability
# --------------------------------------------------------------------------- #
_MICRO_MOMENTUM_W = 0.5   # weight on 1d price change (continuation)
_MICRO_IMBALANCE_W = 0.04  # weight on top-of-book depth imbalance
_MICRO_BOUND = 0.05        # max total deviation from mid


def _top_of_book_imbalance(orderbook: dict[str, Any] | None) -> float | None:
    """Signed top-of-book size imbalance in [-1, 1], or None if unavailable.

    CLOB books list bids/asks with the *best* quote as the last element.
    Positive imbalance => more bid (buy) pressure => mild upward nudge.
    """
    if not orderbook:
        return None
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    if not bids or not asks:
        return None
    try:
        bid_sz = float(bids[-1]["size"])
        ask_sz = float(asks[-1]["size"])
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    denom = bid_sz + ask_sz
    if denom <= 0:
        return None
    return (bid_sz - ask_sz) / denom


def microstructure_signal_probability(view: MarketView) -> SignalResult:
    """Nudge the mid using short-term momentum and order-book imbalance.

    The adjustment is bounded to ``±_MICRO_BOUND``. If neither momentum nor depth
    is available, returns the market mid and flags itself unavailable.
    """
    mid = view.mid_yes
    nudge = 0.0
    used: list[str] = []

    if view.one_day_price_change is not None:
        m = _clamp(_MICRO_MOMENTUM_W * view.one_day_price_change, -0.02, 0.02)
        if abs(m) > 1e-9:
            nudge += m
            used.append(f"1d_momentum={view.one_day_price_change:+.3f}")

    imb = _top_of_book_imbalance(view.orderbook)
    if imb is not None:
        i = _clamp(_MICRO_IMBALANCE_W * imb, -0.03, 0.03)
        nudge += i
        used.append(f"book_imbalance={imb:+.2f}")

    if not used:
        return SignalResult(mid, False, "no microstructure data (momentum/depth)")

    nudge = _clamp(nudge, -_MICRO_BOUND, _MICRO_BOUND)
    prob = _clamp(mid + nudge, _CLAMP_LO, _CLAMP_HI)
    return SignalResult(prob, True, "micro: " + ", ".join(used))


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
class MarketAsPriorModel:
    """First-version fair-probability model: market price as the prior."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or dict(WEIGHTS)
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:  # normalize defensively
            self.weights = {k: v / total for k, v in self.weights.items()}

    def fair_probability(self, view: MarketView) -> FairProbabilityResult:
        """Compute the blended fair probability of YES with a full breakdown."""
        mid = _clamp(view.mid_yes, _CLAMP_LO, _CLAMP_HI)
        cal = calibrated_market_probability(mid)

        ext = external_signal_probability(view.slug, mid)
        micro = microstructure_signal_probability(view)
        news = news_signal_probability(mid, view.slug)

        # Unavailable signals contribute the neutral market mid.
        ext_val = ext.probability if ext.available else mid
        micro_val = micro.probability if micro.available else mid
        news_val = news.probability if news.available else mid

        w = self.weights
        fair = (
            w["market"] * cal
            + w["external"] * ext_val
            + w["microstructure"] * micro_val
            + w["news"] * news_val
        )
        fair = _clamp(fair, _CLAMP_LO, _CLAMP_HI)

        return FairProbabilityResult(
            fair_prob_yes=fair,
            implied_prob_yes=mid,
            calibrated_market_prob=cal,
            external_prob=ext.probability if ext.available else None,
            micro_prob=micro.probability if micro.available else None,
            news_prob=news.probability if news.available else None,
            signals_available={
                "market": True,
                "external": ext.available,
                "microstructure": micro.available,
                "news": news.available,
            },
            weights=dict(w),
            notes=[
                f"calibration: shrink={_CALIBRATION_SHRINK}",
                ext.note,
                micro.note,
                news.note,
            ],
        )
