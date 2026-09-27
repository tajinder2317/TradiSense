"""Tests for public market-data parsing and reconnect behavior."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal

from backend.data.websocket import MarketDataService, MarketTick


def aggregate_trade_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "e": "aggTrade",
        "E": 1_700_000_000_123,
        "s": "BTCUSDT",
        "a": 42,
        "p": "37500.12",
        "q": "0.0025",
    }
    payload.update(overrides)
    return json.dumps(payload)


class FakeWebSocket(AsyncIterator[str | bytes]):
    def __init__(self, messages: list[str | bytes | BaseException]) -> None:
        self._messages = iter(messages)

    async def __aenter__(self) -> FakeWebSocket:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> FakeWebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            message = next(self._messages)
        except StopIteration:
            raise StopAsyncIteration from None
        if isinstance(message, BaseException):
            raise message
        return message


class FakeConnectionFactory:
    def __init__(self, sessions: list[list[str | bytes | BaseException]]) -> None:
        self._sessions = iter(sessions)
        self.urls: list[str] = []

    def __call__(self, url: str) -> FakeWebSocket:
        self.urls.append(url)
        return FakeWebSocket(next(self._sessions))


def test_parse_valid_aggregate_trade() -> None:
    tick = MarketDataService.parse_aggregate_trade(aggregate_trade_payload())

    assert tick == MarketTick(
        timestamp=datetime.fromtimestamp(1_700_000_000.123, tz=timezone.utc),
        symbol="BTCUSDT",
        price=Decimal("37500.12"),
        quantity=Decimal("0.0025"),
        trade_id=42,
    )


def test_parse_malformed_message_returns_none() -> None:
    assert MarketDataService.parse_aggregate_trade("not json") is None


def test_parse_non_aggregate_trade_returns_none() -> None:
    assert (
        MarketDataService.parse_aggregate_trade(
            aggregate_trade_payload(e="bookTicker")
        )
        is None
    )


def test_service_reconnects_after_connection_error() -> None:
    factory = FakeConnectionFactory(
        [
            [ConnectionError("simulated disconnect")],
            [aggregate_trade_payload()],
        ]
    )
    service = MarketDataService(
        url="wss://example.test/btcusdt@aggTrade",
        connection_factory=factory,
        initial_reconnect_delay=0,
        max_reconnect_delay=0,
    )

    async def collect_first_tick() -> MarketTick:
        async for tick in service.ticks():
            service.stop()
            return tick
        raise AssertionError("Expected a tick")

    tick = asyncio.run(collect_first_tick())

    assert tick.symbol == "BTCUSDT"
    assert len(factory.urls) == 2
