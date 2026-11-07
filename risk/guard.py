"""Risk guard: fixed rules checked before every order (docs/spec.md §6).

The guard is last and absolute. Nothing (config flag, strategy, LLM output) can
bypass it. It fails closed: bad config refuses to load, and any error during a
check rejects the order.

Buys open risk and face every rule. Sells only close held shares, so they are
still allowed after a drawdown or daily-loss stop (positions must be flat by
15:15), but never under the kill switch, VI or a trading halt.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from core import ticks
from core.clock import MarketCalendar, to_kst
from core.types import Account, GuardResult, OrderIntent, Quote, Side, StatusFlags

HUNDRED = Decimal(100)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    max_drawdown: Decimal        # fractions, e.g. 0.15
    daily_loss: Decimal
    risk_per_trade: Decimal
    max_weight: Decimal
    max_positions: int
    entry_start: time
    entry_end: time
    near_limit: Decimal
    max_price_deviation: Decimal
    earnings_block_days: int
    kill_switch_file: str
    commission: Decimal
    sell_tax: Decimal


@dataclass(frozen=True)
class MarketContext:
    quote: Quote
    flags: StatusFlags
    now: datetime
    next_earnings: date | None = None
    earnings_flagged: bool = False   # BRAIN marked an unknown earnings date as unsafe


# key → (low, high, low_inclusive); value must be within the range
_PCT_RANGES = {
    "max_drawdown_pct": (0, 50, False),
    "daily_loss_pct": (0, 10, False),
    "risk_per_trade_pct": (0, 5, False),
    "max_weight_pct": (0, 100, False),
    "near_limit_pct": (0, 30, True),
    "max_price_deviation_pct": (0, 30, False),
}
_COST_RANGES = {"commission_pct": (0, 5, True), "sell_tax_pct": (0, 5, True)}


def _number(table: dict, key: str, low, high, low_inclusive: bool) -> Decimal:
    if key not in table:
        raise ConfigError(f"missing key: {key}")
    v = table[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{key} must be a number")
    d = Decimal(str(v))
    if not ((d >= low if low_inclusive else d > low) and d <= high):
        raise ConfigError(f"{key}={v} out of range")
    return d


def _int(table: dict, key: str, low: int, high: int) -> int:
    v = table.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise ConfigError(f"{key} must be an integer in [{low}, {high}]")
    return v


def _time(table: dict, key: str) -> time:
    v = table.get(key)
    try:
        hh, mm = str(v).split(":")
        if len(hh) != 2 or len(mm) != 2:
            raise ValueError
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        raise ConfigError(f"{key} must be HH:MM, got {v!r}") from None


def load_limits(path: Path) -> Limits:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from None
    costs = raw.get("costs")
    if not isinstance(costs, dict):
        raise ConfigError("missing [costs] table")
    pct = {k: _number(raw, k, *r) / HUNDRED for k, r in _PCT_RANGES.items()}
    cost = {k: _number(costs, k, *r) / HUNDRED for k, r in _COST_RANGES.items()}
    start, end = _time(raw, "entry_start"), _time(raw, "entry_end")
    if start >= end:
        raise ConfigError("entry_start must be before entry_end")
    kill = raw.get("kill_switch_file")
    if not isinstance(kill, str) or not kill.strip():
        raise ConfigError("kill_switch_file must be a non-empty string")
    return Limits(
        max_drawdown=pct["max_drawdown_pct"],
        daily_loss=pct["daily_loss_pct"],
        risk_per_trade=pct["risk_per_trade_pct"],
        max_weight=pct["max_weight_pct"],
        max_positions=_int(raw, "max_positions", 1, 50),
        entry_start=start,
        entry_end=end,
        near_limit=pct["near_limit_pct"],
        max_price_deviation=pct["max_price_deviation_pct"],
        earnings_block_days=_int(raw, "earnings_block_days", 0, 60),
        kill_switch_file=kill,
        commission=cost["commission_pct"],
        sell_tax=cost["sell_tax_pct"],
    )


class Guard:
    def __init__(self, limits: Limits, calendar: MarketCalendar, project_root: Path):
        self.limits = limits
        self.calendar = calendar
        self.kill_switch = Path(project_root) / limits.kill_switch_file

    def check(self, intent: OrderIntent, account: Account, ctx: MarketContext) -> GuardResult:
        try:
            return self._check(intent, account, ctx)
        except Exception as e:  # fail closed on any bug or bad input
            return GuardResult(False, (f"internal error: {type(e).__name__}",))

    def _check(self, intent: OrderIntent, account: Account, ctx: MarketContext) -> GuardResult:
        L = self.limits
        fails: list[str] = []
        buy = intent.side is Side.BUY
        last = ctx.quote.last
        now = to_kst(ctx.now)

        if self.kill_switch.exists():
            fails.append("kill switch: STOP file exists")

        # Hours: buys only in the entry window, exits until the session closes.
        if buy:
            if not self.calendar.in_window(now, L.entry_start, L.entry_end):
                fails.append(f"hours: buys only {L.entry_start:%H:%M}-{L.entry_end:%H:%M} on trading days")
        elif not self.calendar.is_open(now):
            fails.append("hours: market closed")

        # Market blocks
        if ctx.flags.vi:
            fails.append("VI in progress")
        if ctx.flags.halted:
            fails.append("trading halt")

        # Quantity and price sanity (round to tick first, then check the rounded price)
        if intent.qty <= 0:
            fails.append("quantity must be > 0")
        if intent.limit_price <= 0:
            return GuardResult(False, tuple(fails + ["limit price must be > 0"]))
        price = ticks.round_down(intent.limit_price) if buy else ticks.round_up(intent.limit_price)
        if abs(price - last) / last > L.max_price_deviation:
            fails.append(f"price deviation: {price} vs last {last}")

        held = account.positions.get(intent.symbol)
        held_qty = held.qty if held else 0

        if buy:
            fails += self._buy_rules(intent, account, ctx, price, held_qty, now.date())
        elif intent.qty > held_qty:
            fails.append(f"short selling not allowed: sell {intent.qty} > held {held_qty}")

        if fails:
            return GuardResult(False, tuple(fails))
        return GuardResult(True, (), replace(intent, limit_price=price))

    def _buy_rules(self, intent, account, ctx, price, held_qty, today) -> list[str]:
        L = self.limits
        fails: list[str] = []
        equity = account.equity

        if account.peak_equity > 0 and (account.peak_equity - equity) / account.peak_equity >= L.max_drawdown:
            fails.append("max drawdown reached: no new buys until the user resets")
        if account.day_start_equity > 0 and (account.day_start_equity - equity) / account.day_start_equity >= L.daily_loss:
            fails.append("daily loss limit reached: no new buys today")

        if ctx.flags.warning:
            fails.append("warning stock (관리/투자경고)")
        up, low = ctx.flags.upper_limit, ctx.flags.lower_limit
        last = ctx.quote.last
        if up is None or low is None:
            fails.append("price limit unknown")
        elif (up - last) / last <= L.near_limit or (last - low) / last <= L.near_limit:
            fails.append("too close to price limit (상한가/하한가)")

        stop = intent.stop_price
        if stop is None or stop <= 0 or stop >= price:
            fails.append("buy needs a stop price below the entry")
        elif (price - stop) * intent.qty > equity * L.risk_per_trade:
            fails.append(f"risk per trade over {L.risk_per_trade * HUNDRED}% of equity")

        if (held_qty + intent.qty) * price > equity * L.max_weight:
            fails.append(f"weight over {L.max_weight * HUNDRED}% of equity")
        if held_qty == 0 and len(account.positions) >= L.max_positions:
            fails.append(f"max positions ({L.max_positions}) reached")

        cost = intent.qty * price * (1 + L.commission)
        if cost > account.cash:
            fails.append(f"not enough cash: need {cost}, have {account.cash}")

        nxt = ctx.next_earnings
        if nxt is None:
            if ctx.earnings_flagged:
                fails.append("earnings date unknown and flagged unsafe")
        elif nxt >= today and self.calendar.trading_days_between(today, nxt) <= L.earnings_block_days:
            fails.append(f"earnings on {nxt}: within {L.earnings_block_days} trading days")
        return fails
