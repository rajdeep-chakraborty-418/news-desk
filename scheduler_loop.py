#!/usr/bin/env python3
"""Refresh scheduler loop, run by the 'Refresh scheduler' workflow.

Every POLL_SECONDS it
  1. reads refresh requests that the website's Refresh button posted to a public ntfy.sh topic, and
  2. checks whether the regular refresh (every refresh_minutes.txt minutes) is due.
Either one starts the "Update news and deploy" workflow through the GitHub CLI.
After LOOP_MINUTES it exits so the workflow can start a fresh round of itself.

Requests carry only the chosen time range ("hours=168"); anything else is ignored, the range must be one of
the allowed values, and at most one refresh is started per MIN_GAP_SECONDS, so spamming the topic does nothing.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
ALLOWED = {6, 12, 24, 72, 168, 720, 2160}
NTFY = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
GH = os.environ.get("GH_BIN", "gh")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOPIC = (ROOT / "refresh_topic.txt").read_text().strip()
INTERVAL_MIN = int(re.sub(r"\D", "", (ROOT / "refresh_minutes.txt").read_text()) or 118)
LOOP_MINUTES = float(os.environ.get("LOOP_MINUTES", 175))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 30))
MIN_GAP_SECONDS = float(os.environ.get("MIN_GAP_SECONDS", 300))


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def gh(*args):
    return subprocess.run([GH, *args], capture_output=True, text=True, timeout=120)


def parse_hours(text):
    m = re.search(r"hours=(\d+)", text or "")
    hours = int(m.group(1)) if m else 24
    return hours if hours in ALLOWED else 24


def run_ages():
    """(minutes since the newest update run started, minutes since the newest successful one); None if unknown."""
    try:
        r = gh("run", "list", "--repo", REPO, "--workflow", "update.yml", "--limit", "20", "--json", "createdAt,conclusion")
        runs = json.loads(r.stdout)
    except Exception:
        return None, None
    now = datetime.now(timezone.utc)
    age = lambda run: (now - datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))).total_seconds() / 60
    newest = age(runs[0]) if runs else None
    ok = next((age(x) for x in runs if x.get("conclusion") == "success"), None)
    return newest, ok


def trigger(hours, why):
    r = gh("workflow", "run", "update.yml", "--repo", REPO, "--ref", "main", "-f", f"hours={hours}")
    ok = r.returncode == 0
    log(("Started" if ok else "FAILED to start") + f" refresh ({why}, last {hours} h)" + ("" if ok else f": {r.stderr.strip()[:200]}"))
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
    newest_age, ok_age = run_ages()
    # when the last refresh started (stops a second round from repeating a request the first round just handled)
    last_start = time.time() - newest_age * 60 if newest_age is not None else 0.0
    next_due = time.time() + (max(0.0, INTERVAL_MIN - ok_age) * 60 if ok_age is not None else 0.0)
    log(f"Loop started: every {INTERVAL_MIN} min, polling the relay every {POLL_SECONDS:g}s for {LOOP_MINUTES:g} min; "
        f"next scheduled refresh in {max(0, next_due - time.time()) / 60:.0f} min")
    seen, since = set(), start - 90          # also catch a request made just before this round began
    while time.time() < end:
        new = [m for m in poll_requests(since) if m["id"] not in seen]
        for m in new:
            seen.add(m["id"])
            since = max(since, float(m.get("time", since)))
        if new:
            hours = parse_hours(new[-1].get("message"))
            if time.time() - last_start < MIN_GAP_SECONDS:
                log(f"Ignored {len(new)} refresh request(s): a refresh started less than {MIN_GAP_SECONDS / 60:g} min ago")
            elif trigger(hours, f"requested on the website, {len(new)} request(s)"):
                last_start = time.time()
                next_due = last_start + INTERVAL_MIN * 60
        elif time.time() >= next_due:
            if trigger(24, "scheduled"):
                last_start = time.time()
                next_due = last_start + INTERVAL_MIN * 60
            else:
                next_due = time.time() + 300      # try again in 5 minutes
        time.sleep(POLL_SECONDS)
    log("Loop finished; the workflow starts the next round")


if __name__ == "__main__":
    main()
