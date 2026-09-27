# TradiSense

TradiSense V0.1 Phase 1 is a real-time market-data research foundation for a
paper-trading-only crypto system. It connects only to Binance's public,
unauthenticated BTCUSDT aggregate-trade WebSocket.

This project has no live-order execution, exchange credentials, authenticated
endpoints, withdrawals, AI, or dashboard. All trading behavior remains
internal paper simulation only.

## Architecture

Current: the Python implementation is the tested behavioral reference for
market data, features, baseline signals, and paper trading.

New: `engine/` is an isolated Go foundation that currently migrates only public
BTCUSDT aggregate-trade ingestion. It is designed to publish ticks through a
channel so future Go candle, feature, strategy, JEV-adapter, paper-exchange,
and dashboard consumers can subscribe without creating another market stream.

Future work may incrementally move the runtime to a Go trading engine and add a
JEV AI layer plus a React/TypeScript dashboard. The system remains paper-only
and does not place real orders.

Run the Go market-data foundation from the repository root:

```powershell
go run ./engine/cmd/tradisense
```

## Phase 2 feature engine

Live aggregate trades are locally aggregated into 1-minute and 5-minute
OHLCV candles. The feature engine produces returns, volume metrics, RSI(14),
SMA20/SMA50, return volatility, ATR(14), intraday VWAP, and aggregate trade
flow estimates. Missing or insufficient contiguous history is represented by
`None` internally and `N/A` in the console snapshot.

`number_of_trades` counts received aggregate-trade events. Binance may combine
multiple fills from one taker order into an aggregate-trade event, so it is not
a count of every underlying exchange fill.

## Phase 3 paper exchange

The paper exchange is an in-memory simulator driven exclusively by the existing
public `MarketDataService` ticks. It never creates a second WebSocket
connection, sends orders to Binance, uses authenticated endpoints, or stores
credentials.

Market orders fill at the latest public price with configurable adverse
slippage, defaulting to `0.02%`. The simulator charges a configurable `0.10%`
quote-currency fee. Limit buys fill when the public price is at or below the
limit; limit sells fill when it is at or above the limit. A crossed limit order
fills at its stated limit price. This intentionally does not model exchange
queue position, partial fills, latency, liquidity, or the Binance matching
engine.

## Phase 4 baseline strategy

The baseline is a transparent research rule set, not a validated profitable
trading strategy. It awards one point each for: positive 1m and 5m momentum;
price above SMA20 with SMA20 above SMA50; price above VWAP; volume ratio at or
above `1.2`; and buy/sell volume ratio above `1`. A score of at least `4/5`
can produce a LONG signal only when both momentum windows are positive and RSI
is available and no greater than `70`.

Signal strength is the normalized rule score, such as `4/5 = 0.80`. It is not
a probability of profit or a confidence estimate. Missing features do not earn
points and explicitly prevent a fabricated bullish interpretation.

The strategy evaluates only the current `MarketFeatureSnapshot`, which contains
data observed no later than its timestamp. It does not access future candles,
future prices, or revised indicators. Repeated LONG state is suppressed until a
HOLD reset occurs.

The paper executor may BUY the fixed `0.001 BTC` simulator position when flat.
It never opens a short position. A bearish market state is distinct from a
short signal: it can only generate a `SELL_EXECUTION_SIGNAL` to close BTC that
is already held. This remains paper-only and never sends orders to Binance.

Binance aggregate-trade payloads include `m`, documented as "is the buyer the
market maker?". When `m` is `false`, the buyer was the taker and its quantity
is counted as estimated buy volume. When `m` is `true`, the seller was the
taker and its quantity is counted as estimated sell volume. This is an
aggressor-side estimate, not a complete order-book reconstruction.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run the public market-data service

```powershell
python -m backend.main
```

Stop it cleanly with `Ctrl+C`.

Successful operation logs the public connection and prints a compact feature
snapshot every five seconds. Set `LOG_LEVEL=DEBUG` to also log every received
BTCUSDT tick.

## Test

```powershell
python -m pytest
```

The tests use fake WebSocket connections and do not contact Binance.

## Binance WebSocket notes

- The service uses `wss://stream.binance.com:9443/ws/btcusdt@aggTrade` only.
- Binance can disconnect WebSocket sessions; the service reconnects with
  exponential backoff from 1 to 30 seconds.
- Aggregate trades are exchange-provided summaries, not an execution feed and
  not a guarantee of complete market history.
- Availability can vary by network, Binance region, maintenance, and exchange
  rate or connection limits.
