"""What the refresh jobs may ask GitHub: the recent runs of the "Update news and deploy" workflow, as plain dicts.
Shared by the scheduled-refresh job and the adhoc-refresh listener; neither knows about the other.

A run is {"kind": "scheduled"|"adhoc", "status", "conclusion", "created", "updated"} (the datetimes are UTC). Only refreshes
count (started with workflow_dispatch); a code push merely redeploys. The kind comes from the run's name, which update.yml sets
to "Refresh (scheduled)" or "Refresh (adhoc)"; an older dispatched run with no kind in its name counts as adhoc."""
import json
import os
import re
import subprocess
from datetime import datetime

GH = os.environ.get("GH_BIN", "gh")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")


def gh(*args):
    return subprocess.run([GH, *args], capture_output=True, text=True, timeout=120)


def _time(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def list_runs(limit=40):
    """Newest first; None when GitHub cannot be asked (callers must not treat that as 'no runs')."""
    try:
        r = gh("run", "list", "--repo", REPO, "--workflow", "update.yml", "--limit", str(limit),
               "--json", "createdAt,updatedAt,conclusion,status,event,displayTitle")
        if r.returncode != 0:
            return None
        raw = json.loads(r.stdout)
    except Exception:
        return None
    out = []
    for x in raw:
        if x.get("event") != "workflow_dispatch":
            continue
        m = re.search(r"\((scheduled|adhoc)\)", x.get("displayTitle") or "")
        out.append({"kind": m.group(1) if m else "adhoc", "status": x.get("status"), "conclusion": x.get("conclusion"),
                    "created": _time(x["createdAt"]), "updated": _time(x["updatedAt"])})
    return out


def is_active(run):
    return run["status"] in ACTIVE
