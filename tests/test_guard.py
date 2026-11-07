"""Guard tests: one pass and one reject case per rule in spec §6, plus fail-closed config."""
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

from core.clock import KST, MarketCalendar
from core.types import Account, OrderIntent, Position, Quote, Side, StatusFlags
from risk.guard import ConfigError, Guard, MarketContext, load_limits

LIMITS_TOML = Path(__file__).resolve().parent.parent / "risk" / "limits.toml"
CAL = MarketCalendar({date(2026, 12, 25)})
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=KST)  # Thursday, inside the entry window


def account(**kw):
    base = dict(equity=D("10000000"), cash=D("10000000"),
                peak_equity=D("10000000"), day_start_equity=D("10000000"), positions={})
    base.update(kw)
    return Account(**base)


def quote(last="50000"):
    p = D(last)
    return Quote("005930", p, p - 100, p, 100, 100, NOW)


def ctx(**kw):
    base = dict(quote=quote(), flags=StatusFlags(upper_limit=D("65000"), lower_limit=D("35000")),
                now=NOW, next_earnings=None, earnings_flagged=False)
    base.update(kw)
    return MarketContext(**base)


# Buy 20 @ 50,000 with stop 49,000: risk 20,000 (0.2%), value 1,000,000 (10%)
BUY = OrderIntent("005930", Side.BUY, 20, D("50000"), stop_price=D("49000"))
SELL = OrderIntent("005930", Side.SELL, 20, D("50000"))
HELD = {"005930": Position("005930", 20, D("49500"))}


class GuardTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.guard = Guard(load_limits(LIMITS_TOML), CAL, project_root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def assertPass(self, intent, acct=None, context=None):
        r = self.guard.check(intent, acct or account(), context or ctx())
        self.assertTrue(r.approved, r.reasons)
        return r

    def assertReject(self, intent, acct=None, context=None, reason=""):
        r = self.guard.check(intent, acct or account(), context or ctx())
        self.assertFalse(r.approved)
        self.assertTrue(any(reason in x for x in r.reasons), r.reasons)
        return r


class BaselineTest(GuardTestBase):
    def test_plain_buy_and_sell_pass(self):
        self.assertPass(BUY)
        self.assertPass(SELL, account(positions=HELD))


class DrawdownTest(GuardTestBase):
    def test_under_limit_passes(self):
        self.assertPass(BUY, account(equity=D("8600000"), cash=D("8600000"),
                                     day_start_equity=D("8600000")))

    def test_at_limit_blocks_buys_not_exits(self):
        a = account(equity=D("8500000"), cash=D("7500000"),
                    day_start_equity=D("8500000"), positions=HELD)
        self.assertReject(BUY, a, reason="drawdown")
        self.assertPass(SELL, a)


class DailyLossTest(GuardTestBase):
    def test_under_limit_passes(self):
        self.assertPass(BUY, account(equity=D("9810000"), cash=D("9810000")))

    def test_at_limit_blocks_buys_not_exits(self):
        a = account(equity=D("9800000"), cash=D("8800000"), positions=HELD)
        self.assertReject(BUY, a, reason="daily loss")
        self.assertPass(SELL, a)


class RiskPerTradeTest(GuardTestBase):
    def test_exactly_one_percent_passes(self):
        # (50,000 − 40,000) × 10 = 100,000 = 1% of 10,000,000
        self.assertPass(replace(BUY, qty=10, stop_price=D("40000")),
                        context=ctx(flags=StatusFlags(upper_limit=D("65000"), lower_limit=D("35000"))))

    def test_over_one_percent_rejected(self):
        self.assertReject(replace(BUY, qty=11, stop_price=D("40000")), reason="risk per trade")

    def test_buy_without_stop_rejected(self):
        self.assertReject(replace(BUY, stop_price=None), reason="stop")

    def test_stop_above_entry_rejected(self):
        self.assertReject(replace(BUY, stop_price=D("50100")), reason="stop")


class WeightTest(GuardTestBase):
    def test_twenty_percent_passes(self):
        # 40 × 50,000 = 2,000,000 = 20%; stop risk 40 × 500 = 20,000
        self.assertPass(replace(BUY, qty=40, stop_price=D("49500")))

    def test_over_twenty_percent_rejected(self):
        self.assertReject(replace(BUY, qty=41, stop_price=D("49500")), reason="weight")

    def test_existing_position_counts(self):
        a = account(cash=D("9000000"), positions={"005930": Position("005930", 30, D("50000"))})
        self.assertReject(replace(BUY, qty=11, stop_price=D("49500")), a, reason="weight")


class MaxPositionsTest(GuardTestBase):
    def _positions(self, n):
        return {f"00000{i}": Position(f"00000{i}", 1, D("1000")) for i in range(n)}

    def test_fifth_position_passes(self):
        self.assertPass(BUY, account(positions=self._positions(4)))

    def test_sixth_position_rejected(self):
        self.assertReject(BUY, account(positions=self._positions(5)), reason="max positions")

    def test_adding_to_held_stock_at_five_passes(self):
        pos = self._positions(4) | HELD
        self.assertPass(BUY, account(positions=pos))


class KillSwitchTest(GuardTestBase):
    def test_kill_switch_blocks_everything(self):
        (self.root / "STOP").write_text("")
        self.assertReject(BUY, reason="kill switch")
        self.assertReject(SELL, account(positions=HELD), reason="kill switch")


class HoursTest(GuardTestBase):
    def at(self, hh, mm, day=5):
        return ctx(now=datetime(2026, 11, day, hh, mm, tzinfo=KST))

    def test_entry_window_edges(self):
        self.assertPass(BUY, context=self.at(9, 5))
        self.assertPass(BUY, context=self.at(15, 10))
        self.assertReject(BUY, context=self.at(9, 4), reason="hours")
        self.assertReject(BUY, context=self.at(15, 11), reason="hours")

    def test_exit_allowed_until_close(self):
        a = account(positions=HELD)
        self.assertPass(SELL, a, self.at(15, 15))
        self.assertReject(SELL, a, self.at(15, 30), reason="hours")

    def test_weekend_and_holiday_rejected(self):
        self.assertReject(BUY, context=self.at(10, 0, day=7), reason="hours")
        hol = ctx(now=datetime(2026, 12, 25, 10, 0, tzinfo=KST))
        self.assertReject(BUY, context=hol, reason="hours")


class MarketBlockTest(GuardTestBase):
    def flags(self, **kw):
        return ctx(flags=StatusFlags(upper_limit=D("65000"), lower_limit=D("35000"), **kw))

    def test_vi_and_halt_block_both_sides(self):
        a = account(positions=HELD)
        for kw, reason in (({"vi": True}, "VI"), ({"halted": True}, "halt")):
            self.assertReject(BUY, a, self.flags(**kw), reason=reason)
            self.assertReject(SELL, a, self.flags(**kw), reason=reason)

    def test_warning_blocks_buy_only(self):
        a = account(positions=HELD)
        self.assertReject(BUY, a, self.flags(warning=True), reason="warning")
        self.assertPass(SELL, a, self.flags(warning=True))

    def test_near_upper_limit(self):
        # last 50,000; upper 51,500 is exactly 3% away → blocked; 51,600 → allowed
        near = ctx(flags=StatusFlags(upper_limit=D("51500"), lower_limit=D("35000")))
        far = ctx(flags=StatusFlags(upper_limit=D("51600"), lower_limit=D("35000")))
        self.assertReject(BUY, context=near, reason="price limit")
        self.assertPass(BUY, context=far)

    def test_near_lower_limit(self):
        near = ctx(flags=StatusFlags(upper_limit=D("65000"), lower_limit=D("48500")))
        self.assertReject(BUY, context=near, reason="price limit")

    def test_unknown_limits_rejected(self):
        self.assertReject(BUY, context=ctx(flags=StatusFlags()), reason="price limit")


class OrderSanityTest(GuardTestBase):
    def test_tick_rounding(self):
        # buy rounds down, sell rounds up: never pay more or sell for less than asked
        r = self.assertPass(replace(BUY, limit_price=D("50050")))
        self.assertEqual(r.intent.limit_price, D("50000"))
        r = self.assertPass(replace(SELL, limit_price=D("49960")), account(positions=HELD))
        self.assertEqual(r.intent.limit_price, D("50000"))

    def test_price_deviation(self):
        self.assertPass(replace(BUY, limit_price=D("51500"), stop_price=D("50500")))
        self.assertReject(replace(BUY, limit_price=D("51600"), stop_price=D("50600")),
                          reason="price deviation")
        self.assertReject(replace(SELL, limit_price=D("48400")), account(positions=HELD),
                          reason="price deviation")

    def test_quantity_positive(self):
        self.assertReject(replace(BUY, qty=0), reason="quantity")
        self.assertReject(replace(BUY, qty=-1), reason="quantity")

    def test_cash(self):
        # 20 × 50,000 = 1,000,000 plus commission
        self.assertPass(BUY, account(cash=D("1000150")))
        self.assertReject(BUY, account(cash=D("1000000")), reason="cash")

    def test_no_short_selling(self):
        self.assertReject(SELL, reason="short")
        self.assertReject(replace(SELL, qty=21), account(positions=HELD), reason="short")


class EarningsTest(GuardTestBase):
    def test_five_trading_days_blocked(self):
        # Thu 11-05 → Thu 11-12 is 5 trading days ahead → blocked
        self.assertReject(BUY, context=ctx(next_earnings=date(2026, 11, 12)), reason="earnings")
        # earnings today → blocked
        self.assertReject(BUY, context=ctx(next_earnings=date(2026, 11, 5)), reason="earnings")

    def test_six_trading_days_passes(self):
        self.assertPass(BUY, context=ctx(next_earnings=date(2026, 11, 13)))

    def test_past_earnings_passes(self):
        self.assertPass(BUY, context=ctx(next_earnings=date(2026, 11, 4)))

    def test_unknown_date(self):
        self.assertPass(BUY, context=ctx(next_earnings=None))
        self.assertReject(BUY, context=ctx(next_earnings=None, earnings_flagged=True), reason="earnings")

    def test_exit_not_blocked(self):
        self.assertPass(SELL, account(positions=HELD), ctx(next_earnings=date(2026, 11, 6)))


class MultipleReasonsTest(GuardTestBase):
    def test_all_failures_reported(self):
        r = self.assertReject(replace(BUY, qty=1000), account(cash=D("100")), reason="cash")
        self.assertGreaterEqual(len(r.reasons), 3)  # cash, weight, risk per trade


class FailClosedTest(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_limits(Path("/nonexistent/limits.toml"))

    def _load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "limits.toml"
            p.write_text(text)
            return load_limits(p)

    def test_bad_toml(self):
        with self.assertRaises(ConfigError):
            self._load("max_drawdown_pct = = 15")

    def test_missing_key(self):
        text = LIMITS_TOML.read_text().replace("max_positions = 5", "")
        with self.assertRaises(ConfigError):
            self._load(text)

    def test_out_of_range_value(self):
        for old, new in (("max_drawdown_pct = 15", "max_drawdown_pct = 0"),
                         ("risk_per_trade_pct = 1", "risk_per_trade_pct = 50"),
                         ('entry_start = "09:05"', 'entry_start = "9시"')):
            with self.subTest(new=new), self.assertRaises(ConfigError):
                self._load(LIMITS_TOML.read_text().replace(old, new))

    def test_internal_error_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            guard = Guard(load_limits(LIMITS_TOML), CAL, project_root=Path(d))
            bad = ctx(quote=None)  # would raise inside the checks
            r = guard.check(BUY, account(), bad)
            self.assertFalse(r.approved)
            self.assertTrue(any("internal" in x for x in r.reasons), r.reasons)


if __name__ == "__main__":
    unittest.main()
