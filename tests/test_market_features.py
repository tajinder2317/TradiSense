"""Deterministic tests for rolling market features."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.data.websocket import MarketTick
from backend.features.market_features import MarketFeatures


BASE_TIME = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_tick(
    minute: int,
    *,
    price: str,
    quantity: str = "1",
    buyer_is_market_maker: bool | None = False,
    second: int = 0,
) -> MarketTick:
    return MarketTick(
        timestamp=BASE_TIME + timedelta(minutes=minute, seconds=second),
        symbol="BTCUSDT",
        price=Decimal(price),
        quantity=Decimal(quantity),
        trade_id=minute * 100 + second,
        is_buyer_market_maker=buyer_is_market_maker,
    )


def test_calculates_one_minute_return() -> None:
    features = MarketFeatures()
    features.update(make_tick(0, price="100"))
    snapshot = features.update(make_tick(1, price="110"))

    assert snapshot.return_1m == Decimal("0.1")
    assert snapshot.return_5m is None


def test_calculates_five_minute_return_when_the_exact_candle_exists() -> None:
    features = MarketFeatures()
    features.update(make_tick(0, price="100"))
    for minute in range(1, 5):
        features.update(make_tick(minute, price="100"))
    snapshot = features.update(make_tick(5, price="110"))

    assert snapshot.return_5m == Decimal("0.1")


def test_calculates_volume_ratio_from_completed_candles() -> None:
    features = MarketFeatures(volume_window=1)
    features.update(make_tick(0, price="100", quantity="2"))
    snapshot = features.update(make_tick(1, price="100", quantity="6"))

    assert snapshot.average_1m_volume == Decimal("2")
    assert snapshot.volume_ratio == Decimal("3")


def test_calculates_rsi_for_consistent_gains() -> None:
    features = MarketFeatures()
    snapshot = None
    for minute in range(15):
        snapshot = features.update(make_tick(minute, price=str(100 + minute)))

    assert snapshot is not None
    assert snapshot.rsi_14 == Decimal("100")


def test_calculates_session_vwap() -> None:
    features = MarketFeatures()
    features.update(make_tick(0, price="100", quantity="2"))
    snapshot = features.update(make_tick(1, price="110", quantity="1"))

    assert snapshot.vwap == Decimal("103.3333333333333333333333333")


def test_classifies_buy_and_sell_volume_from_buyer_market_maker_flag() -> None:
    features = MarketFeatures()
    features.update(
        make_tick(0, price="100", quantity="2", buyer_is_market_maker=False)
    )
    snapshot = features.update(
        make_tick(
            0,
            second=1,
            price="100",
            quantity="1",
            buyer_is_market_maker=True,
        )
    )

    assert snapshot.buy_volume == Decimal("2")
    assert snapshot.sell_volume == Decimal("1")
    assert snapshot.buy_sell_volume_ratio == Decimal("2")


def test_returns_none_when_history_is_insufficient_or_denominator_is_zero() -> None:
    snapshot = MarketFeatures().update(make_tick(0, price="100", quantity="1"))

    assert snapshot.return_1m is None
    assert snapshot.volume_ratio is None
    assert snapshot.rsi_14 is None
    assert snapshot.sma_20 is None
    assert snapshot.atr_14 is None
    assert snapshot.return_volatility_20 is None
    assert snapshot.buy_sell_volume_ratio is None
