// Package market contains public market-data domain types and decoding.
package market

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"strings"
)

// Decimal preserves an exchange-supplied positive decimal string exactly.
//
// Prices and quantities intentionally do not use float64 in the initial Go
// engine. Keeping their validated wire representation avoids silent rounding
// and gives a future fixed-point or decimal implementation a stable domain
// boundary.
type Decimal string

// MarketTick is a normalized Binance public aggregate-trade event. EventTime
// and TradeTime are Unix milliseconds; IDs are exchange-provided integer IDs.
//
// IsBuyerMarketMaker is an aggressor-side estimate: false means the buyer was
// the taker, while true means the seller was the taker. It is not an order-book
// reconstruction.
type MarketTick struct {
	EventType          string
	EventTime          int64
	Symbol             string
	AggregateTradeID   int64
	Price              Decimal
	Quantity           Decimal
	FirstTradeID       int64
	LastTradeID        int64
	TradeTime          int64
	IsBuyerMarketMaker bool
}

type aggregateTradePayload struct {
	EventType          *string `json:"e"`
	EventTime          *int64  `json:"E"`
	Symbol             *string `json:"s"`
	AggregateTradeID   *int64  `json:"a"`
	Price              *string `json:"p"`
	Quantity           *string `json:"q"`
	FirstTradeID       *int64  `json:"f"`
	LastTradeID        *int64  `json:"l"`
	TradeTime          *int64  `json:"T"`
	IsBuyerMarketMaker *bool   `json:"m"`
}

// DecodeAggregateTrade validates and maps one Binance aggregate-trade payload.
func DecodeAggregateTrade(data []byte) (MarketTick, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	var payload aggregateTradePayload
	if err := decoder.Decode(&payload); err != nil {
		return MarketTick{}, fmt.Errorf("decode aggregate trade JSON: %w", err)
	}
	if err := ensureNoTrailingJSON(decoder); err != nil {
		return MarketTick{}, err
	}
	if err := validatePayload(payload); err != nil {
		return MarketTick{}, err
	}

	price, err := newPositiveDecimal(*payload.Price)
	if err != nil {
		return MarketTick{}, fmt.Errorf("invalid price: %w", err)
	}
	quantity, err := newPositiveDecimal(*payload.Quantity)
	if err != nil {
		return MarketTick{}, fmt.Errorf("invalid quantity: %w", err)
	}

	return MarketTick{
		EventType:          *payload.EventType,
		EventTime:          *payload.EventTime,
		Symbol:             *payload.Symbol,
		AggregateTradeID:   *payload.AggregateTradeID,
		Price:              price,
		Quantity:           quantity,
		FirstTradeID:       *payload.FirstTradeID,
		LastTradeID:        *payload.LastTradeID,
		TradeTime:          *payload.TradeTime,
		IsBuyerMarketMaker: *payload.IsBuyerMarketMaker,
	}, nil
}

func ensureNoTrailingJSON(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return fmt.Errorf("decode aggregate trade JSON: unexpected trailing value")
		}
		return fmt.Errorf("decode aggregate trade JSON: %w", err)
	}
	return nil
}

func validatePayload(payload aggregateTradePayload) error {
	if payload.EventType == nil || *payload.EventType != "aggTrade" {
		return fmt.Errorf("required event type aggTrade is missing or invalid")
	}
	if payload.EventTime == nil || *payload.EventTime <= 0 {
		return fmt.Errorf("required event time is missing or invalid")
	}
	if payload.Symbol == nil || strings.TrimSpace(*payload.Symbol) == "" {
		return fmt.Errorf("required symbol is missing or invalid")
	}
	if payload.AggregateTradeID == nil {
		return fmt.Errorf("required aggregate trade ID is missing")
	}
	if payload.Price == nil {
		return fmt.Errorf("required price is missing")
	}
	if payload.Quantity == nil {
		return fmt.Errorf("required quantity is missing")
	}
	if payload.FirstTradeID == nil {
		return fmt.Errorf("required first trade ID is missing")
	}
	if payload.LastTradeID == nil {
		return fmt.Errorf("required last trade ID is missing")
	}
	if payload.TradeTime == nil || *payload.TradeTime <= 0 {
		return fmt.Errorf("required trade time is missing or invalid")
	}
	if payload.IsBuyerMarketMaker == nil {
		return fmt.Errorf("required buyer market-maker flag is missing")
	}
	return nil
}

func newPositiveDecimal(value string) (Decimal, error) {
	if value == "" || strings.TrimSpace(value) != value {
		return "", fmt.Errorf("must be a non-empty decimal string")
	}
	for index, character := range value {
		if character == '.' && index > 0 && index < len(value)-1 {
			continue
		}
		if character < '0' || character > '9' {
			return "", fmt.Errorf("contains non-decimal characters")
		}
	}
	if strings.Count(value, ".") > 1 {
		return "", fmt.Errorf("contains multiple decimal points")
	}
	parsed, ok := new(big.Rat).SetString(value)
	if !ok || parsed.Sign() <= 0 {
		return "", fmt.Errorf("must be positive")
	}
	return Decimal(value), nil
}
