import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from broker.fake_broker import FakeBroker
from core.clock import KST, FixedClock, MarketCalendar
from core.types import Account, OrderIntent, Position, Quote, Side
from execution.flatten import flatten_all, stop_exits, stops_from_journal
from execution.order import Mode, OrderService
from journal.writer import Journal
from risk.guard import Guard, MarketContext, load_limits

LIMITS = load_limits(Path(__file__).resolve().parent.parent / "risk" / "limits.toml")
T0 = datetime(2026, 11, 5, 10, 0, tzinfo=KST)
A, B = "005930", "000660"


class Env:
    def __init__(self, mode=Mode.MANUAL, broker_cls=None, **broker_kw):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.clock = FixedClock(T0)
        self.broker = (broker_cls or FakeBroker)(D("10000000"), self.clock, LIMITS.commission,
                                                 LIMITS.sell_tax, **broker_kw)
        for sym, px in ((A, "50000"), (B, "100000")):
            self.set_px(sym, px)
            self.broker.set_prev_close(sym, D(px))
        self.guard = Guard(LIMITS, MarketCalendar([]), project_root=self.root)
        self.journal = Journal(self.root / "journal", self.clock)
        self.svc = OrderService(self.broker, self.guard, self.journal, self.clock, mode, live=False)

    def set_px(self, sym, px, spread=100):
        p = D(px)
        self.broker.set_quote(Quote(sym, p, p - spread, p, 1000, 1000, self.clock.now()))

    def account(self):
        bal = self.broker.get_balance()
        return Account(bal.equity, bal.available_cash, D("10000000"), D("10000000"),
                       self.broker.get_positions())

    def ctx(self, sym):
        return MarketContext(self.broker.get_quote(sym), self.broker.get_status_flags(sym), self.clock.now())

    def submit(self, intent, **kw):
        return self.svc.submit(intent, self.account(), self.ctx(intent.symbol), **kw)

    def kinds(self):
        return [e["kind"] for e in self.journal.read(T0.date())]

    def close(self):
        self.tmp.cleanup()


def buy(sym=A, qty=10, price="50000", stop="49000"):
    return OrderIntent(sym, Side.BUY, qty, D(price), D(stop), reason="breakout")


class Base(unittest.TestCase):
    mode = Mode.MANUAL

    def setUp(self):
        self.e = Env(self.mode)

    def tearDown(self):
        self.e.close()


class ModeTest(unittest.TestCase):
    def test_auto_refused_on_live(self):
        e = Env()
        with self.assertRaises(ValueError):
            OrderService(e.broker, e.guard, e.journal, e.clock, Mode.AUTO, live=True)
        e.close()


class ManualTest(Base):
    def test_buy_waits_for_approval(self):
        s = self.e.submit(buy(), meta={"regime": "추세", "breadth": "50"})
        self.assertEqual(s.status, "pending_approval")
        self.assertEqual(self.e.broker.open_orders() + list(self.e.broker.get_positions().values()), [])
        self.assertEqual([p.approval_id for p in self.e.svc.pending()], [s.approval_id])
        self.assertEqual(self.e.kinds(), ["guard", "approval_requested"])

    def test_approve_places_order(self):
        s = self.e.submit(buy())
        r = self.e.svc.approve(s.approval_id, self.e.account(), self.e.ctx(A))
        self.assertEqual(r.status, "placed")
        self.assertEqual(self.e.broker.get_positions()[A].qty, 10)
        self.assertEqual(self.e.svc.pending(), [])
        order = [e for e in self.e.journal.read(T0.date()) if e["kind"] == "order"][0]
        self.assertEqual(order["entry_index"], "1st")
        self.assertEqual(order["stop_price"], "49000")
        self.assertEqual(order["initial_risk"], "10000")   # (50,000 − 49,000) × 10

    def test_approval_expires(self):
        s = self.e.submit(buy())
        self.e.clock.advance(timedelta(minutes=6))
        r = self.e.svc.approve(s.approval_id, self.e.account(), self.e.ctx(A))
        self.assertEqual(r.status, "expired")
        self.assertEqual(self.e.broker.get_positions(), {})

    def test_approve_rechecks_guard(self):
        s = self.e.submit(buy())
        (self.e.root / "STOP").write_text("")
        r = self.e.svc.approve(s.approval_id, self.e.account(), self.e.ctx(A))
        self.assertEqual(r.status, "rejected_by_guard")
        self.assertEqual(self.e.broker.get_positions(), {})

    def test_reject(self):
        s = self.e.submit(buy())
        self.assertEqual(self.e.svc.reject(s.approval_id, "user said no").status, "declined")
        self.assertEqual(self.e.svc.pending(), [])
        with self.assertRaises(KeyError):
            self.e.svc.approve(s.approval_id, self.e.account(), self.e.ctx(A))

    def test_exit_order_skips_approval(self):
        s = self.e.submit(buy())
        self.e.svc.approve(s.approval_id, self.e.account(), self.e.ctx(A))
        r = self.e.submit(OrderIntent(A, Side.SELL, 10, D("49900")), exit_order=True)
        self.assertEqual(r.status, "placed")
        self.assertEqual(self.e.broker.get_positions(), {})

    def test_exit_flag_on_buy_refused(self):
        with self.assertRaises(ValueError):
            self.e.submit(buy(), exit_order=True)


class GuardRejectTest(Base):
    def test_guard_rejection_is_journaled(self):
        s = self.e.submit(buy(qty=1000))
        self.assertEqual(s.status, "rejected_by_guard")
        self.assertTrue(s.reasons)
        self.assertEqual(self.e.svc.pending(), [])
        entry = self.e.journal.read(T0.date())[0]
        self.assertEqual((entry["kind"], entry["approved"]), ("guard", False))


