#!/usr/bin/env python3
"""Fetch headlines from newspaper RSS/Atom feeds and write site/news.json.

Standard library only, so it runs anywhere (including GitHub Actions) with no installs.
Only headline, source, time, a short snippet and the link back to the original are stored.
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

ROOT = Path(__file__).parent
FEEDS_FILE = ROOT / "feeds.json"
OUT_FILE = ROOT / "site" / "news.json"

PER_FEED_LIMIT = 10      # newest N items per feed
MAX_AGE_DAYS = 3         # drop anything older than this
TIMEOUT = 20
USER_AGENT = "NewsHubBot/1.0 (headline aggregator; links back to originals)"
SNIPPET_LEN = 160


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
            summary = summary[: SNIPPET_LEN].rsplit(" ", 1)[0] + "…"
        items.append({"title": title, "link": link, "date": date, "summary": summary})
    return items


def fetch_one(feed):
    status = {"source": feed["source"], "category": feed["category"], "url": feed["url"], "ok": False, "count": 0}
    try:
        req = Request(feed["url"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        items = parse_feed(data)
    except Exception as exc:  # one broken feed must never break the build
        status["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return [], status

    keywords = [k.lower() for k in feed.get("keywords", [])]
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    out = []
    for it in items:
        if keywords and not any(k in (it["title"] + " " + it["summary"]).lower() for k in keywords):
            continue
        if it["date"] and it["date"] < cutoff:
            continue
        out.append({
            "title": it["title"],
            "link": it["link"],
            "summary": it["summary"],
            "published": (it["date"] or datetime.now(timezone.utc)).isoformat(),
            "source": feed["source"],
            "continent": feed["continent"],
            "category": feed["category"],
        })
    out.sort(key=lambda x: x["published"], reverse=True)
    out = out[:PER_FEED_LIMIT]
    status.update(ok=True, count=len(out))
    return out, status


def main():
    feeds = json.loads(FEEDS_FILE.read_text())
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch_one, feeds))

    seen, items, statuses = set(), [], []
    for feed_items, status in results:
        statuses.append(status)
        for it in feed_items:
            key = (it["link"], it["category"])
            if key not in seen:
                seen.add(key)
                items.append(it)
    items.sort(key=lambda x: x["published"], reverse=True)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "feeds": statuses,
    }, ensure_ascii=False, indent=1))

    ok = sum(s["ok"] for s in statuses)
    print(f"{len(items)} items from {ok}/{len(statuses)} feeds -> {OUT_FILE}")
    for s in statuses:
        if not s["ok"]:
            print(f"  FAILED {s['source']} ({s['category']}): {s.get('error')}", file=sys.stderr)
    # Fail the build only if nothing at all worked, so the old site stays up.
    if not items:
        sys.exit(1)


if __name__ == "__main__":
    main()
