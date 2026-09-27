"""Command-line entry point for the public BTCUSDT market-data stream."""

from __future__ import annotations

import asyncio
import logging
import os

from backend.data.websocket import MarketDataService
from backend.features.market_features import MarketFeatureSnapshot, MarketFeatures
from backend.paper.exchange import PaperExchange
from backend.paper.portfolio import PaperAccountSnapshot
from backend.strategy.baseline import BaselineStrategy
from backend.strategy.evaluator import PaperSignalExecutor
from backend.strategy.signals import Signal


def configure_logging() -> None:
    """Configure readable console logs for the market-data process."""

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run_market_data_service() -> None:
    """Run public data, features, baseline strategy, and paper execution."""

    service = MarketDataService()
    features = MarketFeatures()
    paper_exchange = PaperExchange()
    strategy = BaselineStrategy()
    executor = PaperSignalExecutor(paper_exchange)
    next_snapshot_at = asyncio.get_running_loop().time() + 5
    try:
        async for tick in service.ticks():
            snapshot = features.update(tick)
            paper_exchange.on_market_tick(tick)
            signal = strategy.evaluate(snapshot)
            executor.execute(signal)
            now = asyncio.get_running_loop().time()
            if now >= next_snapshot_at:
                print_feature_snapshot(snapshot)
                print_strategy_signal(signal)
                print_paper_account(paper_exchange.account_snapshot())
                next_snapshot_at = now + 5
    finally:
        service.stop()


def print_feature_snapshot(snapshot: MarketFeatureSnapshot) -> None:
    """Print a compact operator-facing snapshot without printing every trade."""

    print("\n## FEATURE SNAPSHOT")
    print(snapshot.symbol)
    print(f"Price: {_display(snapshot.price)}")
    print(f"1m Return: {_display(snapshot.return_1m)}")
    print(f"5m Return: {_display(snapshot.return_5m)}")
    print(f"Volume Ratio: {_display(snapshot.volume_ratio)}")
    print(f"RSI: {_display(snapshot.rsi_14)}")
    print(f"SMA20: {_display(snapshot.sma_20)}")
    print(f"SMA50: {_display(snapshot.sma_50)}")
    print(f"VWAP: {_display(snapshot.vwap)}")
    print(f"VWAP Distance: {_display(snapshot.price_distance_vwap)}")
    print(f"Buy/Sell Ratio: {_display(snapshot.buy_sell_volume_ratio)}")
    print(f"Volatility: {_display(snapshot.return_volatility_20)}")


def _display(value: object) -> str:
    return "N/A" if value is None else str(value)


def print_strategy_signal(signal: Signal) -> None:
    """Print the baseline's explainable current-only decision."""

    print("\n## STRATEGY")
    print(signal.symbol)
    print(f"Price: {signal.feature_snapshot.price}")
    print(f"Signal: {signal.action}")
    print(f"Market state: {signal.market_state}")
    print(f"Signal strength: {signal.signal_strength:.2f}")
    print(f"Score: {signal.score}/{signal.max_score}")
    print("Reasons:")
    for reason in signal.reasons:
        print(f"- {reason}")


def print_paper_account(account: PaperAccountSnapshot) -> None:
    """Print the in-memory account mark for the paper-trading demo."""

    print("\n## PAPER ACCOUNT")
    print(f"Cash: ${account.cash_balance}")
    print(f"BTC: {account.btc_quantity}")
    print(f"Equity: ${account.total_equity}")
    print(f"Realized P&L: ${account.realized_pnl}")
    print(f"Unrealized P&L: ${account.unrealized_pnl}")


def main() -> None:
    configure_logging()
    try:
        asyncio.run(run_market_data_service())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Ctrl+C received; market-data service stopped")


if __name__ == "__main__":
    main()
