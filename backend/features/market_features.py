"""Rolling features derived from live, locally aggregated market candles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from backend.data.candles import Candle, CandleAggregator, ONE_MINUTE_SECONDS
from backend.data.websocket import MarketTick


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class MarketFeatureSnapshot:
    """A typed feature vector for a future paper-trading strategy layer.

    A ``None`` field is unavailable because the live stream has not yet supplied
    enough contiguous history, or because its calculation would divide by zero.
    """

    timestamp: datetime
    symbol: str
    price: Decimal
    return_1m: Decimal | None
    return_5m: Decimal | None
    current_1m_volume: Decimal
    average_1m_volume: Decimal | None
    volume_ratio: Decimal | None
    number_of_trades: int
    average_trade_size: Decimal | None
    rsi_14: Decimal | None
    sma_20: Decimal | None
    sma_50: Decimal | None
    price_distance_sma20: Decimal | None
    return_volatility_20: Decimal | None
    atr_14: Decimal | None
    vwap: Decimal | None
    price_distance_vwap: Decimal | None
    buy_volume: Decimal
    sell_volume: Decimal
    buy_sell_volume_ratio: Decimal | None


class MarketFeatures:
    """Maintain candle history and calculate rolling BTCUSDT market features."""

    def __init__(
        self,
        *,
        volume_window: int = 20,
        volatility_window: int = 20,
    ) -> None:
        if volume_window <= 0 or volatility_window <= 0:
            raise ValueError("rolling windows must be positive")
        self._aggregator = CandleAggregator()
        self._volume_window = volume_window
        self._volatility_window = volatility_window

    def update(self, tick: MarketTick) -> MarketFeatureSnapshot:
        """Consume one live tick and return the feature snapshot after it."""

        self._aggregator.add_tick(tick)
        return self.snapshot()

    def snapshot(self) -> MarketFeatureSnapshot:
        """Build a snapshot from the most recent active 1-minute candle."""

        candles = self._aggregator.candles(ONE_MINUTE_SECONDS)
        current = self._aggregator.current_candle(ONE_MINUTE_SECONDS)
        if current is None:
            raise RuntimeError("No ticks have been processed")

        return_1m = _return_for_period(candles, timedelta(minutes=1))
        return_5m = _return_for_period(candles, timedelta(minutes=5))
        previous_volume_candles = _contiguous_tail(candles[:-1], self._volume_window)
        average_1m_volume = (
            sum((candle.volume for candle in previous_volume_candles), ZERO)
            / Decimal(len(previous_volume_candles))
            if previous_volume_candles
            else None
        )
        volume_ratio = _ratio(current.volume, average_1m_volume)
        average_trade_size = (
            current.volume / Decimal(current.number_of_trades)
            if current.number_of_trades > 0
            else None
        )

        rsi_14 = _rsi(candles, period=14)
        sma_20 = _sma(candles, period=20)
        sma_50 = _sma(candles, period=50)
        price_distance_sma20 = _relative(current.close, sma_20)
        return_volatility_20 = _return_volatility(
            candles, period=self._volatility_window
        )
        atr_14 = _atr(candles, period=14)
        vwap = _session_vwap(candles, current)
        price_distance_vwap = _relative(current.close, vwap)

        return MarketFeatureSnapshot(
            timestamp=current.last_trade_timestamp,
            symbol=current.symbol,
            price=current.close,
            return_1m=return_1m,
            return_5m=return_5m,
            current_1m_volume=current.volume,
            average_1m_volume=average_1m_volume,
            volume_ratio=volume_ratio,
            number_of_trades=current.number_of_trades,
            average_trade_size=average_trade_size,
            rsi_14=rsi_14,
            sma_20=sma_20,
            sma_50=sma_50,
            price_distance_sma20=price_distance_sma20,
            return_volatility_20=return_volatility_20,
            atr_14=atr_14,
            vwap=vwap,
            price_distance_vwap=price_distance_vwap,
            buy_volume=current.buy_volume,
            sell_volume=current.sell_volume,
            buy_sell_volume_ratio=_ratio(current.buy_volume, current.sell_volume),
        )


def _contiguous_tail(candles: list[Candle], count: int) -> list[Candle] | None:
    if len(candles) < count:
        return None
    tail = candles[-count:]
    interval = timedelta(minutes=1)
    if any(
        later.timestamp - earlier.timestamp != interval
        for earlier, later in zip(tail, tail[1:])
    ):
        return None
    return tail


def _return_for_period(candles: list[Candle], period: timedelta) -> Decimal | None:
    if len(candles) < 2:
        return None
    current = candles[-1]
    target_timestamp = current.timestamp - period
    previous = next(
        (candle for candle in reversed(candles[:-1]) if candle.timestamp == target_timestamp),
        None,
    )
    return _relative(current.close, previous.close) if previous else None


def _relative(value: Decimal, reference: Decimal | None) -> Decimal | None:
    if reference is None or reference == ZERO:
        return None
    return value / reference - ONE


def _ratio(value: Decimal, reference: Decimal | None) -> Decimal | None:
    if reference is None or reference == ZERO:
        return None
    return value / reference


def _sma(candles: list[Candle], period: int) -> Decimal | None:
    window = _contiguous_tail(candles, period)
    if window is None:
        return None
    return sum((candle.close for candle in window), ZERO) / Decimal(period)


def _rsi(candles: list[Candle], period: int) -> Decimal | None:
    window = _contiguous_tail(candles, period + 1)
    if window is None:
        return None
    changes = [
        later.close - earlier.close
        for earlier, later in zip(window, window[1:])
    ]
    average_gain = sum((max(change, ZERO) for change in changes), ZERO) / Decimal(period)
    average_loss = sum((max(-change, ZERO) for change in changes), ZERO) / Decimal(period)
    if average_loss == ZERO:
        return Decimal("100") if average_gain > ZERO else None
    relative_strength = average_gain / average_loss
    return Decimal("100") - Decimal("100") / (ONE + relative_strength)


def _return_volatility(candles: list[Candle], period: int) -> Decimal | None:
    window = _contiguous_tail(candles, period + 1)
    if window is None:
        return None
    returns = [
        _relative(later.close, earlier.close)
        for earlier, later in zip(window, window[1:])
    ]
    if any(value is None for value in returns):
        return None
    values = [value for value in returns if value is not None]
    mean = sum(values, ZERO) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), ZERO) / Decimal(
        len(values)
    )
    return variance.sqrt()


def _atr(candles: list[Candle], period: int) -> Decimal | None:
    window = _contiguous_tail(candles, period + 1)
    if window is None:
        return None
    true_ranges = [
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in zip(window, window[1:])
    ]
    return sum(true_ranges, ZERO) / Decimal(period)


def _session_vwap(candles: list[Candle], current: Candle) -> Decimal | None:
    session_candles = [
        candle for candle in candles if candle.timestamp.date() == current.timestamp.date()
    ]
    total_volume = sum((candle.volume for candle in session_candles), ZERO)
    if total_volume == ZERO:
        return None
    return sum((candle.notional for candle in session_candles), ZERO) / total_volume
