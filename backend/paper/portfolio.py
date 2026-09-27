"""Paper-account balance, position, and P&L accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.paper.fills import PaperFill
from backend.paper.orders import OrderSide


ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PaperAccountSnapshot:
    """A marked-to-market view of the in-memory paper account."""

    cash_balance: Decimal
    btc_quantity: Decimal
    average_entry_price: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_equity: Decimal
    open_position: bool
    trade_count: int


class PaperPortfolio:
    """Maintain cash, BTC position, and P&L without allowing leverage.

    Buy fees are included in the BTC cost basis. Sell fees reduce sell proceeds.
    Therefore realized and unrealized P&L consistently include simulator fees.
    """

    def __init__(self, starting_usdt: Decimal = Decimal("10000")) -> None:
        if starting_usdt < ZERO:
            raise ValueError("starting_usdt must be non-negative")
        self.cash_balance = starting_usdt
        self.btc_quantity = ZERO
        self.average_entry_price: Decimal | None = None
        self.realized_pnl = ZERO
        self.trade_count = 0

    def apply_fill(self, fill: PaperFill) -> Decimal:
        """Apply a validated fill and return its realized P&L.

        The exchange validates available cash or BTC before calling this method.
        This method retains guards so a programming error cannot create negative
        paper balances.
        """

        if fill.side is OrderSide.BUY:
            total_cost = fill.execution_price * fill.quantity + fill.fee
            if total_cost > self.cash_balance:
                raise ValueError("Insufficient USDT for paper fill")
            existing_cost = (self.average_entry_price or ZERO) * self.btc_quantity
            new_quantity = self.btc_quantity + fill.quantity
            self.average_entry_price = (existing_cost + total_cost) / new_quantity
            self.cash_balance -= total_cost
            self.btc_quantity = new_quantity
            realized_pnl = ZERO
        else:
            if fill.quantity > self.btc_quantity:
                raise ValueError("Insufficient BTC for paper fill")
            if self.average_entry_price is None:
                raise ValueError("Cannot sell a flat paper position")
            net_proceeds = fill.execution_price * fill.quantity - fill.fee
            realized_pnl = net_proceeds - self.average_entry_price * fill.quantity
            self.cash_balance += net_proceeds
            self.btc_quantity -= fill.quantity
            self.realized_pnl += realized_pnl
            if self.btc_quantity == ZERO:
                self.average_entry_price = None

        self.trade_count += 1
        if self.cash_balance < ZERO or self.btc_quantity < ZERO:
            raise RuntimeError("Paper portfolio cannot have negative balances")
        return realized_pnl

    def snapshot(self, market_price: Decimal | None) -> PaperAccountSnapshot:
        """Mark the account using the supplied public BTCUSDT price only."""

        if self.btc_quantity == ZERO or self.average_entry_price is None:
            unrealized_pnl = ZERO
        elif market_price is None:
            unrealized_pnl = ZERO
        else:
            unrealized_pnl = (market_price - self.average_entry_price) * self.btc_quantity

        marked_btc_value = self.btc_quantity * market_price if market_price else ZERO
        return PaperAccountSnapshot(
            cash_balance=self.cash_balance,
            btc_quantity=self.btc_quantity,
            average_entry_price=self.average_entry_price,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_equity=self.cash_balance + marked_btc_value,
            open_position=self.btc_quantity > ZERO,
            trade_count=self.trade_count,
        )
