package candles

import (
	"log/slog"
	"testing"
	"time"

	"tradisense/engine/internal/market"
)

var baseTime = time.Date(
	2025,
	time.January,
	1,
	12,
	0,
	0,
	0,
	time.UTC,
)

func makeTick(
	minute int,
	second int,
	price string,
	quantity string,
	buyerIsMarketMaker bool,
) market.MarketTick {
	tradeTime := baseTime.
		Add(time.Duration(minute) * time.Minute).
		Add(time.Duration(second) * time.Second)

	return market.MarketTick{
		EventType:          "aggTrade",
		EventTime:          tradeTime.UnixMilli(),
		Symbol:             "BTCUSDT",
		AggregateTradeID:   int64(minute*100 + second),
		Price:              market.Decimal(price),
		Quantity:           market.Decimal(quantity),
		FirstTradeID:       int64(minute*100 + second),
		LastTradeID:        int64(minute*100 + second),
		TradeTime:          tradeTime.UnixMilli(),
		IsBuyerMarketMaker: buyerIsMarketMaker,
	}
}

func newTestAggregator(
	timeframes []int64,
	historyLimit int,
) *Aggregator {
	aggregator, err := NewAggregator(
		timeframes,
		historyLimit,
		slog.Default(),
	)
	if err != nil {
		panic(err)
	}

	return aggregator
}

func TestCreatesOneMinuteAndFiveMinuteCandles(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 0, "100", "1", false),
	)

	oneMinute, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle(1m) error: %v", err)
	}

	if oneMinute == nil {
		t.Fatal("expected current 1-minute candle")
	}

	fiveMinutes, err := aggregator.CurrentCandle(
		FiveMinutesSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle(5m) error: %v", err)
	}

	if fiveMinutes == nil {
		t.Fatal("expected current 5-minute candle")
	}
}

func TestCandleOHLCIsCorrect(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 1, "100", "1", false),
	)
	aggregator.AddTick(
		makeTick(0, 10, "105", "1", false),
	)
	aggregator.AddTick(
		makeTick(0, 20, "95", "1", false),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if candle.Open != "100" {
		t.Errorf("open = %q, want %q", candle.Open, "100")
	}

	if candle.High != "105" {
		t.Errorf("high = %q, want %q", candle.High, "105")
	}

	if candle.Low != "95" {
		t.Errorf("low = %q, want %q", candle.Low, "95")
	}

	if candle.Close != "95" {
		t.Errorf("close = %q, want %q", candle.Close, "95")
	}
}

func TestCandleAggregatesVolumeAndTradeCount(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 0, "100", "0.2", false),
	)
	aggregator.AddTick(
		makeTick(0, 10, "100", "0.3", false),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if candle.Volume != "0.5" {
		t.Errorf(
			"volume = %q, want %q",
			candle.Volume,
			"0.5",
		)
	}

	if candle.NumberOfTrades != 2 {
		t.Errorf(
			"number of trades = %d, want %d",
			candle.NumberOfTrades,
			2,
		)
	}
}

func TestMinuteBoundaryClosesPreviousCandleWithoutGapFilling(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 59, "100", "1", false),
	)

	closed := aggregator.AddTick(
		makeTick(1, 0, "110", "1", false),
	)

	var oneMinuteClosed *Candle

	for i := range closed {
		if closed[i].Timestamp.Equal(baseTime) {
			oneMinuteClosed = &closed[i]
			break
		}
	}

	if oneMinuteClosed == nil {
		t.Fatal("expected previous 1-minute candle to close")
	}

	if oneMinuteClosed.Close != "100" {
		t.Errorf(
			"closed candle close = %q, want %q",
			oneMinuteClosed.Close,
			"100",
		)
	}

	current, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if current == nil {
		t.Fatal("expected current candle")
	}

	expectedTimestamp := baseTime.Add(time.Minute)

	if !current.Timestamp.Equal(expectedTimestamp) {
		t.Errorf(
			"current timestamp = %v, want %v",
			current.Timestamp,
			expectedTimestamp,
		)
	}
}

func TestCandleNotionalIsCalculatedExactly(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 0, "100.25", "0.2", false),
	)

	aggregator.AddTick(
		makeTick(0, 10, "101.50", "0.3", false),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	// 100.25 * 0.2 = 20.05
	// 101.50 * 0.3 = 30.45
	// total = 50.50
	if candle.Notional != "50.5" {
		t.Errorf(
			"notional = %q, want %q",
			candle.Notional,
			"50.5",
		)
	}
}