class AutoTest(Base):
    mode = Mode.AUTO

    def test_places_directly(self):
        self.assertEqual(self.e.submit(buy()).status, "placed")
        self.assertEqual(self.e.broker.get_positions()[A].qty, 10)

    def test_reentry_index(self):
        self.e.submit(buy())
        self.e.submit(OrderIntent(A, Side.SELL, 10, D("49900")), exit_order=True)
        self.e.submit(buy())
        orders = [e for e in self.e.journal.read(T0.date()) if e["kind"] == "order" and e["side"] == "buy"]
        self.assertEqual([o["entry_index"] for o in orders], ["1st", "2nd"])

    def test_unique_order_ids(self):
        a = self.e.submit(buy(qty=1))
        b = self.e.submit(buy(qty=1))
        self.assertNotEqual(a.client_order_id, b.client_order_id)

    def test_broker_reject_reported(self):
        # our records say we hold 10 shares, the broker says none: guard passes, broker rejects
        stale = Account(D("10000000"), D("10000000"), D("10000000"), D("10000000"),
                        {A: Position(A, 10, D("50000"))})
        s = self.e.svc.submit(OrderIntent(A, Side.SELL, 10, D("49900")), stale, self.e.ctx(A), exit_order=True)
        self.assertEqual(s.status, "broker_rejected")
        self.assertIn("held", s.reasons[0])


class FlakyBroker(FakeBroker):
    """place_order raises: either after the order went through, or before it did."""
    def __init__(self, *a, fail_after=False, **kw):
        super().__init__(*a, **kw)
        self.fail_after = fail_after
        self.fail_place = False
        self.fail_lookup = False

    def place_order(self, intent, client_order_id):
        if self.fail_place:
            if self.fail_after:
                super().place_order(intent, client_order_id)
            raise ConnectionError("timeout")
        return super().place_order(intent, client_order_id)

    def get_order(self, client_order_id):
        if self.fail_lookup:
            raise ConnectionError("down")
        return super().get_order(client_order_id)


class UnknownStateTest(unittest.TestCase):
    def make(self, fail_after):
        e = Env(Mode.AUTO, broker_cls=FlakyBroker, fail_after=fail_after)
        e.broker.fail_place = True
        return e

    def test_timeout_but_order_went_through(self):
        e = self.make(fail_after=True)
        s = e.submit(buy())
        self.assertEqual(s.status, "placed")          # recovered by asking the broker
        self.assertEqual(e.broker.get_positions()[A].qty, 10)
        e.close()

    def test_unknown_blocks_symbol_until_resolved(self):
        e = self.make(fail_after=False)
        e.broker.fail_lookup = True
        self.assertEqual(e.submit(buy()).status, "error")
        e.broker.fail_place = False
        blocked = e.submit(buy())                     # lookup still down → symbol blocked
        self.assertEqual(blocked.status, "rejected_unknown_state")
        e.broker.fail_lookup = False                   # broker answers "no such order"
        self.assertEqual(e.submit(buy()).status, "placed")
        e.close()


class FlattenTest(Base):
    mode = Mode.AUTO

    def setUp(self):
        super().setUp()
        self.e.submit(buy(A, 10))
        self.e.submit(buy(B, 5, price="100000", stop="98000"))
        self.e.submit(buy(A, 5, price="49000", stop="48000"))   # resting, not filled
        self.e.clock.set(datetime(2026, 11, 5, 15, 15, tzinfo=KST))

    def test_flatten_sells_everything_and_cancels(self):
        subs = flatten_all(self.e.broker, self.e.svc, self.e.account(), self.e.ctx)
        self.assertEqual(sorted(s.status for s in subs), ["placed", "placed"])
        self.assertEqual(self.e.broker.get_positions(), {})
        self.assertEqual(self.e.broker.open_orders(), [])
        self.assertIn("flatten", self.e.kinds())

    def test_flatten_blocked_by_kill_switch_is_reported(self):
        (self.e.root / "STOP").write_text("")
        subs = flatten_all(self.e.broker, self.e.svc, self.e.account(), self.e.ctx)
        self.assertTrue(all(s.status == "rejected_by_guard" for s in subs))
        self.assertEqual(len(self.e.broker.get_positions()), 2)


class StopTest(Base):
    mode = Mode.AUTO

    def test_stop_triggers_only_below(self):
        self.e.submit(buy(A, 10, stop="49000"))
        self.e.submit(buy(B, 5, price="100000", stop="98000"))
        stops = stops_from_journal(self.e.journal.read(T0.date()))
        self.assertEqual(stops, {A: D("49000"), B: D("98000")})
        self.e.set_px(A, "48900")                          # below stop
        self.e.set_px(B, "99000")                          # above stop
        subs = stop_exits(self.e.broker, self.e.svc, self.e.account(), self.e.ctx, stops)
        self.assertEqual([s.status for s in subs], ["placed"])
        self.assertNotIn(A, self.e.broker.get_positions())
        self.assertIn(B, self.e.broker.get_positions())


class JournalTest(unittest.TestCase):
    def test_round_trip_and_torn_line(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d), FixedClock(T0))
            j.append("x", price=D("1.5"), side=Side.BUY)
            with open(j.path_for(T0.date()), "a") as f:
                f.write('{"kind": "y", "broken')
            rows = j.read(T0.date())
            self.assertEqual(rows[0]["price"], "1.5")
            self.assertEqual(rows[0]["side"], "buy")
            self.assertEqual(rows[1]["kind"], "journal_error")


if __name__ == "__main__":
    unittest.main()
