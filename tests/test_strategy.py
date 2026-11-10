import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

from core.clock import KST
from core.types import Direction, Regime, RiskState, Snapshot, TrendClass
from risk.guard import load_limits
from strategy.breakout import BreakoutStrategy, market_regime, risk_state
from strategy.schema import Signal

LIMITS = load_limits(Path(__file__).resolve().parent.parent / "risk" / "limits.toml")
AS_OF = datetime(2026, 11, 5, 10, 0, tzinfo=KST)


def snap(**kw):
    # prev range 2,000 → target = 50,000 + 1,000 = 51,000; last 51,200 is a breakout
    base = dict(symbol="005930", as_of=AS_OF, last=D("51200"), mid=D("51150"), spread_bps=D("19.5"),
                imbalance=D("0.2"), day_open=D("50000"), day_high=D("51300"), day_low=D("49900"),
                prev_high=D("51000"), prev_low=D("49000"), prev_close=D("50000"),
                trend=TrendClass.MEDIOCRE, adr_pct=D("4"), avg_traded_value=D("20000000000"),
                realized_vol_pct=D("2"), position_qty=0, position_avg_price=None,
                equity=D("10000000"), drawdown_pct=D("0"), daily_pnl_pct=D("0"))
    base.update(kw)
    return Snapshot(**base)


class SchemaTest(unittest.TestCase):
    def test_quality_range(self):
        with self.assertRaises(ValueError):
            Signal("X", AS_OF, Regime.TREND, Direction.LONG, 4, RiskState.SAFE, ())

    def test_long_needs_prices(self):
        with self.assertRaises(ValueError):
            Signal("X", AS_OF, Regime.TREND, Direction.LONG, 2, RiskState.SAFE, ())

    def test_stop_below_entry(self):
        with self.assertRaises(ValueError):
            Signal("X", AS_OF, Regime.TREND, Direction.LONG, 2, RiskState.SAFE, (),
                   entry_price=D("100"), stop_price=D("100"))


