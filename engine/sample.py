"""A made-up but realistic trading day for simulation and tests (no real market data).

Four stocks with 70 days of history:
  WIN  (Lead)  breaks out around 09:25 and keeps rising → winner, closed at 15:15
  LOSE (Lead)  breaks out, then falls through the −2% stop → stopped out
  FLAT (Lead)  never reaches its breakout target
  DOWN (Lag)   falling history → excluded by the screener
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from core import ticks
from core.clock import KST
from core.types import Bar

SAMPLE_DAY = date(2026, 11, 5)
HISTORY = 70
SYMBOLS = {"WIN": "반도체", "LOSE": "반도체", "FLAT": "조선", "DOWN": "조선"}


def _trading_days_before(day: date, n: int) -> list[date]:
    out, d = [], day
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out[::-1]


def _history(symbol: str, base: float, step: float, day: date) -> list[Bar]:
    bars = []
    for i, d in enumerate(_trading_days_before(day, HISTORY)):
        c = ticks.round_down(Decimal(str(round(base * (1 + step) ** i))))
        bars.append(Bar(symbol, d, c, ticks.round_down(c * Decimal("1.025")), ticks.round_down(c * Decimal("0.975")),
                        c, 1_000_000, datetime.combine(d, time(15, 30), KST)))
    return bars


def _path(kind: str, i: int) -> Decimal:
    """Price multiple of the open for 5-minute step i (0 = 09:00 … 78 = 15:30)."""
    if kind == "WIN":
        return Decimal(1) + Decimal("0.005") * min(i, 12)               # +6% by 10:00, then flat
    if kind == "LOSE":
        up = Decimal("0.005") * min(i, 6)                                # +3% by 09:30
        down = Decimal("0.004") * max(0, i - 6)                          # then −0.4% per step
        return max(Decimal("0.95"), Decimal(1) + up - down)
    return Decimal(1) + Decimal("0.002") * (i % 3) - Decimal("0.002")    # FLAT, DOWN: ±0.2%


def sample_day(day: date = SAMPLE_DAY) -> dict:
    """Returns {"day", "sectors", "daily_bars": {sym: [Bar]}, "ticks": [(datetime, sym, last, bid, ask, bs, as)]}."""
    bars = {"WIN": _history("WIN", 40000, 0.004, day), "LOSE": _history("LOSE", 40000, 0.004, day),
            "FLAT": _history("FLAT", 40000, 0.004, day), "DOWN": _history("DOWN", 60000, -0.004, day)}
    tick_rows = []
    for i in range(79):
        t = datetime.combine(day, time(9, 0), KST) + timedelta(minutes=5 * i)
        for sym, hist in bars.items():
            open_ = hist[-1].close
            last = ticks.round_down(open_ * _path(sym, i))
            tick_rows.append((t, sym, last, last, last + ticks.tick_size(last), 1000, 1000))
    return {"day": day, "sectors": dict(SYMBOLS), "daily_bars": bars, "ticks": tick_rows}
