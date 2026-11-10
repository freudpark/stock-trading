import unittest
from decimal import Decimal as D
from pathlib import Path

from execution.sizing import buy_quantity
from risk.guard import load_limits

LIMITS = load_limits(Path(__file__).resolve().parent.parent / "risk" / "limits.toml")


class SizingTest(unittest.TestCase):
    def size(self, equity="10000000", cash="10000000", entry="50000", stop="49000", held=0):
        return buy_quantity(D(equity), D(cash), D(entry), D(stop), held, LIMITS)

    def test_risk_bound(self):
        # 1% of 10,000,000 = 100,000; stop distance 10,000 → 10 shares
        self.assertEqual(self.size(stop="40000"), 10)

    def test_rounds_down(self):
        # 100,000 / 3,000 = 33.3 → 33
        self.assertEqual(self.size(stop="47000"), 33)

    def test_weight_cap(self):
        # risk allows 100 shares (stop distance 1,000), 20% cap = 2,000,000 / 50,000 = 40
        self.assertEqual(self.size(stop="49000"), 40)

    def test_weight_cap_counts_held(self):
        self.assertEqual(self.size(stop="49000", held=30), 10)
        self.assertEqual(self.size(stop="49000", held=45), 0)

    def test_cash_cap(self):
        # 1,000,000 cash / (50,000 × 1.00015) = 19.99 → 19
        self.assertEqual(self.size(cash="1000000", stop="49000"), 19)

    def test_invalid_inputs_give_zero(self):
        self.assertEqual(self.size(stop="50000"), 0)   # stop not below entry
        self.assertEqual(self.size(stop="0"), 0)
        self.assertEqual(self.size(entry="0"), 0)
        self.assertEqual(self.size(equity="0"), 0)

    def test_reduced_risk_uses_reduced_share(self):
        # 0.2% of 10,000,000 = 20,000 / 10,000 → 2 shares (normal: 10)
        self.assertEqual(buy_quantity(D("10000000"), D("10000000"), D("50000"), D("40000"), 0, LIMITS,
                                      reduced=True), 2)

    def test_reduced_risk_halves_size_with_two_percent_stop(self):
        # −2% stop: normal size is set by the 20% weight cap (40 shares); 축소 gives 0.2% / 2% = 10% → 20
        normal = buy_quantity(D("10000000"), D("10000000"), D("50000"), D("49000"), 0, LIMITS)
        reduced = buy_quantity(D("10000000"), D("10000000"), D("50000"), D("49000"), 0, LIMITS, reduced=True)
        self.assertEqual((normal, reduced), (40, 20))

    def test_sized_order_passes_guard_risk_rule(self):
        q = self.size(stop="47000")
        self.assertLessEqual((D("50000") - D("47000")) * q, D("10000000") * LIMITS.risk_per_trade)


if __name__ == "__main__":
    unittest.main()
