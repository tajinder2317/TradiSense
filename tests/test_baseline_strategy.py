"""Deterministic tests for the transparent Phase 4 baseline strategy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.data.websocket import MarketTick
from backend.features.market_features import MarketFeatureSnapshot
from backend.paper.exchange import PaperExchange
from backend.paper.orders import OrderSide, OrderType, PaperOrder
from backend.strategy.baseline import BaselineStrategy
from backend.strategy.evaluator import PaperSignalExecutor
from backend.strategy.signals import ExecutionAction, MarketState, SignalAction


TIME = datetime(2025, 1, 1, tzinfo=timezone.utc)


def snapshot(**overrides: object) -> MarketFeatureSnapshot:
    values: dict[str, object] = {
        "timestamp": TIME,
        "symbol": "BTCUSDT",
        "price": Decimal("110"),
        "return_1m": Decimal("0.01"),
        "return_5m": Decimal("0.02"),
        "current_1m_volume": Decimal("10"),
        "average_1m_volume": Decimal("5"),
        "volume_ratio": Decimal("2"),
        "number_of_trades": 5,
        "average_trade_size": Decimal("2"),
        "rsi_14": Decimal("60"),
        "sma_20": Decimal("105"),
        "sma_50": Decimal("100"),
        "price_distance_sma20": Decimal("0.0476"),
        "return_volatility_20": Decimal("0.01"),
        "atr_14": Decimal("2"),
        "vwap": Decimal("108"),
        "price_distance_vwap": Decimal("0.0185"),
        "buy_volume": Decimal("7"),
        "sell_volume": Decimal("3"),
        "buy_sell_volume_ratio": Decimal("2"),
    }
    values.update(overrides)
    return MarketFeatureSnapshot(**values)  # type: ignore[arg-type]


def connected_exchange(price: str = "110") -> PaperExchange:
    paper_exchange = PaperExchange(slippage_rate=Decimal("0"), fee_rate=Decimal("0"))
    paper_exchange.on_market_tick(
        MarketTick(TIME, "BTCUSDT", Decimal(price), Decimal("1"), 1)
    )
    return paper_exchange


def test_strong_bullish_conditions_produce_long() -> None:
    signal = BaselineStrategy().evaluate(snapshot())

    assert signal.action is SignalAction.LONG
    assert signal.score == 5
    assert signal.signal_strength == 1.0
    assert signal.is_actionable is True


def test_weak_neutral_conditions_produce_hold() -> None:
    signal = BaselineStrategy().evaluate(snapshot(return_1m=Decimal("-0.01")))

    assert signal.action is SignalAction.HOLD
    assert signal.market_state is MarketState.NEUTRAL


def test_bearish_conditions_are_hold_not_short() -> None:
    signal = BaselineStrategy().evaluate(
        snapshot(return_1m=Decimal("-0.01"), return_5m=Decimal("-0.02"))
    )

    assert signal.action is SignalAction.HOLD
    assert signal.market_state is MarketState.BEARISH


def test_missing_features_do_not_fabricate_bullish_signal() -> None:
    signal = BaselineStrategy().evaluate(
        snapshot(return_1m=None, rsi_14=None, vwap=None, volume_ratio=None)
    )

    assert signal.action is SignalAction.HOLD
    assert "1m momentum unavailable" in signal.reasons
    assert "RSI unavailable; entry blocked" in signal.reasons


def test_overbought_rsi_prevents_entry() -> None:
    signal = BaselineStrategy().evaluate(snapshot(rsi_14=Decimal("71")))

    assert signal.action is SignalAction.HOLD
    assert any("exceeds entry limit" in reason for reason in signal.reasons)


def test_volume_threshold_is_applied() -> None:
    signal = BaselineStrategy().evaluate(snapshot(volume_ratio=Decimal("1.19")))

    assert signal.action is SignalAction.LONG
    assert signal.score == 4
    assert any("below 1.2" in reason for reason in signal.reasons)


def test_vwap_condition_is_applied() -> None:
    signal = BaselineStrategy().evaluate(snapshot(vwap=Decimal("111")))

    assert signal.action is SignalAction.LONG
    assert signal.score == 4
    assert "price is not above VWAP" in signal.reasons


def test_trend_condition_is_applied() -> None:
    signal = BaselineStrategy().evaluate(snapshot(sma_20=Decimal("99"), sma_50=Decimal("100")))

    assert signal.action is SignalAction.LONG
    assert signal.score == 4
    assert "bullish trend not confirmed" in signal.reasons


def test_buy_sell_ratio_condition_is_applied() -> None:
    signal = BaselineStrategy().evaluate(snapshot(buy_sell_volume_ratio=Decimal("1")))

    assert signal.action is SignalAction.LONG
    assert signal.score == 4
    assert any("does not exceed 1" in reason for reason in signal.reasons)


def test_signal_reasons_match_actual_conditions() -> None:
    signal = BaselineStrategy().evaluate(snapshot(volume_ratio=Decimal("1.1")))

    assert "positive 1m and 5m momentum" in signal.reasons
    assert any("volume ratio 1.1 is below 1.2" == reason for reason in signal.reasons)


def test_duplicate_long_signal_is_suppressed() -> None:
    strategy = BaselineStrategy()
    strategy.evaluate(snapshot())
    repeated = strategy.evaluate(snapshot(timestamp=TIME + timedelta(seconds=1)))

    assert repeated.action is SignalAction.LONG
    assert repeated.is_actionable is False


def test_long_generates_one_paper_buy_when_flat() -> None:
    paper_exchange = connected_exchange()
    signal = BaselineStrategy().evaluate(snapshot())
    decision = PaperSignalExecutor(paper_exchange).execute(signal)

    assert decision.action is ExecutionAction.BUY
    assert paper_exchange.portfolio.btc_quantity == Decimal("0.001")


def test_long_does_not_buy_again_when_already_holding_btc() -> None:
    paper_exchange = connected_exchange()
    executor = PaperSignalExecutor(paper_exchange)
    signal = BaselineStrategy().evaluate(snapshot())
    executor.execute(signal)
    second_signal = BaselineStrategy().evaluate(snapshot(timestamp=TIME + timedelta(seconds=1)))
    decision = executor.execute(second_signal)

    assert decision.action is ExecutionAction.HOLD
    assert len(paper_exchange.fills) == 1


def test_bearish_state_closes_existing_btc_position() -> None:
    paper_exchange = connected_exchange()
    paper_exchange.submit_order(
        PaperOrder("BTCUSDT", OrderSide.BUY, OrderType.MARKET, Decimal("0.001"))
    )
    bearish = BaselineStrategy().evaluate(
        snapshot(return_1m=Decimal("-0.01"), return_5m=Decimal("-0.02"))
    )
    decision = PaperSignalExecutor(paper_exchange).execute(bearish)

    assert decision.action is ExecutionAction.SELL
    assert paper_exchange.portfolio.btc_quantity == Decimal("0")


def test_no_short_position_is_created() -> None:
    paper_exchange = connected_exchange()
    bearish = BaselineStrategy().evaluate(
        snapshot(return_1m=Decimal("-0.01"), return_5m=Decimal("-0.02"))
    )
    PaperSignalExecutor(paper_exchange).execute(bearish)

    assert paper_exchange.portfolio.btc_quantity == Decimal("0")
    assert all(fill.side is not OrderSide.SELL for fill in paper_exchange.fills)


def test_strategy_uses_only_the_supplied_current_snapshot() -> None:
    strategy = BaselineStrategy()
    current = snapshot(timestamp=TIME, price=Decimal("110"))
    later_bearish = snapshot(
        timestamp=TIME + timedelta(minutes=1),
        price=Decimal("90"),
        return_1m=Decimal("-0.1"),
        return_5m=Decimal("-0.1"),
    )

    signal = strategy.evaluate(current)

    assert signal.feature_snapshot is current
    assert signal.timestamp == current.timestamp
    assert signal.action is SignalAction.LONG
    assert later_bearish.price == Decimal("90")
