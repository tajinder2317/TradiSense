// Package config loads the credential-free Go engine settings.
package config

import (
	"fmt"
	"strings"

	"tradisense/engine/internal/market"
)

const (
	defaultSymbol = "BTCUSDT"
	defaultStream = "aggTrade"
)

// Config contains only public market-data configuration. No credential fields
// exist because the Phase 5 Go engine never uses authenticated APIs.
type Config struct {
	Symbol    string
	Stream    string
	StreamURL string
}

// Load returns configuration from environment lookup with safe public defaults.
func Load(lookup func(string) string) (Config, error) {
	symbol := lookup("TRADISENSE_SYMBOL")
	if symbol == "" {
		symbol = defaultSymbol
	}
	stream := lookup("TRADISENSE_STREAM")
	if stream == "" {
		stream = defaultStream
	}
	if !strings.EqualFold(stream, defaultStream) {
		return Config{}, fmt.Errorf("unsupported public stream type: %s", stream)
	}
	streamURL := lookup("TRADISENSE_STREAM_URL")
	if streamURL == "" {
		streamURL = "wss://stream.binance.com:9443/ws/" + strings.ToLower(symbol) + "@aggTrade"
	}
	return Config{
		Symbol:    strings.ToUpper(symbol),
		Stream:    defaultStream,
		StreamURL: streamURL,
	}, nil
}

// Default returns the public BTCUSDT aggregate-trade configuration.
func Default() Config {
	configuration, err := Load(func(string) string { return "" })
	if err != nil {
		panic(fmt.Sprintf("default configuration is invalid: %v", err))
	}
	return configuration
}

// DefaultStreamURL is exposed for applications that need the fixed default.
func DefaultStreamURL() string {
	return market.DefaultBTCUSDTAggregateTradeURL
}
