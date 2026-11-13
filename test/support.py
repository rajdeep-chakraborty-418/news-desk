"""Shared test helpers. Importing this module (every test does) puts src/ on the import path, points the code at a
throw-away sample configuration, and installs a guard that fails any test which tries to read the real
external_config/ folder: the tests must stand on their own sample data and mocks."""
import builtins
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
REAL_CONFIG = (REPO / "external_config").resolve()
sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------- sample configuration (never the real one)
SAMPLE_SECTIONS = {"sections": [
    {"key": "home", "label": "Home News", "color": {"light": "#b0123a", "dark": "#ff7a9a"}, "place": "newspaper"},
    {"key": "india", "label": "India Desk", "color": {"light": "#c2570c", "dark": "#ff9a4d"},
     "place": {"country": "India", "continent": "Asia"}},
    {"key": "world", "label": "World Desk", "color": {"light": "#2a4d8f", "dark": "#7ea3f0"}},
    {"key": "sports", "label": "Sports Desk", "color": {"light": "#1b6e5a", "dark": "#4cc3a4"},
     "keywords": ["cricket", "football", "tennis"], "include_general_newspapers": True},
    {"key": "showbiz", "label": "Showbiz Desk", "color": {"light": "#9b2f7a", "dark": "#e27cc0"},
     "keywords": ["film", "actor"], "also_from_sections": ["world", "india"], "include_general_newspapers": True,
     "extra_keywords_for_general_newspapers": ["festival", "celebrity"]},
    {"key": "defence", "label": "Defence Desk", "color": {"light": "#4a5a2a", "dark": "#9fbf5f"},
     "keywords": ["army", "navy", "missile"], "also_from_sections": ["world", "india"]},
    {"key": "money", "label": "Money Desk", "color": {"light": "#6b4e16", "dark": "#d9b25f"},
     "keywords": ["sensex", "inflation", "stock market"], "also_from_sections": ["world", "india"],
     "include_general_newspapers": True},
]}

SAMPLE_NEWSPAPERS = {
    "primary": [
        {"name": "Alpha Times", "homepage": "https://www.alphatimes.example/", "country": "India", "continent": "Asia",
         "feeds": [{"section": "india", "url": "https://www.alphatimes.example/rss/india.xml"},
                   {"section": "world", "url": "https://www.alphatimes.example/rss/world.xml", "general": True,
                    "label": "Alpha Times (World)"}]},
        {"name": "Gazette Home", "homepage": "https://gazettehome.example/", "country": "Bangladesh", "continent": "Asia",
         "feeds": [{"section": "home", "url": "https://gazettehome.example/feed", "state": "Dhaka"}]},
    ],
    "secondary": [
        {"name": "Beta Post", "homepage": "https://betapost.example/", "country": "France", "continent": "Europe",
         "feeds": [{"section": "world", "url": "https://betapost.example/rss"}]},
        {"name": "Gamma Wire", "homepage": "https://gammawire.example/", "feeds": [
            {"section": "sports", "url": "https://news.google.com/rss/search?q=site%3Agammawire.example%20when%3A3d&hl=en-US",
             "country": "United Kingdom", "continent": "Europe"}]},
        {"name": "Hidden Search", "homepage": "https://news.google.com/", "listed": False,
         "feeds": [{"section": "showbiz", "url": "https://news.google.com/rss/search?q=film%20festival%20when%3A3d"}]},
    ],
}


# deliberately different from the shipped settings, so nothing can pass by relying on built-in numbers
SAMPLE_SETTINGS = {
    "refresh": {"interval_minutes": 60, "min_gap_seconds": 120, "request_topic": "test-topic-abc"},
    "time_ranges": {"default_hours": 24, "options": [
        {"hours": 6, "label": "Six hours"}, {"hours": 24, "label": "One day"},
        {"hours": 72, "label": "Three days"}, {"hours": 168, "label": "One week"}]},
    "article_counts": {"default": 150, "options": [50, 150, 250]},
}


def write_config(directory, sections=None, newspapers=None, settings=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sections.json").write_text(json.dumps(sections if sections is not None else SAMPLE_SECTIONS))
    (directory / "newspapers.json").write_text(json.dumps(newspapers if newspapers is not None else SAMPLE_NEWSPAPERS))
    (directory / "settings.json").write_text(json.dumps(settings if settings is not None else SAMPLE_SETTINGS))
    return directory


SESSION_DIR = Path(tempfile.mkdtemp(prefix="newsdesk-test-"))
SAMPLE_CONFIG = write_config(SESSION_DIR / "sample_config")
os.environ["NEWSDESK_CONFIG_DIR"] = str(SAMPLE_CONFIG)

# ---------------------------------------------------------------- guard: no test may read external_config/
def _inside_real_config(path):
    try:
        return Path(os.path.abspath(os.fspath(path))).resolve().is_relative_to(REAL_CONFIG)
    except (TypeError, ValueError, OSError):
        return False


_real_open, _real_path_open = builtins.open, pathlib.Path.open


def _guard(path):
    if _inside_real_config(path):
        raise AssertionError(f"a test tried to read the real configuration: {path}. Use test/support.py sample data.")


def _open(file, *a, **k):
    _guard(file)
    return _real_open(file, *a, **k)


def _path_open(self, *a, **k):
    _guard(self)
    return _real_path_open(self, *a, **k)


if not getattr(builtins, "_newsdesk_guard", False):
    builtins.open = _open
    pathlib.Path.open = _path_open          # Path.read_text / read_bytes go through Path.open
    builtins._newsdesk_guard = True

# ---------------------------------------------------------------- small builders and fakes
def rfc822(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def hours_ago(h):
    return datetime.now(timezone.utc) - timedelta(hours=h)


def rss(items):
    """items: list of dicts with title, link, hours_ago?, summary?, image?  -> RSS bytes."""
    body = ""
    for it in items:
        date = f"<pubDate>{rfc822(hours_ago(it['hours_ago']))}</pubDate>" if "hours_ago" in it else ""
        img = f'<media:content url="{it["image"]}" medium="image"/>' if it.get("image") else ""
        body += (f"<item><title>{it['title']}</title><link>{it['link']}</link>{date}"
                 f"<description>{it.get('summary', '')}</description>{img}</item>")
    return (f'<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>{body}</channel></rss>').encode()


class FakeResp:
    """What urlopen() returns: a context manager with read()."""
    def __init__(self, data=b"", status=200):
        self.data, self.status = data, status

    def read(self, n=-1):
        return self.data if n is None or n < 0 else self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def story(n, sections, primary=False, hours=0, **extra):
    base = {"title": f"Story {n}", "link": f"https://news.example/{n}", "summary": "", "image": "",
            "published": hours_ago(hours).isoformat(), "source": "Src", "primary": primary, "category": sections[0],
            "sections": sections, "continent": "Asia", "country": "India", "state": None}
    base.update(extra)
    return base


class TestCase(unittest.TestCase):
    """Base class: a private temp folder per test."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="nd-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