class RegimeTest(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(market_regime(D("50"), D("55")), Regime.TREND)
        self.assertEqual(market_regime(D("40"), D("40")), Regime.TREND)
        self.assertEqual(market_regime(D("39"), D("39")), Regime.RANGE)
        self.assertEqual(market_regime(D("50"), D("60")), Regime.RANGE)   # fell 10 points
        self.assertEqual(market_regime(D("19"), D("19")), Regime.CRISIS)
        self.assertEqual(market_regime(D("45"), D("65")), Regime.CRISIS)  # fell 20 points

    def test_unknown_breadth_is_range(self):
        self.assertEqual(market_regime(None, None), Regime.RANGE)
        self.assertEqual(market_regime(D("50"), None), Regime.TREND)


class RiskStateTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(risk_state(snap(), LIMITS), RiskState.SAFE)
        # 75% of the 2% daily limit = −1.5% → no entry today
        self.assertEqual(risk_state(snap(daily_pnl_pct=D("-1.5")), LIMITS), RiskState.NEAR_LIMIT)
        self.assertEqual(risk_state(snap(daily_pnl_pct=D("-2")), LIMITS), RiskState.NEAR_LIMIT)
        # 75% of the 15% drawdown = 11.25% → 축소 (trade at reduced risk); at 15% → no entry
        self.assertEqual(risk_state(snap(drawdown_pct=D("11.24")), LIMITS), RiskState.SAFE)
        self.assertEqual(risk_state(snap(drawdown_pct=D("11.25")), LIMITS), RiskState.REDUCE)
        self.assertEqual(risk_state(snap(drawdown_pct=D("15")), LIMITS), RiskState.NEAR_LIMIT)
        # a daily-loss block wins over 축소
        self.assertEqual(risk_state(snap(drawdown_pct=D("12"), daily_pnl_pct=D("-1.6")), LIMITS),
                         RiskState.NEAR_LIMIT)


class BreakoutTest(unittest.TestCase):
    def setUp(self):
        self.s = BreakoutStrategy(LIMITS)

    def run_(self, sn, regime=Regime.TREND, avoid=False):
        return self.s.signal(sn, regime, avoid=avoid)

    def test_target_and_prices(self):
        sig = self.run_(snap())
        self.assertEqual(sig.direction, Direction.LONG)
        self.assertEqual(sig.target_price, D("51000"))
        self.assertEqual(sig.entry_price, D("51200"))        # last, on a valid tick
        self.assertEqual(sig.stop_price, D("50100"))         # 51,200 × 0.98 = 50,176 → 50,100
        self.assertTrue(sig.should_enter)

    def test_entry_pays_the_ask(self):
        sig = self.run_(snap(ask=D("51300")))
        self.assertEqual(sig.entry_price, D("51300"))

    def test_no_breakout(self):
        sig = self.run_(snap(last=D("50900")))
        self.assertEqual((sig.direction, sig.quality), (Direction.NEUTRAL, 0))
        self.assertFalse(sig.should_enter)

    def test_quality_points(self):
        # Mediocre, good book → 1 (breakout) + 1 (book) = 2
        self.assertEqual(self.run_(snap()).quality, 2)
        # Mediocre, weak book → 1 → not enough
        weak = self.run_(snap(imbalance=D("-0.1")))
        self.assertEqual(weak.quality, 1)
        self.assertFalse(weak.should_enter)
        wide = self.run_(snap(spread_bps=D("31")))
        self.assertEqual(wide.quality, 1)
        # Lead adds 1, capped at 3
        self.assertEqual(self.run_(snap(trend=TrendClass.LEAD)).quality, 3)
        self.assertEqual(self.run_(snap(trend=TrendClass.LEAD, imbalance=D("-0.1"))).quality, 2)

    def test_lag_never_long(self):
        sig = self.run_(snap(trend=TrendClass.LAG))
        self.assertEqual(sig.direction, Direction.NEUTRAL)
        self.assertTrue(any("Lag" in r for r in sig.reasons))

    def test_crisis_blocks(self):
        sig = self.run_(snap(trend=TrendClass.LEAD), regime=Regime.CRISIS)
        self.assertEqual(sig.regime, Regime.CRISIS)
        self.assertFalse(sig.should_enter)

    def test_volatile_overrides_trend(self):
        # today's range 3,000 / 50,000 = 6% > 2 × ADR 2% → 고변동 (entry still allowed)
        sig = self.run_(snap(adr_pct=D("2"), day_high=D("52000"), day_low=D("49000")))
        self.assertEqual(sig.regime, Regime.VOLATILE)
        self.assertTrue(sig.should_enter)

    def test_volatile_does_not_override_crisis(self):
        sig = self.run_(snap(adr_pct=D("2"), day_high=D("52000"), day_low=D("49000")), regime=Regime.CRISIS)
        self.assertEqual(sig.regime, Regime.CRISIS)

    def test_reduce_still_enters(self):
        sig = self.run_(snap(drawdown_pct=D("12")))
        self.assertEqual(sig.risk_state, RiskState.REDUCE)
        self.assertTrue(sig.should_enter)

    def test_risk_state_blocks(self):
        sig = self.run_(snap(daily_pnl_pct=D("-1.6")))
        self.assertEqual(sig.risk_state, RiskState.NEAR_LIMIT)
        self.assertFalse(sig.should_enter)

    def test_brain_avoid_blocks(self):
        sig = self.run_(snap(), avoid=True)
        self.assertFalse(sig.should_enter)
        self.assertTrue(any("회피" in r for r in sig.reasons))

    def test_already_holding(self):
        sig = self.run_(snap(position_qty=10, position_avg_price=D("51000")))
        self.assertEqual(sig.direction, Direction.NEUTRAL)

    def test_missing_data(self):
        for field in ("day_open", "prev_high", "prev_low"):
            with self.subTest(field=field):
                sig = self.run_(replace(snap(), **{field: None}))
                self.assertEqual((sig.direction, sig.quality), (Direction.NEUTRAL, 0))

    def test_signal_carries_as_of(self):
        self.assertEqual(self.run_(snap()).as_of, AS_OF)


if __name__ == "__main__":
    unittest.main()
