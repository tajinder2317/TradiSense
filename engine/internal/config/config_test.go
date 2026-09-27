package config

import (
	"os"
	"testing"
)

func TestLoadUsesDefaults(t *testing.T) {
	config, err := Load(func(string) string {
		return ""
	})
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}

	if config.Symbol != "BTCUSDT" {
		t.Fatalf("expected default symbol BTCUSDT, got %q", config.Symbol)
	}

	if config.Stream != "aggTrade" {
		t.Fatalf("expected default stream aggTrade, got %q", config.Stream)
	}

	expectedURL := "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
	if config.StreamURL != expectedURL {
		t.Fatalf("expected default stream URL %q, got %q", expectedURL, config.StreamURL)
	}
}

func TestLoadReadsEnvironment(t *testing.T) {
	lookup := func(key string) string {
		switch key {
		case "TRADISENSE_SYMBOL":
			return "ethusdt"
		case "TRADISENSE_STREAM":
			return "aggTrade"
		case "TRADISENSE_STREAM_URL":
			return "wss://example.com/ws"
		default:
			return ""
		}
	}

	config, err := Load(lookup)
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}

	if config.Symbol != "ETHUSDT" {
		t.Fatalf("expected ETHUSDT, got %q", config.Symbol)
	}

	if config.Stream != "aggTrade" {
		t.Fatalf("expected aggTrade, got %q", config.Stream)
	}

	if config.StreamURL != "wss://example.com/ws" {
		t.Fatalf("unexpected stream URL: %q", config.StreamURL)
	}
}

func TestLoadRejectsUnsupportedStream(t *testing.T) {
	config, err := Load(func(key string) string {
		if key == "TRADISENSE_STREAM" {
			return "ticker"
		}
		return ""
	})

	if err == nil {
		t.Fatal("expected error for unsupported stream")
	}

	if config != (Config{}) {
		t.Fatalf("expected zero config on error, got %+v", config)
	}
}

func TestDefault(t *testing.T) {
	config := Default()

	if config.Symbol != "BTCUSDT" {
		t.Fatalf("expected BTCUSDT, got %q", config.Symbol)
	}

	if config.Stream != "aggTrade" {
		t.Fatalf("expected aggTrade, got %q", config.Stream)
	}
}

func TestDefaultStreamURL(t *testing.T) {
	expected := "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"

	if got := DefaultStreamURL(); got != expected {
		t.Fatalf("expected %q, got %q", expected, got)
	}
}

func TestLoadCanUseOSEnvironment(t *testing.T) {
	t.Setenv("TRADISENSE_SYMBOL", "BTCUSDT")
	t.Setenv("TRADISENSE_STREAM", "aggTrade")
	t.Setenv("TRADISENSE_STREAM_URL", "wss://example.com/test")

	config, err := Load(os.Getenv)
	if err != nil {
		t.Fatalf("Load(os.Getenv) returned error: %v", err)
	}

	if config.Symbol != "BTCUSDT" {
		t.Fatalf("expected BTCUSDT, got %q", config.Symbol)
	}

	if config.StreamURL != "wss://example.com/test" {
		t.Fatalf("unexpected stream URL: %q", config.StreamURL)
	}
}
