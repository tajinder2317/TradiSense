"""Deterministic tests for local candle aggregation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.data.candles import CandleAggregator, FIVE_MINUTES_SECONDS, ONE_MINUTE_SECONDS
from backend.data.websocket import MarketTick


BASE_TIME = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_tick(
    minute: int = 0,
    second: int = 0,
    *,
    price: str = "100",
    quantity: str = "1",
    buyer_is_market_maker: bool | None = False,
) -> MarketTick:
    return MarketTick(
        timestamp=BASE_TIME + timedelta(minutes=minute, seconds=second),
        symbol="BTCUSDT",
        price=Decimal(price),
        quantity=Decimal(quantity),
        trade_id=minute * 100 + second,
        is_buyer_market_maker=buyer_is_market_maker,
    )


def test_creates_one_minute_and_five_minute_candles() -> None:
    aggregator = CandleAggregator()
    aggregator.add_tick(make_tick())

    assert aggregator.current_candle(ONE_MINUTE_SECONDS) is not None
    assert aggregator.current_candle(FIVE_MINUTES_SECONDS) is not None


def test_candle_ohlc_is_correct() -> None:
    aggregator = CandleAggregator()
    aggregator.add_tick(make_tick(second=1, price="100"))
    aggregator.add_tick(make_tick(second=10, price="105"))
    aggregator.add_tick(make_tick(second=20, price="95"))

    candle = aggregator.current_candle(ONE_MINUTE_SECONDS)
    assert candle is not None
    assert (candle.open, candle.high, candle.low, candle.close) == (
        Decimal("100"),
        Decimal("105"),
        Decimal("95"),
        Decimal("95"),
    )


def test_candle_aggregates_volume_and_trade_count() -> None:
    aggregator = CandleAggregator()
    aggregator.add_tick(make_tick(quantity="0.2"))
    aggregator.add_tick(make_tick(second=10, quantity="0.3"))

    candle = aggregator.current_candle(ONE_MINUTE_SECONDS)
    assert candle is not None
    assert candle.volume == Decimal("0.5")
    assert candle.number_of_trades == 2


def test_minute_boundary_closes_previous_candle_without_gap_filling() -> None:
    aggregator = CandleAggregator()
    aggregator.add_tick(make_tick(second=59, price="100"))
    closed = aggregator.add_tick(make_tick(minute=1, price="110"))

    one_minute_closed = [candle for candle in closed if candle.timestamp == BASE_TIME]
    current = aggregator.current_candle(ONE_MINUTE_SECONDS)
    assert len(one_minute_closed) == 1
    assert one_minute_closed[0].close == Decimal("100")
    assert current is not None
    assert current.timestamp == BASE_TIME + timedelta(minutes=1)
