"""One trading day, end to end: screen → intraday signals and orders → hard stops →
15:15 flatten → nightly review. Same code for simulation now and the KIS paper account later.

The caller feeds quotes in time order (from a recorded/sample day or, later, KIS).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

from broker.base import Broker
from core.clock import FixedClock, MarketCalendar
from core.types import Account, OrderIntent, Quote, RiskState, Side
from engine.state import EquityTracker, build_snapshot
from execution.flatten import flatten_all, stop_exits, stops_from_journal
from execution.order import OrderService, Pending
from execution.sizing import buy_quantity
from journal.writer import Journal
from review.nightly import build_trades, render_report, write_report
from risk.guard import Guard, Limits, MarketContext
from strategy.breakout import BreakoutStrategy, market_regime
from universe.screener import save as save_screen, screen

Approver = Callable[[Pending], bool]


@dataclass
class DayResult:
    report_path: Path
    report: str
    candidates: list[str]
    open_positions: list[str]
    trades: list = field(default_factory=list)


class DayRunner:
    def __init__(self, broker: Broker, clock: FixedClock, calendar: MarketCalendar, limits: Limits,
                 guard: Guard, service: OrderService, journal: Journal, tracker: EquityTracker,
                 reports_dir: Path, screen_dir: Path, times: dict[str, time],
                 earnings: dict[str, date] | None = None, sectors: dict[str, str] | None = None,
                 approver: Approver | None = None):
        self.broker, self.clock, self.calendar, self.limits = broker, clock, calendar, limits
        self.guard, self.svc, self.journal, self.tracker = guard, service, journal, tracker
        self.reports_dir, self.screen_dir, self.times = Path(reports_dir), Path(screen_dir), times
        self.earnings, self.sectors, self.approver = earnings or {}, sectors or {}, approver
        self.candidates: list[str] = []
        self.regime = None
        self.breadth = None
        self._seen_fills = 0
        self._day_range: dict[str, tuple[Decimal, Decimal, Decimal]] = {}  # open, high, low

    # ---- helpers ----
    def _at(self, day: date, t: time) -> datetime:
        return datetime.combine(day, t, self.clock.now().tzinfo)

    def account(self) -> Account:
        bal = self.broker.get_balance()
        return self.tracker.account(bal.equity, bal.available_cash, self.broker.get_positions())

    def ctx(self, symbol: str) -> MarketContext:
        return MarketContext(self.broker.get_quote(symbol), self.broker.get_status_flags(symbol),
                             self.clock.now(), next_earnings=self.earnings.get(symbol))

    def _sync_fills(self) -> None:
        fills = self.broker.get_fills()
        for f in fills[self._seen_fills:]:
            self.journal.append("fill", fill=f)
        self._seen_fills = len(fills)

    # ---- phases ----
    def pre_open(self, day: date, watchlist: Iterable[str]) -> None:
        self.clock.set(self._at(day, self.times["screen"]))
        self.tracker.start_day(day, self.broker.get_balance().equity)
        universe = {s: self.broker.get_daily_bars(s) for s in watchlist}
        result = screen(universe, self.clock.now(), self.sectors)
        save_screen(result, self.screen_dir)
        self.candidates = [r.symbol for r in result.candidates]
        self.breadth = result.breadth_now
        self.regime = market_regime(result.breadth_now, result.breadth_5d_ago)
        self.journal.append("screen", candidates=self.candidates, breadth_now=result.breadth_now,
                            breadth_5d_ago=result.breadth_5d_ago, regime=self.regime, clusters=result.clusters)

    def on_quote(self, q: Quote) -> None:
        """Feed one quote. Fills, approvals, stops and entries are handled here."""
        self.clock.set(q.time)
        o, h, l = self._day_range.get(q.symbol, (q.last, q.last, q.last))
        self._day_range[q.symbol] = (o, max(h, q.last), min(l, q.last))
        o, h, l = self._day_range[q.symbol]
        q = Quote(q.symbol, q.last, q.bid, q.ask, q.bid_size, q.ask_size, q.time, o, h, l)
        self.broker.set_quote(q)
        self._sync_fills()
        self.svc.expire_stale()
        self._handle_approvals()
        if q.symbol in self.broker.get_positions():
            stops = stops_from_journal(self.journal.read(self.clock.now().date()))
            mine = {s: v for s, v in stops.items() if s == q.symbol}
            stop_exits(self.broker, self.svc, self.account(), self.ctx, mine)
        if q.time.time() <= self.limits.entry_end and q.symbol in self.candidates:
            self._maybe_enter(q.symbol)
        self._sync_fills()

    def _handle_approvals(self) -> None:
        if self.approver is None:
            return
        for p in self.svc.pending():
            if self.approver(p):
                self.svc.approve(p.approval_id, self.account(), self.ctx(p.intent.symbol))
            else:
                self.svc.reject(p.approval_id, "not approved")

    def _maybe_enter(self, symbol: str) -> None:
        if symbol in self.broker.get_positions():
            return
        if any(o.intent.symbol == symbol for o in self.broker.open_orders()):
            return
        if any(p.intent.symbol == symbol for p in self.svc.pending()):
            return
        acct = self.account()
        snap = build_snapshot(symbol, self.clock.now(), self.broker.get_quote(symbol),
                              self.broker.get_daily_bars(symbol), acct)
        sig = self.strategy.signal(snap, self.regime)
        if sig.direction.value != "롱":
            return
        self.journal.append("signal", symbol=symbol, direction=sig.direction, quality=sig.quality,
                            regime=sig.regime, risk_state=sig.risk_state, should_enter=sig.should_enter,
                            target=sig.target_price, entry=sig.entry_price, stop=sig.stop_price,
                            reasons=sig.reasons)
        if not sig.should_enter:
            return
        qty = buy_quantity(acct.equity, acct.cash, sig.entry_price, sig.stop_price, 0, self.limits,
                           reduced=sig.risk_state is RiskState.REDUCE)
        if qty <= 0:
            self.journal.append("skip", symbol=symbol, reason="size is zero")
            return
        intent = OrderIntent(symbol, Side.BUY, qty, sig.entry_price, sig.stop_price, reason="breakout")
        self.svc.submit(intent, acct, self.ctx(symbol),
                        meta={"quality": sig.quality, "regime": sig.regime.value, "breadth": self.breadth,
                              "risk_state": sig.risk_state.value})

    @property
    def strategy(self) -> BreakoutStrategy:
        if not hasattr(self, "_strategy"):
            self._strategy = BreakoutStrategy(self.limits)
        return self._strategy

    def flatten(self, day: date) -> None:
        self.clock.set(max(self.clock.now(), self._at(day, self.times["flatten"])))
        flatten_all(self.broker, self.svc, self.account(), self.ctx)
        self._sync_fills()

    def review(self, day: date, cumulative_entries: list[dict]) -> DayResult:
        self.clock.set(max(self.clock.now(), self._at(day, self.times["review"])))
        self._sync_fills()
        self.tracker.update(self.broker.get_balance().equity)
        entries = self.journal.read(day)
        left = sorted(self.broker.get_positions())
        text = render_report(day, entries, build_trades(cumulative_entries + entries), left)
        path = write_report(day, text, self.reports_dir)
        self.journal.append("review", report=str(path), open_positions=left)
        return DayResult(path, text, self.candidates, left, build_trades(entries))

    def run(self, day: date, watchlist: Iterable[str], quotes: Iterable[Quote],
            cumulative_entries: list[dict] | None = None) -> DayResult:
        if not self.calendar.is_trading_day(day):
            raise ValueError(f"{day} is not a trading day")
        self.pre_open(day, list(watchlist))
        flatten_at = self._at(day, self.times["flatten"])
        flattened = False
        for q in sorted(quotes, key=lambda x: x.time):
            if not flattened and q.time >= flatten_at:
                self.flatten(day)
                flattened = True
            self.on_quote(q)
        if not flattened:
            self.flatten(day)
        return self.review(day, cumulative_entries or [])
