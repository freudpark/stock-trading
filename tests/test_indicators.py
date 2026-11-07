import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from core import indicators as ind
from core.clock import KST
from core.types import Bar, TrendClass


def bar(i, o, h, l, c, v=1000):
    day = date(2026, 1, 1) + timedelta(days=i)
    return Bar("X", day, D(o), D(h), D(l), D(c), v,
               datetime.combine(day, datetime.min.time(), KST) + timedelta(hours=15, minutes=30))


class EmaTest(unittest.TestCase):
    def test_hand_computed(self):
        # n=3, alpha=0.5, seed = SMA(1,2,3) = 2 → 3 → 4
        self.assertEqual(ind.ema([D(x) for x in (1, 2, 3, 4, 5)], 3), [None, None, D(2), D(3), D(4)])

    def test_alpha(self):
        # n=4, alpha=0.4, seed = SMA(10,20,30,40) = 25; next = 25 + 0.4 × (50 − 25) = 35
        self.assertEqual(ind.ema([D(x) for x in (10, 20, 30, 40, 50)], 4)[-1], D(35))

    def test_short_series(self):
        self.assertEqual(ind.ema([D(1), D(2)], 3), [None, None])

    def test_bad_period(self):
        with self.assertRaises(ValueError):
            ind.ema([D(1)], 0)


class AdrTest(unittest.TestCase):
    def test_hand_computed(self):
        bars = [bar(0, 100, 110, 100, 105), bar(1, 100, 105, 100, 102), bar(2, 100, 102, 100, 101)]
        # mean(1.10, 1.05, 1.02) − 1 = 0.056666… → 5.6667%
        self.assertEqual(ind.adr_pct(bars, 3).quantize(D("0.0001")), D("5.6667"))

    def test_uses_last_n(self):
        bars = [bar(0, 100, 200, 100, 150)] + [bar(i, 100, 101, 100, 100) for i in range(1, 4)]
        self.assertEqual(ind.adr_pct(bars, 3), D("1.0"))

    def test_not_enough_bars(self):
        self.assertIsNone(ind.adr_pct([bar(0, 1, 2, 1, 1)], 3))


class TradedValueTest(unittest.TestCase):
    def test_average(self):
        bars = [bar(0, 1, 1, 1, 100, 10), bar(1, 1, 1, 1, 200, 10), bar(2, 1, 1, 1, 300, 10)]
        self.assertEqual(ind.avg_traded_value(bars, 2), D(2500))  # (2000 + 3000) / 2
        self.assertIsNone(ind.avg_traded_value(bars, 4))


class TrendClassTest(unittest.TestCase):
    def closes(self, values):
        return [bar(i, v, v, v, v) for i, v in enumerate(values)]

    def test_rising_is_lead(self):
        self.assertEqual(ind.trend_class(self.closes(range(100, 160))), TrendClass.LEAD)

    def test_falling_is_lag(self):
        self.assertEqual(ind.trend_class(self.closes(range(160, 100, -1))), TrendClass.LAG)

    def test_flat_is_mediocre(self):
        self.assertEqual(ind.trend_class(self.closes([100] * 60)), TrendClass.MEDIOCRE)

    def test_not_enough_bars(self):
        self.assertIsNone(ind.trend_class(self.closes(range(49))))


class RMultipleTest(unittest.TestCase):
    def test_r(self):
        self.assertEqual(ind.r_multiple(D(30000), D(10000)), D(3))
        self.assertEqual(ind.r_multiple(D(-10000), D(10000)), D(-1))

    def test_zero_risk_rejected(self):
        with self.assertRaises(ValueError):
            ind.r_multiple(D(1), D(0))


if __name__ == "__main__":
    unittest.main()