func TestBuyAndSellVolumeUsesBinanceAggressorFlag(t *testing.T) {
	aggregator := NewDefaultAggregator()

	// m=false:
	// buyer was not the market maker -> buyer was taker.
	aggregator.AddTick(
		makeTick(0, 0, "100", "0.4", false),
	)

	// m=true:
	// buyer was market maker -> seller was taker.
	aggregator.AddTick(
		makeTick(0, 10, "101", "0.6", true),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if candle.BuyVolume != "0.4" {
		t.Errorf(
			"buy volume = %q, want %q",
			candle.BuyVolume,
			"0.4",
		)
	}

	if candle.SellVolume != "0.6" {
		t.Errorf(
			"sell volume = %q, want %q",
			candle.SellVolume,
			"0.6",
		)
	}
}

func TestFiveMinuteCandleAggregatesMultipleMinutes(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 1, "100", "1", false),
	)

	aggregator.AddTick(
		makeTick(1, 10, "105", "2", false),
	)

	aggregator.AddTick(
		makeTick(3, 20, "95", "3", true),
	)

	aggregator.AddTick(
		makeTick(4, 59, "102", "4", false),
	)

	candle, err := aggregator.CurrentCandle(
		FiveMinutesSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current 5-minute candle")
	}

	if candle.Open != "100" {
		t.Errorf("open = %q, want %q", candle.Open, "100")
	}

	if candle.High != "105" {
		t.Errorf("high = %q, want %q", candle.High, "105")
	}

	if candle.Low != "95" {
		t.Errorf("low = %q, want %q", candle.Low, "95")
	}

	if candle.Close != "102" {
		t.Errorf("close = %q, want %q", candle.Close, "102")
	}

	if candle.Volume != "10" {
		t.Errorf("volume = %q, want %q", candle.Volume, "10")
	}

	if candle.NumberOfTrades != 4 {
		t.Errorf(
			"number of trades = %d, want %d",
			candle.NumberOfTrades,
			4,
		)
	}

	if candle.BuyVolume != "7" {
		t.Errorf(
			"buy volume = %q, want %q",
			candle.BuyVolume,
			"7",
		)
	}

	if candle.SellVolume != "3" {
		t.Errorf(
			"sell volume = %q, want %q",
			candle.SellVolume,
			"3",
		)
	}
}

func TestFiveMinuteBoundaryClosesPreviousCandle(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(4, 59, "100", "1", false),
	)

	closed := aggregator.AddTick(
		makeTick(5, 0, "110", "2", false),
	)

	var fiveMinuteClosed *Candle

	for i := range closed {
		if closed[i].Timestamp.Equal(baseTime) {
			fiveMinuteClosed = &closed[i]
			break
		}
	}

	if fiveMinuteClosed == nil {
		t.Fatal("expected previous 5-minute candle to close")
	}

	if fiveMinuteClosed.Close != "100" {
		t.Errorf(
			"closed candle close = %q, want %q",
			fiveMinuteClosed.Close,
			"100",
		)
	}

	current, err := aggregator.CurrentCandle(
		FiveMinutesSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if current == nil {
		t.Fatal("expected current 5-minute candle")
	}

	expected := baseTime.Add(5 * time.Minute)

	if !current.Timestamp.Equal(expected) {
		t.Errorf(
			"current timestamp = %v, want %v",
			current.Timestamp,
			expected,
		)
	}
}

func TestNoGapFilling(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 10, "100", "1", false),
	)

	closed := aggregator.AddTick(
		makeTick(5, 10, "110", "1", false),
	)

	if len(closed) != 1 {
		t.Fatalf(
			"closed candle count = %d, want %d",
			len(closed),
			1,
		)
	}

	candles, err := aggregator.Candles(
		OneMinuteSeconds,
		true,
	)
	if err != nil {
		t.Fatalf("Candles error: %v", err)
	}

	// One completed candle + one active candle.
	if len(candles) != 2 {
		t.Fatalf(
			"candle count = %d, want %d",
			len(candles),
			2,
		)
	}

	if !candles[0].Timestamp.Equal(baseTime) {
		t.Errorf(
			"first candle timestamp = %v, want %v",
			candles[0].Timestamp,
			baseTime,
		)
	}

	expectedCurrent := baseTime.Add(5 * time.Minute)

	if !candles[1].Timestamp.Equal(expectedCurrent) {
		t.Errorf(
			"current candle timestamp = %v, want %v",
			candles[1].Timestamp,
			expectedCurrent,
		)
	}
}

