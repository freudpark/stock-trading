"""KST clock and KRX trading calendar. Clocks are injectable for tests and backtests."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Protocol

KST = timezone(timedelta(hours=9), "KST")  # Korea has no daylight saving time

SESSION_OPEN = time(9, 0)
SESSION_CLOSE = time(15, 30)  # regular session ends; closing auction 15:20–15:30


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(KST)


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, start: datetime):
        self._now = to_kst(start)

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = to_kst(moment)

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def to_kst(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("naive datetime; attach a time zone")
    return moment.astimezone(KST)


class MarketCalendar:
    def __init__(self, holidays: Iterable[date]):
        self.holidays = frozenset(holidays)

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def is_open(self, moment: datetime) -> bool:
        m = to_kst(moment)
        return self.is_trading_day(m.date()) and SESSION_OPEN <= m.time() < SESSION_CLOSE

    def in_window(self, moment: datetime, start: time, end: time) -> bool:
        """True on a trading day when start <= time <= end (both inclusive, KST)."""
        m = to_kst(moment)
        return self.is_trading_day(m.date()) and start <= m.time().replace(tzinfo=None) <= end

    def trading_days_between(self, start: date, end: date) -> int:
        """Number of trading days d with start < d <= end."""
        count, d = 0, start
        while d < end:
            d += timedelta(days=1)
            if self.is_trading_day(d):
                count += 1
        return count
