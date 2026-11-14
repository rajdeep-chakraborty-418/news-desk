"""scheduler_loop: request parsing, relay polling, starting refreshes through gh, the timing rules."""
import contextlib
import io
import json
from types import SimpleNamespace
from unittest import mock

import support
from support import FakeResp, TestCase

import scheduler_loop as sl


def msg(i, text, t):
    return json.dumps({"id": f"m{i}", "time": t, "event": "message", "topic": "x", "message": text})


class Clock:
    """A fake clock: sleep() just moves time forward."""
    def __init__(self, start=1_800_000_000.0):
        self.now = start

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s

    def strftime(self, fmt):
        return "00:00:00"


class SettingsDrivenTest(TestCase):
    def test_everything_comes_from_the_sample_settings(self):
        self.assertEqual((sl.TOPIC, sl.COOLDOWN_MIN, sl.DEFAULT_HOURS, sl.DEFAULT_COUNT), ("test-topic-abc", 60, 24, 150))
        self.assertEqual(sl.ALLOWED, {6, 24, 72, 168})
        self.assertEqual(sl.ALLOWED_COUNTS, {50, 150, 250})
        self.assertEqual(sl.MIN_GAP_SECONDS, 120)


class ParseTest(TestCase):
    def test_hours(self):
        for text, want in (("hours=6", 6), ("hours=168&count=50", 168), ("hours=12", 24), ("hours=2160", 24),
                           ("count=50", 24), ("", 24), (None, 24), ("hours=abc", 24)):
            self.assertEqual(sl.parse_hours(text), want, text)

    def test_count(self):
        for text, want in (("count=50", 50), ("hours=24&count=250", 250), ("count=300", 150), ("count=1000", 150),
                           ("hours=24", 150), ("", 150), (None, 150)):
            self.assertEqual(sl.parse_count(text), want, text)


class PollTest(TestCase):
    def poll(self, lines=None, exc=None):
        seen = []
        def opener(req, timeout=None):
            seen.append(req.full_url)
            if exc: raise exc
            return FakeResp("\n".join(lines).encode())
        with mock.patch.object(sl, "urlopen", opener), contextlib.redirect_stdout(io.StringIO()):
            return sl.poll_requests(1700000000.9), seen

    def test_url_uses_the_topic_and_since(self):
        _, seen = self.poll([])
        self.assertEqual(seen, ["https://ntfy.sh/test-topic-abc/json?poll=1&since=1700000000"])

    def test_only_valid_requests_are_returned(self):
        lines = [msg(1, "hours=24&count=150", 1), msg(2, "hello", 2), "not json", msg(3, "", 3),
                 json.dumps({"id": "k", "event": "keepalive"}), json.dumps({"event": "message", "message": "hours=24"}),   # no id
                 msg(4, "please hours=72", 4)]
        got, _ = self.poll(lines)
        self.assertEqual([m["id"] for m in got], ["m1", "m4"])

    def test_network_errors_return_nothing(self):
        got, _ = self.poll(exc=OSError("down"))
        self.assertEqual(got, [])


