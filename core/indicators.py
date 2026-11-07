"""Pure indicator functions. Callers pass closed bars only (engine/state.py enforces as_of)."""
from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from core.types import Bar, TrendClass

EMA_FAST, EMA_MID, EMA_SLOW = 9, 21, 50


def ema(values: Sequence[Decimal], n: int) -> list[Decimal | None]:
    """EMA with alpha = 2/(n+1), seeded by the simple mean of the first n values.
    Entries before the seed are None."""
    if n < 1:
        raise ValueError("period must be >= 1")
    out: list[Decimal | None] = [None] * len(values)
    if len(values) < n:
        return out
    alpha = Decimal(2) / Decimal(n + 1)
    e = sum(values[:n], Decimal(0)) / n
    out[n - 1] = e
    for i in range(n, len(values)):
        e = e + alpha * (values[i] - e)
        out[i] = e
    return out


def adr_pct(bars: Sequence[Bar], n: int = 20) -> Decimal | None:
    """Average daily range in percent: (mean of high/low over the last n bars − 1) × 100."""
    if len(bars) < n:
        return None
    last = bars[-n:]
    mean = sum((b.high / b.low for b in last), Decimal(0)) / n
    return (mean - 1) * 100


def avg_traded_value(bars: Sequence[Bar], n: int = 20) -> Decimal | None:
    """Mean of close × volume over the last n bars (KRW)."""
    if len(bars) < n:
        return None
    return sum((b.close * b.volume for b in bars[-n:]), Decimal(0)) / n


def trend_class(bars: Sequence[Bar]) -> TrendClass | None:
    """Lead: EMA9 > EMA21 > EMA50; Lag: EMA9 < EMA21 < EMA50; else Mediocre.
    None when there are fewer than 50 bars."""
    closes = [b.close for b in bars]
    if len(closes) < EMA_SLOW:
        return None
    f, m, s = (ema(closes, n)[-1] for n in (EMA_FAST, EMA_MID, EMA_SLOW))
    if f > m > s:
        return TrendClass.LEAD
    if f < m < s:
        return TrendClass.LAG
    return TrendClass.MEDIOCRE


def r_multiple(pnl: Decimal, initial_risk: Decimal) -> Decimal:
    """Trade result in units of the initial risk (P&L ÷ initial risk)."""
    if initial_risk <= 0:
        raise ValueError("initial risk must be positive")
    return pnl / initial_risk
