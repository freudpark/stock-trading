"""Daily-bar backtest of the v1 volatility breakout (docs/spec.md §5–§6).

Reuses the live pieces (screener, breadth regime, risk state thresholds, sizing,
ticks, costs). Daily bars cannot show the order of events inside a day, so the
rules lean pessimistic:
  - entry when high ≥ target (target is always above the open), at target rounded up plus 1 tick;
  - stop rule, two variants because daily bars hide the order of the low and the high:
      "pessimistic": low ≤ stop → stopped, even if the low came before the entry;
      "path": up day (close ≥ open) moves open→low→high→close, so after the entry the lowest
              price is the close; down day moves open→high→low→close, so it is the low;
    a stop exits 1 tick below the stop price;
  - otherwise exit at the close minus 1 tick (stands in for the 15:15 flatten);
  - candidates are taken in screener rank order; the daily loss limit stops later entries;
  - drawdown ≥ 75% of the halt → 축소: trades continue at the reduced risk; the halt stops all.
Not modelled: earnings block (no data), VI/halts, order-book quality (two variants instead).
No look-ahead: the screen for day d sees only bars dated before d (screen() also checks).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_FLOOR, Decimal
from typing import Mapping, Sequence

from core import ticks
from core.clock import KST
from core.types import Bar, Regime, TrendClass
from review.nightly import Summary, Trade, summarize
from risk.guard import Limits
from execution.sizing import buy_quantity
from strategy.breakout import HARD_STOP, K, NEAR_LIMIT_SHARE, market_regime
from universe.screener import screen

WINDOW = 150          # bars handed to the screener (like the ~100–150 a broker API returns)
SCREEN_TIME = time(8, 0)


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[tuple[date, Decimal]]
    summary: Summary
    max_drawdown_pct: Decimal
    total_return_pct: Decimal
    halted_on: date | None
    per_year: dict[int, Summary] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)


def _won(x: Decimal) -> Decimal:
    return x.to_integral_value(rounding=ROUND_FLOOR)


def history_before(bars: Sequence[Bar], day: date, window: int = WINDOW) -> list[Bar]:
    past = [b for b in bars if b.day < day]
    return past[-window:]


def run_backtest(universe: Mapping[str, Sequence[Bar]], limits: Limits, start_equity: Decimal,
                 book_point: bool, stop_rule: str = "path", start: date | None = None, end: date | None = None,
                 sectors: Mapping[str, str] | None = None,
                 start_peak: Decimal | None = None, drawdown_stops: bool = True) -> BacktestResult:
    """start_peak: continue an account that already has this peak equity (default: start_equity).
    drawdown_stops=False is for research only: it measures the strategy's edge over the whole
    period by ignoring the drawdown halt and the drawdown "near limit" block."""
    if stop_rule not in ("path", "pessimistic"):
        raise ValueError("stop_rule must be 'path' or 'pessimistic'")
    data = {s: sorted(b, key=lambda x: x.day) for s, b in universe.items()}
    by_day = {s: {b.day: b for b in bars} for s, bars in data.items()}
    days = sorted({b.day for bars in data.values() for b in bars})
    days = [d for d in days if (start is None or d >= start) and (end is None or d <= end)]

    cash = start_equity
    peak = max(start_peak or start_equity, start_equity)
    curve: list[tuple[date, Decimal]] = []
    trades: list[Trade] = []
    skipped: dict[str, int] = {}
    halted_on: date | None = None

    def skip(why: str) -> None:
        skipped[why] = skipped.get(why, 0) + 1

    for d in days:
        if drawdown_stops and halted_on is None and (peak - cash) / peak >= limits.max_drawdown:
            halted_on = d
        if halted_on is not None:
            curve.append((d, cash))
            continue
        hist = {s: history_before(bars, d) for s, bars in data.items()}
        hist = {s: h for s, h in hist.items() if h}
        if not hist:
            curve.append((d, cash))
            continue
        as_of = datetime.combine(d, SCREEN_TIME, KST)
        res = screen(hist, as_of, sectors)
        regime = market_regime(res.breadth_now, res.breadth_5d_ago)
        dd = (peak - cash) / peak
        day_start = cash
        if regime is Regime.CRISIS:
            skip("regime 위기")
            curve.append((d, cash))
            continue
        reduced = drawdown_stops and dd >= limits.max_drawdown * NEAR_LIMIT_SHARE   # 축소: reduced risk

        open_count = 0
        invested = Decimal(0)
        for row in res.candidates:
            bar = by_day[row.symbol].get(d)
            if bar is None:
                continue
            prev = hist[row.symbol][-1]
            target = bar.open + (prev.high - prev.low) * K
            if bar.high < target:
                continue
            quality = 1 + (1 if book_point else 0) + (1 if row.trend is TrendClass.LEAD else 0)
            if quality < 2:
                skip("quality < 2")
                continue
            if open_count >= limits.max_positions:
                skip("max positions")
                continue
            if (day_start - cash) / day_start >= limits.daily_loss * NEAR_LIMIT_SHARE:
                skip("risk state not 안전 (daily loss)")
                break
            upper, _ = ticks.price_limits(prev.close)
            entry = ticks.round_up(target)
            entry = min(entry + ticks.tick_size(entry), bar.high)
            if (upper - entry) / entry <= limits.near_limit:
                skip("near 상한가")
                continue
            stop = ticks.round_down(entry * (1 - HARD_STOP))
            free = cash - invested
            qty = buy_quantity(cash, free, entry, stop, 0, limits, reduced=reduced)
            if qty <= 0:
                skip("size zero")
                continue
            if stop_rule == "pessimistic":
                low_after_entry = bar.low
            else:
                low_after_entry = bar.close if bar.close >= bar.open else bar.low
            if low_after_entry <= stop:
                exit_px = stop - ticks.tick_size(stop)
                why = "stop"
            else:
                exit_px = bar.close - ticks.tick_size(bar.close)
                why = "close"
            gross_buy, gross_sell = entry * qty, exit_px * qty
            costs = (_won(gross_buy * limits.commission) + _won(gross_sell * limits.commission)
                     + _won(gross_sell * limits.sell_tax))
            t = Trade(row.symbol, f"{d.isoformat()}T09:00:00+09:00", "1st", quality, regime.value,
                      (entry - stop) * qty, qty=qty, bought=gross_buy, sold=gross_sell, costs=costs,
                      closed=True, closed_at=why)
            trades.append(t)
            invested += gross_buy   # capital is tied up for the rest of the day
            cash += t.pnl
            open_count += 1
        peak = max(peak, cash)
        curve.append((d, cash))

    worst = Decimal(0)
    hi = peak if start_peak is None else max(start_peak, start_equity)
    for _, eq in curve:
        hi = max(hi, eq)
        worst = max(worst, (hi - eq) / hi)
    years: dict[int, list[Trade]] = {}
    for t in trades:
        years.setdefault(int(t.opened[:4]), []).append(t)
    final = curve[-1][1] if curve else start_equity
    return BacktestResult(trades, curve, summarize(trades), worst * 100,
                          (final / start_equity - 1) * 100, halted_on,
                          {y: summarize(ts) for y, ts in sorted(years.items())}, skipped)
