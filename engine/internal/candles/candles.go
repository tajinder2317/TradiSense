package candles

import (
	"fmt"
	"log/slog"
	"math/big"
	"time"

	"tradisense/engine/internal/market"
)

const (
	OneMinuteSeconds   int64 = 60
	FiveMinutesSeconds int64 = 300
)

type Candle struct {
	Timestamp          time.Time
	Symbol             string
	Open               market.Decimal
	High               market.Decimal
	Low                market.Decimal
	Close              market.Decimal
	Volume             market.Decimal
	NumberOfTrades     int
	LastTradeTimestamp time.Time
	Notional           market.Decimal
	BuyVolume          market.Decimal
	SellVolume         market.Decimal
}

func FromTick(timestamp time.Time, tick market.MarketTick) Candle {
	buyVolume, sellVolume := splitAggressorVolume(tick)

	return Candle{
		Timestamp:          timestamp,
		Symbol:             tick.Symbol,
		Open:               tick.Price,
		High:               tick.Price,
		Low:                tick.Price,
		Close:              tick.Price,
		Volume:             tick.Quantity,
		NumberOfTrades:     1,
		LastTradeTimestamp: time.UnixMilli(tick.TradeTime).UTC(),
		Notional:           multiplyDecimal(tick.Price, tick.Quantity),
		BuyVolume:          buyVolume,
		SellVolume:         sellVolume,
	}
}

func (candle *Candle) AddTick(tick market.MarketTick) {
	if decimalGreater(tick.Price, candle.High) {
		candle.High = tick.Price
	}

	if decimalLess(tick.Price, candle.Low) {
		candle.Low = tick.Price
	}

	candle.Close = tick.Price
	candle.Volume = addDecimal(candle.Volume, tick.Quantity)
	candle.NumberOfTrades++
	candle.Notional = addDecimal(
		candle.Notional,
		multiplyDecimal(tick.Price, tick.Quantity),
	)

	buyVolume, sellVolume := splitAggressorVolume(tick)
	candle.BuyVolume = addDecimal(candle.BuyVolume, buyVolume)
	candle.SellVolume = addDecimal(candle.SellVolume, sellVolume)

	tradeTimestamp := time.UnixMilli(tick.TradeTime).UTC()
	if tradeTimestamp.After(candle.LastTradeTimestamp) {
		candle.LastTradeTimestamp = tradeTimestamp
	}
}

func splitAggressorVolume(
	tick market.MarketTick,
) (market.Decimal, market.Decimal) {
	if tick.IsBuyerMarketMaker {
		return market.Decimal("0"), tick.Quantity
	}

	return tick.Quantity, market.Decimal("0")
}

type Aggregator struct {
	timeframes   []int64
	active       map[int64]Candle
	completed    map[int64][]Candle
	historyLimit int
	logger       *slog.Logger
}

func NewAggregator(
	timeframes []int64,
	historyLimit int,
	logger *slog.Logger,
) (*Aggregator, error) {
	if len(timeframes) == 0 {
		return nil, fmt.Errorf(
			"timeframes must contain positive durations",
		)
	}

	seen := make(map[int64]struct{}, len(timeframes))

	for _, seconds := range timeframes {
		if seconds <= 0 {
			return nil, fmt.Errorf(
				"timeframes must contain positive durations",
			)
		}

		if _, exists := seen[seconds]; exists {
			return nil, fmt.Errorf(
				"timeframes must be unique",
			)
		}

		seen[seconds] = struct{}{}
	}

	if historyLimit <= 0 {
		return nil, fmt.Errorf("history_limit must be positive")
	}

	if logger == nil {
		logger = slog.Default()
	}

	completed := make(map[int64][]Candle, len(timeframes))

	for _, seconds := range timeframes {
		completed[seconds] = make([]Candle, 0, historyLimit)
	}

	return &Aggregator{
		timeframes:   append([]int64(nil), timeframes...),
		active:       make(map[int64]Candle),
		completed:    completed,
		historyLimit: historyLimit,
		logger:       logger,
	}, nil
}

func NewDefaultAggregator() *Aggregator {
	aggregator, err := NewAggregator(
		[]int64{
			OneMinuteSeconds,
			FiveMinutesSeconds,
		},
		1000,
		nil,
	)
	if err != nil {
		panic(err)
	}

	return aggregator
}

