"""Volatility breakout (docs/spec.md §5).

target = today's open + (prev high − prev low) × K, K = 0.5. Long when last ≥ target.

Signal quality (starting values, tuned by backtest in stage 5, then approved):
  +1 breakout (last ≥ target)       — without it quality is 0
  +1 order book supports the entry: imbalance ≥ 0 and spread ≤ 30 bps
  +1 trend class Lead                (cap 3); Lag is never traded long
Regime from watchlist breadth (todo D1); a stock whose range today exceeds 2 × ADR
is 고변동 unless the market is in 위기.
Risk state: daily loss ≥ 75% of its limit, or drawdown at the halt → 한도근접 (no entry);
drawdown ≥ 75% of the halt → 축소 (entry allowed at the reduced risk per trade, spec §6).
"""
from __future__ import annotations

from decimal import Decimal

from core import ticks
from core.types import Direction, Regime, RiskState, Snapshot, TrendClass
from risk.guard import NEAR_LIMIT_SHARE, Limits
from strategy.schema import Signal

K = Decimal("0.5")
HARD_STOP = Decimal("0.02")          # −2% from entry
MAX_SPREAD_BPS = Decimal(30)
VOLATILE_ADR_MULT = Decimal(2)


def market_regime(breadth_now: Decimal | None, breadth_5d_ago: Decimal | None) -> Regime:
    """Breadth = % of the watchlist in Lead. Unknown breadth → 횡보 (no boost, not blocked)."""
    if breadth_now is None:
        return Regime.RANGE
    drop = (breadth_5d_ago - breadth_now) if breadth_5d_ago is not None else Decimal(0)
    if breadth_now < 20 or drop >= 20:
        return Regime.CRISIS
    if breadth_now < 40 or drop >= 10:
        return Regime.RANGE
    return Regime.TREND


def risk_state_from(daily_pnl_pct: Decimal, drawdown_pct: Decimal, limits: Limits) -> RiskState:
    daily_loss = -daily_pnl_pct / 100      # positive when losing
    dd = drawdown_pct / 100
    if daily_loss >= limits.daily_loss * NEAR_LIMIT_SHARE or dd >= limits.max_drawdown:
        return RiskState.NEAR_LIMIT
    if dd >= limits.max_drawdown * NEAR_LIMIT_SHARE:
        return RiskState.REDUCE
    return RiskState.SAFE


def risk_state(s: Snapshot, limits: Limits) -> RiskState:
    return risk_state_from(s.daily_pnl_pct, s.drawdown_pct, limits)


class BreakoutStrategy:
    def __init__(self, limits: Limits):
        self.limits = limits

    def signal(self, s: Snapshot, market: Regime, avoid: bool = False) -> Signal:
        regime = market
        if (market is not Regime.CRISIS and s.adr_pct and s.prev_close and s.day_high and s.day_low
                and (s.day_high - s.day_low) / s.prev_close * 100 > VOLATILE_ADR_MULT * s.adr_pct):
            regime = Regime.VOLATILE
        rs = risk_state(s, self.limits)
        reasons: list[str] = [f"regime {regime.value}", f"risk {rs.value}"]
        if avoid:
            reasons.append("BRAIN 필터: 회피")

        def neutral(why: str, quality: int = 0, target=None) -> Signal:
            return Signal(s.symbol, s.as_of, regime, Direction.NEUTRAL, quality, rs,
                          tuple(reasons + [why]), target_price=target, avoid=avoid)

        if s.day_open is None or s.prev_high is None or s.prev_low is None:
            return neutral("data missing: open or previous range")
        target = s.day_open + (s.prev_high - s.prev_low) * K
        if s.last < target:
            return neutral(f"no breakout: last {s.last} < target {target}", target=target)

        quality = 1
        reasons.append(f"breakout: last {s.last} >= target {target}")
        if s.imbalance >= 0 and s.spread_bps <= MAX_SPREAD_BPS:
            quality += 1
            reasons.append("order book supports")
        if s.trend is TrendClass.LEAD:
            quality = min(3, quality + 1)
            reasons.append("trend Lead")

        if s.trend is TrendClass.LAG:
            return neutral("trend Lag: no long", quality, target)
        if s.position_qty > 0:
            return neutral("already holding", quality, target)

        entry = ticks.round_up(max(s.last, s.ask) if s.ask is not None else s.last)  # pay the ask to fill
        stop = ticks.round_down(entry * (1 - HARD_STOP))
        return Signal(s.symbol, s.as_of, regime, Direction.LONG, quality, rs, tuple(reasons),
                      target_price=target, entry_price=entry, stop_price=stop, avoid=avoid)
