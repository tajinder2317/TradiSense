"""Binance public aggregate-trade WebSocket ingestion.

This module intentionally contains no authenticated endpoints, credentials, or
order execution code. It is only a real-time market-data source for research
and a future paper-trading simulator.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import websockets


LOGGER = logging.getLogger(__name__)

BINANCE_BTCUSDT_AGG_TRADE_STREAM = (
    "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
)


@dataclass(frozen=True, slots=True)
class MarketTick:
    """A normalized aggregate trade received from a public market-data stream."""

    timestamp: datetime
    symbol: str
    price: Decimal
    quantity: Decimal
    trade_id: int | None
    is_buyer_market_maker: bool | None = None


ConnectionFactory = Callable[
    [str], AbstractAsyncContextManager[AsyncIterator[str | bytes]]
]


def default_connection_factory(
    url: str,
) -> AbstractAsyncContextManager[AsyncIterator[str | bytes]]:
    """Open an unauthenticated Binance public WebSocket connection."""

    return websockets.connect(
        url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
    )


class MarketDataService:
    """Expose Binance public aggregate trades as an async stream of MarketTicks."""

    def __init__(
        self,
        url: str = BINANCE_BTCUSDT_AGG_TRADE_STREAM,
        *,
        connection_factory: ConnectionFactory = default_connection_factory,
        initial_reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 30.0,
    ) -> None:
        if initial_reconnect_delay < 0:
            raise ValueError("initial_reconnect_delay must be non-negative")
        if max_reconnect_delay < initial_reconnect_delay:
            raise ValueError(
                "max_reconnect_delay must be at least initial_reconnect_delay"
            )

        self._url = url
        self._connection_factory = connection_factory
        self._initial_reconnect_delay = initial_reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._stop_requested = asyncio.Event()

    def stop(self) -> None:
        """Request a graceful stop after the current receive operation completes."""

        self._stop_requested.set()

    @staticmethod
    def parse_aggregate_trade(message: str | bytes) -> MarketTick | None:
        """Parse one Binance aggregate-trade payload, returning None when invalid."""

        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            if not isinstance(message, str):
                raise TypeError("WebSocket message must be text or bytes")

            payload: Any = json.loads(message)
            if not isinstance(payload, dict):
                raise ValueError("WebSocket payload must be a JSON object")
            if payload.get("e") != "aggTrade":
                raise ValueError("WebSocket payload is not an aggregate trade")

            event_time_ms = payload["E"]
            if isinstance(event_time_ms, bool):
                raise ValueError("Event timestamp must be an integer")
            event_time_ms = int(event_time_ms)

            symbol = payload["s"]
            if not isinstance(symbol, str) or not symbol:
                raise ValueError("Symbol must be a non-empty string")

            price = Decimal(str(payload["p"]))
            quantity = Decimal(str(payload["q"]))
            if not price.is_finite() or price <= 0:
                raise ValueError("Price must be a positive finite number")
            if not quantity.is_finite() or quantity <= 0:
                raise ValueError("Quantity must be a positive finite number")

            raw_trade_id = payload.get("a")
            if isinstance(raw_trade_id, bool):
                raise ValueError("Trade ID must be an integer")
            trade_id = None if raw_trade_id is None else int(raw_trade_id)

            buyer_is_market_maker = payload.get("m")
            if buyer_is_market_maker is not None and not isinstance(
                buyer_is_market_maker, bool
            ):
                raise ValueError("Buyer market-maker flag must be a boolean")

            return MarketTick(
                timestamp=datetime.fromtimestamp(
                    event_time_ms / 1_000, tz=timezone.utc
                ),
                symbol=symbol,
                price=price,
                quantity=quantity,
                trade_id=trade_id,
                is_buyer_market_maker=buyer_is_market_maker,
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation,
            OverflowError,
            OSError,
        ) as error:
            LOGGER.warning("Ignoring malformed Binance WebSocket message: %s", error)
            return None

    async def ticks(self) -> AsyncIterator[MarketTick]:
        """Yield ticks continuously, reconnecting after disconnects or errors."""

        reconnect_attempt = 0
        while not self._stop_requested.is_set():
            try:
                LOGGER.info("Connecting to Binance public WebSocket: %s", self._url)
                async with self._connection_factory(self._url) as websocket:
                    reconnect_attempt = 0
                    LOGGER.info("Binance public WebSocket connection established")

                    async for message in websocket:
                        if self._stop_requested.is_set():
                            break

                        tick = self.parse_aggregate_trade(message)
                        if tick is None:
                            continue

                        LOGGER.debug(
                            "Received tick symbol=%s price=%s quantity=%s trade_id=%s",
                            tick.symbol,
                            tick.price,
                            tick.quantity,
                            tick.trade_id,
                        )
                        yield tick

                    if not self._stop_requested.is_set():
                        raise ConnectionError("Binance WebSocket stream ended")
            except asyncio.CancelledError:
                LOGGER.info("Binance public WebSocket task cancelled")
                raise
            except Exception as error:
                if self._stop_requested.is_set():
                    break

                reconnect_attempt += 1
                delay = min(
                    self._initial_reconnect_delay * (2 ** (reconnect_attempt - 1)),
                    self._max_reconnect_delay,
                )
                LOGGER.error("Binance public WebSocket error: %s", error)
                LOGGER.warning(
                    "Reconnection attempt %d in %.1f seconds",
                    reconnect_attempt,
                    delay,
                )
                await self._wait_for_stop_or_delay(delay)

        LOGGER.info("Binance public WebSocket service stopped")

    async def _wait_for_stop_or_delay(self, delay: float) -> None:
        """Wait without blocking the event loop, returning early on shutdown."""

        if delay == 0:
            await asyncio.sleep(0)
            return

        try:
            await asyncio.wait_for(self._stop_requested.wait(), timeout=delay)
        except TimeoutError:
            pass