func TestOutOfOrderTickIsIgnored(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 10, "100", "1", false),
	)

	aggregator.AddTick(
		makeTick(0, 20, "105", "2", false),
	)

	// Earlier than the active candle's timestamp.
	aggregator.AddTick(
		makeTick(0, 5, "50", "100", false),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if candle.Open != "100" {
		t.Errorf(
			"open changed after out-of-order tick: got %q, want %q",
			candle.Open,
			"100",
		)
	}

	if candle.High != "105" {
		t.Errorf(
			"high changed after out-of-order tick: got %q, want %q",
			candle.High,
			"105",
		)
	}

	if candle.Low != "100" {
		t.Errorf(
			"low changed after out-of-order tick: got %q, want %q",
			candle.Low,
			"100",
		)
	}

	if candle.Close != "105" {
		t.Errorf(
			"close changed after out-of-order tick: got %q, want %q",
			candle.Close,
			"105",
		)
	}

	if candle.Volume != "3" {
		t.Errorf(
			"volume changed after out-of-order tick: got %q, want %q",
			candle.Volume,
			"3",
		)
	}

	if candle.NumberOfTrades != 2 {
		t.Errorf(
			"trade count changed after out-of-order tick: got %d, want %d",
			candle.NumberOfTrades,
			2,
		)
	}
}

func TestCompletedCandlesExcludeCurrentWhenRequested(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 10, "100", "1", false),
	)

	aggregator.AddTick(
		makeTick(1, 10, "110", "1", false),
	)

	aggregator.AddTick(
		makeTick(2, 10, "120", "1", false),
	)

	candles, err := aggregator.Candles(
		OneMinuteSeconds,
		false,
	)
	if err != nil {
		t.Fatalf("Candles error: %v", err)
	}

	if len(candles) != 2 {
		t.Fatalf(
			"completed candle count = %d, want %d",
			len(candles),
			2,
		)
	}

	if !candles[0].Timestamp.Equal(baseTime) {
		t.Errorf(
			"first timestamp = %v, want %v",
			candles[0].Timestamp,
			baseTime,
		)
	}

	if !candles[1].Timestamp.Equal(
		baseTime.Add(time.Minute),
	) {
		t.Errorf(
			"second timestamp = %v, want %v",
			candles[1].Timestamp,
			baseTime.Add(time.Minute),
		)
	}
}

func TestCandlesIncludeCurrentWhenRequested(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 10, "100", "1", false),
	)

	aggregator.AddTick(
		makeTick(1, 10, "110", "1", false),
	)

	candles, err := aggregator.Candles(
		OneMinuteSeconds,
		true,
	)
	if err != nil {
		t.Fatalf("Candles error: %v", err)
	}

	if len(candles) != 2 {
		t.Fatalf(
			"candle count = %d, want %d",
			len(candles),
			2,
		)
	}

	if !candles[1].Timestamp.Equal(
		baseTime.Add(time.Minute),
	) {
		t.Errorf(
			"current timestamp = %v, want %v",
			candles[1].Timestamp,
			baseTime.Add(time.Minute),
		)
	}

	if candles[1].Close != "110" {
		t.Errorf(
			"current close = %q, want %q",
			candles[1].Close,
			"110",
		)
	}
}

func TestHistoryLimitIsEnforced(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		2,
	)

	aggregator.AddTick(
		makeTick(0, 1, "100", "1", false),
	)

	aggregator.AddTick(
		makeTick(1, 1, "101", "1", false),
	)

	aggregator.AddTick(
		makeTick(2, 1, "102", "1", false),
	)

	aggregator.AddTick(
		makeTick(3, 1, "103", "1", false),
	)

	candles, err := aggregator.Candles(
		OneMinuteSeconds,
		false,
	)
	if err != nil {
		t.Fatalf("Candles error: %v", err)
	}

	if len(candles) != 2 {
		t.Fatalf(
			"completed candle count = %d, want %d",
			len(candles),
			2,
		)
	}

	expectedFirst := baseTime.Add(1 * time.Minute)
	expectedSecond := baseTime.Add(2 * time.Minute)

	if !candles[0].Timestamp.Equal(expectedFirst) {
		t.Errorf(
			"oldest retained timestamp = %v, want %v",
			candles[0].Timestamp,
			expectedFirst,
		)
	}

	if !candles[1].Timestamp.Equal(expectedSecond) {
		t.Errorf(
			"newest retained timestamp = %v, want %v",
			candles[1].Timestamp,
			expectedSecond,
		)
	}
}

