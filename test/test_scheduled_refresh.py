"""scheduled_refresh: the per-slot decision rules and the loop that starts the scheduled refreshes."""
import contextlib
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from support import TestCase

import refresh_runs
import refresh_schedule
import scheduled_refresh as sr
from test_refresh_schedule import IST

SLOT = datetime(2026, 11, 16, 8, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)      # 08:00 IST
M = lambda n: timedelta(minutes=n)


def run(created, conclusion="success", status="completed", kind="scheduled", took=2):
    return {"kind": kind, "status": status, "conclusion": conclusion, "created": created, "updated": created + M(took)}


class DecideTest(TestCase):
    def decide(self, minutes_after_slot, runs):
        return sr.decide(SLOT + M(minutes_after_slot), runs, IST)[0]

    def test_a_slot_with_no_run_triggers(self):
        self.assertEqual(self.decide(0, []), "trigger")
        self.assertEqual(self.decide(150, []), "trigger")            # catch-up, however late
        self.assertEqual(self.decide(1, [run(SLOT - M(240))]), "trigger")      # the previous slot's run does not count

    def test_a_successful_scheduled_run_since_the_slot_means_done(self):
        self.assertEqual(self.decide(30, [run(SLOT + M(1))]), "done")

    def test_adhoc_runs_never_satisfy_a_slot(self):
        self.assertEqual(self.decide(30, [run(SLOT + M(1), kind="adhoc")]), "trigger")

    def test_a_running_scheduled_run_means_wait(self):
        self.assertEqual(self.decide(2, [run(SLOT + M(1), conclusion=None, status="in_progress")]), "wait")
        self.assertEqual(self.decide(2, [run(SLOT + M(1), conclusion=None, status="queued")]), "wait")

    def test_a_failed_run_is_retried_after_the_gap(self):
        failed = run(SLOT + M(1), "failure", took=2)                # finished at +3 min; the retry gap is 10 min
        self.assertEqual(self.decide(8, [failed]), "wait")
        self.assertEqual(self.decide(14, [failed]), "trigger")

    def test_retries_are_limited_then_it_gives_up_for_the_slot(self):
        fails = [run(SLOT + M(1 + 15 * i), "failure") for i in range(4)]       # 1 try + 3 retries, all failed
        self.assertEqual(self.decide(80, fails), "give_up")
        self.assertEqual(self.decide(80, fails[:3]), "trigger")                # one retry left
        # but the next slot starts afresh
        self.assertEqual(sr.decide(SLOT + M(241), fails, IST)[0], "trigger")

    def test_cancelled_runs_are_retried_but_capped(self):
        cancelled = [run(SLOT + M(1 + 15 * i), "cancelled") for i in range(7)]
        self.assertEqual(self.decide(120, cancelled[:3]), "trigger")
        self.assertEqual(self.decide(120, cancelled), "trigger")
        self.assertEqual(self.decide(150, cancelled + [run(SLOT + M(120), "cancelled")]), "give_up")     # 8 = 2 x (1 + 3 retries)

    def test_a_success_after_failures_is_done(self):
        self.assertEqual(self.decide(40, [run(SLOT + M(1), "failure"), run(SLOT + M(15))]), "done")


class LoopTest(TestCase):
    """main() against a fake clock and a fake GitHub: what it starts, and when."""

    def run_loop(self, runs_at, start_utc, loop_minutes=60, gh_ok=True):
        t0 = start_utc.timestamp()
        clock = SimpleNamespace(now=t0)
        started = []
        def fake_time():
            return clock.now
        def fake_sleep(s):
            clock.now += s
        def fake_gh(*args):
            if args[:2] == ("workflow", "run"):
                started.append((clock.now - t0, [a for a in args if "=" in a]))
                return SimpleNamespace(returncode=0 if gh_ok else 1, stdout="", stderr="denied")
            raise AssertionError(args)
        fake_clock = SimpleNamespace(time=fake_time, sleep=fake_sleep, strftime=lambda f: "00:00:00")
        def fake_runs(limit=40):
            return runs_at(clock.now, started)
        with contextlib.ExitStack() as st, contextlib.redirect_stdout(io.StringIO()):
            for p in (mock.patch.object(sr, "time", fake_clock), mock.patch.object(sr.refresh_runs, "gh", fake_gh),
                      mock.patch.object(sr.refresh_runs, "list_runs", fake_runs), mock.patch.object(sr, "LOOP_MINUTES", loop_minutes),
                      mock.patch.object(sr, "SCHEDULE", IST)):
                st.enter_context(p)
            sr.main()
        return started

    def test_it_waits_for_the_slot_then_starts_one_scheduled_refresh_with_the_schedule_settings(self):
        # a started run shows up (running) in the list right away and succeeds soon after
        def runs(now, started):
            return [run(SLOT + M(0), conclusion="success")] if started else [run(SLOT - M(240))]
        started = self.run_loop(runs, SLOT - M(10), loop_minutes=60)
        self.assertEqual(len(started), 1)
        at, args = started[0]
        self.assertAlmostEqual(at / 60, 10, delta=1)               # started at the slot, within a poll
        self.assertEqual(args, ["kind=scheduled", "hours=24", "count=3000"])

    def test_a_missed_slot_is_caught_up_once_when_the_job_starts(self):
        started = self.run_loop(lambda now, st: [run(SLOT + M(30))] if st else [], SLOT + M(100), loop_minutes=20)
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], 0)                         # at once, not at the next slot

    def test_nothing_is_started_when_the_slot_is_done(self):
        self.assertEqual(self.run_loop(lambda now, st: [run(SLOT + M(1))], SLOT + M(20), loop_minutes=120), [])

    def test_it_does_not_start_a_second_run_before_the_first_shows_in_the_list(self):
        started = self.run_loop(lambda now, st: [], SLOT + M(1), loop_minutes=1)       # the list never shows our run
        self.assertEqual(len(started), 1)

    def test_a_failed_start_is_retried_on_the_next_poll(self):
        started = self.run_loop(lambda now, st: [], SLOT + M(1), loop_minutes=4, gh_ok=False)
        self.assertGreater(len(started), 1)

    def test_github_being_unreachable_starts_nothing_and_does_not_crash(self):
        self.assertEqual(self.run_loop(lambda now, st: None, SLOT + M(1), loop_minutes=5), [])
