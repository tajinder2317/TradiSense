package market

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const DefaultBTCUSDTAggregateTradeURL = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"

type WebSocketConnection interface {
	ReadMessage() (messageType int, payload []byte, err error)
	Close() error
}

type WebSocketDialer interface {
	DialContext(ctx context.Context, url string) (WebSocketConnection, error)
}

type gorillaDialer struct {
	dialer *websocket.Dialer
}

func (dialer gorillaDialer) DialContext(
	ctx context.Context,
	url string,
) (WebSocketConnection, error) {
	connection, _, err := dialer.dialer.DialContext(
		ctx,
		url,
		http.Header{},
	)
	if err != nil {
		return nil, err
	}

	return connection, nil
}

type BackoffWaiter func(ctx context.Context, duration time.Duration) error

type Service struct {
	URL                   string
	Dialer                WebSocketDialer
	Logger                *slog.Logger
	InitialBackoff        time.Duration
	MaxBackoff            time.Duration
	StableConnectionAfter time.Duration
	Wait                  BackoffWaiter
	Now                   func() time.Time
}

func NewService(url string) *Service {
	if url == "" {
		url = DefaultBTCUSDTAggregateTradeURL
	}

	return &Service{
		URL: url,
		Dialer: gorillaDialer{
			dialer: websocket.DefaultDialer,
		},
		Logger:                slog.Default(),
		InitialBackoff:        time.Second,
		MaxBackoff:            30 * time.Second,
		StableConnectionAfter: 10 * time.Second,
		Wait:                  waitForBackoff,
		Now:                   time.Now,
	}
}

func (service *Service) Run(
	ctx context.Context,
	ticks chan<- MarketTick,
) {
	defer close(ticks)

	backoff := service.InitialBackoff

	for ctx.Err() == nil {
		connection, err := service.Dialer.DialContext(
			ctx,
			service.URL,
		)

		if err != nil {
			service.Logger.Warn(
				"public WebSocket connection failed",
				"error",
				err,
				"retry_in",
				backoff,
			)

			if !service.wait(ctx, backoff) {
				return
			}

			backoff = nextBackoff(
				backoff,
				service.MaxBackoff,
			)

			continue
		}

		connectedAt := service.Now()

		service.Logger.Info(
			"public WebSocket connection established",
			"url",
			service.URL,
		)

		err = service.readConnectionWithCancellation(
			ctx,
			connection,
			ticks,
		)

		_ = connection.Close()

		if ctx.Err() != nil {
			return
		}

		if service.Now().Sub(connectedAt) >= service.StableConnectionAfter {
			backoff = service.InitialBackoff
		} else {
			backoff = nextBackoff(
				backoff,
				service.MaxBackoff,
			)
		}

		service.Logger.Warn(
			"public WebSocket disconnected",
			"error",
			err,
			"retry_in",
			backoff,
		)

		if !service.wait(ctx, backoff) {
			return
		}
	}
}

func (service *Service) readConnectionWithCancellation(
	ctx context.Context,
	connection WebSocketConnection,
	ticks chan<- MarketTick,
) error {
	closed := make(chan struct{})

	var closeOnce sync.Once
	closeConnection := func() {
		closeOnce.Do(func() {
			_ = connection.Close()
		})
	}

	go func() {
		select {
		case <-ctx.Done():
			closeConnection()

		case <-closed:
		}
	}()

	defer close(closed)

	return service.readConnection(
		ctx,
		connection,
		ticks,
	)
}

func (service *Service) readConnection(
	ctx context.Context,
	connection WebSocketConnection,
	ticks chan<- MarketTick,
) error {
	for {
		messageType, payload, err := connection.ReadMessage()

		if err != nil {
			return fmt.Errorf(
				"read public WebSocket message: %w",
				err,
			)
		}

		if messageType != websocket.TextMessage {
			service.Logger.Warn(
				"ignoring non-text public WebSocket message",
			)

			continue
		}

		tick, err := DecodeAggregateTrade(payload)

		if err != nil {
			service.Logger.Warn(
				"ignoring malformed public WebSocket message",
				"error",
				err,
			)

			continue
		}

		select {
		case ticks <- tick:

		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

func (service *Service) wait(
	ctx context.Context,
	duration time.Duration,
) bool {
	if duration <= 0 {
		return ctx.Err() == nil
	}

	if err := service.Wait(ctx, duration); err != nil {
		return !errors.Is(err, context.Canceled) &&
			ctx.Err() == nil
	}

	return ctx.Err() == nil
}

func waitForBackoff(
	ctx context.Context,
	duration time.Duration,
) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()

	case <-timer.C:
		return nil
	}
}

func nextBackoff(
	current time.Duration,
	maximum time.Duration,
) time.Duration {
	if current <= 0 {
		return time.Second
	}

	if maximum <= 0 {
		return current * 2
	}

	if current >= maximum/2 {
		return maximum
	}

	return current * 2
}
