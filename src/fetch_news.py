#!/usr/bin/env python3
"""Fetch headlines from newspaper RSS/Atom feeds and write site/news.json.

Standard library only. For every story we keep: headline, short snippet, link back to the
original, source, time, primary image URL (hotlinked from the publisher), the sections it
belongs to, and its continent/country.
"""
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import config
import geo
import settings

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "site" / "news.json"

# The allowed time ranges and story counts come from external_config/settings.json (configure() loads them);
# the values below are only what is used if configure() was never called.
ALLOWED_WINDOWS = (6, 12, 24, 72, 168, 720, 2160)
DEFAULT_WINDOW = 24
WINDOW_HOURS = DEFAULT_WINDOW        # set in main() from the WINDOW_HOURS environment variable
ALLOWED_COUNTS = (200, 300, 400, 500, 1000)   # stories kept per section
DEFAULT_COUNT = 300
ARTICLE_COUNT = DEFAULT_COUNT        # set in main() from the ARTICLE_COUNT environment variable
OG_BUDGET_SECONDS = 150              # time allowed for fetching missing article images
OG_MAX_ITEMS = 900                   # raised in proportion when more stories are requested
TIMEOUT = 30
USER_AGENT = "NewsHubBot/1.0 (headline aggregator; links back to originals)"
SNIPPET_LEN = 160

# The sections and their keyword rules come from external_config/sections.json (see config.py); main() loads them.
SECTIONS = []          # validated section definitions, in tab order
PLACE = {}             # section key -> "newspaper" | {"country", "continent"} for sections whose stories get a fixed place


def configure(sections, st=None):
    """Install the section rules and the refresh choices (settings.json; loaded from the config folder if not given)."""
    global SECTIONS, PLACE, ALLOWED_WINDOWS, DEFAULT_WINDOW, ALLOWED_COUNTS, DEFAULT_COUNT
    st = st or settings.load_settings()
    ALLOWED_WINDOWS, DEFAULT_WINDOW = st["hours"], st["default_hours"]
    ALLOWED_COUNTS, DEFAULT_COUNT = st["counts"], st["default_count"]
    SECTIONS = sections
    PLACE = {s["key"]: s["place"] for s in sections if s["place"]}


