import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from core.clock import KST
from core.types import Account, Bar, Position, Quote, TrendClass
from engine.state import EquityTracker, LookAheadError, build_snapshot, snapshot_json

AS_OF = datetime(2026, 11, 5, 10, 0, tzinfo=KST)
SYM = "005930"


def daily_bars(n, end_day=date(2026, 11, 4), start=100):
    """n rising daily bars ending on end_day, each closed at 15:30 KST."""
    bars = []
    for i in range(n):
        day = end_day - timedelta(days=n - 1 - i)
        c = D(start + i)
        bars.append(Bar(SYM, day, c - 1, c + 2, c - 2, c, 1000,
                        datetime(day.year, day.month, day.day, 15, 30, tzinfo=KST)))
    return bars


def quote(**kw):
    base = dict(symbol=SYM, last=D("160"), bid=D("159"), ask=D("161"), bid_size=300, ask_size=100,
                time=AS_OF, day_open=D("158"), day_high=D("162"), day_low=D("157"))
    base.update(kw)
    return Quote(**base)


def account(**kw):
    base = dict(equity=D("9500000"), cash=D("9000000"), peak_equity=D("10000000"),
                day_start_equity=D("9600000"), positions={SYM: Position(SYM, 5, D("150"))})
    base.update(kw)
    return Account(**base)


class SnapshotTest(unittest.TestCase):
    def test_fields(self):
        s = build_snapshot(SYM, AS_OF, quote(), daily_bars(60), account())
        self.assertEqual(s.mid, D("160"))
        self.assertEqual(s.spread_bps, D("125"))          # 2 / 160 × 10,000
        self.assertEqual(s.imbalance, D("0.5"))            # (300 − 100) / 400
        self.assertEqual((s.prev_high, s.prev_low, s.prev_close), (D("161"), D("157"), D("159")))
        self.assertEqual(s.trend, TrendClass.LEAD)
        self.assertIsNotNone(s.adr_pct)
        self.assertIsNotNone(s.realized_vol_pct)
        self.assertEqual((s.position_qty, s.position_avg_price), (5, D("150")))
        self.assertEqual(s.drawdown_pct, D("5"))           # 10.0M → 9.5M
        self.assertEqual(s.daily_pnl_pct.quantize(D("0.01")), D("-1.04"))  # 9.6M → 9.5M

    def test_no_position(self):
        s = build_snapshot(SYM, AS_OF, quote(), daily_bars(60), account(positions={}))
        self.assertEqual((s.position_qty, s.position_avg_price), (0, None))

    def test_short_history_gives_none(self):
        s = build_snapshot(SYM, AS_OF, quote(), daily_bars(5), account())
        self.assertIsNone(s.trend)
        self.assertIsNone(s.adr_pct)
        self.assertEqual(s.prev_close, D("104"))

    def test_todays_closed_bar_is_not_prev(self):
        # as_of after today's close: today's bar is visible but "prev" must stay yesterday
        late = datetime(2026, 11, 5, 16, 0, tzinfo=KST)
        bars = daily_bars(60, end_day=date(2026, 11, 5))
        s = build_snapshot(SYM, late, quote(time=late), bars, account())
        self.assertEqual(s.prev_close, bars[-2].close)

    def test_zero_sizes(self):
        s = build_snapshot(SYM, AS_OF, quote(bid_size=0, ask_size=0), daily_bars(60), account())
        self.assertEqual(s.imbalance, D("0"))


class LookAheadTest(unittest.TestCase):
    def test_future_bar_rejected(self):
        bars = daily_bars(60, end_day=date(2026, 11, 5))  # today's bar closes 15:30, after as_of
        with self.assertRaises(LookAheadError):
            build_snapshot(SYM, AS_OF, quote(), bars, account())

    def test_future_quote_rejected(self):
        with self.assertRaises(LookAheadError):
            build_snapshot(SYM, AS_OF, quote(time=AS_OF + timedelta(seconds=1)), daily_bars(60), account())

    def test_wrong_symbol_rejected(self):
        with self.assertRaises(ValueError):
            build_snapshot("000660", AS_OF, quote(), daily_bars(60), account())


class SerializeTest(unittest.TestCase):
    def test_compact_json(self):
        s = build_snapshot(SYM, AS_OF, quote(), daily_bars(60), account())
        text = snapshot_json(s)
        data = json.loads(text)
        self.assertEqual(data["trend"], "Lead")
        self.assertEqual(data["as_of"], "2026-11-05T10:00:00+09:00")
        # < 400 tokens: ~3 characters per token is a safe upper bound for this JSON
        self.assertLess(len(text), 1200, text)


class EquityTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "equity.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_peak_and_day_start(self):
        t = EquityTracker(self.path)
        t.start_day(date(2026, 11, 5), D("10000000"))
        t.update(D("10500000"))
        t.update(D("10200000"))
        self.assertEqual((t.peak, t.day_start), (D("10500000"), D("10000000")))
        t.start_day(date(2026, 11, 6), D("10200000"))
        self.assertEqual((t.peak, t.day_start), (D("10500000"), D("10200000")))

    def test_start_day_twice_keeps_first(self):
        # a restart in the middle of the day must not reset today's loss count
        t = EquityTracker(self.path)
        t.start_day(date(2026, 11, 5), D("10000000"))
        t.start_day(date(2026, 11, 5), D("9700000"))
        self.assertEqual(t.day_start, D("10000000"))

    def test_survives_restart(self):
        t = EquityTracker(self.path)
        t.start_day(date(2026, 11, 5), D("10000000"))
        t.update(D("11000000"))
        t2 = EquityTracker(self.path)
        self.assertEqual((t2.peak, t2.day_start, t2.day), (D("11000000"), D("10000000"), date(2026, 11, 5)))

    def test_account(self):
        t = EquityTracker(self.path)
        t.start_day(date(2026, 11, 5), D("10000000"))
        a = t.account(D("9900000"), D("9000000"), {})
        self.assertEqual((a.peak_equity, a.day_start_equity, a.equity), (D("10000000"), D("10000000"), D("9900000")))

    def test_account_before_start_day_fails(self):
        with self.assertRaises(RuntimeError):
            EquityTracker(self.path).account(D("1"), D("1"), {})

    def test_corrupt_file_fails_closed(self):
        self.path.write_text("{not json")
        with self.assertRaises(RuntimeError):
            EquityTracker(self.path)

    def test_reset_peak(self):
        t = EquityTracker(self.path)
        t.start_day(date(2026, 11, 5), D("10000000"))
        t.update(D("8000000"))
        t.reset_peak()
        self.assertEqual(t.peak, D("8000000"))


if __name__ == "__main__":
    unittest.main()
