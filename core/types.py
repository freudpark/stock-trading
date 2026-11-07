"""Shared data types. Prices and money are Decimal (KRW); quantities are int."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Regime(str, Enum):
    TREND = "추세"
    RANGE = "횡보"
    VOLATILE = "고변동"
    CRISIS = "위기"


class Direction(str, Enum):
    LONG = "롱"
    NEUTRAL = "중립"


class RiskState(str, Enum):
    SAFE = "안전"
    NEAR_LIMIT = "한도근접"
    REDUCE = "축소"


class TrendClass(str, Enum):
    LEAD = "Lead"
    MEDIOCRE = "Mediocre"
    LAG = "Lag"


@dataclass(frozen=True)
class Bar:
    """One closed bar. `close_time` is when the bar became final."""
    symbol: str
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    close_time: datetime


@dataclass(frozen=True)
class Quote:
    symbol: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    time: datetime
    day_open: Decimal | None = None   # today's session so far
    day_high: Decimal | None = None
    day_low: Decimal | None = None


@dataclass(frozen=True)
class Snapshot:
    """Numbers only, for the strategy. Everything here was known at `as_of`."""
    symbol: str
    as_of: datetime
    last: Decimal
    mid: Decimal
    spread_bps: Decimal          # (ask − bid) / mid × 10,000
    imbalance: Decimal           # (bid_size − ask_size) / (bid_size + ask_size), −1..1
    day_open: Decimal | None
    day_high: Decimal | None
    day_low: Decimal | None
    prev_high: Decimal | None    # last closed daily bar before today
    prev_low: Decimal | None
    prev_close: Decimal | None
    trend: TrendClass | None
    adr_pct: Decimal | None
    avg_traded_value: Decimal | None
    realized_vol_pct: Decimal | None   # stdev of daily close-to-close returns, 20 days, %
    position_qty: int
    position_avg_price: Decimal | None
    equity: Decimal
    drawdown_pct: Decimal        # from peak, %
    daily_pnl_pct: Decimal       # vs today's starting equity, %


@dataclass(frozen=True)
class StatusFlags:
    """Korean market blocks for one stock (spec §6)."""
    vi: bool = False
    halted: bool = False
    warning: bool = False      # 관리종목 / 투자경고 and similar
    upper_limit: Decimal | None = None   # 상한가
    lower_limit: Decimal | None = None   # 하한가


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: int
    avg_price: Decimal


@dataclass(frozen=True)
class Account:
    """What the guard needs to know about the account right now."""
    equity: Decimal            # cash + market value of positions
    cash: Decimal
    peak_equity: Decimal       # highest equity seen (for drawdown)
    day_start_equity: Decimal  # equity at today's open (for daily loss)
    positions: dict[str, Position] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderIntent:
    """A proposed limit order, before the guard."""
    symbol: str
    side: Side
    qty: int
    limit_price: Decimal
    stop_price: Decimal | None = None   # initial stop, required for buys
    reason: str = ""


class OrderStatus(str, Enum):
    OPEN = "open"            # accepted, not (fully) filled
    FILLED = "filled"
    CANCELLED = "cancelled"  # may be partially filled before cancel
    REJECTED = "rejected"


@dataclass(frozen=True)
class Order:
    order_id: str            # client order id (idempotency key)
    intent: OrderIntent
    status: OrderStatus
    filled_qty: int = 0
    avg_fill_price: Decimal | None = None
    message: str = ""        # short reason on reject; never a raw broker body
    created: datetime | None = None


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: int
    price: Decimal
    commission: Decimal
    tax: Decimal
    time: datetime


@dataclass(frozen=True)
class Balance:
    cash: Decimal            # settled cash, including cash held for open buys
    available_cash: Decimal  # cash minus what open buy orders hold
    equity: Decimal          # cash + positions at last price


@dataclass(frozen=True)
class GuardResult:
    approved: bool
    reasons: tuple[str, ...] = ()     # every failed rule, empty when approved
    intent: OrderIntent | None = None  # the (tick-rounded) order when approved
