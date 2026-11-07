import unittest
from datetime import date, datetime, time, timedelta, timezone

from core.clock import KST, FixedClock, MarketCalendar

HOLIDAYS = {date(2026, 12, 25)}


def kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


class CalendarTest(unittest.TestCase):
    def setUp(self):
        self.cal = MarketCalendar(HOLIDAYS)

    def test_weekend_and_holiday_closed(self):
        self.assertFalse(self.cal.is_trading_day(date(2026, 11, 7)))   # Saturday
        self.assertFalse(self.cal.is_trading_day(date(2026, 11, 8)))   # Sunday
        self.assertFalse(self.cal.is_trading_day(date(2026, 12, 25)))  # holiday
        self.assertTrue(self.cal.is_trading_day(date(2026, 11, 5)))    # Thursday

    def test_session(self):
        self.assertFalse(self.cal.is_open(kst(2026, 11, 5, 8, 59)))
        self.assertTrue(self.cal.is_open(kst(2026, 11, 5, 9, 0)))
        self.assertTrue(self.cal.is_open(kst(2026, 11, 5, 15, 29)))
        self.assertFalse(self.cal.is_open(kst(2026, 11, 5, 15, 30)))
        self.assertFalse(self.cal.is_open(kst(2026, 11, 7, 10, 0)))

    def test_converts_other_time_zones(self):
        # 00:30 UTC == 09:30 KST
        utc = datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc)
        self.assertTrue(self.cal.is_open(utc))

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            self.cal.is_open(datetime(2026, 11, 5, 10, 0))

    def test_trading_days_between(self):
        # Fri 11-06 → Thu 11-12: Mon, Tue, Wed, Thu = 4 trading days after start
        self.assertEqual(self.cal.trading_days_between(date(2026, 11, 6), date(2026, 11, 12)), 4)
        # Thu 12-24 → Mon 12-28 skips the 25th holiday and the weekend
        self.assertEqual(self.cal.trading_days_between(date(2026, 12, 24), date(2026, 12, 28)), 1)
        self.assertEqual(self.cal.trading_days_between(date(2026, 11, 6), date(2026, 11, 6)), 0)

    def test_in_window(self):
        start, end = time(9, 5), time(15, 10)
        self.assertFalse(self.cal.in_window(kst(2026, 11, 5, 9, 4), start, end))
        self.assertTrue(self.cal.in_window(kst(2026, 11, 5, 9, 5), start, end))
        self.assertTrue(self.cal.in_window(kst(2026, 11, 5, 15, 10), start, end))
        self.assertFalse(self.cal.in_window(kst(2026, 11, 5, 15, 11), start, end))


class FixedClockTest(unittest.TestCase):
    def test_fixed_and_advance(self):
        clock = FixedClock(kst(2026, 11, 5, 9, 0))
        self.assertEqual(clock.now(), kst(2026, 11, 5, 9, 0))
        clock.advance(timedelta(minutes=5))
        self.assertEqual(clock.now(), kst(2026, 11, 5, 9, 5))


if __name__ == "__main__":
    unittest.main()
