import unittest
from decimal import Decimal as D

from core import ticks


class TickSizeTest(unittest.TestCase):
    def test_bands(self):
        cases = [
            (D("1999"), D("1")), (D("2000"), D("5")),
            (D("4995"), D("5")), (D("5000"), D("10")),
            (D("19990"), D("10")), (D("20000"), D("50")),
            (D("49950"), D("50")), (D("50000"), D("100")),
            (D("199900"), D("100")), (D("200000"), D("500")),
            (D("499500"), D("500")), (D("500000"), D("1000")),
        ]
        for price, tick in cases:
            with self.subTest(price=price):
                self.assertEqual(ticks.tick_size(price), tick)

    def test_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            ticks.tick_size(D("0"))


class RoundTest(unittest.TestCase):
    def test_round_down_and_up(self):
        self.assertEqual(ticks.round_down(D("50170")), D("50100"))
        self.assertEqual(ticks.round_up(D("50170")), D("50200"))
        self.assertEqual(ticks.round_down(D("50100")), D("50100"))
        self.assertEqual(ticks.round_up(D("50100")), D("50100"))

    def test_round_across_band_edge(self):
        # 49,990 is not a valid 50-won tick; down → 49,950, up → 50,000
        self.assertEqual(ticks.round_down(D("49990")), D("49950"))
        self.assertEqual(ticks.round_up(D("49990")), D("50000"))

    def test_is_valid(self):
        self.assertTrue(ticks.is_valid_price(D("50100")))
        self.assertFalse(ticks.is_valid_price(D("50150")))
        self.assertFalse(ticks.is_valid_price(D("-1")))


class PriceLimitTest(unittest.TestCase):
    def test_limits_from_prev_close(self):
        upper, lower = ticks.price_limits(D("10000"))
        self.assertEqual(upper, D("13000"))
        self.assertEqual(lower, D("7000"))

    def test_limits_rounded_inside_band(self):
        # 33,333 × 1.3 = 43,332.9 → round down to 50-won tick = 43,300
        # 33,333 × 0.7 = 23,333.1 → round up to 50-won tick = 23,350
        upper, lower = ticks.price_limits(D("33333"))
        self.assertEqual(upper, D("43300"))
        self.assertEqual(lower, D("23350"))


if __name__ == "__main__":
    unittest.main()
