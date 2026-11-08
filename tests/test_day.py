"""End-to-end day on the fake broker (todo 3.3 verify): orders only inside the window,
flat after 15:15, every step journaled, a report written."""
import io
import json
import tempfile
import unittest
from datetime import datetime, time
from decimal import Decimal as D
from pathlib import Path

from broker.fake_broker import FakeBroker
from core.clock import KST, FixedClock, MarketCalendar
from core.config import ROOT, load_settings
from core.types import Quote
from engine.day import DayRunner
from engine.sample import sample_day
from engine.state import EquityTracker
from execution.order import Mode, OrderService
from journal.writer import Journal
from notify import telegram
from risk.guard import ConfigError, Guard, load_limits

LIMITS = load_limits(ROOT / "risk" / "limits.toml")
TIMES = {"screen": time(8, 0), "flatten": time(15, 15), "review": time(16, 0)}


def run(mode=Mode.AUTO, approver=None, kill_switch_at=None):
    tmp = tempfile.TemporaryDirectory()
    out = Path(tmp.name)
    data = sample_day()
    day = data["day"]
    clock = FixedClock(datetime.combine(day, time(8, 0), KST))
    cal = MarketCalendar([])
    broker = FakeBroker(D("10000000"), clock, LIMITS.commission, LIMITS.sell_tax)
    for sym, bars in data["daily_bars"].items():
        broker.set_daily_bars(sym, bars)
        broker.set_prev_close(sym, bars[-1].close)
    journal = Journal(out / "journal", clock)
    guard = Guard(LIMITS, cal, project_root=out)
    svc = OrderService(broker, guard, journal, clock, mode, live=False)
    runner = DayRunner(broker, clock, cal, LIMITS, guard, svc, journal, EquityTracker(out / "equity.json"),
                       out / "reports", out / "screen", TIMES, sectors=data["sectors"], approver=approver)
    quotes = [Quote(s, l, b, a, bs, as_, t) for t, s, l, b, a, bs, as_ in data["ticks"]]
    if kill_switch_at:
        before = [q for q in quotes if q.time.time() < kill_switch_at]
        after = [q for q in quotes if q.time.time() >= kill_switch_at]
        runner.pre_open(day, data["daily_bars"].keys())
        for q in before:
            runner.on_quote(q)
        (out / "STOP").write_text("")
        for q in after:
            runner.on_quote(q)
        runner.flatten(day)
        result = runner.review(day, [])
    else:
        result = runner.run(day, data["daily_bars"].keys(), quotes)
    return tmp, out, broker, journal.read(day), result


class SampleDayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.out, cls.broker, cls.entries, cls.result = run()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def kinds(self):
        return {e["kind"] for e in self.entries}

    def test_screen_excludes_lag(self):
        self.assertEqual(sorted(self.result.candidates), ["FLAT", "LOSE", "WIN"])
        self.assertTrue((self.out / "screen" / "2026-11-05.json").exists())

    def test_trades(self):
        by = {t.symbol: t for t in self.result.trades}
        self.assertEqual(sorted(by), ["LOSE", "WIN"])
        self.assertGreater(by["WIN"].r, 1)
        self.assertTrue(D("-1.3") < by["LOSE"].r < D("-0.9"))   # stopped near −1R
        self.assertTrue(all(t.closed for t in by.values()))

    def test_buys_only_inside_window(self):
        buys = [e for e in self.entries if e["kind"] == "order" and e["side"] == "buy"]
        self.assertTrue(buys)
        for e in buys:
            t = datetime.fromisoformat(e["t"]).time()
            self.assertTrue(time(9, 5) <= t <= time(15, 10), e["t"])

    def test_flat_after_close(self):
        self.assertEqual(self.broker.get_positions(), {})
        self.assertEqual(self.result.open_positions, [])
        self.assertEqual(self.broker.open_orders(), [])

    def test_every_step_journaled(self):
        for k in ("screen", "signal", "guard", "order", "fill", "flatten", "review"):
            self.assertIn(k, self.kinds())

    def test_stop_exit_recorded(self):
        exits = [e for e in self.entries if e["kind"] == "order" and e["side"] == "sell"]
        self.assertTrue(any(e["meta"].get("exit", "").startswith("hard stop") for e in exits))
        self.assertTrue(any(e["meta"].get("exit") == "15:15 flatten" for e in exits))

    def test_report_written(self):
        self.assertTrue(self.result.report_path.exists())
        self.assertIn("WIN", self.result.report)


class ManualModeTest(unittest.TestCase):
    def test_approved_matches_auto(self):
        tmp, _, _, _, r = run(Mode.MANUAL, approver=lambda p: True)
        self.assertEqual(sorted(t.symbol for t in r.trades), ["LOSE", "WIN"])
        tmp.cleanup()

    def test_declined_means_no_trades(self):
        tmp, _, broker, entries, r = run(Mode.MANUAL, approver=lambda p: False)
        self.assertEqual(r.trades, [])
        self.assertIn("declined", {e["kind"] for e in entries})
        tmp.cleanup()


class KillSwitchDayTest(unittest.TestCase):
    def test_stop_file_mid_day(self):
        # STOP at 09:20, before any breakout: no buys at all, nothing left open
        tmp, _, broker, entries, r = run(kill_switch_at=time(9, 20))
        self.assertEqual(r.trades, [])
        self.assertTrue(any("kill switch" in x for e in entries if e["kind"] == "guard" for x in e["reasons"]))
        self.assertEqual(broker.get_positions(), {})
        tmp.cleanup()


class SettingsTest(unittest.TestCase):
    def test_project_settings_load(self):
        s = load_settings()
        self.assertEqual(s.broker, "fake")
        self.assertIn(datetime(2026, 12, 25).date(), s.holidays)

    def test_bad_settings_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.toml"
            p.write_text((ROOT / "config" / "settings.toml").read_text().replace('broker = "fake"', 'broker = "real"'))
            with self.assertRaises(ConfigError):
                load_settings(p)
            p.write_text("broker = ")
            with self.assertRaises(ConfigError):
                load_settings(p)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TelegramTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / "bot.env"
        self.env.write_text("TELEGRAM_BOT_TOKEN=123:SECRET\nTELEGRAM_CHAT_ID=42\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_send_ok_and_chunked(self):
        sent = []

        def opener(req, timeout):
            sent.append(req.data.decode())
            return FakeResponse(json.dumps({"ok": True}).encode())

        ok, status = telegram.send("line\n" * 2000, self.env, opener)
        self.assertEqual((ok, status), (True, "sent"))
        self.assertEqual(len(sent), 3)   # 10,000 characters → 3 messages of ≤ 4,000

    def test_errors_never_leak_token(self):
        def opener(req, timeout):
            raise ConnectionError("network down")

        ok, status = telegram.send("hi", self.env, opener)
        self.assertFalse(ok)
        self.assertNotIn("SECRET", status)

    def test_missing_config(self):
        ok, status = telegram.send("hi", Path(self.tmp.name) / "none.env", lambda *a, **k: None)
        self.assertEqual((ok, status), (False, "config: FileNotFoundError"))


if __name__ == "__main__":
    unittest.main()
