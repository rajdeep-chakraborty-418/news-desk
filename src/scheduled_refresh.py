#!/usr/bin/env python3
"""Scheduled refresh job, run by the 'Scheduled refresh' workflow. Independent of the adhoc (Refresh button) listener.

It keeps time itself: at every slot of the schedule (settings.json "schedule", e.g. every 4 hours from 00:00 India time) it
starts the "Update news and deploy" workflow with the schedule's own time range and story count, and checks that a scheduled
refresh really succeeded for that slot. Adhoc refreshes never count as the scheduled one and never move a slot.

Per slot (decide() holds the rules):  done if a scheduled run since the slot succeeded;  wait while one is running or while
the retry gap has not passed;  retry after a failure (schedule.retries extra attempts);  give up for that slot when they are
used up (the previous headlines stay on the site) and try again at the next slot. A slot missed because this job was not
running is started as soon as the job is back (catch-up), once, for the newest slot only.
After LOOP_MINUTES it exits so the workflow can start the next round of itself; a 30-minute cron restarts a broken chain."""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import config
import refresh_runs
import refresh_schedule
import settings

try:
    SCHEDULE = settings.load_settings(os.environ.get("NEWSDESK_CONFIG_DIR") or None)["schedule"]
except config.ConfigError as exc:
    raise SystemExit(f"Configuration error: {exc}")
LOOP_MINUTES = float(os.environ.get("LOOP_MINUTES", 175))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 30))
IDLE_POLL_SECONDS = float(os.environ.get("IDLE_POLL_SECONDS", 300))     # once a slot is done, look again only this often
NEW_RUN_VISIBLE_SECONDS = 90                                              # a run just started may not be in GitHub's list yet
FAILED = ("failure", "timed_out", "startup_failure")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def decide(now, runs, schedule=None):
    """(action, slot, why): action is 'trigger', 'done', 'wait' or 'give_up' for the newest slot at or before `now`."""
    schedule = schedule or SCHEDULE
    slot = refresh_schedule.last_slot(schedule, now)
    mine = [r for r in runs if r["kind"] == "scheduled" and r["created"] >= slot]
    if any(r["conclusion"] == "success" for r in mine):
        return "done", slot, "a scheduled refresh already succeeded for this slot"
    if any(refresh_runs.is_active(r) for r in mine):
        return "wait", slot, "a scheduled refresh for this slot is running"
    failures = sum(r["conclusion"] in FAILED for r in mine)
    if failures > schedule["retries"] or len(mine) >= 2 * (1 + schedule["retries"]):
        return "give_up", slot, f"{len(mine)} attempts used up for this slot ({failures} failed)"
    if mine:
        gap = timedelta(minutes=schedule["retry_gap_minutes"])
        if now - max(r["updated"] for r in mine) < gap:
            return "wait", slot, f"retry gap of {schedule['retry_gap_minutes']} min has not passed"
    return "trigger", slot, ("retry " + str(len(mine) + 1)) if mine else "slot reached"


def trigger(schedule=None):
    schedule = schedule or SCHEDULE
    r = refresh_runs.gh("workflow", "run", "update.yml", "--repo", refresh_runs.REPO, "--ref", "main", "-f", "kind=scheduled",
                        "-f", f"hours={schedule['range_hours']}", "-f", f"count={schedule['count']}")
    if r.returncode != 0:
        log(f"FAILED to start the scheduled refresh: {r.stderr.strip()[:200]}")
    return r.returncode == 0


def main():
    end = time.time() + LOOP_MINUTES * 60
    log(f"Scheduled refresh: every {SCHEDULE['every_hours']} h from {SCHEDULE['first_slot'][0]:02d}:{SCHEDULE['first_slot'][1]:02d} "
        f"{SCHEDULE['timezone']}, last {SCHEDULE['range_hours']} h, {SCHEDULE['count']} per section; looping {LOOP_MINUTES:g} min")
    started_at, last_logged = 0.0, None
    while time.time() < end:
        now = datetime.fromtimestamp(time.time(), timezone.utc)
        sleep_for = POLL_SECONDS
        runs = refresh_runs.list_runs()
        if runs is None:
            log("Could not read the run list from GitHub; will try again")
        else:
            action, slot, why = decide(now, runs)
            if (action, slot, why) != last_logged:
                log(f"Slot {slot:%Y-%m-%d %H:%M} UTC: {action} ({why})")
                last_logged = (action, slot, why)
            if action == "trigger" and time.time() - started_at >= NEW_RUN_VISIBLE_SECONDS:
                if trigger():
                    started_at = time.time()
                    late = (now - slot).total_seconds() / 60
                    if late > SCHEDULE["catchup_grace_minutes"]:
                        log(f"This slot was started {late:.0f} min late (catch-up)")
            elif action in ("done", "give_up"):
                sleep_for = max(POLL_SECONDS, min(IDLE_POLL_SECONDS, (refresh_schedule.next_slot(SCHEDULE, now) - now).total_seconds()))
        time.sleep(sleep_for)
    log("Loop finished; the workflow starts the next round")


if __name__ == "__main__":
    main()
