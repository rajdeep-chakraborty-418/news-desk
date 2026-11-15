"""Loads and validates the two configuration files that live outside the code, in external_config/:

  newspaper_sections/<newspaper>.json   one file per newspaper (the only list of newspapers)
      {"newspaper", "tier": "primary"|"secondary", "homepage", "country"?, "continent"?, "listed"?, "feeds": [feed, ...],
       "section_map": {"<our section>": ["<its own section>", ...]}, "other": [...]}
      feed      = {"section", "url", "label"?, "state"?, "country"?, "continent"?}
  sections.json    {"sections": [section, ...]}   (the order here is the order of the tabs on the page)
      section   = {"key", "label", "color": {"light", "dark"}}

A feed's "section" is where its stories always appear. A story also appears in every section that its newspaper's file in
newspaper_sections/ maps its own section to (see load_section_maps); there are no keyword rules.
A story's country and continent are always its newspaper's (the "country" and "continent" in its newspaper_sections file).

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


def _is_url(v):
    return isinstance(v, str) and re.match(r"^https?://[^\s/]+", v) is not None


def load_sections(directory=None):
    """The validated list of sections, in tab order. """
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
        for old in ("keywords", "also_from_sections", "include_general_newspapers", "extra_keywords_for_general_newspapers", "place"):
            if old in s:
                raise ConfigError(f"{where}: '{old}' is no longer supported (keyword rules and place rules were removed; use newspaper_sections/ maps; the country comes from the newspaper)")
        out.append({"key": key, "label": s["label"].strip(), "color": color})
    return out


def load_newspapers(sections, directory=None):
    """The validated newspapers as {'primary': [...], 'secondary': [...]}, read from external_config/newspaper_sections/*.json
    (one file per newspaper: name, tier, homepage, feeds and its section map). Nothing else lists newspapers."""
    folder = Path(directory or config_dir()) / "newspaper_sections"
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    if not files:
        raise ConfigError(f"{folder} has no newspaper files; add one JSON file per newspaper")
    keys = {s["key"] for s in sections}
    data = {"primary": [], "secondary": []}
    for path in files:
        try:
            p = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} is not valid JSON: {e}")
        where = f"newspaper_sections/{path.name}"
        if not isinstance(p, dict):
            raise ConfigError(f"{where} must be an object")
        if not isinstance(p.get("newspaper"), str) or not p["newspaper"].strip():
            raise ConfigError(f"{where}: 'name' is required (key \"newspaper\")")
        where = f"newspaper_sections/{path.name} '{p['newspaper']}'"
        tier = p.get("tier", "primary")
        if tier not in ("primary", "secondary"):
            raise ConfigError(f"{where}: 'tier' must be \"primary\" or \"secondary\"")
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
        entry = {k: p[k] for k in ("homepage", "country", "continent", "listed", "feeds") if k in p}
        data[tier].append(dict(entry, name=p["newspaper"]))
    return data


def norm_label(text):
    """A section name or URL piece in one comparable form: lowercase words, no punctuation, no trailing 'news'."""
    t = re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()
    return re.sub(r"\s+news$", "", t) or t


def load_section_maps(sections, directory=None):
    """Per-newspaper section maps from external_config/newspaper_sections/*.json, as {newspaper name: {normalised source
    section: [section keys]}}. Each file: {"newspaper", "section_map": {"<ui section key>": ["<newspaper section>", ...]},
    "other": [...]}. Many newspaper sections may map to one section; names under "other" (or not listed) map to nothing extra.
    A missing folder is fine (no maps)."""
    folder = Path(directory or config_dir()) / "newspaper_sections"
    if not folder.is_dir():
        return {}
    keys = {s["key"] for s in sections}
    maps = {}
    for path in sorted(folder.glob("*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} is not valid JSON: {e}")
        where = f"newspaper_sections/{path.name}"
        d.setdefault("section_map", {})
        if not isinstance(d, dict) or not isinstance(d.get("newspaper"), str) or not isinstance(d["section_map"], dict):
            raise ConfigError(f'{where} must be {{"newspaper": "...", "section_map": {{...}}}}')
        look = {}
        for key, names in d["section_map"].items():
            if key not in keys:
                raise ConfigError(f"{where}: section_map names '{key}', which is not in sections.json (known: {', '.join(sorted(keys))})")
            if not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names):
                raise ConfigError(f"{where}: '{key}' must be a list of newspaper section names")
            for n in names:
                dest = look.setdefault(norm_label(n), [])
                if key not in dest:
                    dest.append(key)
        if "other" in keys:                      # names listed under "other" put the story in the Other section
            for n in d.get("other") or []:
                dest = look.setdefault(norm_label(n), [])
                if "other" not in dest and not dest:
                    dest.append("other")
        maps[d["newspaper"]] = look
    return maps


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
    """The list behind the Newspaper Homepage page (a homepage listed more than once appears once, as the first/primary entry;
    "names" holds every newspaper name that shares it, so stories can be matched to it)."""
    by_url, out = {}, []
    for node in ("primary", "secondary"):
        for p in newspapers[node]:
            if p.get("listed", True) is False:
                continue
            if p["homepage"] in by_url:                       # same homepage listed again: remember the name for story matching
                by_url[p["homepage"]]["names"].append(p["name"])
                continue
            entry = {"name": p["name"], "names": [p["name"]], "url": p["homepage"], "country": p.get("country") or "International",
                     "continent": p.get("continent") or "Other", "primary": node == "primary"}
            by_url[p["homepage"]] = entry
            out.append(entry)
    return sorted(out, key=lambda p: re.sub(r"^the\s+", "", p["name"].lower()))
