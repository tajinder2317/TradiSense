package market

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

const validAggregateTrade = `{"e":"aggTrade","E":1700000000123,"s":"BTCUSDT","a":42,"p":"37500.12","q":"0.0025","f":40,"l":42,"T":1700000000100,"m":false}`

func TestDecodeAggregateTrade(t *testing.T) {
	tick, err := DecodeAggregateTrade([]byte(validAggregateTrade))
	if err != nil {
		t.Fatalf("DecodeAggregateTrade() error = %v", err)
	}

	if tick.EventType != "aggTrade" || tick.Symbol != "BTCUSDT" {
		t.Fatalf("unexpected event mapping: %#v", tick)
	}

	if tick.EventTime != 1700000000123 ||
		tick.TradeTime != 1700000000100 {
		t.Fatalf("unexpected timestamp mapping: %#v", tick)
	}

	if tick.AggregateTradeID != 42 ||
		tick.FirstTradeID != 40 ||
		tick.LastTradeID != 42 {
		t.Fatalf("unexpected ID mapping: %#v", tick)
	}

	if tick.Price != Decimal("37500.12") ||
		tick.Quantity != Decimal("0.0025") {
		t.Fatalf("unexpected decimal mapping: %#v", tick)
	}
}

func TestDecodeAggregateTradeMapsBuyerMarketMaker(t *testing.T) {
	tick, err := DecodeAggregateTrade([]byte(validAggregateTrade))
	if err != nil {
		t.Fatalf("DecodeAggregateTrade() error = %v", err)
	}

	if tick.IsBuyerMarketMaker {
		t.Fatal("IsBuyerMarketMaker = true, want false")
	}
}

func TestDecodeAggregateTradeRejectsMalformedJSON(t *testing.T) {
	if _, err := DecodeAggregateTrade([]byte(`{"e":`)); err == nil {
		t.Fatal("DecodeAggregateTrade() error = nil, want malformed JSON error")
	}
}

func TestDecodeAggregateTradeRejectsMissingRequiredField(t *testing.T) {
	missingQuantity := `{"e":"aggTrade","E":1700000000123,"s":"BTCUSDT","a":42,"p":"37500.12","f":40,"l":42,"T":1700000000100,"m":false}`

	if _, err := DecodeAggregateTrade([]byte(missingQuantity)); err == nil {
		t.Fatal("DecodeAggregateTrade() error = nil, want required-field error")
	}
}

func TestServiceClosesTickChannelOnContextCancellation(t *testing.T) {
	connection := newBlockingConnection()

	service := testService(
		&fakeDialer{
			connections: []WebSocketConnection{connection},
		},
	)

	ctx, cancel := context.WithCancel(context.Background())
	ticks := make(chan MarketTick)
	done := make(chan struct{})

	go func() {
		service.Run(ctx, ticks)
		close(done)
	}()

	select {
	case <-connection.readStarted:
	case <-time.After(time.Second):
		cancel()
		t.Fatal("ReadMessage did not start")
	}

	cancel()

	select {
	case <-connection.closedSignal:
	case <-time.After(time.Second):
		t.Fatal("connection was not closed on context cancellation")
	}

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("service did not stop after context cancellation")
	}

	if _, open := <-ticks; open {
		t.Fatal("tick channel remains open after service shutdown")
	}

	if !connection.wasClosed() {
		t.Fatal("connection was not closed on context cancellation")
	}
}

