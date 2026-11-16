"""Slot maths for the scheduled refresh. No network, no GitHub: pure functions, so the timing rules are easy to test and to change.

The schedule is a set of fixed clock slots (settings.json "schedule"): every `every_hours` hours starting at `first_slot`
in `timezone`, every day (e.g. 00:00, 04:00, ... 20:00 India time). A slot never moves, whatever else refreshes the site.

  last_slot(schedule, now)  the newest slot at or before `now`  (UTC datetime)
  next_slot(schedule, now)  the first slot after `now`
  public_schedule(...)      what the web page needs to show "next refresh" (it counts slots from one real slot)
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _now(now):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def last_slot(schedule, now=None):
    now = _now(now)
    local = now.astimezone(ZoneInfo(schedule["timezone"]))
    hour, minute = schedule["first_slot"]
    anchor = local.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(timezone.utc)
    every = timedelta(hours=schedule["every_hours"])
    return anchor + ((now - anchor) // every) * every


def next_slot(schedule, now=None):
    return last_slot(schedule, now) + timedelta(hours=schedule["every_hours"])


def public_schedule(schedule, now=None):
    return {"every_minutes": schedule["every_hours"] * 60,
            "anchor": last_slot(schedule, now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "range_hours": schedule["range_hours"], "count": schedule["count"],
            "grace_minutes": schedule["catchup_grace_minutes"]}