WIDTH_QS_RE = re.compile(r"[?&](?:w|width)=(\d{2,4})\b", re.I)
BBC_W_RE = re.compile(r"/(?:ace/standard|ace/ws|news)/(\d{3,4})/", re.I)
BBC_SIZE_RE = re.compile(r"/(ace/standard|ace/ws|news)/(\d{3,4})/", re.I)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)
OG_NAME_RE = re.compile(r"""(?:property|name)=["'](?:og:image(?::secure_url|:url)?|twitter:image(?::src)?)["']""", re.I)
CONTENT_RE = re.compile(r"""content=["']([^"']+)["']""", re.I)
IMG_TAG_RE = re.compile(r"""<img[^>]+?src=["']([^"']+)["']""", re.I)
IMG_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|avif)(?:[?#]|$)", re.I)
BAD_IMG = ("pixel", "1x1", "spacer", "blank.gif", "tracking", "/ads/", "doubleclick", "feedburner.com/~")


def window_hours():
    try:
        h = int(os.environ.get("WINDOW_HOURS", DEFAULT_WINDOW))
    except ValueError:
        h = DEFAULT_WINDOW
    return h if h in ALLOWED_WINDOWS else DEFAULT_WINDOW


def article_count():
    try:
        n = int(os.environ.get("ARTICLE_COUNT", DEFAULT_COUNT))
    except ValueError:
        n = DEFAULT_COUNT
    return n if n in ALLOWED_COUNTS else DEFAULT_COUNT


def per_feed_limit(hours, count=None):
    """Longer windows may take more stories per feed (feeds only list what they still hold); asking for more
    stories per section raises the per-feed allowance in proportion."""
    count = count or DEFAULT_COUNT
    base = 20 if hours <= 24 else 30 if hours <= 72 else 50 if hours <= 168 else 80 if hours <= 720 else 100
    return int(base * max(1.0, count / DEFAULT_COUNT) + 0.999)


def window_url(url, hours):
    """Google News feeds carry their own 'when:' window; point it at the chosen range."""
    if "news.google.com" not in url:
        return url
    when = f"{hours}h" if hours <= 72 else f"{hours // 24}d"
    return re.sub(r"when%3A\d+[dh]", f"when%3A{when}", url)


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def child_text(el, *names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def entry_link(el):
    for c in el:
        if local(c.tag) == "link":
            if c.get("href") and c.get("rel", "alternate") == "alternate":
                return c.get("href").strip()
            if (c.text or "").strip():
                return c.text.strip()
    return ""


def clean_image(url):
    url = (url or "").strip()
    if not url or url.startswith("data:"):
        return None
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not url.startswith("https://") or any(b in url.lower() for b in BAD_IMG):
        return None
    return html.unescape(url)


def guess_width(el, url):
    """Width in pixels of an image candidate, from its width attribute or from the URL (0 = unknown)."""
    v = (el.get("width") or "").strip()
    if v.isdigit():
        return int(v)
    m = WIDTH_QS_RE.search(url) or BBC_W_RE.search(url)
    return int(m.group(1)) if m else 0


def upgrade_image(url):
    """Ask for a bigger version where the publisher's URL scheme allows it (BBC thumbnails are 240px)."""
    if "ichef.bbci.co.uk" in url:
        m = BBC_SIZE_RE.search(url)
        if m and int(m.group(2)) < 624:
            return url[: m.start()] + f"/{m.group(1)}/800/" + url[m.end():]
    return url


def image_rank(width):
    """Known-large beats unknown, unknown beats known-small."""
    return width if width >= 300 else (299 if width == 0 else width)


def find_image(entry):
    """Best image for a story: the largest of media:content / thumbnail / enclosure / image,
    else the first <img> in the body."""
    cands = []
    for c in entry.iter():
        t = local(c.tag)
        url = None
        if t == "content" and (c.get("medium") == "image" or (c.get("type") or "").startswith("image")
                               or IMG_EXT_RE.search(c.get("url") or "")):
            url = c.get("url")
        elif t == "thumbnail":
            url = c.get("url")
        elif t == "enclosure" and ((c.get("type") or "").startswith("image") or IMG_EXT_RE.search(c.get("url") or "")):
            url = c.get("url")
        elif t == "link" and c.get("rel") == "enclosure" and (c.get("type") or "").startswith("image"):
            url = c.get("href")
        elif t == "image":
            url = c.get("url") or c.get("href") or (c.text or "").strip()
        img = clean_image(url)
        if img:
            cands.append((image_rank(guess_width(c, img)), -len(cands), img))
    if cands:
        return upgrade_image(max(cands)[2])
    for name in ("encoded", "description", "summary", "content"):
        body = child_text(entry, name)
        for m in IMG_TAG_RE.finditer(body):
            img = clean_image(m.group(1))
            if img:
                return upgrade_image(img)
    return None


def og_image(page_html, page_url):
    """The article's own main image, from its og:image / twitter:image meta tag."""
    for tag in META_RE.findall(page_html):
        if OG_NAME_RE.search(tag):
            m = CONTENT_RE.search(tag)
            if m:
                img = clean_image(urljoin(page_url, html.unescape(m.group(1).strip())))
                if img:
                    return img
    return None


def enrich_images(items):
    """For stories whose feed gave no image, read the article page's og:image (time-boxed, polite)."""
    todo = [i for i in items if not i["image"] and "news.google.com" not in i["link"]]
    todo.sort(key=lambda i: i["published"], reverse=True)      # newest first ...
    todo.sort(key=lambda i: not i["primary"])                    # ... but primary papers before the rest (stable)
    todo = todo[:int(OG_MAX_ITEMS * max(1.0, ARTICLE_COUNT / DEFAULT_COUNT))]
    deadline = time.monotonic() + OG_BUDGET_SECONDS
    stats = {}                                   # host -> [ok, fail]

    def work(it):
        host = urlparse(it["link"]).netloc
        ok, fail = stats.setdefault(host, [0, 0])
        if time.monotonic() > deadline or (fail >= 3 and ok == 0):
            return
        try:
            req = Request(it["link"], headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
            with urlopen(req, timeout=8) as r:
                page = r.read(250_000).decode("utf-8", "ignore")
            img = og_image(page, it["link"])
            if img:
                it["image"] = img
                stats[host][0] += 1
            else:
                stats[host][1] += 1
        except Exception:
            stats[host][1] += 1

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(work, todo))
    return sum(1 for i in todo if i["image"]), len(todo)


def trim_sections(items, keep=None):
    """Keep the newest (primary-boosted) `keep` stories of each section so news.json stays a sane size."""
    keep = keep or DEFAULT_COUNT
    boost = timedelta(hours=6)
    score = lambda i: datetime.fromisoformat(i["published"]) + (boost if i["primary"] else timedelta())
    by_sec, keepers = {}, set()
    for it in items:
        for sec in it["sections"]:
            by_sec.setdefault(sec, []).append(it)
    for lst in by_sec.values():
        lst.sort(key=score, reverse=True)
        keepers.update(id(i) for i in lst[:keep])
    return [i for i in items if id(i) in keepers]


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    entries = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    items = []
    for e in entries:
        title = strip_html(child_text(e, "title"))
        link = entry_link(e)
        if not title or not link:
            continue
        src = child_text(e, "source")
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].rstrip()
        date = parse_date(child_text(e, "pubDate", "published", "updated", "date"))
        summary = strip_html(child_text(e, "description", "summary"))
        if len(summary) > SNIPPET_LEN:
            summary = summary[:SNIPPET_LEN].rsplit(" ", 1)[0] + "…"
        items.append({"title": title, "link": link, "date": date, "summary": summary, "image": find_image(e)})
    return items


def classify(feed, title, summary):
    """Return the list of sections a story belongs to: its newspaper's own section for that feed, plus every section
    whose keyword rule matches (see config.py for the rule fields)."""
    cat = feed["category"]
    text = title + " " + summary
    sections = [cat]
    for sec in SECTIONS:
        if sec["key"] == cat or not sec["rx"]:
            continue
        if cat in sec["also_from"] and sec["rx"].search(text):
            sections.append(sec["key"])
        elif feed.get("general") and sec["general"] and sec["rx_general"].search(text):
            sections.append(sec["key"])
    return sections


def place(feed, title, summary):
    """Country and continent a story is about. A section can pin it (Indian News = India) or take it from the newspaper."""
    rule = PLACE.get(feed["category"])
    if isinstance(rule, dict):
        return rule["country"], rule["continent"]
    if rule == "newspaper":
        return feed.get("country") or "Other", feed.get("continent") or "Other"
    country, continent = geo.find_country(title, summary)
    if country:
        return country, continent
    return feed.get("country") or "Other", feed.get("continent") or "Other"


def fetch_one(feed):
    status = {"source": feed["source"], "category": feed["category"], "primary": feed.get("primary", False),
              "url": feed["url"], "ok": False, "count": 0}
    try:
        req = Request(window_url(feed["url"], WINDOW_HOURS), headers={"User-Agent": USER_AGENT,
                                            "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        items = parse_feed(data)
    except Exception as exc:  # one broken feed must never break the build
        status["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return [], status

    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    items = [it for it in items if not it["date"] or it["date"] >= cutoff]
    items.sort(key=lambda x: x["date"] or datetime.now(timezone.utc), reverse=True)
    out = []
    for it in items[:per_feed_limit(WINDOW_HOURS, ARTICLE_COUNT)]:
        country, continent = place(feed, it["title"], it["summary"])
        out.append({
            "title": it["title"],
            "link": it["link"],
            "summary": it["summary"],
            "image": it["image"],
            "published": (it["date"] or datetime.now(timezone.utc)).isoformat(),
            "source": feed["source"],
            "newspaper": feed.get("newspaper") or feed["source"],      # the paper in newspapers.json (source may be a section label)
            "primary": bool(feed.get("primary")),
            "category": feed["category"],
            "sections": classify(feed, it["title"], it["summary"]),
            "continent": continent,
            "country": country,
            "state": feed.get("state"),
        })
    status.update(ok=True, count=len(out))
    return out, status


def main():
    global WINDOW_HOURS, ARTICLE_COUNT
    try:
        sections, feeds = config.load_all()
        configure(sections)
    except config.ConfigError as e:
        sys.exit(f"Configuration error: {e}")
    WINDOW_HOURS = window_hours()
    ARTICLE_COUNT = article_count()
    print(f"Time window: last {WINDOW_HOURS} hours; keeping up to {ARTICLE_COUNT} stories per section")
    print(f"{len(sections)} sections, {len(feeds)} feeds from {config.config_dir()}")
    # Google News throttles bursts (HTTP 503), so its feeds are fetched one at a time, with a pause and one retry.
    google = [f for f in feeds if "news.google.com" in f["url"]]
    others = [f for f in feeds if "news.google.com" not in f["url"]]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(fetch_one, others))
    for f in google:
        out, status = fetch_one(f)
        if not status["ok"] and any(c in status.get("error", "") for c in ("503", "429")):
            time.sleep(10)
            out, status = fetch_one(f)
        results.append((out, status))
        time.sleep(2)

    by_link, statuses = {}, []
    for feed_items, status in results:
        statuses.append(status)
        for it in feed_items:
            prev = by_link.get(it["link"])
            if prev is None:
                by_link[it["link"]] = it
            else:  # same story from two feeds: merge sections, prefer primary source and an image
                prev["sections"] = sorted(set(prev["sections"]) | set(it["sections"]))
                if it["primary"] and not prev["primary"]:
                    prev["primary"], prev["source"], prev["newspaper"] = True, it["source"], it["newspaper"]
                if not prev["image"] and it["image"]:
                    prev["image"] = it["image"]
    items = sorted(by_link.values(), key=lambda x: x["published"], reverse=True)
    before = len(items)
    items = trim_sections(items, ARTICLE_COUNT)
    got, tried = enrich_images(items)
    print(f"Article-page images: found {got} of {tried} tried; trimmed {before - len(items)} extra stories")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    # refresh.json is tiny: the page reads it to know when the next manual refresh is allowed without downloading news.json
    (OUT_FILE.parent / "refresh.json").write_text(json.dumps(
        {"refreshed_at": generated_at, "range_hours": WINDOW_HOURS, "max_articles": ARTICLE_COUNT}))
    OUT_FILE.write_text(json.dumps({
        "generated_at": generated_at,
        "range_hours": WINDOW_HOURS,
        "max_articles": ARTICLE_COUNT,
        "items": items,
        "feeds": statuses,
    }, ensure_ascii=False, separators=(",", ":")))

    ok = sum(s["ok"] for s in statuses)
    with_img = sum(1 for i in items if i["image"])
    print(f"{len(items)} items ({with_img} with images) from {ok}/{len(statuses)} feeds -> {OUT_FILE}")
    for s in statuses:
        if not s["ok"]:
            tag = "PRIMARY" if s["primary"] else "secondary"
            print(f"  FAILED [{tag}] {s['source']} ({s['category']}) {s['url'][:90]}: {s.get('error')}", file=sys.stderr)
    for s_ in statuses:
        if s_["ok"] and "news.google.com" in s_["url"]:
            print(f"  GNEWS {s_['source']} ({s_['category']}): {s_['count']} items")
    if not items:
        sys.exit(1)


if __name__ == "__main__":
    main()
