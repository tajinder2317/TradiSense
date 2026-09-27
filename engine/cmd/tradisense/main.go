// tradisense prints public Binance aggregate trades from the Go engine.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"tradisense/engine/internal/config"
	"tradisense/engine/internal/market"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	configuration, err := config.Load(os.Getenv)
	if err != nil {
		slog.Error("invalid public market-data configuration", "error", err)
		os.Exit(1)
	}
	service := market.NewService(configuration.StreamURL)
	ticks := make(chan market.MarketTick)
	go service.Run(ctx, ticks)

	for tick := range ticks {
		fmt.Printf(
			"tick time=%s symbol=%s price=%s quantity=%s aggregate_trade_id=%d buyer_market_maker=%t\n",
			time.UnixMilli(tick.EventTime).UTC().Format(time.RFC3339Nano),
			tick.Symbol,
			tick.Price,
			tick.Quantity,
			tick.AggregateTradeID,
			tick.IsBuyerMarketMaker,
		)
	}
	if err := ctx.Err(); err != nil && err != context.Canceled {
		slog.Error("market-data service stopped", "error", err)
	}
}
