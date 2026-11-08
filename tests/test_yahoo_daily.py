import copy
import io
import json
import tempfile
import unittest
from datetime import date, datetime, time
from decimal import Decimal as D
from pathlib import Path

from core.clock import KST
from marketdata.yahoo_daily import fetch_daily, parse_chart, yahoo_symbol

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "yahoo_005930_sample.json").read_text())


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ParseTest(unittest.TestCase):
    def test_parses_bars(self):
        bars, issues = parse_chart(FIXTURE, "005930")
        self.assertEqual(len(bars), 70)
        self.assertEqual(issues, [])
        b = bars[0]
        self.assertEqual((b.symbol, b.day), ("005930", date(2023, 11, 6)))
        self.assertEqual((b.open, b.high, b.low, b.close, b.volume),
                         (D("69800"), D("70900"), D("69300"), D("70900"), 22228489))
        self.assertEqual(b.close_time, datetime(2023, 11, 6, 15, 30, tzinfo=KST))
        self.assertTrue(all(x.day < y.day for x, y in zip(bars, bars[1:])))

    def test_bad_rows_dropped_and_reported(self):
        d = copy.deepcopy(FIXTURE)
        q = d["chart"]["result"][0]["indicators"]["quote"][0]
        q["close"][3] = None                                # missing value
        q["high"][5] = q["low"][5] - 100                     # high below low
        q["close"][10] = q["close"][9] * 1.5                 # +50% in a day: beyond the ±30% band
        bars, issues = parse_chart(d, "005930")
        self.assertEqual(len(bars), 67)
        self.assertEqual(len(issues), 3)

    def test_unfinished_today_dropped(self):
        last = parse_chart(FIXTURE, "005930")[0][-1].day
        during = datetime.combine(last, time(11, 0), KST)
        bars, _ = parse_chart(FIXTURE, "005930", now=during)
        self.assertEqual(len(bars), 69)

    def test_error_payload(self):
        with self.assertRaises(ValueError):
            parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}}, "999999")


class SymbolTest(unittest.TestCase):
    def test_suffix(self):
        self.assertEqual(yahoo_symbol("005930", "KOSPI"), "005930.KS")
        self.assertEqual(yahoo_symbol("247540", "KOSDAQ"), "247540.KQ")
        with self.assertRaises(ValueError):
            yahoo_symbol("005930", "NYSE")


class FetchCacheTest(unittest.TestCase):
    def test_uses_cache_without_network(self):
        calls = []

        def opener(req, timeout):
            calls.append(req.full_url)
            return FakeResponse(json.dumps(FIXTURE).encode())

        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 11, 8, 10, 0, tzinfo=KST)
            a = fetch_daily("005930", "KOSPI", Path(d), now=now, opener=opener)
            b = fetch_daily("005930", "KOSPI", Path(d), now=now, opener=opener)
            self.assertEqual(len(calls), 1)
            self.assertIn("005930.KS", calls[0])
            self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
