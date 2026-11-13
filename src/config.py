"""Loads and validates the two configuration files that live outside the code, in external_config/:

  newspapers.json  {"primary": [newspaper, ...], "secondary": [newspaper, ...]}
      newspaper = {"name", "homepage", "country"?, "continent"?, "listed"?, "feeds": [feed, ...]}
      feed      = {"section", "url", "label"?, "state"?, "general"?, "country"?, "continent"?}
  sections.json    {"sections": [section, ...]}   (the order here is the order of the tabs on the page)
      section   = {"key", "label", "color": {"light", "dark"}, "keywords"?, "also_from_sections"?,
                   "include_general_newspapers"?, "extra_keywords_for_general_newspapers"?, "place"?}

A feed's "section" is where its stories always appear. Keyword rules let stories from other feeds land in a section too:
"keywords" are matched (whole words, any case) in the headline and snippet of stories from feeds in "also_from_sections",
and from feeds flagged "general" when "include_general_newspapers" is true (those also use the extra keywords).
"place" decides the story's country: omitted = detected from the text, "newspaper" = the newspaper's own country,
or a fixed {"country", "continent"}.

NEWSDESK_CONFIG_DIR points the code at a different folder (for example one written by a hosted app for one user).
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTINENTS = ("Asia", "Europe", "Africa", "North America", "South America", "Oceania", "Other")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConfigError(ValueError):
    """The configuration files are wrong; the message says which file, which entry and what to fix."""


def config_dir():
    return Path(os.environ.get("NEWSDESK_CONFIG_DIR") or ROOT / "external_config")


def _read(name, directory):
    path = Path(directory) / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} not found")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}")


def _word_re(words):
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.I) if words else None


def _is_url(v):
    return isinstance(v, str) and re.match(r"^https?://[^\s/]+", v) is not None


def _words(sec, field, where):
    v = sec.get(field, [])
    if not isinstance(v, list) or not all(isinstance(w, str) and w.strip() for w in v):
        raise ConfigError(f"{where}: '{field}' must be a list of words")
    return v


def load_sections(directory=None):
    """The validated list of sections, in tab order. Each gets compiled patterns under 'rx' and 'rx_general'."""
    data = _read("sections.json", directory or config_dir())
    items = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ConfigError('sections.json must be {"sections": [ ... ]} with at least one section')
    out, seen = [], set()
    for n, s in enumerate(items, 1):
        where = f"sections.json section #{n}"
        if not isinstance(s, dict):
            raise ConfigError(f"{where} must be an object")
        key = s.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise ConfigError(f"{where}: 'key' must be lowercase letters, digits or _ and start with a letter (got {key!r})")
        where = f"sections.json section '{key}'"
        if key in seen:
            raise ConfigError(f"{where} is listed twice")
        seen.add(key)
        if not isinstance(s.get("label"), str) or not s["label"].strip():
            raise ConfigError(f"{where}: 'label' is required")
        color = s.get("color")
        if not (isinstance(color, dict) and COLOR_RE.match(str(color.get("light"))) and COLOR_RE.match(str(color.get("dark")))):
            raise ConfigError(f"{where}: 'color' must be {{\"light\": \"#rrggbb\", \"dark\": \"#rrggbb\"}}")
        place = s.get("place")
        if place not in (None, "newspaper") and not (isinstance(place, dict) and place.get("country") and place.get("continent")):
            raise ConfigError(f"{where}: 'place' must be \"newspaper\" or {{\"country\": ..., \"continent\": ...}}")
        kw, extra = _words(s, "keywords", where), _words(s, "extra_keywords_for_general_newspapers", where)
        frm = s.get("also_from_sections", [])
        if not isinstance(frm, list):
            raise ConfigError(f"{where}: 'also_from_sections' must be a list of section keys")
        out.append({"key": key, "label": s["label"].strip(), "color": color, "place": place, "keywords": kw,
                    "also_from": list(frm), "general": bool(s.get("include_general_newspapers", False)),
                    "rx": _word_re(kw), "rx_general": _word_re(kw + extra)})
    for s in out:
        for k in s["also_from"]:
            if k not in seen:
                raise ConfigError(f"sections.json section '{s['key']}': 'also_from_sections' names '{k}', which is not a section")
    return out


def load_newspapers(sections, directory=None):
    """The validated newspapers as {'primary': [...], 'secondary': [...]}."""
    data = _read("newspapers.json", directory or config_dir())
    if not isinstance(data, dict) or not isinstance(data.get("primary"), list) or not isinstance(data.get("secondary"), list):
        raise ConfigError('newspapers.json must be {"primary": [ ... ], "secondary": [ ... ]}')
    keys = {s["key"] for s in sections}
    for node in ("primary", "secondary"):
        for n, p in enumerate(data[node], 1):
            where = f"newspapers.json {node} #{n}"
            if not isinstance(p, dict):
                raise ConfigError(f"{where} must be an object")
            if not isinstance(p.get("name"), str) or not p["name"].strip():
                raise ConfigError(f"{where}: 'name' is required")
            where = f"newspapers.json {node} '{p['name']}'"
            if not _is_url(p.get("homepage")):
                raise ConfigError(f"{where}: 'homepage' must be a web address starting with http:// or https://")
            if p.get("continent") is not None and p["continent"] not in CONTINENTS:
                raise ConfigError(f"{where}: 'continent' must be one of {', '.join(CONTINENTS)}")
            feeds = p.get("feeds")
            if not isinstance(feeds, list) or not feeds:
                raise ConfigError(f"{where}: needs at least one entry in 'feeds'")
            for f in feeds:
                if not isinstance(f, dict) or not _is_url(f.get("url")):
                    raise ConfigError(f"{where}: every feed needs a 'url' starting with http:// or https://")
                if f.get("section") not in keys:
                    raise ConfigError(f"{where}: feed {f.get('url')} has section {f.get('section')!r}, which is not in sections.json "
                                      f"(known: {', '.join(sorted(keys))})")
                if f.get("continent") is not None and f["continent"] not in CONTINENTS:
                    raise ConfigError(f"{where}: feed {f['url']} has an unknown continent {f['continent']!r}")
    return data


def load_feeds(sections, newspapers):
    """One flat entry per feed, as the fetcher uses them (primary/secondary comes from the node the newspaper is in)."""
    feeds = []
    for node in ("primary", "secondary"):
        for p in newspapers[node]:
            for f in p["feeds"]:
                feed = {"source": f.get("label") or p["name"], "newspaper": p["name"], "section": f["section"],
                        "category": f["section"],           # kept under the old name too
                        "country": f.get("country", p.get("country")), "continent": f.get("continent", p.get("continent")),
                        "url": f["url"], "primary": node == "primary"}
                if f.get("state"):
                    feed["state"] = f["state"]
                if f.get("general"):
                    feed["general"] = True
                feeds.append(feed)
    return feeds


def load_all(directory=None):
    """(sections, feeds) from the config folder; raises ConfigError with a readable message if anything is wrong."""
    sections = load_sections(directory)
    return sections, load_feeds(sections, load_newspapers(sections, directory))


def public_sections(sections):
    """What the web page needs to draw the tabs and their colours."""
    return [{"key": s["key"], "label": s["label"], "color": s["color"]} for s in sections]


def public_newspapers(newspapers):
    """The list behind the page's Newspaper Homepage dropdown (a paper in both nodes appears once, as primary)."""
    seen, out = set(), []
    for node in ("primary", "secondary"):
        for p in newspapers[node]:
            if p.get("listed", True) is False or p["homepage"] in seen:
                continue
            seen.add(p["homepage"])
            out.append({"name": p["name"], "url": p["homepage"], "country": p.get("country") or "International",
                        "continent": p.get("continent") or "Other", "primary": node == "primary"})
    return sorted(out, key=lambda p: re.sub(r"^the\s+", "", p["name"].lower()))
