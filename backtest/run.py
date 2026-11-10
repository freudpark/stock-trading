#!/usr/bin/env python3
"""Run the v1 daily-bar backtest on real KRX history (Yahoo daily bars, cached).

  python3 -m backtest.run            fetch (or reuse cache) and print the result table
  python3 -m backtest.run --offline  use the cache only

Writes var/backtest/<today>/summary.json. The stock list is chosen today, so the
result has survivorship bias (optimistic).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from backtest.daily import run_backtest
from core.clock import KST
from core.config import ROOT
from marketdata.yahoo_daily import fetch_daily, parse_chart, yahoo_symbol
from risk.guard import load_limits

# 20 liquid KOSPI200 / KOSDAQ150 names (picked 2026-11-08 → survivorship bias)
UNIVERSE = {
    "005930": ("삼성전자", "KOSPI", "반도체"), "000660": ("SK하이닉스", "KOSPI", "반도체"),
    "373220": ("LG에너지솔루션", "KOSPI", "2차전지"), "006400": ("삼성SDI", "KOSPI", "2차전지"),
    "051910": ("LG화학", "KOSPI", "화학"), "207940": ("삼성바이오로직스", "KOSPI", "바이오"),
    "068270": ("셀트리온", "KOSPI", "바이오"), "005380": ("현대차", "KOSPI", "자동차"),
    "000270": ("기아", "KOSPI", "자동차"), "035420": ("NAVER", "KOSPI", "인터넷"),
    "035720": ("카카오", "KOSPI", "인터넷"), "105560": ("KB금융", "KOSPI", "금융"),
    "055550": ("신한지주", "KOSPI", "금융"), "012450": ("한화에어로스페이스", "KOSPI", "방산"),
    "042660": ("한화오션", "KOSPI", "조선"), "329180": ("HD현대중공업", "KOSPI", "조선"),
    "247540": ("에코프로비엠", "KOSDAQ", "2차전지"), "086520": ("에코프로", "KOSDAQ", "2차전지"),
    "196170": ("알테오젠", "KOSDAQ", "바이오"), "028300": ("HLB", "KOSDAQ", "바이오"),
}
START_EQUITY = Decimal(10_000_000)
WARMUP = 71   # bars needed before the first test day (EMA50 + 1-month return)


def load(offline: bool, now: datetime) -> tuple[dict, list[str]]:
    cache = ROOT / "var" / "cache" / "yahoo"
    bars, problems = {}, []
    for code, (name, market, _) in UNIVERSE.items():
        try:
            if offline:
                f = cache / f"{yahoo_symbol(code, market)}_3y.json"
                b, _ = parse_chart(json.loads(f.read_text(encoding="utf-8")), code, now)
            else:
                b = fetch_daily(code, market, cache, now, pause=1.0)
            if len(b) <= WARMUP:
                problems.append(f"{code} {name}: only {len(b)} bars")
                continue
            bars[code] = b
        except Exception as e:  # one bad symbol should not stop the run
            problems.append(f"{code} {name}: {type(e).__name__}")
    return bars, problems


def fmt(x, nd=2):
    return "—" if x is None else f"{x:.{nd}f}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    now = datetime.now(KST)
    limits = load_limits(ROOT / "risk" / "limits.toml")
    bars, problems = load(a.offline, now)
    if not bars:
        print("no data", problems)
        return 1
    days = sorted({b.day for bs in bars.values() for b in bs})
    start, end = days[WARMUP], days[-1]
    sectors = {c: UNIVERSE[c][2] for c in bars}
    out, rows = {"start": start.isoformat(), "end": end.isoformat(), "symbols": len(bars),
                 "problems": problems, "runs": {}}, []
    for dd_stops in (True, False):
      for stop_rule in ("pessimistic", "path"):
        for book in (False, True):
            r = run_backtest(bars, limits, START_EQUITY, book_point=book, stop_rule=stop_rule,
                             start=start, end=end, sectors=sectors, drawdown_stops=dd_stops)
            s = r.summary
            key = f"{'' if dd_stops else 'research:'}{stop_rule}/{'book' if book else 'lead-only'}"
            out["runs"][key] = {
                "trades": s.count, "expectancy_r": fmt(s.expectancy_r, 3), "hit_rate": fmt(s.hit_rate, 3),
                "max_losing_streak": s.max_losing_streak, "pnl": str(s.pnl),
                "total_return_pct": fmt(r.total_return_pct), "max_drawdown_pct": fmt(r.max_drawdown_pct),
                "halted_on": r.halted_on.isoformat() if r.halted_on else None,
                "per_year": {y: {"trades": v.count, "expectancy_r": fmt(v.expectancy_r, 3), "pnl": str(v.pnl)}
                             for y, v in r.per_year.items()},
                "skipped": r.skipped,
                "exits": {k: sum(1 for t in r.trades if t.closed_at == k) for k in ("stop", "close")},
                "curve": [[d.isoformat(), str(eq)] for d, eq in r.equity_curve],
            }
            rows.append((key, s, r))
    dest = ROOT / "var" / "backtest" / now.date().isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"period {start} – {end}, {len(bars)} symbols, start equity {START_EQUITY:,}")
    if problems:
        print("problems:", "; ".join(problems))
    print(f"{'variant':35} {'trades':>6} {'exp R':>7} {'hit':>6} {'streak':>6} {'return%':>8} {'maxDD%':>7}")
    for key, s, r in rows:
        print(f"{key:35} {s.count:>6} {fmt(s.expectancy_r, 3):>7} {fmt(s.hit_rate, 3):>6} "
              f"{s.max_losing_streak:>6} {fmt(r.total_return_pct):>8} {fmt(r.max_drawdown_pct):>7}"
              + (f"  halted {r.halted_on}" if r.halted_on else ""))
    print(f"saved: {dest / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
