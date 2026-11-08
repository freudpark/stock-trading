import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from core.clock import KST
from core.types import Bar, TrendClass
from engine.state import LookAheadError
from universe.screener import breadth, save, screen

END = date(2026, 11, 4)
AS_OF = datetime(2026, 11, 5, 8, 0, tzinfo=KST)


def make_bars(symbol, closes, range_pct=5, volume=20_000_000, end=END):
    """Daily bars ending on `end`; high/low spread around the close by range_pct."""
    half = D(range_pct) / 200
    out = []
    for i, c in enumerate(closes):
        day = end - timedelta(days=len(closes) - 1 - i)
        c = D(str(c))
        out.append(Bar(symbol, day, c, c * (1 + half), c * (1 - half), c, volume,
                       datetime(day.year, day.month, day.day, 15, 30, tzinfo=KST)))
    return out


RISING = [100 + i for i in range(60)]
FALLING = [160 - i for i in range(60)]
FLAT = [100] * 60
TURNING = [100] * 55 + [105, 110, 116, 122, 128]  # becomes Lead in the last 5 days


class ScreenTest(unittest.TestCase):
    def test_filters_and_ranking(self):
        universe = {
            "LEAD1": make_bars("LEAD1", RISING),
            "LEAD2": make_bars("LEAD2", [100 + 2 * i for i in range(60)]),   # higher 1-month return
            "MED": make_bars("MED", FLAT),
            "LAG": make_bars("LAG", FALLING),
            "CALM": make_bars("CALM", RISING, range_pct=2),                  # ADR too low
            "THIN": make_bars("THIN", RISING, volume=1_000_000),            # traded value too low
        }
        r = screen(universe, AS_OF)
        self.assertEqual([c.symbol for c in r.candidates], ["LEAD2", "LEAD1", "MED"])
        rows = {x.symbol: x for x in r.rows}
        self.assertEqual(rows["LAG"].trend, TrendClass.LAG)
        self.assertFalse(rows["LAG"].passed)
        self.assertTrue(any("ADR" in x for x in rows["CALM"].reasons))
        self.assertTrue(any("traded value" in x for x in rows["THIN"].reasons))

    def test_short_history_excluded(self):
        r = screen({"NEW": make_bars("NEW", RISING[:30])}, AS_OF)
        self.assertEqual(r.candidates, [])
        self.assertTrue(any("history" in x for x in r.rows[0].reasons))

    def test_look_ahead(self):
        bars = make_bars("X", RISING, end=date(2026, 11, 5))  # closes 15:30 today, after 08:00
        with self.assertRaises(LookAheadError):
            screen({"X": bars}, AS_OF)


class BreadthTest(unittest.TestCase):
    def test_share_in_lead(self):
        u = {"A": make_bars("A", RISING), "B": make_bars("B", RISING),
             "C": make_bars("C", FLAT), "D": make_bars("D", FALLING)}
        self.assertEqual(breadth(u), D(50))

    def test_five_days_ago(self):
        u = {"A": make_bars("A", TURNING), "B": make_bars("B", FLAT)}
        self.assertEqual(breadth(u), D(50))
        self.assertEqual(breadth(u, days_ago=5), D(0))

    def test_unknown_when_no_history(self):
        self.assertIsNone(breadth({"A": make_bars("A", RISING[:10])}))

    def test_screen_reports_both(self):
        u = {"A": make_bars("A", TURNING), "B": make_bars("B", FLAT)}
        r = screen(u, AS_OF)
        self.assertEqual((r.breadth_now, r.breadth_5d_ago), (D(50), D(0)))


class ClusterTest(unittest.TestCase):
    def test_sector_cluster_flagged(self):
        u = {"S1": make_bars("S1", TURNING), "S2": make_bars("S2", TURNING),
             "S3": make_bars("S3", TURNING), "B1": make_bars("B1", RISING)}
        sectors = {"S1": "반도체", "S2": "반도체", "S3": "조선", "B1": "조선"}
        r = screen(u, AS_OF, sectors=sectors)
        # 반도체: two stocks turned Lead this week; 조선: only one turned (B1 was already Lead)
        self.assertEqual(r.clusters, {"반도체": ["S1", "S2"]})


class SaveTest(unittest.TestCase):
    def test_writes_dated_json(self):
        r = screen({"A": make_bars("A", RISING)}, AS_OF)
        with tempfile.TemporaryDirectory() as d:
            p = save(r, Path(d))
            self.assertEqual(p.name, "2026-11-05.json")
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["candidates"], ["A"])
            self.assertEqual(data["rows"][0]["trend"], "Lead")


if __name__ == "__main__":
    unittest.main()
