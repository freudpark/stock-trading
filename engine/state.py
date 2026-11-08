"""Builds the per-stock Snapshot the strategy sees, and tracks peak / day-start equity.

No look-ahead: building a snapshot fails if any bar closed, or the quote was taken,
after `as_of`. The backtester relies on the same check.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Sequence

from core import indicators as ind
from core.clock import to_kst
from core.types import Account, Bar, Position, Quote, Snapshot

HUNDRED = Decimal(100)
VOL_DAYS = 20


class LookAheadError(Exception):
    pass


def _realized_vol_pct(bars: Sequence[Bar], n: int = VOL_DAYS) -> Decimal | None:
    if len(bars) < n + 1:
        return None
    closes = [b.close for b in bars[-(n + 1):]]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    mean = sum(rets, Decimal(0)) / n
    var = sum(((r - mean) ** 2 for r in rets), Decimal(0)) / n
    return var.sqrt() * HUNDRED


def build_snapshot(symbol: str, as_of: datetime, quote: Quote, bars: Sequence[Bar],
                   account: Account) -> Snapshot:
    as_of = to_kst(as_of)
    if quote.symbol != symbol or any(b.symbol != symbol for b in bars):
        raise ValueError("quote/bars symbol mismatch")
    if to_kst(quote.time) > as_of:
        raise LookAheadError(f"quote time {quote.time} is after as_of {as_of}")
    late = [b for b in bars if to_kst(b.close_time) > as_of]
    if late:
        raise LookAheadError(f"{len(late)} bar(s) close after as_of {as_of}")

    bars = sorted(bars, key=lambda b: b.close_time)
    before_today = [b for b in bars if b.day < as_of.date()]
    prev = before_today[-1] if before_today else None

    mid = (quote.bid + quote.ask) / 2
    sizes = quote.bid_size + quote.ask_size
    pos: Position | None = account.positions.get(symbol)
    peak, start = account.peak_equity, account.day_start_equity

    return Snapshot(
        symbol=symbol,
        as_of=as_of,
        last=quote.last,
        mid=mid,
        spread_bps=(quote.ask - quote.bid) / mid * 10000 if mid > 0 else Decimal(0),
        imbalance=Decimal(quote.bid_size - quote.ask_size) / sizes if sizes else Decimal(0),
        day_open=quote.day_open,
        day_high=quote.day_high,
        day_low=quote.day_low,
        prev_high=prev.high if prev else None,
        prev_low=prev.low if prev else None,
        prev_close=prev.close if prev else None,
        trend=ind.trend_class(bars),
        adr_pct=ind.adr_pct(bars),
        avg_traded_value=ind.avg_traded_value(bars),
        realized_vol_pct=_realized_vol_pct(bars),
        position_qty=pos.qty if pos else 0,
        position_avg_price=pos.avg_price if pos else None,
        equity=account.equity,
        drawdown_pct=(peak - account.equity) / peak * HUNDRED if peak > 0 else Decimal(0),
        daily_pnl_pct=(account.equity - start) / start * HUNDRED if start > 0 else Decimal(0),
        ask=quote.ask,
    )


def _plain(v):
    if isinstance(v, Decimal):
        return format(round(v, 4).normalize(), "f")
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def snapshot_json(s: Snapshot) -> str:
    """Compact JSON (no spaces, Decimals rounded to 4 places)."""
    return json.dumps({k: _plain(v) for k, v in asdict(s).items()},
                      ensure_ascii=False, separators=(",", ":"))


class EquityTracker:
    """Persists peak equity and today's starting equity, so a restart does not
    forget a drawdown or reset today's loss limit. A corrupt file fails closed."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.day: date | None = None
        self.day_start: Decimal | None = None
        self.peak: Decimal | None = None
        self.last: Decimal | None = None
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.day = date.fromisoformat(d["day"])
                self.day_start, self.peak, self.last = (Decimal(d[k]) for k in ("day_start", "peak", "last"))
            except (ValueError, KeyError, TypeError, InvalidOperation) as e:
                raise RuntimeError(f"equity state file unreadable: {self.path}: {e}") from None

    def start_day(self, day: date, equity: Decimal) -> None:
        if day == self.day:
            return  # restart during the day: keep the first starting equity
        self.day, self.day_start = day, equity
        self._see(equity)

    def update(self, equity: Decimal) -> None:
        self._see(equity)

    def reset_peak(self) -> None:
        """User action after a drawdown halt: the current equity becomes the new peak."""
        if self.last is None:
            raise RuntimeError("no equity seen yet")
        self.peak = self.last
        self._save()

    def account(self, equity: Decimal, cash: Decimal, positions: dict[str, Position]) -> Account:
        if self.day_start is None or self.peak is None:
            raise RuntimeError("start_day() must be called before trading")
        self.update(equity)
        return Account(equity=equity, cash=cash, peak_equity=self.peak,
                       day_start_equity=self.day_start, positions=dict(positions))

    def _see(self, equity: Decimal) -> None:
        self.last = equity
        self.peak = equity if self.peak is None else max(self.peak, equity)
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": self.day.isoformat() if self.day else None,
                                   "day_start": str(self.day_start), "peak": str(self.peak),
                                   "last": str(self.last)}), encoding="utf-8")
        os.replace(tmp, self.path)
