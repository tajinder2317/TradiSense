"""Typed baseline-strategy signals, separate from paper order models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from backend.features.market_features import MarketFeatureSnapshot


class SignalAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"


class MarketState(StrEnum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


class ExecutionAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class Signal:
    """An explainable decision calculated from one currently available snapshot.

    ``signal_strength`` is the normalized count of satisfied rule categories.
    It is not a probability or a prediction of profit. ``SHORT`` is reserved
    for future research; this spot-only baseline emits HOLD with a BEARISH
    market state rather than implying that a short position can be opened.
    """

    timestamp: datetime
    symbol: str
    action: SignalAction
    signal_strength: float
    score: int
    max_score: int
    reasons: tuple[str, ...]
    feature_snapshot: MarketFeatureSnapshot
    market_state: MarketState
    is_actionable: bool
