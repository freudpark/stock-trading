import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

from backtest.daily import history_before, run_backtest
from core import ticks
from core.clock import KST
from core.config import ROOT
from core.types import Bar
from risk.guard import load_limits

LIMITS = load_limits(ROOT / "risk" / "limits.toml")
EQ = D("10000000")


def weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(date(2026, 1, 5), 80)   # 70 history days + 10 test days
TEST_DAYS = DAYS[70:]


def bar(sym, d, o, h, l, c, v=1_000_000):
    r = ticks.round_down
    return Bar(sym, d, r(D(o)), r(D(h)), r(D(l)), r(D(c)), v, datetime.combine(d, time(15, 30), KST))


def series(sym, patterns, base=40000, step=0.004):
    """70 rising history days (Lead, ADR ≈ 5%), then one bar per pattern."""
    bars, c = [], D(base)
    for d in DAYS[:70]:
        c = c * D(1 + step)
        bars.append(bar(sym, d, c, c * D("1.025"), c * D("0.975"), c))
    for d, p in zip(TEST_DAYS, patterns):
        o = bars[-1].close
        h, l, cl = {"win": ("1.06", "0.995", "1.05"), "stop": ("1.04", "0.95", "1.03"),
                    "none": ("1.01", "0.99", "1.005"), "fade": ("1.04", "0.95", "0.96")}[p]
        bars.append(bar(sym, d, o, o * D(h), o * D(l), o * D(cl)))
    return bars


def run(universe, **kw):
    kw.setdefault("start", TEST_DAYS[0])
    kw.setdefault("book_point", True)
    return run_backtest(universe, LIMITS, EQ, **kw)


class SingleTradeTest(unittest.TestCase):
    def test_win_exact_prices_and_costs(self):
        u = {"A": series("A", ["win"])}
        r = run(u)
        self.assertEqual(len(r.trades), 1)
        t = r.trades[0]
        b, prev = u["A"][70], u["A"][69]
        target = b.open + (prev.high - prev.low) * D("0.5")
        entry = ticks.round_up(max(target, b.open))
        entry += ticks.tick_size(entry)
        stop = ticks.round_down(entry * D("0.98"))
        exit_px = b.close - ticks.tick_size(b.close)
        self.assertEqual(t.bought, entry * t.qty)
        self.assertEqual(t.sold, exit_px * t.qty)
        self.assertEqual(t.initial_risk, (entry - stop) * t.qty)
        floor = lambda x: x.to_integral_value(rounding="ROUND_FLOOR")
        costs = floor(t.bought * D("0.00015")) + floor(t.sold * D("0.00015")) + floor(t.sold * D("0.002"))
        self.assertEqual(t.costs, costs)
        self.assertLessEqual(t.bought, EQ * D("0.2"))          # 20% weight cap
        self.assertEqual(r.equity_curve[-1][1], EQ + t.pnl)

    def test_pessimistic_stops_whenever_low_touches(self):
        # up day whose low (below the stop) probably came before the entry
        t = run({"A": series("A", ["win"])}, stop_rule="pessimistic").trades[0]
        self.assertEqual(t.closed_at, "stop")
        self.assertTrue(D("-1.4") < t.r < D("-1"))

    def test_path_rule(self):
        # up day: after the entry the lowest price is the close → not stopped
        self.assertEqual(run({"A": series("A", ["win"])}).trades[0].closed_at, "close")
        # down day reaching the stop after the high → stopped
        self.assertEqual(run({"A": series("A", ["fade"])}).trades[0].closed_at, "stop")

    def test_bad_stop_rule(self):
        with self.assertRaises(ValueError):
            run({"A": series("A", ["win"])}, stop_rule="maybe")

    def test_no_breakout_no_trade(self):
        self.assertEqual(run({"A": series("A", ["none"])}).trades, [])


class CapsTest(unittest.TestCase):
    def test_max_five_positions(self):
        u = {f"S{i}": series(f"S{i}", ["win"]) for i in range(7)}
        r = run(u)
        self.assertEqual(len(r.trades), 5)
        self.assertEqual(r.skipped.get("max positions"), 2)

    def test_daily_loss_stops_new_entries(self):
        # the 20% weight cap makes 1R ≈ 0.44% of equity here; after 4 stops (≈1.76%)
        # the 1.5% "near limit" (75% of the 2% daily limit) blocks the 5th
        u = {f"S{i}": series(f"S{i}", ["fade"]) for i in range(5)}
        r = run(u)
        self.assertEqual(len(r.trades), 4)
        self.assertEqual(r.skipped.get("risk state not 안전 (daily loss)"), 1)

    def test_drawdown_near_limit_trades_at_reduced_risk(self):
        # an account 11.25% below its peak (75% of the 15% halt) keeps trading at 0.2% risk (about half the normal size)
        normal = run({"A": series("A", ["fade"])}).trades[0]
        peak = (EQ / (1 - D("0.1125"))).quantize(D(1)) + 1
        reduced = run({"A": series("A", ["fade"])}, start_peak=peak).trades[0]
        self.assertLessEqual(reduced.initial_risk, EQ * D("0.002"))
        self.assertLess(reduced.qty, normal.qty)

    def test_research_mode_ignores_drawdown_stops(self):
        peak = (EQ / (1 - D("0.2"))).quantize(D(1))
        r = run({"A": series("A", ["win"])}, start_peak=peak, drawdown_stops=False)
        self.assertEqual(len(r.trades), 1)

    def test_drawdown_halt(self):
        peak = (EQ / (1 - D("0.15"))).quantize(D(1)) + 1
        r = run({"A": series("A", ["win"])}, start_peak=peak)
        self.assertEqual(r.halted_on, TEST_DAYS[0])
        self.assertEqual(r.trades, [])


class NoLookAheadTest(unittest.TestCase):
    def test_history_before(self):
        bars = series("A", ["win"])
        h = history_before(bars, TEST_DAYS[0])
        self.assertTrue(all(b.day < TEST_DAYS[0] for b in h))

    def test_future_changes_do_not_change_the_past(self):
        base = {s: series(s, ["win", "fade", "none", "win", "win"]) for s in ("A", "B")}
        changed = {s: series(s, ["win", "fade", "none", "fade", "fade"]) for s in ("A", "B")}
        cut = TEST_DAYS[2].isoformat()
        a = [(t.symbol, t.opened, t.pnl) for t in run(base).trades if t.opened[:10] <= cut]
        b = [(t.symbol, t.opened, t.pnl) for t in run(changed).trades if t.opened[:10] <= cut]
        self.assertTrue(a)
        self.assertEqual(a, b)


class VariantTest(unittest.TestCase):
    def test_book_point_matters_only_for_mediocre(self):
        u = {"A": series("A", ["win"])}           # Lead: quality 2 even without the book point
        self.assertEqual(len(run(u, book_point=False).trades), 1)


if __name__ == "__main__":
    unittest.main()
