"""Broker interface. FakeBroker (now) and KisBroker (later) implement the same methods,
so tests, backtests, paper and live trading run the same code."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.types import Balance, Bar, Fill, Order, OrderIntent, Position, Quote, StatusFlags


@runtime_checkable
class Broker(Protocol):
    def get_quote(self, symbol: str) -> Quote | None: ...

    def get_daily_bars(self, symbol: str) -> list[Bar]:
        """Closed daily bars only (close_time <= now), oldest first."""
        ...

    def get_balance(self) -> Balance: ...

    def get_positions(self) -> dict[str, Position]: ...

    def get_status_flags(self, symbol: str) -> StatusFlags: ...

    def place_order(self, intent: OrderIntent, client_order_id: str) -> Order:
        """Limit order. Same client_order_id → same order, never a duplicate."""
        ...

    def cancel_order(self, client_order_id: str) -> Order: ...

    def get_order(self, client_order_id: str) -> Order: ...

    def open_orders(self) -> list[Order]: ...

    def get_fills(self) -> list[Fill]:
        """Today's fills, oldest first."""
        ...
