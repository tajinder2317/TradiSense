"""Records generated only when an internal paper order is filled."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from backend.paper.orders import OrderSide


@dataclass(frozen=True, slots=True)
class PaperFill:
    """An immutable simulated execution record held in memory."""

    order_id: str
    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: Decimal
    market_price: Decimal
    execution_price: Decimal
    fee: Decimal
    slippage: Decimal
    realized_pnl: Decimal
