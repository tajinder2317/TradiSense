"""Translate strategy state into allowable spot paper-exchange actions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.paper.exchange import PaperExchange
from backend.paper.orders import OrderSide, OrderType, PaperOrder
from backend.strategy.signals import ExecutionAction, MarketState, Signal, SignalAction


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    """The internal paper action derived from a signal, if any."""

    action: ExecutionAction
    reason: str
    order: PaperOrder | None


class PaperSignalExecutor:
    """Map baseline signals to non-leveraged spot paper orders only.

    LONG can create one paper buy when flat. BEARISH market state can create a
    paper sell only when BTC is already held. SHORT never opens a position.
    """

    def __init__(
        self,
        exchange: PaperExchange,
        *,
        position_quantity: Decimal = Decimal("0.001"),
    ) -> None:
        if position_quantity <= 0:
            raise ValueError("position_quantity must be positive")
        self.exchange = exchange
        self.position_quantity = position_quantity

    def execute(self, signal: Signal) -> ExecutionDecision:
        """Create at most one allowable market paper order for a signal."""

        holding_btc = self.exchange.portfolio.btc_quantity > 0
        if signal.action is SignalAction.LONG:
            if not signal.is_actionable:
                return ExecutionDecision(
                    ExecutionAction.HOLD,
                    "LONG state is unchanged; duplicate paper buy suppressed",
                    None,
                )
            if holding_btc:
                return ExecutionDecision(
                    ExecutionAction.HOLD,
                    "LONG signal received while BTC is already held",
                    None,
                )
            order = PaperOrder(
                symbol=signal.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=self.position_quantity,
                timestamp=signal.timestamp,
            )
            self.exchange.submit_order(order)
            return ExecutionDecision(ExecutionAction.BUY, "LONG paper entry", order)

        if signal.market_state is MarketState.BEARISH and holding_btc:
            order = PaperOrder(
                symbol=signal.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=self.exchange.portfolio.btc_quantity,
                timestamp=signal.timestamp,
            )
            self.exchange.submit_order(order)
            return ExecutionDecision(
                ExecutionAction.SELL,
                "SELL_EXECUTION_SIGNAL: close existing BTC on bearish market state",
                order,
            )

        return ExecutionDecision(
            ExecutionAction.HOLD,
            "No permitted spot paper action for this signal",
            None,
        )