func TestServiceReconnectsWithBackoffWithoutNetwork(t *testing.T) {
	first := &fakeConnection{
		results: []readResult{
			{
				err: io.ErrUnexpectedEOF,
			},
		},
	}

	second := &fakeConnection{
		results: []readResult{
			{
				payload: []byte(validAggregateTrade),
			},
		},
	}

	dialer := &fakeDialer{
		connections: []WebSocketConnection{
			first,
			second,
		},
	}

	var waits []time.Duration

	service := testService(dialer)

	service.Wait = func(
		_ context.Context,
		duration time.Duration,
	) error {
		waits = append(waits, duration)
		return nil
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ticks := make(chan MarketTick, 1)
	done := make(chan struct{})

	go func() {
		service.Run(ctx, ticks)
		close(done)
	}()

	select {
	case tick, ok := <-ticks:
		if !ok {
			t.Fatal("tick channel closed before receiving tick")
		}

		if tick.Symbol != "BTCUSDT" {
			t.Fatalf(
				"tick symbol = %s, want BTCUSDT",
				tick.Symbol,
			)
		}

	case <-time.After(time.Second):
		t.Fatal("did not receive tick after reconnect")
	}

	cancel()

	select {
	case <-done:

	case <-time.After(time.Second):
		t.Fatal(
			"service did not stop after reconnect test cancellation",
		)
	}

	if len(waits) != 1 || waits[0] != time.Second*2 {
		t.Fatalf(
			"backoff waits = %v, want [2s]",
			waits,
		)
	}
}

func TestServiceIgnoresNonTextMessages(t *testing.T) {
	connection := &sequenceWebSocketConnection{
		wait: make(chan struct{}),
		messages: []sequenceMessage{
			{
				messageType: websocket.BinaryMessage,
				payload:     []byte(`{}`),
			},
			{
				messageType: websocket.TextMessage,
				payload:     []byte(validAggregateTrade),
			},
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ticks := make(chan MarketTick, 1)

	service := NewService("")
	service.Logger = slog.New(
		slog.NewTextHandler(io.Discard, nil),
	)

	done := make(chan error, 1)

	go func() {
		done <- service.readConnection(
			ctx,
			connection,
			ticks,
		)
	}()

	select {
	case tick, ok := <-ticks:
		if !ok {
			t.Fatal("tick channel closed before receiving valid tick")
		}

		if tick.Symbol != "BTCUSDT" {
			t.Fatalf(
				"tick symbol = %s, want BTCUSDT",
				tick.Symbol,
			)
		}

		cancel()
		connection.Close()

	case err := <-done:
		t.Fatalf(
			"readConnection returned before receiving valid tick: %v",
			err,
		)

	case <-time.After(time.Second):
		t.Fatal("did not receive valid tick")
	}

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf(
				"readConnection error = %v, want context.Canceled",
				err,
			)
		}

	case <-time.After(time.Second):
		t.Fatal("readConnection did not stop after cancellation")
	}
}

func TestServiceIgnoresMalformedMessages(t *testing.T) {
	connection := &sequenceWebSocketConnection{
		wait: make(chan struct{}),
		messages: []sequenceMessage{
			{
				messageType: websocket.TextMessage,
				payload:     []byte(`not valid json`),
			},
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ticks := make(chan MarketTick)

	service := NewService("")
	service.Logger = slog.New(
		slog.NewTextHandler(io.Discard, nil),
	)

	go func() {
		time.Sleep(10 * time.Millisecond)
		cancel()
		connection.Close()
	}()

	err := service.readConnection(
		ctx,
		connection,
		ticks,
	)

	if !errors.Is(err, context.Canceled) {
		t.Fatalf(
			"readConnection error = %v, want context.Canceled",
			err,
		)
	}
}

func testService(dialer WebSocketDialer) *Service {
	service := NewService("ws://example.test/aggTrade")

	service.Dialer = dialer
	service.Logger = slog.New(
		slog.NewTextHandler(io.Discard, nil),
	)

	service.StableConnectionAfter = time.Hour

	return service
}

type fakeDialer struct {
	connections []WebSocketConnection
	index       int
}

func (dialer *fakeDialer) DialContext(
	_ context.Context,
	_ string,
) (WebSocketConnection, error) {
	if dialer.index >= len(dialer.connections) {
		return nil, errors.New("no fake connection available")
	}

	connection := dialer.connections[dialer.index]
	dialer.index++

	return connection, nil
}

type readResult struct {
	payload []byte
	err     error
}

type fakeConnection struct {
	results []readResult

	mu     sync.Mutex
	index  int
	closed bool

	readStarted  chan struct{}
	closedSignal chan struct{}

	readStartedOnce sync.Once
	closedOnce      sync.Once
}

func newBlockingConnection() *fakeConnection {
	return &fakeConnection{
		readStarted:  make(chan struct{}),
		closedSignal: make(chan struct{}),
	}
}

func (connection *fakeConnection) ReadMessage() (
	int,
	[]byte,
	error,
) {
	if connection.readStarted != nil {
		connection.readStartedOnce.Do(func() {
			close(connection.readStarted)
		})
	}

	for {
		connection.mu.Lock()

		if connection.closed {
			connection.mu.Unlock()
			return 0, nil, io.EOF
		}

		if connection.index < len(connection.results) {
			result := connection.results[connection.index]
			connection.index++

			connection.mu.Unlock()

			if result.err != nil {
				return 0, nil, result.err
			}

			return websocket.TextMessage, result.payload, nil
		}

		connection.mu.Unlock()

		time.Sleep(time.Millisecond)
	}
}

func (connection *fakeConnection) Close() error {
	connection.mu.Lock()
	connection.closed = true
	connection.mu.Unlock()

	if connection.closedSignal != nil {
		connection.closedOnce.Do(func() {
			close(connection.closedSignal)
		})
	}

	return nil
}

func (connection *fakeConnection) wasClosed() bool {
	connection.mu.Lock()
	defer connection.mu.Unlock()

	return connection.closed
}

type sequenceMessage struct {
	messageType int
	payload     []byte
}

type sequenceWebSocketConnection struct {
	mu        sync.Mutex
	messages  []sequenceMessage
	index     int
	wait      chan struct{}
	closed    bool
	closeOnce sync.Once
}

func (connection *sequenceWebSocketConnection) ReadMessage() (
	int,
	[]byte,
	error,
) {
	connection.mu.Lock()

	if connection.index < len(connection.messages) {
		message := connection.messages[connection.index]
		connection.index++
		connection.mu.Unlock()

		return message.messageType, message.payload, nil
	}

	wait := connection.wait
	connection.mu.Unlock()

	<-wait

	return 0, nil, context.Canceled
}

func (connection *sequenceWebSocketConnection) Close() error {
	connection.mu.Lock()
	connection.closed = true
	connection.mu.Unlock()

	connection.closeOnce.Do(func() {
		close(connection.wait)
	})

	return nil
}
