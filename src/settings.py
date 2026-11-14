"""Loads and validates external_config/settings.json: the manual-refresh rules and which refresh choices exist.

  refresh.manual_cooldown_minutes  after a refresh completes, no other manual refresh is accepted for this long
                                   (there is no periodic automatic refresh: the news only updates when someone clicks Refresh)
  refresh.min_gap_seconds    at most one refresh is started per this many seconds, however many requests arrive
  refresh.request_topic      the name of the relay channel the page's Refresh button posts to (3-64 letters, digits, - or _)
  time_ranges                the "Fetch stories from" choices: default_hours and options [{hours, label}]
  article_counts             the "Stories per section" choices: default and options [number, ...]

A request that names no valid time range or story count uses the defaults.
Command line (used by the workflow):  python3 src/settings.py cooldown_minutes
"""
import json
import re
import sys
from pathlib import Path

import config
from config import ConfigError

TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")


def _int(value, where, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"settings.json: {where} must be a whole number of at least {minimum} (got {value!r})")
    return value


def load_settings(directory=None):
    path = Path(directory or config.config_dir()) / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} not found")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ConfigError("settings.json must be an object")
    refresh = data.get("refresh") or {}
    topic = refresh.get("request_topic")
    if not isinstance(topic, str) or not TOPIC_RE.match(topic):
        raise ConfigError("settings.json: refresh.request_topic must be 3-64 letters, digits, - or _")
    ranges = (data.get("time_ranges") or {}).get("options")
    if not isinstance(ranges, list) or not ranges:
        raise ConfigError("settings.json: time_ranges.options must list at least one {hours, label}")
    options = []
    for n, r in enumerate(ranges, 1):
        if not isinstance(r, dict) or not isinstance(r.get("label"), str) or not r["label"].strip():
            raise ConfigError(f"settings.json: time_ranges.options #{n} needs a 'label'")
        options.append({"hours": _int(r.get("hours"), f"time_ranges.options #{n} hours"), "label": r["label"].strip()})
    hours = [o["hours"] for o in options]
    if len(set(hours)) != len(hours):
        raise ConfigError("settings.json: time_ranges.options repeats an hours value")
    default_hours = _int(data["time_ranges"].get("default_hours"), "time_ranges.default_hours")
    if default_hours not in hours:
        raise ConfigError(f"settings.json: time_ranges.default_hours ({default_hours}) must be one of the options ({hours})")
    counts_cfg = data.get("article_counts") or {}
    counts = counts_cfg.get("options")
    if not isinstance(counts, list) or not counts:
        raise ConfigError("settings.json: article_counts.options must list at least one number")
    counts = [_int(c, "article_counts.options entries") for c in counts]
    if len(set(counts)) != len(counts):
        raise ConfigError("settings.json: article_counts.options repeats a number")
    default_count = _int(counts_cfg.get("default"), "article_counts.default")
    if default_count not in counts:
        raise ConfigError(f"settings.json: article_counts.default ({default_count}) must be one of the options ({counts})")
    return {
        "cooldown_minutes": _int(refresh.get("manual_cooldown_minutes"), "refresh.manual_cooldown_minutes", 0),
        "min_gap_seconds": _int(refresh.get("min_gap_seconds"), "refresh.min_gap_seconds", 0),
        "request_topic": topic,
        "time_ranges": options, "hours": tuple(hours), "default_hours": default_hours,
        "counts": tuple(counts), "default_count": default_count,
    }


def public_settings(st):
    """What the web page needs: the two choice lists, their defaults, the relay topic and the refresh interval."""
    return {"cooldown_minutes": st["cooldown_minutes"],      # lets the page work out when the next manual refresh is allowed
            "time_ranges": st["time_ranges"], "default_hours": st["default_hours"],
            "article_counts": list(st["counts"]), "default_count": st["default_count"], "request_topic": st["request_topic"]}


if __name__ == "__main__":
    try:
        st = load_settings()
    except ConfigError as e:
        sys.exit(f"Configuration error: {e}")
    if sys.argv[1:] == ["cooldown_minutes"]:
        print(st["cooldown_minutes"])
    else:
        sys.exit("usage: python3 src/settings.py cooldown_minutes")
