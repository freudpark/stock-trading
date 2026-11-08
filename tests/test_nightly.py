import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from core.clock import KST, FixedClock
from core.types import Fill, Side
from journal.writer import Journal
from review.nightly import build_trades, render_report, summarize, write_report

DAY = date(2026, 11, 5)


def at(hh, mm, day=DAY):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=KST)


class JournalBuilder:
    def __init__(self, root):
        self.clock = FixedClock(at(9, 0))
        self.j = Journal(Path(root), self.clock)
        self.n = 0

    def trade(self, sym, qty, buy_px, sell_px, risk, quality, entry_index="1st", t=(10, 0), day=DAY,
              commission="0", tax="0"):
        self.n += 1
        oid_b, oid_s = f"B{self.n}", f"S{self.n}"
        self.clock.set(at(*t, day=day))
        self.j.append("order", client_order_id=oid_b, symbol=sym, side=Side.BUY, qty=qty, status="filled",
                      entry_index=entry_index, initial_risk=D(risk), stop_price=D(buy_px) - D(risk) / qty,
                      meta={"quality": quality, "regime": "추세"})
        self.j.append("fill", fill=Fill(oid_b, sym, Side.BUY, qty, D(buy_px), D(commission), D(0), self.clock.now()))
        self.clock.advance(timedelta(minutes=30))
        self.j.append("order", client_order_id=oid_s, symbol=sym, side=Side.SELL, qty=qty, status="filled",
                      meta={"exit": "15:15 flatten"})
        self.j.append("fill", fill=Fill(oid_s, sym, Side.SELL, qty, D(sell_px), D(commission), D(tax), self.clock.now()))

    def entries(self, day=DAY):
        return self.j.read(day)


class TradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = JournalBuilder(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pnl_after_costs_and_r(self):
        # buy 10 @ 50,000, sell @ 51,000: gross +10,000, costs 75 + 76 + 1,020 = 1,171
        self.b.trade("A", 10, "50000", "51000", risk="10000", quality=2, commission="75", tax="1020")
        t = build_trades(self.b.entries())[0]
        self.assertEqual(t.pnl, D("10000") - D("75") * 2 - D("1020"))
        self.assertEqual(t.r, t.pnl / D("10000"))
        self.assertEqual((t.entry_index, t.quality, t.closed), ("1st", 2, True))

    def test_partial_fills_one_trade(self):
        j, c = self.b.j, self.b.clock
        j.append("order", client_order_id="B1", symbol="A", side=Side.BUY, qty=10, status="filled",
                 entry_index="1st", initial_risk=D("10000"), meta={"quality": 3})
        j.append("fill", fill=Fill("B1", "A", Side.BUY, 4, D("50000"), D(0), D(0), c.now()))
        j.append("fill", fill=Fill("B1", "A", Side.BUY, 6, D("50100"), D(0), D(0), c.now()))
        j.append("fill", fill=Fill("S1", "A", Side.SELL, 10, D("50500"), D(0), D(0), c.now()))
        trades = build_trades(self.b.entries())
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].qty, 10)
        self.assertEqual(trades[0].pnl, D("50500") * 10 - D("50000") * 4 - D("50100") * 6)

    def test_open_trade_flagged(self):
        j, c = self.b.j, self.b.clock
        j.append("order", client_order_id="B1", symbol="A", side=Side.BUY, qty=10, status="filled",
                 entry_index="1st", initial_risk=D("10000"), meta={})
        j.append("fill", fill=Fill("B1", "A", Side.BUY, 10, D("50000"), D(0), D(0), c.now()))
        t = build_trades(self.b.entries())[0]
        self.assertFalse(t.closed)

    def test_reentry_is_a_separate_trade(self):
        self.b.trade("A", 10, "50000", "50500", "10000", 2, "1st", t=(10, 0))
        self.b.trade("A", 10, "50600", "50100", "10000", 2, "2nd", t=(11, 0))
        trades = build_trades(self.b.entries())
        self.assertEqual([x.entry_index for x in trades], ["1st", "2nd"])


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = JournalBuilder(self.tmp.name)
        # R: +2, −1, −1, +3  (risk 10,000 each)
        self.b.trade("A", 10, "50000", "52000", "10000", 3, "1st", t=(9, 10))
        self.b.trade("B", 10, "50000", "49000", "10000", 2, "1st", t=(9, 20))
        self.b.trade("C", 10, "50000", "49000", "10000", 1, "1st", t=(9, 30))
        self.b.trade("A", 10, "50000", "53000", "10000", 3, "2nd", t=(11, 0))
        self.trades = build_trades(self.b.entries())

    def tearDown(self):
        self.tmp.cleanup()

    def test_metrics(self):
        s = summarize(self.trades)
        self.assertEqual(s.count, 4)
        self.assertEqual(s.hit_rate, D("0.5"))
        self.assertEqual(s.expectancy_r, D("0.75"))      # (2 − 1 − 1 + 3) / 4
        self.assertEqual(s.max_losing_streak, 2)
        self.assertEqual(s.pnl, D("30000"))
        # p = quality / 3: (1−1)², (0.667−0)², (0.333−0)², (1−1)² → (0.4444 + 0.1111) / 4
        self.assertAlmostEqual(float(s.brier), 0.1389, places=3)
        self.assertEqual(s.by_entry["1st"], (3, D("0")))   # count, mean R: (2 − 1 − 1) / 3
        self.assertEqual(s.by_entry["2nd"], (1, D("3")))

    def test_empty(self):
        s = summarize([])
        self.assertEqual((s.count, s.expectancy_r, s.hit_rate, s.brier), (0, None, None, None))

    def test_open_trades_excluded(self):
        self.b.j.append("order", client_order_id="BX", symbol="Z", side=Side.BUY, qty=1, status="filled",
                        entry_index="1st", initial_risk=D("100"), meta={})
        self.b.j.append("fill", fill=Fill("BX", "Z", Side.BUY, 1, D("1000"), D(0), D(0), self.b.clock.now()))
        self.assertEqual(summarize(build_trades(self.b.entries())).count, 4)


class ReportTest(unittest.TestCase):
    def test_report_contents_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            b = JournalBuilder(Path(d) / "journal")
            b.trade("A", 10, "50000", "52000", "10000", 3)
            b.j.append("guard", symbol="B", approved=False, reasons=["hours: market closed"])
            b.j.append("guard", symbol="C", approved=False, reasons=["hours: market closed", "VI in progress"])
            b.j.append("signal", symbol="D", direction="롱", should_enter=False)
            b.j.append("broker_error", client_order_id="X", symbol="E", error="ConnectionError")
            text = render_report(DAY, b.entries(), cumulative=build_trades(b.entries()), open_positions=["F"])
            for needle in ("2026-11-05", "+2.00R", "hours: market closed ×2", "VI in progress ×1",
                           "broker_error", "F", "건너뛴 신호 1"):
                self.assertIn(needle, text)
            p = write_report(DAY, text, Path(d) / "reports")
            self.assertEqual(p.name, "2026-11-05.md")
            self.assertEqual(p.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