func TestUnsupportedTimeframeReturnsError(t *testing.T) {
	aggregator := NewDefaultAggregator()

	aggregator.AddTick(
		makeTick(0, 0, "100", "1", false),
	)

	if _, err := aggregator.Candles(
		123,
		true,
	); err == nil {
		t.Fatal("expected error for unsupported timeframe")
	}

	if _, err := aggregator.CurrentCandle(123); err == nil {
		t.Fatal("expected error for unsupported timeframe")
	}
}

func TestEmptyTimeframesAreRejected(t *testing.T) {
	_, err := NewAggregator(
		[]int64{},
		100,
		slog.Default(),
	)

	if err == nil {
		t.Fatal("expected error for empty timeframes")
	}
}

func TestNonPositiveTimeframeIsRejected(t *testing.T) {
	tests := []int64{
		0,
		-1,
		-60,
	}

	for _, seconds := range tests {
		_, err := NewAggregator(
			[]int64{seconds},
			100,
			slog.Default(),
		)

		if err == nil {
			t.Errorf(
				"expected error for timeframe %d",
				seconds,
			)
		}
	}
}

func TestDuplicateTimeframesAreRejected(t *testing.T) {
	_, err := NewAggregator(
		[]int64{
			OneMinuteSeconds,
			OneMinuteSeconds,
		},
		100,
		slog.Default(),
	)

	if err == nil {
		t.Fatal("expected error for duplicate timeframes")
	}
}

func TestNonPositiveHistoryLimitIsRejected(t *testing.T) {
	tests := []int{
		0,
		-1,
		-100,
	}

	for _, historyLimit := range tests {
		_, err := NewAggregator(
			[]int64{OneMinuteSeconds},
			historyLimit,
			slog.Default(),
		)

		if err == nil {
			t.Errorf(
				"expected error for history limit %d",
				historyLimit,
			)
		}
	}
}

func TestNilLoggerIsAccepted(t *testing.T) {
	aggregator, err := NewAggregator(
		[]int64{OneMinuteSeconds},
		100,
		nil,
	)

	if err != nil {
		t.Fatalf(
			"NewAggregator with nil logger returned error: %v",
			err,
		)
	}

	if aggregator == nil {
		t.Fatal("expected aggregator")
	}
}

func TestCandleTimestampsAreUTC(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	tick := makeTick(
		0,
		10,
		"100",
		"1",
		false,
	)

	// Same instant as baseTime + 10 seconds, represented in IST.
	ist := time.FixedZone(
		"IST",
		5*60*60+30*60,
	)

	localTime := baseTime.
		In(ist).
		Add(10 * time.Second)

	tick.TradeTime = localTime.UnixMilli()

	aggregator.AddTick(tick)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if candle.Timestamp.Location() != time.UTC {
		t.Errorf(
			"candle location = %v, want UTC",
			candle.Timestamp.Location(),
		)
	}

	if !candle.Timestamp.Equal(baseTime) {
		t.Errorf(
			"candle timestamp = %v, want %v",
			candle.Timestamp,
			baseTime,
		)
	}
}

func TestFiveMinuteCandleStartsOnFiveMinuteBoundary(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{FiveMinutesSeconds},
		100,
	)

	// 12:03:25 belongs to the 12:00 five-minute bucket.
	aggregator.AddTick(
		makeTick(3, 25, "100", "1", false),
	)

	candle, err := aggregator.CurrentCandle(
		FiveMinutesSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if !candle.Timestamp.Equal(baseTime) {
		t.Errorf(
			"timestamp = %v, want %v",
			candle.Timestamp,
			baseTime,
		)
	}
}

func TestLastTradeTimestampTracksLatestTrade(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 10, "100", "1", false),
	)

	aggregator.AddTick(
		makeTick(0, 20, "105", "1", false),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	expected := baseTime.Add(20 * time.Second)

	if !candle.LastTradeTimestamp.Equal(expected) {
		t.Errorf(
			"last trade timestamp = %v, want %v",
			candle.LastTradeTimestamp,
			expected,
		)
	}
}

