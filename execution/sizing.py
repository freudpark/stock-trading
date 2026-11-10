"""Position sizing: fixed fractional risk (docs/spec.md §6). Kelly is not used."""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from risk.guard import Limits


def _floor(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


def buy_quantity(equity: Decimal, cash: Decimal, entry: Decimal, stop: Decimal,
                 held_qty: int, limits: Limits, reduced: bool = False) -> int:
    """Shares to buy so that (entry − stop) × qty ≤ risk share of equity (the reduced share in 축소),
    capped by the max weight (including shares already held) and by cash.
    Returns 0 when inputs are invalid or nothing fits."""
    if equity <= 0 or cash <= 0 or entry <= 0 or stop <= 0 or stop >= entry:
        return 0
    risk = limits.reduced_risk_per_trade if reduced else limits.risk_per_trade
    by_risk = _floor(equity * risk / (entry - stop))
    by_weight = _floor(equity * limits.max_weight / entry) - held_qty
    by_cash = _floor(cash / (entry * (1 + limits.commission)))
    return max(0, min(by_risk, by_weight, by_cash))
