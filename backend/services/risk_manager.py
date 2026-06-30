"""Risk management: position sizing and hard exposure limits (paper bankroll).

These rules are intentionally strict and conservative. They operate on a
*snapshot* of currently open paper positions and never mutate state, which keeps
them pure and unit-testable. The scanner/paper-trader call :meth:`evaluate` to
decide whether (and how large) a candidate paper trade may be.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Edge-strength thresholds and the bankroll fraction each maps to.
STRONG_EDGE = 0.06
MEDIUM_EDGE = 0.04
SIZE_PCT = {"weak": 0.0025, "medium": 0.005, "strong": 0.010}
MIN_TRADE_DOLLARS = 1.0  # paper trades below this are not worth recording


@dataclass
class OpenExposure:
    """A minimal view of an open paper position for exposure accounting."""

    market_id: str
    category: str
    outcome: str
    size_usd: float


@dataclass
class RiskDecision:
    approved: bool
    size_usd: float
    shares: float
    strength: str
    reasons: list[str] = field(default_factory=list)


def classify_edge_strength(edge: float, min_edge_to_trade: float) -> str:
    """Bucket an edge into weak / medium / strong for position sizing."""
    if edge >= STRONG_EDGE:
        return "strong"
    if edge >= MEDIUM_EDGE:
        return "medium"
    return "weak"  # assumes edge >= min_edge_to_trade was already checked


def base_position_size(edge: float, bankroll: float, *, min_edge_to_trade: float,
                       max_position_pct: float) -> tuple[float, str]:
    """Return the (uncapped-by-exposure) target size and its strength label.

    The size is the edge-strength fraction of bankroll, then clipped to the
    per-trade maximum (``max_position_pct``).
    """
    strength = classify_edge_strength(edge, min_edge_to_trade)
    pct = min(SIZE_PCT[strength], max_position_pct)
    return bankroll * pct, strength


class RiskManager:
    """Encapsulates bankroll-relative sizing and exposure caps."""

    def __init__(
        self,
        bankroll: float,
        *,
        max_position_pct: float = 0.01,
        max_market_exposure_pct: float = 0.05,
        max_category_exposure_pct: float = 0.15,
        min_edge_to_trade: float = 0.025,
        allow_averaging: bool = False,
    ) -> None:
        self.bankroll = bankroll
        self.max_position_pct = max_position_pct
        self.max_market_exposure_pct = max_market_exposure_pct
        self.max_category_exposure_pct = max_category_exposure_pct
        self.min_edge_to_trade = min_edge_to_trade
        self.allow_averaging = allow_averaging

    # ---- accounting helpers ------------------------------------------------
    @staticmethod
    def market_exposure(open_positions: list[OpenExposure], market_id: str) -> float:
        return sum(p.size_usd for p in open_positions if p.market_id == market_id)

    @staticmethod
    def category_exposure(open_positions: list[OpenExposure], category: str) -> float:
        return sum(p.size_usd for p in open_positions if p.category == category)

    # ---- the decision ------------------------------------------------------
    def evaluate(
        self,
        *,
        edge: float,
        price: float,
        market_id: str,
        category: str,
        outcome: str,
        cash_available: float,
        open_positions: list[OpenExposure],
    ) -> RiskDecision:
        """Decide whether a candidate trade is allowed and at what size.

        The target size (from edge strength) is shrunk to respect, in order:
        cash on hand, per-trade cap, per-market cap, and per-category cap. If the
        survivable size falls below ``MIN_TRADE_DOLLARS`` the trade is rejected.
        """
        reasons: list[str] = []

        if edge < self.min_edge_to_trade:
            return RiskDecision(False, 0.0, 0.0, "none",
                                [f"edge {edge:.3f} below min {self.min_edge_to_trade:.3f}"])
        if not (0.0 < price < 1.0):
            return RiskDecision(False, 0.0, 0.0, "none",
                                [f"invalid price {price}"])

        # Duplicate guard.
        if not self.allow_averaging:
            dup = any(
                p.market_id == market_id and p.outcome == outcome
                for p in open_positions
            )
            if dup:
                return RiskDecision(False, 0.0, 0.0, "none",
                                    ["duplicate open position (averaging disabled)"])

        target, strength = base_position_size(
            edge, self.bankroll,
            min_edge_to_trade=self.min_edge_to_trade,
            max_position_pct=self.max_position_pct,
        )

        caps = {
            "cash": max(0.0, cash_available),
            "per-trade": self.bankroll * self.max_position_pct,
            "per-market": max(
                0.0,
                self.bankroll * self.max_market_exposure_pct
                - self.market_exposure(open_positions, market_id),
            ),
            "per-category": max(
                0.0,
                self.bankroll * self.max_category_exposure_pct
                - self.category_exposure(open_positions, category),
            ),
        }
        size = target
        binding: str | None = None
        for name, cap in caps.items():
            if cap < size:
                size, binding = cap, name

        if size < MIN_TRADE_DOLLARS:
            return RiskDecision(
                False, 0.0, 0.0, strength,
                [f"no capacity: limited by {binding or 'caps'} (${size:.2f})"],
            )

        if binding:
            reasons.append(f"size capped by {binding} to ${size:.2f}")
        else:
            reasons.append(f"sized at {strength} = ${size:.2f}")

        shares = size / price
        return RiskDecision(True, round(size, 2), round(shares, 4), strength, reasons)