func TestDecimalArithmeticDoesNotIntroduceFloatRounding(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{OneMinuteSeconds},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 0, "0.1", "0.1", false),
	)

	aggregator.AddTick(
		makeTick(0, 1, "0.2", "0.2", false),
	)

	aggregator.AddTick(
		makeTick(0, 2, "0.3", "0.3", false),
	)

	candle, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("CurrentCandle error: %v", err)
	}

	if candle == nil {
		t.Fatal("expected current candle")
	}

	if candle.Volume != "0.6" {
		t.Errorf(
			"volume = %q, want exact %q",
			candle.Volume,
			"0.6",
		)
	}

	// 0.1*0.1 + 0.2*0.2 + 0.3*0.3
	// = 0.01 + 0.04 + 0.09
	// = 0.14
	if candle.Notional != "0.14" {
		t.Errorf(
			"notional = %q, want exact %q",
			candle.Notional,
			"0.14",
		)
	}
}

func TestFromTickInitializesAllFields(t *testing.T) {
	tick := makeTick(
		2,
		15,
		"123.45",
		"0.75",
		false,
	)

	candle := FromTick(
		baseTime.Add(2*time.Minute),
		tick,
	)

	if !candle.Timestamp.Equal(
		baseTime.Add(2 * time.Minute),
	) {
		t.Errorf(
			"timestamp = %v, want %v",
			candle.Timestamp,
			baseTime.Add(2*time.Minute),
		)
	}

	if candle.Symbol != "BTCUSDT" {
		t.Errorf(
			"symbol = %q, want %q",
			candle.Symbol,
			"BTCUSDT",
		)
	}

	if candle.Open != "123.45" {
		t.Errorf(
			"open = %q, want %q",
			candle.Open,
			"123.45",
		)
	}

	if candle.High != "123.45" {
		t.Errorf(
			"high = %q, want %q",
			candle.High,
			"123.45",
		)
	}

	if candle.Low != "123.45" {
		t.Errorf(
			"low = %q, want %q",
			candle.Low,
			"123.45",
		)
	}

	if candle.Close != "123.45" {
		t.Errorf(
			"close = %q, want %q",
			candle.Close,
			"123.45",
		)
	}

	if candle.Volume != "0.75" {
		t.Errorf(
			"volume = %q, want %q",
			candle.Volume,
			"0.75",
		)
	}

	if candle.NumberOfTrades != 1 {
		t.Errorf(
			"number of trades = %d, want %d",
			candle.NumberOfTrades,
			1,
		)
	}

	expectedTradeTime := baseTime.
		Add(2 * time.Minute).
		Add(15 * time.Second)

	if !candle.LastTradeTimestamp.Equal(expectedTradeTime) {
		t.Errorf(
			"last trade timestamp = %v, want %v",
			candle.LastTradeTimestamp,
			expectedTradeTime,
		)
	}

	if candle.Notional != "92.5875" {
		t.Errorf(
			"notional = %q, want %q",
			candle.Notional,
			"92.5875",
		)
	}

	if candle.BuyVolume != "0.75" {
		t.Errorf(
			"buy volume = %q, want %q",
			candle.BuyVolume,
			"0.75",
		)
	}

	if candle.SellVolume != "0" {
		t.Errorf(
			"sell volume = %q, want %q",
			candle.SellVolume,
			"0",
		)
	}
}

func TestCandleSymbolAndTimeframeRemainIndependent(t *testing.T) {
	aggregator := newTestAggregator(
		[]int64{
			OneMinuteSeconds,
			FiveMinutesSeconds,
		},
		100,
	)

	aggregator.AddTick(
		makeTick(0, 10, "100", "1", false),
	)

	oneMinute, err := aggregator.CurrentCandle(
		OneMinuteSeconds,
	)
	if err != nil {
		t.Fatalf("1-minute CurrentCandle error: %v", err)
	}

	fiveMinute, err := aggregator.CurrentCandle(
		FiveMinutesSeconds,
	)
	if err != nil {
		t.Fatalf("5-minute CurrentCandle error: %v", err)
	}

	if oneMinute == nil || fiveMinute == nil {
		t.Fatal("expected both active candles")
	}

	if oneMinute.Symbol != "BTCUSDT" {
		t.Errorf(
			"1-minute symbol = %q, want BTCUSDT",
			oneMinute.Symbol,
		)
	}

	if fiveMinute.Symbol != "BTCUSDT" {
		t.Errorf(
			"5-minute symbol = %q, want BTCUSDT",
			fiveMinute.Symbol,
		)
	}

	if !oneMinute.Timestamp.Equal(baseTime) {
		t.Errorf(
			"1-minute timestamp = %v, want %v",
			oneMinute.Timestamp,
			baseTime,
		)
	}

	if !fiveMinute.Timestamp.Equal(baseTime) {
		t.Errorf(
			"5-minute timestamp = %v, want %v",
			fiveMinute.Timestamp,
			baseTime,
		)
	}
}