func (aggregator *Aggregator) AddTick(
	tick market.MarketTick,
) []Candle {
	completed := make([]Candle, 0)

	for _, seconds := range aggregator.timeframes {
		candleStart := candleStart(tick.TradeTime, seconds)
		active, exists := aggregator.active[seconds]

		if !exists {
			aggregator.active[seconds] = FromTick(
				candleStart,
				tick,
			)
			continue
		}

		if candleStart.Equal(active.Timestamp) {
			active.AddTick(tick)
			aggregator.active[seconds] = active
			continue
		}

		if candleStart.After(active.Timestamp) {
			aggregator.appendCompleted(seconds, active)
			completed = append(completed, active)

			aggregator.active[seconds] = FromTick(
				candleStart,
				tick,
			)
			continue
		}

		aggregator.logger.Warn(
			"Ignoring out-of-order tick",
			"timestamp", time.UnixMilli(tick.TradeTime).UTC(),
			"interval_seconds", seconds,
		)
	}

	return completed
}

func (aggregator *Aggregator) Candles(
	seconds int64,
	includeCurrent bool,
) ([]Candle, error) {
	if _, exists := aggregator.completed[seconds]; !exists {
		return nil, fmt.Errorf(
			"unsupported candle interval: %d",
			seconds,
		)
	}

	candles := append(
		[]Candle(nil),
		aggregator.completed[seconds]...,
	)

	if includeCurrent {
		if active, exists := aggregator.active[seconds]; exists {
			candles = append(candles, active)
		}
	}

	return candles, nil
}

func (aggregator *Aggregator) CurrentCandle(
	seconds int64,
) (*Candle, error) {
	if _, exists := aggregator.completed[seconds]; !exists {
		return nil, fmt.Errorf(
			"unsupported candle interval: %d",
			seconds,
		)
	}

	active, exists := aggregator.active[seconds]
	if !exists {
		return nil, nil
	}

	result := active
	return &result, nil
}

func (aggregator *Aggregator) appendCompleted(
	seconds int64,
	candle Candle,
) {
	history := aggregator.completed[seconds]
	history = append(history, candle)

	if len(history) > aggregator.historyLimit {
		history = history[len(history)-aggregator.historyLimit:]
	}

	aggregator.completed[seconds] = history
}

func candleStart(tradeTimeMillis int64, seconds int64) time.Time {
	epochSeconds := tradeTimeMillis / 1000
	start := epochSeconds - epochSeconds%seconds

	return time.Unix(start, 0).UTC()
}

func parseDecimal(value market.Decimal) *big.Rat {
	rat, ok := new(big.Rat).SetString(string(value))
	if !ok {
		panic(fmt.Sprintf("invalid market decimal: %q", value))
	}

	return rat
}

func decimalString(value *big.Rat) market.Decimal {
	return market.Decimal(value.FloatString(decimalScale(value)))
}

func decimalScale(value *big.Rat) int {
	denominator := new(big.Int).Set(value.Denom())

	twos := 0
	fives := 0

	two := big.NewInt(2)
	five := big.NewInt(5)
	remainder := new(big.Int)

	for {
		remainder.Mod(denominator, two)
		if remainder.Sign() != 0 {
			break
		}

		denominator.Div(denominator, two)
		twos++
	}

	for {
		remainder.Mod(denominator, five)
		if remainder.Sign() != 0 {
			break
		}

		denominator.Div(denominator, five)
		fives++
	}

	if denominator.Cmp(big.NewInt(1)) == 0 {
		if twos > fives {
			return twos
		}
		return fives
	}

	return 18
}
func addDecimal(
	left market.Decimal,
	right market.Decimal,
) market.Decimal {
	result := new(big.Rat).Add(
		parseDecimal(left),
		parseDecimal(right),
	)

	return decimalString(result)
}

func multiplyDecimal(
	left market.Decimal,
	right market.Decimal,
) market.Decimal {
	result := new(big.Rat).Mul(
		parseDecimal(left),
		parseDecimal(right),
	)

	return decimalString(result)
}

func decimalGreater(
	left market.Decimal,
	right market.Decimal,
) bool {
	return parseDecimal(left).Cmp(parseDecimal(right)) > 0
}

func decimalLess(
	left market.Decimal,
	right market.Decimal,
) bool {
	return parseDecimal(left).Cmp(parseDecimal(right)) < 0
}
