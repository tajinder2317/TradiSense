"""Deterministic unit tests for the internal paper-only exchange simulator."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from backend.data.websocket import MarketTick
from backend.paper.exchange import PaperExchange
from backend.paper.orders import OrderSide, OrderStatus, OrderType, PaperOrder
from backend.paper.portfolio import PaperPortfolio


TIME = datetime(2025, 1, 1, tzinfo=timezone.utc)


def tick(price: str) -> MarketTick:
    return MarketTick(
        timestamp=TIME,
        symbol="BTCUSDT",
        price=Decimal(price),
        quantity=Decimal("1"),
        trade_id=1,
    )


def order(
    side: OrderSide,
    order_type: OrderType,
    quantity: str,
    *,
    limit_price: str | None = None,
    order_id: str = "test-order",
) -> PaperOrder:
    return PaperOrder(
        order_id=order_id,
        timestamp=TIME,
        symbol="BTCUSDT",
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        limit_price=Decimal(limit_price) if limit_price else None,
    )


def exchange(
    *,
    starting_usdt: str = "10000",
    fee_rate: str = "0",
    slippage_rate: str = "0",
    market_price: str = "100",
) -> PaperExchange:
    paper_exchange = PaperExchange(
        portfolio=PaperPortfolio(Decimal(starting_usdt)),
        fee_rate=Decimal(fee_rate),
        slippage_rate=Decimal(slippage_rate),
    )
    paper_exchange.on_market_tick(tick(market_price))
    return paper_exchange


def test_starting_balance() -> None:
    account = PaperPortfolio().snapshot(None)

    assert account.cash_balance == Decimal("10000")
    assert account.btc_quantity == Decimal("0")
    assert account.total_equity == Decimal("10000")


def test_market_buy() -> None:
    paper_exchange = exchange()
    submitted = paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "2"))

    assert submitted.status is OrderStatus.FILLED
    assert paper_exchange.portfolio.cash_balance == Decimal("9800")
    assert paper_exchange.portfolio.btc_quantity == Decimal("2")


def test_market_sell() -> None:
    paper_exchange = exchange()
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1", order_id="buy"))
    submitted = paper_exchange.submit_order(order(OrderSide.SELL, OrderType.MARKET, "1", order_id="sell"))

    assert submitted.status is OrderStatus.FILLED
    assert paper_exchange.portfolio.btc_quantity == Decimal("0")
    assert paper_exchange.portfolio.cash_balance == Decimal("10000")


def test_fee_calculation() -> None:
    paper_exchange = exchange(fee_rate="0.001")
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1"))

    assert paper_exchange.fills[-1].fee == Decimal("0.1")
    assert paper_exchange.portfolio.cash_balance == Decimal("9899.9")


def test_market_slippage_calculation() -> None:
    paper_exchange = exchange(slippage_rate="0.0002")
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1"))

    assert paper_exchange.fills[-1].execution_price == Decimal("100.0200")


def test_rejects_insufficient_usdt() -> None:
    paper_exchange = exchange(starting_usdt="100")
    submitted = paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "2"))

    assert submitted.status is OrderStatus.REJECTED
    assert paper_exchange.portfolio.cash_balance == Decimal("100")


def test_rejects_insufficient_btc() -> None:
    paper_exchange = exchange()
    submitted = paper_exchange.submit_order(order(OrderSide.SELL, OrderType.MARKET, "1"))

    assert submitted.status is OrderStatus.REJECTED
    assert paper_exchange.portfolio.btc_quantity == Decimal("0")


def test_rejects_invalid_quantity() -> None:
    paper_exchange = exchange()
    submitted = paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "0"))

    assert submitted.status is OrderStatus.REJECTED


def test_rejects_invalid_symbol() -> None:
    paper_exchange = exchange()
    submitted = PaperOrder(
        order_id="invalid-symbol",
        timestamp=TIME,
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    paper_exchange.submit_order(submitted)

    assert submitted.status is OrderStatus.REJECTED


def test_limit_buy_fills_only_when_market_reaches_limit() -> None:
    paper_exchange = exchange(market_price="110")
    submitted = paper_exchange.submit_order(
        order(OrderSide.BUY, OrderType.LIMIT, "1", limit_price="100")
    )
    assert submitted.status is OrderStatus.NEW

    paper_exchange.on_market_tick(tick("100"))
    assert submitted.status is OrderStatus.FILLED
    assert paper_exchange.fills[-1].execution_price == Decimal("100")


def test_limit_sell_fills_only_when_market_reaches_limit() -> None:
    paper_exchange = exchange(market_price="100")
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1", order_id="buy"))
    submitted = paper_exchange.submit_order(
        order(OrderSide.SELL, OrderType.LIMIT, "1", limit_price="110", order_id="sell")
    )
    assert submitted.status is OrderStatus.NEW

    paper_exchange.on_market_tick(tick("110"))
    assert submitted.status is OrderStatus.FILLED
    assert paper_exchange.fills[-1].execution_price == Decimal("110")


def test_position_accounting() -> None:
    paper_exchange = exchange()
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "2"))

    account = paper_exchange.account_snapshot()
    assert account.open_position is True
    assert account.trade_count == 1
    assert account.btc_quantity == Decimal("2")


def test_average_entry_price_includes_buy_fee() -> None:
    paper_exchange = exchange(fee_rate="0.001")
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1", order_id="buy-1"))
    paper_exchange.on_market_tick(tick("200"))
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1", order_id="buy-2"))

    assert paper_exchange.portfolio.average_entry_price == Decimal("150.15")


def test_realized_pnl() -> None:
    paper_exchange = exchange()
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1", order_id="buy"))
    paper_exchange.on_market_tick(tick("120"))
    paper_exchange.submit_order(order(OrderSide.SELL, OrderType.MARKET, "1", order_id="sell"))

    assert paper_exchange.fills[-1].realized_pnl == Decimal("20")
    assert paper_exchange.portfolio.realized_pnl == Decimal("20")


def test_unrealized_pnl() -> None:
    paper_exchange = exchange()
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1"))
    paper_exchange.on_market_tick(tick("110"))

    assert paper_exchange.account_snapshot().unrealized_pnl == Decimal("10")


def test_equity_calculation() -> None:
    paper_exchange = exchange(starting_usdt="1000")
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "1"))
    paper_exchange.on_market_tick(tick("120"))

    assert paper_exchange.account_snapshot().total_equity == Decimal("1020")


def test_never_allows_negative_balances() -> None:
    paper_exchange = exchange(starting_usdt="100")
    paper_exchange.submit_order(order(OrderSide.BUY, OrderType.MARKET, "2"))
    paper_exchange.submit_order(order(OrderSide.SELL, OrderType.MARKET, "1"))

    account = paper_exchange.account_snapshot()
    assert account.cash_balance >= Decimal("0")
    assert account.btc_quantity >= Decimal("0")
