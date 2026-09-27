"""Paper-only exchange simulator driven by externally supplied market ticks."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from backend.data.websocket import MarketTick
from backend.paper.fills import PaperFill
from backend.paper.orders import OrderSide, OrderStatus, OrderType, PaperOrder
from backend.paper.portfolio import PaperAccountSnapshot, PaperPortfolio


ZERO = Decimal("0")
ONE = Decimal("1")


class PaperExchange:
    """Fill internal paper orders against the latest public BTCUSDT tick.

    This class has no network client and never transmits orders. Market-order
    fills use adverse percentage slippage. Limit orders fill at their stated
    limit when the observed market price crosses it; no order-book queue,
    partial fill, latency, or matching-engine simulation is attempted.
    """

    def __init__(
        self,
        *,
        portfolio: PaperPortfolio | None = None,
        symbol: str = "BTCUSDT",
        slippage_rate: Decimal = Decimal("0.0002"),
        fee_rate: Decimal = Decimal("0.001"),
    ) -> None:
        if slippage_rate < ZERO or fee_rate < ZERO:
            raise ValueError("slippage_rate and fee_rate must be non-negative")
        self.symbol = symbol
        self.slippage_rate = slippage_rate
        self.fee_rate = fee_rate
        self.portfolio = portfolio or PaperPortfolio()
        self.orders: dict[str, PaperOrder] = {}
        self.fills: list[PaperFill] = []
        self._latest_price: Decimal | None = None
        self._latest_timestamp = None

    def on_market_tick(self, tick: MarketTick) -> list[PaperFill]:
        """Accept the sole market-data source and evaluate pending limit orders."""

        if tick.symbol != self.symbol:
            return []
        self._latest_price = tick.price
        self._latest_timestamp = tick.timestamp
        fills: list[PaperFill] = []
        for order in self.orders.values():
            if order.status is not OrderStatus.NEW or order.order_type is not OrderType.LIMIT:
                continue
            if self._limit_is_marketable(order, tick.price):
                fill = self._attempt_fill(
                    order,
                    market_price=tick.price,
                    execution_price=order.limit_price,
                    timestamp=tick.timestamp,
                    slippage=ZERO,
                )
                if fill is not None:
                    fills.append(fill)
        return fills

    def submit_order(self, order: PaperOrder) -> PaperOrder:
        """Validate and process a paper order without making any network request."""

        self.orders[order.order_id] = order
        rejection_reason = self._validation_error(order)
        if rejection_reason:
            self._reject(order, rejection_reason)
            return order

        if order.order_type is OrderType.MARKET:
            if self._latest_price is None or self._latest_timestamp is None:
                self._reject(order, "No market price is available")
                return order
            execution_price = self._market_execution_price(order.side, self._latest_price)
            self._attempt_fill(
                order,
                market_price=self._latest_price,
                execution_price=execution_price,
                timestamp=self._latest_timestamp,
                slippage=self.slippage_rate,
            )
        return order

    def account_snapshot(self) -> PaperAccountSnapshot:
        """Return the account marked by the most recently supplied public tick."""

        return self.portfolio.snapshot(self._latest_price)

    def _validation_error(self, order: PaperOrder) -> str | None:
        if order.symbol != self.symbol:
            return f"Unsupported symbol: {order.symbol}"
        if order.quantity <= ZERO:
            return "Order quantity must be positive"
        if order.order_type is OrderType.LIMIT:
            if order.limit_price is None or order.limit_price <= ZERO:
                return "Limit orders require a positive limit_price"
        elif order.limit_price is not None:
            return "Market orders cannot specify a limit_price"
        return None

    def _limit_is_marketable(self, order: PaperOrder, market_price: Decimal) -> bool:
        if order.limit_price is None:
            return False
        if order.side is OrderSide.BUY:
            return market_price <= order.limit_price
        return market_price >= order.limit_price

    def _market_execution_price(self, side: OrderSide, market_price: Decimal) -> Decimal:
        if side is OrderSide.BUY:
            return market_price * (ONE + self.slippage_rate)
        return market_price * (ONE - self.slippage_rate)

    def _attempt_fill(
        self,
        order: PaperOrder,
        *,
        market_price: Decimal,
        execution_price: Decimal | None,
        timestamp: datetime,
        slippage: Decimal,
    ) -> PaperFill | None:
        if execution_price is None:
            self._reject(order, "Limit price is unavailable")
            return None
        fee = execution_price * order.quantity * self.fee_rate
        if order.side is OrderSide.BUY:
            required_usdt = execution_price * order.quantity + fee
            if required_usdt > self.portfolio.cash_balance:
                self._reject(order, "Insufficient USDT balance")
                return None
        elif order.quantity > self.portfolio.btc_quantity:
            self._reject(order, "Insufficient BTC balance")
            return None

        provisional_fill = PaperFill(
            order_id=order.order_id,
            timestamp=timestamp,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            market_price=market_price,
            execution_price=execution_price,
            fee=fee,
            slippage=slippage,
            realized_pnl=ZERO,
        )
        realized_pnl = self.portfolio.apply_fill(provisional_fill)
        fill = PaperFill(
            order_id=provisional_fill.order_id,
            timestamp=provisional_fill.timestamp,
            symbol=provisional_fill.symbol,
            side=provisional_fill.side,
            quantity=provisional_fill.quantity,
            market_price=provisional_fill.market_price,
            execution_price=provisional_fill.execution_price,
            fee=provisional_fill.fee,
            slippage=provisional_fill.slippage,
            realized_pnl=realized_pnl,
        )
        order.status = OrderStatus.FILLED
        self.fills.append(fill)
        return fill

    @staticmethod
    def _reject(order: PaperOrder, reason: str) -> None:
        order.status = OrderStatus.REJECTED
        order.rejection_reason = reason
