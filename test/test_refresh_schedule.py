"""refresh_schedule: fixed clock slots (pure maths)."""
from datetime import datetime, timedelta, timezone

from support import TestCase

import refresh_schedule as rs

IST = {"every_hours": 4, "first_slot": (0, 0), "timezone": "Asia/Kolkata", "range_hours": 24, "count": 3000,
       "retries": 3, "retry_gap_minutes": 10, "catchup_grace_minutes": 15}


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def ist(*a):
    return datetime(*a, tzinfo=timezone(timedelta(hours=5, minutes=30)))


class SlotTest(TestCase):
    def test_slots_are_every_four_hours_in_india_time(self):
        for hour in (0, 4, 8, 12, 16, 20):
            self.assertEqual(rs.last_slot(IST, ist(2026, 11, 16, hour, 0)), ist(2026, 11, 16, hour, 0))     # a slot counts as its own last slot
        self.assertEqual(rs.last_slot(IST, ist(2026, 11, 16, 7, 59)), ist(2026, 11, 16, 4, 0))
        self.assertEqual(rs.next_slot(IST, ist(2026, 11, 16, 7, 59)), ist(2026, 11, 16, 8, 0))
        self.assertEqual(rs.next_slot(IST, ist(2026, 11, 16, 8, 0)), ist(2026, 11, 16, 12, 0))

    def test_the_day_rolls_over(self):
        self.assertEqual(rs.last_slot(IST, ist(2026, 11, 16, 0, 1)), ist(2026, 11, 16, 0, 0))
        self.assertEqual(rs.next_slot(IST, ist(2026, 11, 16, 23, 59)), ist(2026, 11, 17, 0, 0))
        self.assertEqual(rs.last_slot(IST, ist(2026, 11, 16, 23, 59)), ist(2026, 11, 16, 20, 0))

    def test_input_in_any_zone_gives_the_same_slot(self):
        self.assertEqual(rs.last_slot(IST, utc(2026, 11, 16, 14, 30)), ist(2026, 11, 16, 20, 0))          # 14:30 UTC is 20:00 IST
        self.assertEqual(rs.last_slot(IST, utc(2026, 11, 16, 14, 29)), ist(2026, 11, 16, 16, 0))

    def test_another_interval_and_first_slot(self):
        sch = dict(IST, every_hours=6, first_slot=(1, 30))
        self.assertEqual(rs.last_slot(sch, ist(2026, 11, 16, 1, 29)), ist(2026, 11, 15, 19, 30))
        self.assertEqual(rs.last_slot(sch, ist(2026, 11, 16, 1, 30)), ist(2026, 11, 16, 1, 30))
        self.assertEqual(rs.next_slot(sch, ist(2026, 11, 16, 13, 0)), ist(2026, 11, 16, 13, 30))

    def test_what_the_page_gets(self):
        pub = rs.public_schedule(IST, ist(2026, 11, 16, 22, 10))
        self.assertEqual(pub, {"every_minutes": 240, "anchor": "2026-11-16T14:30:00Z", "range_hours": 24, "count": 3000, "grace_minutes": 15})
