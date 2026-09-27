"""Candle aggregation built from public market ticks, without REST backfills."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.data.websocket import MarketTick


LOGGER = logging.getLogger(__name__)

ONE_MINUTE_SECONDS = 60
FIVE_MINUTES_SECONDS = 300


@dataclass(slots=True)
class Candle:
    """An in-progress or completed OHLCV candle for one symbol and interval."""

    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    number_of_trades: int
    last_trade_timestamp: datetime
    notional: Decimal
    buy_volume: Decimal
    sell_volume: Decimal

    @classmethod
    def from_tick(cls, timestamp: datetime, tick: MarketTick) -> Candle:
        buy_volume, sell_volume = _split_aggressor_volume(tick)
        return cls(
            timestamp=timestamp,
            symbol=tick.symbol,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.quantity,
            number_of_trades=1,
            last_trade_timestamp=tick.timestamp,
            notional=tick.price * tick.quantity,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )

    def add_tick(self, tick: MarketTick) -> None:
        """Include a later aggregate trade in this candle."""

        self.high = max(self.high, tick.price)
        self.low = min(self.low, tick.price)
        self.close = tick.price
        self.volume += tick.quantity
        self.number_of_trades += 1
        self.notional += tick.price * tick.quantity
        buy_volume, sell_volume = _split_aggressor_volume(tick)
        self.buy_volume += buy_volume
        self.sell_volume += sell_volume
        self.last_trade_timestamp = max(self.last_trade_timestamp, tick.timestamp)


def _split_aggressor_volume(tick: MarketTick) -> tuple[Decimal, Decimal]:
    """Return estimated buy and sell volume from Binance's ``m`` field.

    For an aggregate trade, ``m`` means "is the buyer the market maker?".
    A market-maker buyer implies a seller initiated the trade (sell volume);
    otherwise the buyer was the taker (buy volume). Unknown flags are excluded
    from both estimates instead of being guessed.
    """

    if tick.is_buyer_market_maker is True:
        return Decimal("0"), tick.quantity
    if tick.is_buyer_market_maker is False:
        return tick.quantity, Decimal("0")
    return Decimal("0"), Decimal("0")


class CandleAggregator:
    """Aggregate ticks into active and completed 1-minute and 5-minute candles."""

    def __init__(
        self,
        timeframes: tuple[int, ...] = (ONE_MINUTE_SECONDS, FIVE_MINUTES_SECONDS),
        *,
        history_limit: int = 1_000,
    ) -> None:
        if not timeframes or any(seconds <= 0 for seconds in timeframes):
            raise ValueError("timeframes must contain positive durations")
        if len(set(timeframes)) != len(timeframes):
            raise ValueError("timeframes must be unique")
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")

        self._timeframes = timeframes
        self._active: dict[int, Candle] = {}
        self._completed = {
            seconds: deque[Candle](maxlen=history_limit) for seconds in timeframes
        }

    def add_tick(self, tick: MarketTick) -> list[Candle]:
        """Update each timeframe and return candles closed by this tick."""

        completed: list[Candle] = []
        for seconds in self._timeframes:
            candle_start = self._candle_start(tick.timestamp, seconds)
            active = self._active.get(seconds)

            if active is None:
                self._active[seconds] = Candle.from_tick(candle_start, tick)
            elif candle_start == active.timestamp:
                active.add_tick(tick)
            elif candle_start > active.timestamp:
                self._completed[seconds].append(active)
                completed.append(active)
                self._active[seconds] = Candle.from_tick(candle_start, tick)
            else:
                LOGGER.warning(
                    "Ignoring out-of-order tick timestamp=%s for %ss candle",
                    tick.timestamp.isoformat(),
                    seconds,
                )
        return completed

    def candles(self, seconds: int, *, include_current: bool = True) -> list[Candle]:
        """Return retained completed candles and optionally the active candle."""

        if seconds not in self._completed:
            raise ValueError(f"Unsupported candle interval: {seconds}")
        candles = list(self._completed[seconds])
        active = self._active.get(seconds)
        if include_current and active is not None:
            candles.append(active)
        return candles

    def current_candle(self, seconds: int) -> Candle | None:
        """Return the active candle for an interval, if any."""

        if seconds not in self._completed:
            raise ValueError(f"Unsupported candle interval: {seconds}")
        return self._active.get(seconds)

    @staticmethod
    def _candle_start(timestamp: datetime, seconds: int) -> datetime:
        if timestamp.tzinfo is None:
            raise ValueError("Tick timestamps must be timezone-aware")
        utc_timestamp = timestamp.astimezone(timezone.utc)
        epoch_seconds = int(utc_timestamp.timestamp())
        return datetime.fromtimestamp(
            epoch_seconds - (epoch_seconds % seconds), tz=timezone.utc
        )
