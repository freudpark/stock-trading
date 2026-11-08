#!/usr/bin/env python3
"""stock_bot command line.

  python3 main.py simulate            run the built-in sample day on the fake broker
  python3 main.py simulate --notify   ...and send the report to Telegram
  python3 main.py simulate --out DIR  keep journal/reports/state in DIR (default: a temp folder)
  python3 main.py reset-peak          after a drawdown halt: make current equity the new peak

No real orders: only the fake broker exists until the KIS account is set up.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from broker.fake_broker import FakeBroker
from core.clock import KST, FixedClock, MarketCalendar
from core.config import ROOT, load_settings
from core.types import Quote
from engine.day import DayRunner
from engine.sample import sample_day
from engine.state import EquityTracker
from execution.order import Mode, OrderService
from journal.writer import Journal
from risk.guard import Guard, load_limits


def load_earnings(path: Path) -> dict[str, date]:
    if not path.exists():
        return {}
    return {k: date.fromisoformat(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def simulate(out: Path, notify: bool) -> int:
    s = load_settings()
    if s.broker != "fake":
        print("simulate runs on the fake broker only; set broker = \"fake\" in config/settings.toml")
        return 2
    limits = load_limits(ROOT / "risk" / "limits.toml")
    data = sample_day()
    day = data["day"]
    clock = FixedClock(datetime.combine(day, s.screen_time, KST))
    calendar = MarketCalendar(s.holidays)
    broker = FakeBroker(s.starting_cash, clock, limits.commission, limits.sell_tax)
    for sym, bars in data["daily_bars"].items():
        broker.set_daily_bars(sym, bars)
        broker.set_prev_close(sym, bars[-1].close)
    journal = Journal(out / "journal", clock)
    guard = Guard(limits, calendar, project_root=ROOT)   # the real STOP file still applies
    svc = OrderService(broker, guard, journal, clock, Mode(s.order_mode), live=False)
    runner = DayRunner(broker, clock, calendar, limits, guard, svc, journal, EquityTracker(out / "equity.json"),
                       out / "reports", out / "screen",
                       {"screen": s.screen_time, "flatten": s.flatten_time, "review": s.review_time},
                       earnings=load_earnings(s.earnings_file), sectors=data["sectors"],
                       approver=(lambda p: True) if s.order_mode == "manual" else None)
    quotes = [Quote(sym, last, bid, ask, bs, a_s, t) for t, sym, last, bid, ask, bs, a_s in data["ticks"]]
    result = runner.run(day, data["daily_bars"].keys(), quotes)
    print(result.report)
    print(f"report: {result.report_path}")
    if notify:
        from notify.telegram import send
        ok, status = send("[모의 실행 · 가짜 증권사 · 예시 데이터]\n" + result.report)
        print(f"telegram: {status}")
        if not ok:
            return 1
    return 0 if not result.open_positions else 1


def reset_peak() -> int:
    s = load_settings()
    t = EquityTracker(s.equity_state)
    old = t.peak
    t.reset_peak()
    print(f"peak equity reset: {old} → {t.peak}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="stock_bot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sim = sub.add_parser("simulate", help="run the sample day on the fake broker")
    sim.add_argument("--out", type=Path, help="keep output here (default: temp folder)")
    sim.add_argument("--notify", action="store_true", help="send the report to Telegram")
    sub.add_parser("reset-peak", help="make current equity the new peak after a drawdown halt")
    a = p.parse_args(argv)
    if a.cmd == "reset-peak":
        return reset_peak()
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        return simulate(a.out, a.notify)
    with tempfile.TemporaryDirectory() as d:
        return simulate(Path(d), a.notify)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
