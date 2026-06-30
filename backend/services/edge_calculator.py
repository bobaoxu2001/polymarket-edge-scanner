"""Edge calculation, suggested-action logic, and confidence scoring.

All functions here are pure (no I/O), which makes them straightforward to unit
test. Edge is computed *after* fees, slippage, and a safety margin, so a positive
edge already accounts for the main frictions of actually taking the price.
"""
from __future__ import annotations

from dataclasses import dataclass

# Action labels (kept as constants to avoid stringly-typed bugs).
ACTION_BUY_YES = "PAPER BUY YES"
ACTION_BUY_NO = "PAPER BUY NO"
ACTION_WATCH = "WATCH"
ACTION_AVOID = "AVOID"


def estimated_slippage(spread: float | None) -> float:
    """Slippage estimate: ``max(0.005, spread * 0.25)``.

    A wider quoted spread implies a thinner book, hence more slippage when
    crossing it. A floor of 50 bps guards against zero-spread illusions.
    """
    s = spread if spread and spread > 0 else 0.0
    return max(0.005, s * 0.25)


@dataclass
class EdgeResult:
    """Edge for both sides after all frictions, plus the inputs used."""

    edge_yes: float
    edge_no: float
    ask_yes: float
    ask_no: float
    fee: float
    slippage: float
    safety_margin: float
    best_side: str | None
    best_edge: float


def compute_edges(
    p_fair_yes: float,
    ask_yes: float,
    ask_no: float,
    *,
    spread: float | None = None,
    fee: float = 0.0,
    safety_margin: float = 0.015,
    slippage: float | None = None,
) -> EdgeResult:
    """Compute YES/NO edge after fee, slippage, and safety margin.

    ``edge_yes = p_fair - ask_yes - fee - slippage - safety_margin``
    ``edge_no  = (1 - p_fair) - ask_no - fee - slippage - safety_margin``
    """
    slip = estimated_slippage(spread) if slippage is None else slippage
    friction = fee + slip + safety_margin
    edge_yes = p_fair_yes - ask_yes - friction
    edge_no = (1.0 - p_fair_yes) - ask_no - friction

    if edge_yes >= edge_no:
        best_side, best_edge = "YES", edge_yes
    else:
        best_side, best_edge = "NO", edge_no

    return EdgeResult(
        edge_yes=edge_yes,
        edge_no=edge_no,
        ask_yes=ask_yes,
        ask_no=ask_no,
        fee=fee,
        slippage=slip,
        safety_margin=safety_margin,
        best_side=best_side,
        best_edge=best_edge,
    )


@dataclass
class ActionResult:
    action: str
    best_side: str | None
    best_edge: float
    reason: str


def suggested_action(
    edge: EdgeResult,
    *,
    spread: float | None,
    liquidity: float,
    min_edge_to_trade: float = 0.025,
    max_spread: float = 0.05,
    min_liquidity: float = 5000.0,
) -> ActionResult:
    """Map an :class:`EdgeResult` to a suggested action with a reason.

    Precedence: hard AVOID guards (wide spread / thin liquidity) first, then a
    PAPER BUY on whichever side clears ``min_edge_to_trade``, otherwise WATCH.
    """
    if spread is not None and spread > max_spread:
        return ActionResult(
            ACTION_AVOID, edge.best_side, edge.best_edge,
            f"spread {spread:.3f} exceeds max {max_spread:.3f}",
        )
    if liquidity < min_liquidity:
        return ActionResult(
            ACTION_AVOID, edge.best_side, edge.best_edge,
            f"liquidity ${liquidity:,.0f} below min ${min_liquidity:,.0f}",
        )

    if edge.edge_yes >= min_edge_to_trade and edge.edge_yes >= edge.edge_no:
        return ActionResult(
            ACTION_BUY_YES, "YES", edge.edge_yes,
            f"edge {edge.edge_yes:+.3f} >= min {min_edge_to_trade:.3f} on YES "
            f"(ask {edge.ask_yes:.3f})",
        )
    if edge.edge_no >= min_edge_to_trade:
        return ActionResult(
            ACTION_BUY_NO, "NO", edge.edge_no,
            f"edge {edge.edge_no:+.3f} >= min {min_edge_to_trade:.3f} on NO "
            f"(ask {edge.ask_no:.3f})",
        )

    return ActionResult(
        ACTION_WATCH, edge.best_side, edge.best_edge,
        f"best edge {edge.best_edge:+.3f} below min {min_edge_to_trade:.3f}",
    )


def confidence_score(
    best_edge: float,
    *,
    spread: float | None,
    liquidity: float,
    volume_24h: float,
    signals_available: dict[str, bool] | None = None,
    max_spread: float = 0.05,
) -> float:
    """Heuristic confidence in [0, 1] blending edge, liquidity, spread, signals.

    This is a transparency aid, not a probability. Higher means the opportunity
    rests on a larger edge, deeper/tighter market, and more corroborating signals.
    """
    edge_c = _clamp01(best_edge / 0.06)                 # 6%+ edge -> full
    liq_c = _clamp01(liquidity / 50_000.0)              # $50k+ -> full
    vol_c = _clamp01(volume_24h / 25_000.0)             # $25k/24h -> full
    spread_c = 1.0 - _clamp01((spread or max_spread) / max_spread)

    sig = signals_available or {}
    extra = [sig.get("external"), sig.get("microstructure"), sig.get("news")]
    signal_c = sum(1 for s in extra if s) / 3.0

    score = (
        0.40 * edge_c
        + 0.20 * liq_c
        + 0.10 * vol_c
        + 0.15 * spread_c
        + 0.15 * signal_c
    )
    return round(_clamp01(score), 4)


def confidence_level(score: float) -> str:
    """Bucket a confidence score into HIGH / MEDIUM / LOW."""
    if score >= 0.66:
        return "HIGH"
    if score >= 0.40:
        return "MEDIUM"
    return "LOW"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))
