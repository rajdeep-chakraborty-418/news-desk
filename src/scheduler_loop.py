#!/usr/bin/env python3
"""Refresh scheduler loop, run by the 'Refresh scheduler' workflow.

Every POLL_SECONDS it reads refresh requests that the website's Refresh button posted to a public ntfy.sh topic and, if
the cooldown (refresh.manual_cooldown_minutes in external_config/settings.json) since the last successful refresh has
passed and none is running, starts the "Update news and deploy" workflow through the GitHub CLI. There is no automatic
periodic refresh. After LOOP_MINUTES it exits so the workflow can start a fresh round of itself.

Requests carry only the chosen time range and story count ("hours=168&count=500"); anything else is ignored, both must
be one of the allowed values (a missing or invalid value means the default in settings.json), and at most one refresh is started per MIN_GAP_SECONDS, so spamming the topic does nothing.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import config
import settings

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get("NEWSDESK_CONFIG_DIR") or ROOT / "external_config")
NTFY = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
GH = os.environ.get("GH_BIN", "gh")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
try:
    SETTINGS = settings.load_settings(CONFIG)      # external_config/settings.json
except config.ConfigError as exc:
    raise SystemExit(f"Configuration error: {exc}")
ALLOWED_COUNTS = set(SETTINGS["counts"])
ALLOWED = set(SETTINGS["hours"])
DEFAULT_HOURS = SETTINGS["default_hours"]          # used when a request names no valid range
DEFAULT_COUNT = SETTINGS["default_count"]
TOPIC = SETTINGS["request_topic"]
COOLDOWN_MIN = SETTINGS["cooldown_minutes"]
GRACE_MIN = 3                                      # tolerance between the page's clock and the workflow's
LOOP_MINUTES = float(os.environ.get("LOOP_MINUTES", 175))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 30))
MIN_GAP_SECONDS = float(os.environ.get("MIN_GAP_SECONDS", SETTINGS["min_gap_seconds"]))


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def gh(*args):
    return subprocess.run([GH, *args], capture_output=True, text=True, timeout=120)


def parse_count(text):
    m = re.search(r"count=(\d+)", text or "")
    n = int(m.group(1)) if m else DEFAULT_COUNT
    return n if n in ALLOWED_COUNTS else DEFAULT_COUNT


def parse_hours(text):
    m = re.search(r"hours=(\d+)", text or "")
    hours = int(m.group(1)) if m else DEFAULT_HOURS
    return hours if hours in ALLOWED else DEFAULT_HOURS


def refresh_state():
    """(minutes since the newest refresh run started, minutes since the newest successful refresh finished, is one running);
    None where unknown. Only refreshes started by hand (workflow_dispatch) count: a code push merely redeploys."""
    try:
        r = gh("run", "list", "--repo", REPO, "--workflow", "update.yml", "--limit", "30", "--json", "createdAt,updatedAt,conclusion,status,event")
        runs = [x for x in json.loads(r.stdout) if x.get("event") == "workflow_dispatch"]
    except Exception:
        return None, None, False
    now = datetime.now(timezone.utc)
    age = lambda iso: (now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 60
    newest = age(runs[0]["createdAt"]) if runs else None
    done = next((age(x["updatedAt"]) for x in runs if x.get("conclusion") == "success"), None)
    running = any(x.get("status") in ("queued", "in_progress", "waiting", "pending", "requested") for x in runs)
    return newest, done, running


def cooldown_left(done_age):
    """Minutes until a manual refresh is allowed again (0 = allowed). The cooldown counts from when the last successful
    refresh finished; a few minutes of grace cover the gap between the page's own clock and the workflow's."""
    if done_age is None:
        return 0.0
    return max(0.0, COOLDOWN_MIN - GRACE_MIN - done_age)


def trigger(hours, why, count=None):
    count = count or DEFAULT_COUNT
    r = gh("workflow", "run", "update.yml", "--repo", REPO, "--ref", "main", "-f", f"hours={hours}", "-f", f"count={count}")
    ok = r.returncode == 0
    log(("Started" if ok else "FAILED to start") + f" refresh ({why}, last {hours} h, {count} per section)" + ("" if ok else f": {r.stderr.strip()[:200]}"))
    return ok


def poll_requests(since):
    """Messages posted to the request topic since `since` (unix seconds). Never raises."""
    try:
        req = Request(f"{NTFY}/{TOPIC}/json?poll=1&since={int(since)}", headers={"User-Agent": "rc-news-desk-scheduler"})
        with urlopen(req, timeout=15) as r:
            lines = r.read().decode("utf-8", "ignore").splitlines()
    except Exception as exc:
        log(f"relay poll failed: {type(exc).__name__}")
        return []
    out = []
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("event") == "message" and m.get("id") and re.search(r"hours=\d+", m.get("message") or ""):
            out.append(m)                    # anything that is not a proper request is ignored
    return out


def main():
    start = time.time()
    end = start + LOOP_MINUTES * 60
    newest_age, _, _ = refresh_state()
    # when the last refresh started (stops a second round from repeating a request the first round just handled)
    last_start = time.time() - newest_age * 60 if newest_age is not None else 0.0
    log(f"Loop started: no automatic refresh; refreshes only on request, at most one per {COOLDOWN_MIN} min; "
        f"polling the relay every {POLL_SECONDS:g}s for {LOOP_MINUTES:g} min")
    seen, since = set(), start - 90          # also catch a request made just before this round began
    while time.time() < end:
        new = [m for m in poll_requests(since) if m["id"] not in seen]
        for m in new:
            seen.add(m["id"])
            since = max(since, float(m.get("time", since)))
        if new:
            hours, count = parse_hours(new[-1].get("message")), parse_count(new[-1].get("message"))
            if time.time() - last_start < MIN_GAP_SECONDS:
                log(f"Ignored {len(new)} refresh request(s): a refresh started less than {MIN_GAP_SECONDS / 60:g} min ago")
            else:
                _, done_age, running = refresh_state()
                wait = cooldown_left(done_age)
                if running:
                    log(f"Ignored {len(new)} refresh request(s): a refresh is already running")
                elif wait > 0:
                    log(f"Ignored {len(new)} refresh request(s): the next manual refresh is allowed in {wait:.0f} min")
                elif trigger(hours, f"requested on the website, {len(new)} request(s)", count):
                    last_start = time.time()
        time.sleep(POLL_SECONDS)
    log("Loop finished; the workflow starts the next round")


if __name__ == "__main__":
    main()
