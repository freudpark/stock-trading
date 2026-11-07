import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal as D

from broker.base import Broker
from broker.fake_broker import FakeBroker
from core.clock import KST, FixedClock
from core.types import Bar, OrderIntent, OrderStatus, Quote, Side, StatusFlags

T0 = datetime(2026, 11, 5, 10, 0, tzinfo=KST)
SYM = "005930"


def q(bid, ask, bid_size=1000, ask_size=1000, last=None):
    return Quote(SYM, D(last or ask), D(bid), D(ask), bid_size, ask_size, T0)


def buy(qty=10, price="50000", stop="49000"):
    return OrderIntent(SYM, Side.BUY, qty, D(price), D(stop))


def sell(qty=10, price="50000"):
    return OrderIntent(SYM, Side.SELL, qty, D(price))


class Base(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock(T0)
        # commission 0.015%, sell tax 0.20%
        self.b = FakeBroker(D("10000000"), self.clock, commission=D("0.00015"), sell_tax=D("0.002"))
        self.b.set_quote(q("49900", "50000"))


class ProtocolTest(Base):
    def test_implements_protocol(self):
        self.assertIsInstance(self.b, Broker)


class BuyFillTest(Base):
    def test_marketable_buy_fills_at_ask(self):
        o = self.b.place_order(buy(price="50100"), "c1")
        self.assertEqual(o.status, OrderStatus.FILLED)
        self.assertEqual(o.avg_fill_price, D("50000"))  # better than the limit
        f = self.b.fills()[0]
        self.assertEqual(f.commission, D("75"))  # 500,000 × 0.015%
        self.assertEqual(f.tax, D("0"))
        self.assertEqual(self.b.get_balance().cash, D("10000000") - D("500000") - D("75"))
        p = self.b.get_positions()[SYM]
        self.assertEqual((p.qty, p.avg_price), (10, D("50000")))

    def test_resting_buy_fills_when_ask_drops(self):
        o = self.b.place_order(buy(price="49800"), "c1")
        self.assertEqual(o.status, OrderStatus.OPEN)
        # open buy holds cash
        held = D("49800") * 10 * D("1.00015")
        self.assertEqual(self.b.get_balance().available_cash, D("10000000") - held)
        self.b.set_quote(q("49700", "49800"))
        o = self.b.get_order("c1")
        self.assertEqual((o.status, o.avg_fill_price), (OrderStatus.FILLED, D("49800")))
        self.assertEqual(self.b.get_balance().available_cash, self.b.get_balance().cash)

    def test_partial_fill_by_ask_size(self):
        self.b.set_quote(q("49900", "50000", ask_size=4))
        o = self.b.place_order(buy(qty=10), "c1")
        self.assertEqual((o.status, o.filled_qty), (OrderStatus.OPEN, 4))
        self.b.set_quote(q("49900", "50000", ask_size=100))
        o = self.b.get_order("c1")
        self.assertEqual((o.status, o.filled_qty), (OrderStatus.FILLED, 10))

    def test_average_price_over_two_buys(self):
        self.b.place_order(buy(qty=10, price="50000"), "c1")
        self.b.set_quote(q("51900", "52000"))
        self.b.place_order(buy(qty=10, price="52000"), "c2")
        self.assertEqual(self.b.get_positions()[SYM].avg_price, D("51000"))


class SellTest(Base):
    def setUp(self):
        super().setUp()
        self.b.place_order(buy(qty=10), "c1")

    def test_sell_fills_at_bid_with_tax(self):
        o = self.b.place_order(sell(qty=10, price="49900"), "s1")
        self.assertEqual((o.status, o.avg_fill_price), (OrderStatus.FILLED, D("49900")))
        f = self.b.fills()[-1]
        # 499,000 × 0.015% = 74.85 → 74 (원 미만 절사); tax 499,000 × 0.2% = 998
        self.assertEqual((f.commission, f.tax), (D("74"), D("998")))
        self.assertNotIn(SYM, self.b.get_positions())
        expected = D("10000000") - D("500075") + D("499000") - D("74") - D("998")
        self.assertEqual(self.b.get_balance().cash, expected)

    def test_sell_more_than_held_rejected(self):
        o = self.b.place_order(sell(qty=11), "s1")
        self.assertEqual(o.status, OrderStatus.REJECTED)

    def test_open_sells_count_against_holdings(self):
        self.assertEqual(self.b.place_order(sell(qty=6, price="60000"), "s1").status, OrderStatus.OPEN)
        self.assertEqual(self.b.place_order(sell(qty=5, price="60000"), "s2").status, OrderStatus.REJECTED)


class RejectTest(Base):
    def test_not_enough_cash(self):
        o = self.b.place_order(buy(qty=1000, price="50000"), "c1")
        self.assertEqual(o.status, OrderStatus.REJECTED)
        self.assertIn("cash", o.message)

    def test_halted(self):
        self.b.set_flags(SYM, StatusFlags(halted=True))
        self.assertEqual(self.b.place_order(buy(), "c1").status, OrderStatus.REJECTED)

    def test_no_quote(self):
        o = self.b.place_order(OrderIntent("000660", Side.BUY, 1, D("100000"), D("90000")), "c1")
        self.assertEqual(o.status, OrderStatus.REJECTED)

    def test_bad_quantity_or_tick(self):
        self.assertEqual(self.b.place_order(buy(qty=0), "c1").status, OrderStatus.REJECTED)
        self.assertEqual(self.b.place_order(buy(price="50050"), "c2").status, OrderStatus.REJECTED)


class IdempotencyTest(Base):
    def test_same_client_id_does_not_duplicate(self):
        o1 = self.b.place_order(buy(), "c1")
        o2 = self.b.place_order(buy(), "c1")
        self.assertEqual(o1, o2)
        self.assertEqual(len(self.b.fills()), 1)
        self.assertEqual(self.b.get_positions()[SYM].qty, 10)

    def test_same_id_different_order_rejected(self):
        self.b.place_order(buy(), "c1")
        with self.assertRaises(ValueError):
            self.b.place_order(buy(qty=5), "c1")


class CancelTest(Base):
    def test_cancel_open_order_releases_cash(self):
        self.b.place_order(buy(price="49000", stop="48000"), "c1")
        o = self.b.cancel_order("c1")
        self.assertEqual(o.status, OrderStatus.CANCELLED)
        self.assertEqual(self.b.get_balance().available_cash, D("10000000"))
        self.b.set_quote(q("48000", "48500"))  # would have filled
        self.assertEqual(self.b.get_order("c1").status, OrderStatus.CANCELLED)

    def test_cancel_filled_is_noop(self):
        self.b.place_order(buy(), "c1")
        self.assertEqual(self.b.cancel_order("c1").status, OrderStatus.FILLED)

    def test_cancel_all(self):
        self.b.place_order(buy(price="49000", stop="48000"), "c1")
        self.b.place_order(buy(price="48900", stop="48000"), "c2")
        self.b.cancel_all()
        self.assertEqual(self.b.open_orders(), [])

    def test_unknown_order(self):
        with self.assertRaises(KeyError):
            self.b.cancel_order("nope")


class EquityTest(Base):
    def test_equity_marks_to_last(self):
        self.b.place_order(buy(qty=10), "c1")
        self.b.set_quote(q("54900", "55100", last="55000"))
        bal = self.b.get_balance()
        self.assertEqual(bal.equity, bal.cash + D("550000"))


class DailyBarsTest(Base):
    def test_no_bars_from_the_future(self):
        bars = []
        for i in range(3):
            day = date(2026, 11, 3) + timedelta(days=i)
            ct = datetime(day.year, day.month, day.day, 15, 30, tzinfo=KST)
            bars.append(Bar(SYM, day, D(1), D(2), D(1), D(1), 1, ct))
        self.b.set_daily_bars(SYM, bars)
        # clock is 11-05 10:00: today's bar is not closed yet
        self.assertEqual([b.day for b in self.b.get_daily_bars(SYM)], [date(2026, 11, 3), date(2026, 11, 4)])
        self.clock.set(datetime(2026, 11, 5, 15, 30, tzinfo=KST))
        self.assertEqual(len(self.b.get_daily_bars(SYM)), 3)


class StatusFlagsTest(Base):
    def test_default_limits_from_prev_close(self):
        self.b.set_prev_close(SYM, D("50000"))
        f = self.b.get_status_flags(SYM)
        self.assertEqual((f.upper_limit, f.lower_limit), (D("65000"), D("35000")))
        self.assertFalse(f.vi or f.halted or f.warning)


if __name__ == "__main__":
    unittest.main()