class GhTest(TestCase):
    def test_trigger_passes_hours_and_count_to_the_workflow(self):
        calls = []
        def fake(*args):
            calls.append(args); return SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(sl, "gh", fake), mock.patch.object(sl, "REPO", "me/repo"), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(sl.trigger(168, "test", 250))
            self.assertTrue(sl.trigger(24, "test"))
        self.assertEqual(calls[0], ("workflow", "run", "update.yml", "--repo", "me/repo", "--ref", "main", "-f", "hours=168", "-f", "count=250"))
        self.assertEqual(calls[1][-4:], ("-f", "hours=24", "-f", "count=150"))      # default count from settings

    def test_trigger_reports_failure(self):
        with mock.patch.object(sl, "gh", lambda *a: SimpleNamespace(returncode=1, stdout="", stderr="no auth")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(sl.trigger(24, "x"))

    def test_refresh_state_counts_only_manual_refreshes(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        iso = lambda m: (now - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        run = lambda c, u, concl, status, ev="workflow_dispatch": {"createdAt": iso(c), "updatedAt": iso(u), "conclusion": concl, "status": status, "event": ev}
        runs = [run(2, 2, "", "in_progress"), run(5, 4, "success", "completed", "push"), run(30, 29, "failure", "completed"),
                run(70, 65, "success", "completed")]
        with mock.patch.object(sl, "gh", lambda *a: SimpleNamespace(returncode=0, stdout=json.dumps(runs), stderr="")):
            newest, done, running = sl.refresh_state()
        self.assertAlmostEqual(newest, 2, delta=0.5)
        self.assertAlmostEqual(done, 65, delta=0.5)         # measured from when it finished; the push run is ignored
        self.assertTrue(running)
        with mock.patch.object(sl, "gh", lambda *a: SimpleNamespace(returncode=0, stdout="[]", stderr="")):
            self.assertEqual(sl.refresh_state(), (None, None, False))
        with mock.patch.object(sl, "gh", mock.Mock(side_effect=OSError)):
            self.assertEqual(sl.refresh_state(), (None, None, False))

    def test_cooldown_left(self):
        self.assertEqual(sl.cooldown_left(None), 0)
        self.assertAlmostEqual(sl.cooldown_left(10), 47, delta=0.01)      # 60 min cooldown - 3 min grace - 10
        self.assertEqual(sl.cooldown_left(57), 0)
        self.assertEqual(sl.cooldown_left(600), 0)


class LoopTest(TestCase):
    """Runs main() against a fake clock, a fake relay and a fake gh, and records what was started."""

    def run_loop(self, state=(None, None, False), relay=None, loop_minutes=120, gh_ok=True, poll_seconds=30):
        clock, started = Clock(), []
        relay = relay or (lambda now: [])
        def fake_gh(*args):
            if args[:2] == ("workflow", "run"):
                started.append({a.split("=")[0]: a.split("=")[1] for a in args if a.startswith(("hours=", "count="))} | {"at": clock.now - 1_800_000_000.0})
                return SimpleNamespace(returncode=0 if gh_ok else 1, stdout="", stderr="" if gh_ok else "denied")
            raise AssertionError(args)
        patches = [mock.patch.object(sl, "time", clock), mock.patch.object(sl, "gh", fake_gh),
                   mock.patch.object(sl, "refresh_state", lambda: state), mock.patch.object(sl, "LOOP_MINUTES", loop_minutes),
                   mock.patch.object(sl, "POLL_SECONDS", poll_seconds),
                   mock.patch.object(sl, "poll_requests", lambda since: relay(clock.now))]
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
            for p in patches: stack.enter_context(p)
            sl.main()
        return started

    def req(self, at, text="hours=168&count=250", rid="r1"):
        return lambda now: [{"id": rid, "time": now, "message": text}] if abs(now - 1_800_000_000.0 - at) < 1 else []

    def test_there_is_no_automatic_refresh(self):
        self.assertEqual(self.run_loop(state=(None, None, False), loop_minutes=175), [])       # even with no refresh ever
        self.assertEqual(self.run_loop(state=(500, 500, False), loop_minutes=175), [])

    def test_a_request_starts_a_refresh_with_the_chosen_range_and_count(self):
        started = self.run_loop(state=(500, 500, False), relay=self.req(630), loop_minutes=20)
        self.assertEqual([(s["hours"], s["count"]) for s in started], [("168", "250")])

    def test_the_first_ever_request_is_accepted(self):
        self.assertEqual(len(self.run_loop(state=(None, None, False), relay=self.req(120), loop_minutes=10)), 1)

    def test_a_request_inside_the_cooldown_is_refused(self):
        self.assertEqual(self.run_loop(state=(100, 30, False), relay=self.req(120), loop_minutes=10), [])    # finished 30 min ago, cooldown 60

    def test_a_request_just_after_the_cooldown_is_accepted(self):
        self.assertEqual(len(self.run_loop(state=(100, 58, False), relay=self.req(120), loop_minutes=10)), 1)  # 3 min grace

    def test_a_request_while_a_refresh_is_running_is_refused(self):
        self.assertEqual(self.run_loop(state=(5, None, True), relay=self.req(600), loop_minutes=20), [])

    def test_a_failed_refresh_does_not_start_a_cooldown(self):
        # the last refresh failed (no successful one finished recently): the next request is accepted
        self.assertEqual(len(self.run_loop(state=(100, 900, False), relay=self.req(120), loop_minutes=10)), 1)

    def test_invalid_values_in_a_request_fall_back_to_the_defaults(self):
        started = self.run_loop(state=(500, 500, False), relay=self.req(120, "hours=5&count=7"), loop_minutes=20)
        self.assertEqual([(s["hours"], s["count"]) for s in started], [("24", "150")])

    def test_a_request_right_after_a_refresh_started_is_ignored(self):
        def relay(now):
            t = now - 1_800_000_000.0
            if abs(t - 30) < 1: return [{"id": "a", "time": now, "message": "hours=6"}]      # 90 s after the last start: too soon
            if abs(t - 300) < 1: return [{"id": "b", "time": now, "message": "hours=72"}]
            return []
        started = self.run_loop(state=(1, 500, False), relay=relay, loop_minutes=10)
        self.assertEqual([s["hours"] for s in started], ["72"])                              # "a" ignored, "b" accepted

    def test_several_requests_at_once_start_one_refresh_using_the_latest(self):
        relay = lambda now: [{"id": "x", "time": now, "message": "hours=6"}, {"id": "y", "time": now, "message": "hours=72"}] \
            if abs(now - 1_800_000_000.0 - 120) < 1 else []
        self.assertEqual([s["hours"] for s in self.run_loop(state=(500, 500, False), relay=relay, loop_minutes=10)], ["72"])

    def test_the_same_request_is_never_handled_twice(self):
        relay = lambda now: [{"id": "same", "time": 1_800_000_000.0 + 100, "message": "hours=6"}]
        self.assertEqual(len(self.run_loop(state=(500, 500, False), relay=relay, loop_minutes=20)), 1)

    def test_the_loop_ends_after_loop_minutes(self):
        self.run_loop(loop_minutes=1)          # reaching here without hanging is the point
