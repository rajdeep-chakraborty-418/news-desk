#!/usr/bin/env python3
"""Fetch headlines from newspaper RSS/Atom feeds and write site/news.json.

Standard library only. For every story we keep: headline, short snippet, link back to the
original, source, time, primary image URL (hotlinked from the publisher), the sections it
belongs to, and its continent/country.
"""
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

import geo

ROOT = Path(__file__).parent
FEEDS_FILE = ROOT / "feeds.json"
OUT_FILE = ROOT / "site" / "news.json"

PER_FEED_LIMIT = 15
MAX_AGE_DAYS = 4
TIMEOUT = 30
USER_AGENT = "NewsHubBot/1.0 (headline aggregator; links back to originals)"
SNIPPET_LEN = 160

# Sections shown on the site. "india", "world", "sports", "entertainment", "lifestyle", "defence" come from
# the feed's own category; "geopolitics" and "defence" are also derived from keywords.
GEO_WORDS = ["sanction", "sanctions", "diplomat", "diplomats", "diplomacy", "diplomatic", "summit", "treaty",
             "ceasefire", "cease-fire", "nato", "united nations", "security council", "foreign minister",
             "foreign policy", "border", "tensions", "annex", "annexation", "geopolitical", "geopolitics",
             "alliance", "embassy", "ambassador", "trade war", "tariff", "tariffs", "bilateral", "g20", "g7",
             "brics", "war", "invasion", "peace talks", "peace deal", "coup", "sovereignty", "occupation",
             "refugees", "airspace", "strait", "embargo", "talks"]
DEF_WORDS = ["military", "army", "navy", "naval", "air force", "defence", "defense", "missile", "missiles",
             "drone", "drones", "warship", "fighter jet", "troops", "soldier", "soldiers", "weapon", "weapons",
             "submarine", "pentagon", "armed forces", "airstrike", "airstrikes", "artillery", "warplane",
             "warplanes", "ballistic", "combat", "battalion", "paramilitary", "defence ministry", "bomber"]
SPORT_WORDS = ["cricket", "football", "tennis", "olympic", "olympics", "fifa", "premier league", "tournament",
               "champions league", "world cup", "formula 1", "grand prix", "athlete", "nba", "nfl", "mlb",
               "rugby", "golf", "ipl", "medal", "t20", "test match", "wimbledon", "striker", "goalkeeper"]
LIFE_WORDS = ["lifestyle", "recipe", "recipes", "wellness", "fitness", "fashion", "skincare", "diet", "travel",
              "holiday", "destination", "wedding", "parenting", "yoga", "nutrition", "workout", "home decor",
              "interior", "gardening", "mental health", "sleep", "cooking", "restaurant", "beauty", "relationship"]
ENT_WORDS = ["film", "movie", "bollywood", "hollywood", "actor", "actress", "singer", "album", "box office",
             "netflix", "oscar", "oscars", "grammy", "concert", "celebrity", "tv series", "festival"]


def word_re(words):
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


GEO_RE, DEF_RE, SPORT_RE, ENT_RE, LIFE_RE = map(word_re, (GEO_WORDS, DEF_WORDS, SPORT_WORDS, ENT_WORDS, LIFE_WORDS))

IMG_TAG_RE = re.compile(r"""<img[^>]+?src=["']([^"']+)["']""", re.I)
IMG_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|avif)(?:[?#]|$)", re.I)
BAD_IMG = ("pixel", "1x1", "spacer", "blank.gif", "tracking", "/ads/", "doubleclick", "feedburner.com/~")


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


def find_image(entry):
    """Primary image: media:content / media:thumbnail / enclosure / <image>, else first <img> in the body."""
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
            return img
    for name in ("encoded", "description", "summary", "content"):
        body = child_text(entry, name)
        for m in IMG_TAG_RE.finditer(body):
            img = clean_image(m.group(1))
            if img:
                return img
    return None


def parse_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    entries = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    items = []
    for e in entries:
        title = strip_html(child_text(e, "title"))
        link = entry_link(e)
        if not title or not link:
            continue
        date = parse_date(child_text(e, "pubDate", "published", "updated", "date"))
        summary = strip_html(child_text(e, "description", "summary"))
        if len(summary) > SNIPPET_LEN:
            summary = summary[:SNIPPET_LEN].rsplit(" ", 1)[0] + "…"
        items.append({"title": title, "link": link, "date": date, "summary": summary, "image": find_image(e)})
    return items


def classify(feed, title, summary):
    """Return the list of sections a story belongs to."""
    cat = feed["category"]
    text = title + " " + summary
    sections = [cat]
    if cat in ("world", "india", "defence") and GEO_RE.search(text):
        sections.append("geopolitics")
    if cat in ("world", "india") and DEF_RE.search(text):
        sections.append("defence")
    if feed.get("general"):
        if SPORT_RE.search(text):
            sections.append("sports")
        if ENT_RE.search(text):
            sections.append("entertainment")
        if LIFE_RE.search(text):
            sections.append("lifestyle")
    return sorted(set(sections), key=sections.index)


def place(feed, title, summary):
    """Country and continent a story is about. Indian-news stories are always India."""
    if feed["category"] == "india":
        return "India", "Asia"
    country, continent = geo.find_country(title, summary)
    if country:
        return country, continent
    return feed.get("country") or "Other", feed.get("continent") or "Other"


def fetch_one(feed):
    status = {"source": feed["source"], "category": feed["category"], "primary": feed.get("primary", False),
              "url": feed["url"], "ok": False, "count": 0}
    try:
        req = Request(feed["url"], headers={"User-Agent": USER_AGENT,
                                            "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        items = parse_feed(data)
    except Exception as exc:  # one broken feed must never break the build
        status["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return [], status

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    items = [it for it in items if not it["date"] or it["date"] >= cutoff]
    items.sort(key=lambda x: x["date"] or datetime.now(timezone.utc), reverse=True)
    out = []
    for it in items[:PER_FEED_LIMIT]:
        country, continent = place(feed, it["title"], it["summary"])
        out.append({
            "title": it["title"],
            "link": it["link"],
            "summary": it["summary"],
            "image": it["image"],
            "published": (it["date"] or datetime.now(timezone.utc)).isoformat(),
            "source": feed["source"],
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
    feeds = json.loads(FEEDS_FILE.read_text())
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(fetch_one, feeds))

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
                    prev["primary"], prev["source"] = True, it["source"]
                if not prev["image"] and it["image"]:
                    prev["image"] = it["image"]
    items = sorted(by_link.values(), key=lambda x: x["published"], reverse=True)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "feeds": statuses,
    }, ensure_ascii=False, separators=(",", ":")))

    ok = sum(s["ok"] for s in statuses)
    with_img = sum(1 for i in items if i["image"])
    print(f"{len(items)} items ({with_img} with images) from {ok}/{len(statuses)} feeds -> {OUT_FILE}")
    for s in statuses:
        if not s["ok"]:
            tag = "PRIMARY" if s["primary"] else "secondary"
            print(f"  FAILED [{tag}] {s['source']} ({s['category']}): {s.get('error')}", file=sys.stderr)
    if not items:
        sys.exit(1)


if __name__ == "__main__":
    main()
