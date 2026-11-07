"""KRX tick sizes and daily price limits.

Tick table: the unified KOSPI/KOSDAQ table in force since 2023 (from memory,
미검증 against the current KRX rulebook; confirm before live trading).
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

# (upper bound exclusive, tick)
_TICK_TABLE: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("2000"), Decimal("1")),
    (Decimal("5000"), Decimal("5")),
    (Decimal("20000"), Decimal("10")),
    (Decimal("50000"), Decimal("50")),
    (Decimal("200000"), Decimal("100")),
    (Decimal("500000"), Decimal("500")),
)
_TOP_TICK = Decimal("1000")

LIMIT_RATE = Decimal("0.30")  # ±30% daily price band


def tick_size(price: Decimal) -> Decimal:
    if price <= 0:
        raise ValueError(f"price must be positive: {price}")
    for bound, tick in _TICK_TABLE:
        if price < bound:
            return tick
    return _TOP_TICK


def _round(price: Decimal, rounding: str) -> Decimal:
    tick = tick_size(price)
    return (price / tick).to_integral_value(rounding=rounding) * tick


def round_down(price: Decimal) -> Decimal:
    return _round(price, ROUND_FLOOR)


def round_up(price: Decimal) -> Decimal:
    # Rounding up near a band edge lands exactly on the edge, which is valid in both bands.
    return _round(price, ROUND_CEILING)


def is_valid_price(price: Decimal) -> bool:
    if price <= 0:
        return False
    return price % tick_size(price) == 0


def price_limits(prev_close: Decimal) -> tuple[Decimal, Decimal]:
    """(상한가, 하한가): ±30% of the previous close, rounded inward to valid ticks."""
    upper = round_down(prev_close * (1 + LIMIT_RATE))
    lower = round_up(prev_close * (1 - LIMIT_RATE))
    return upper, lower
