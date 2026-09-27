"""A fixed, explainable baseline long strategy for paper-trading research."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.features.market_features import MarketFeatureSnapshot
from backend.strategy.signals import MarketState, Signal, SignalAction


@dataclass(frozen=True, slots=True)
class BaselineStrategyConfig:
    """Explicit, fixed baseline thresholds; these are not live-data optimized."""

    minimum_long_score: int = 4
    minimum_volume_ratio: Decimal = Decimal("1.2")
    minimum_buy_sell_ratio: Decimal = Decimal("1")
    maximum_entry_rsi: Decimal = Decimal("70")
    require_hold_reset_before_long: bool = True


class BaselineStrategy:
    """Score current-only feature evidence without future prices or candles.

    Each evaluation receives exactly one MarketFeatureSnapshot, which the Phase
    2 engine built from ticks observed no later than its timestamp. The strategy
    does not retain candle data, query market data, or revise past decisions.
    """

    MAX_SCORE = 5

    def __init__(self, config: BaselineStrategyConfig | None = None) -> None:
        self.config = config or BaselineStrategyConfig()
        if not 1 <= self.config.minimum_long_score <= self.MAX_SCORE:
            raise ValueError("minimum_long_score must be between 1 and 5")
        self._last_action: dict[str, SignalAction] = {}

    def evaluate(self, snapshot: MarketFeatureSnapshot) -> Signal:
        """Return a transparent long-or-hold signal from the supplied snapshot."""

        score = 0
        reasons: list[str] = []

        momentum_confirmed = self._momentum_confirmed(snapshot, reasons)
        if momentum_confirmed:
            score += 1

        trend_confirmed = self._trend_confirmed(snapshot, reasons)
        if trend_confirmed:
            score += 1

        vwap_confirmed = self._vwap_confirmed(snapshot, reasons)
        if vwap_confirmed:
            score += 1

        volume_confirmed = self._volume_confirmed(snapshot, reasons)
        if volume_confirmed:
            score += 1

        flow_confirmed = self._flow_confirmed(snapshot, reasons)
        if flow_confirmed:
            score += 1

        rsi_allows_entry = self._rsi_allows_entry(snapshot, reasons)
        market_state = self._market_state(snapshot, momentum_confirmed, trend_confirmed)
        qualifies_long = (
            momentum_confirmed
            and score >= self.config.minimum_long_score
            and rsi_allows_entry
        )
        action = SignalAction.LONG if qualifies_long else SignalAction.HOLD

        previous_action = self._last_action.get(snapshot.symbol, SignalAction.HOLD)
        is_actionable = action is SignalAction.LONG and (
            not self.config.require_hold_reset_before_long
            or previous_action is not SignalAction.LONG
        )
        if action is SignalAction.LONG and not is_actionable:
            reasons.append("long signal unchanged; paper buy suppressed until HOLD reset")
        self._last_action[snapshot.symbol] = action

        return Signal(
            timestamp=snapshot.timestamp,
            symbol=snapshot.symbol,
            action=action,
            signal_strength=score / self.MAX_SCORE,
            score=score,
            max_score=self.MAX_SCORE,
            reasons=tuple(reasons),
            feature_snapshot=snapshot,
            market_state=market_state,
            is_actionable=is_actionable,
        )

    def _momentum_confirmed(
        self, snapshot: MarketFeatureSnapshot, reasons: list[str]
    ) -> bool:
        if snapshot.return_1m is None:
            reasons.append("1m momentum unavailable")
            return False
        if snapshot.return_5m is None:
            reasons.append("5m momentum unavailable")
            return False
        if snapshot.return_1m > 0 and snapshot.return_5m > 0:
            reasons.append("positive 1m and 5m momentum")
            return True
        reasons.append("momentum is not positive on both 1m and 5m windows")
        return False

    def _trend_confirmed(
        self, snapshot: MarketFeatureSnapshot, reasons: list[str]
    ) -> bool:
        if snapshot.sma_20 is None or snapshot.sma_50 is None:
            reasons.append("trend unavailable because SMA20 or SMA50 is missing")
            return False
        if snapshot.price > snapshot.sma_20 and snapshot.sma_20 > snapshot.sma_50:
            reasons.append("bullish trend: price above SMA20 and SMA20 above SMA50")
            return True
        reasons.append("bullish trend not confirmed")
        return False

    def _vwap_confirmed(
        self, snapshot: MarketFeatureSnapshot, reasons: list[str]
    ) -> bool:
        if snapshot.vwap is None:
            reasons.append("VWAP unavailable")
            return False
        if snapshot.price > snapshot.vwap:
            reasons.append("price above VWAP")
            return True
        reasons.append("price is not above VWAP")
        return False

    def _volume_confirmed(
        self, snapshot: MarketFeatureSnapshot, reasons: list[str]
    ) -> bool:
        if snapshot.volume_ratio is None:
            reasons.append("volume ratio unavailable")
            return False
        if snapshot.volume_ratio >= self.config.minimum_volume_ratio:
            reasons.append(
                f"volume ratio {snapshot.volume_ratio} meets {self.config.minimum_volume_ratio}"
            )
            return True
        reasons.append(
            f"volume ratio {snapshot.volume_ratio} is below {self.config.minimum_volume_ratio}"
        )
        return False

    def _flow_confirmed(
        self, snapshot: MarketFeatureSnapshot, reasons: list[str]
    ) -> bool:
        if snapshot.buy_sell_volume_ratio is None:
            reasons.append("buy/sell volume ratio unavailable")
            return False
        if snapshot.buy_sell_volume_ratio > self.config.minimum_buy_sell_ratio:
            reasons.append(
                "buy/sell volume ratio "
                f"{snapshot.buy_sell_volume_ratio} exceeds {self.config.minimum_buy_sell_ratio}"
            )
            return True
        reasons.append(
            "buy/sell volume ratio "
            f"{snapshot.buy_sell_volume_ratio} does not exceed {self.config.minimum_buy_sell_ratio}"
        )
        return False

    def _rsi_allows_entry(
        self, snapshot: MarketFeatureSnapshot, reasons: list[str]
    ) -> bool:
        if snapshot.rsi_14 is None:
            reasons.append("RSI unavailable; entry blocked")
            return False
        if snapshot.rsi_14 > self.config.maximum_entry_rsi:
            reasons.append(
                f"RSI {snapshot.rsi_14} exceeds entry limit {self.config.maximum_entry_rsi}"
            )
            return False
        reasons.append(f"RSI {snapshot.rsi_14} is within entry limit")
        return True

    @staticmethod
    def _market_state(
        snapshot: MarketFeatureSnapshot,
        momentum_confirmed: bool,
        trend_confirmed: bool,
    ) -> MarketState:
        if momentum_confirmed and trend_confirmed:
            return MarketState.BULLISH
        if (
            snapshot.return_1m is not None
            and snapshot.return_5m is not None
            and snapshot.return_1m < 0
            and snapshot.return_5m < 0
        ):
            return MarketState.BEARISH
        return MarketState.NEUTRAL
