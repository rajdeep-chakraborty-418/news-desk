"""Offline check of the RSS/Atom parser, plus generation of a demo site/news.json."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fetch_news as fn

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Test &amp; headline</title><link>https://example.com/a</link>
<pubDate>Sat, 07 Nov 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item></channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title><link rel="alternate" href="https://example.com/b"/>
<updated>2026-11-07T09:30:00Z</updated><summary>Short summary</summary></entry></feed>"""

r = fn.parse_feed(RSS)[0]
assert r["title"] == "Test & headline" and r["summary"] == "Hello world" and r["date"].hour == 10, r
a = fn.parse_feed(ATOM)[0]
assert a["link"] == "https://example.com/b" and a["date"].minute == 30, a
print("parser OK")

now = datetime.now(timezone.utc)
demo = [
    ("sports", "Asia", "The Hindu", "Sample: Cricket series decider set for Sunday"),
    ("sports", "Europe", "BBC Sport", "Sample: Title race tightens after weekend fixtures"),
    ("sports", "Africa", "News24", "Sample: Springboks name squad for autumn tour"),
    ("sports", "North America", "CBC Sports", "Sample: Playoff picture clears up in the east"),
    ("sports", "South America", "The Rio Times", "Sample: Copa semifinal line-ups confirmed"),
    ("sports", "Oceania", "ABC News Australia", "Sample: Wallabies prepare for northern tour"),
    ("geopolitics", "Asia", "Straits Times", "Sample: Regional leaders meet on trade framework"),
    ("geopolitics", "Europe", "Deutsche Welle", "Sample: EU ministers discuss energy security"),
    ("geopolitics", "Africa", "Premium Times", "Sample: Continental bloc convenes on security"),
    ("geopolitics", "North America", "NPR", "Sample: Congress debates foreign aid package"),
    ("geopolitics", "South America", "MercoPress", "Sample: Mercosur talks resume on trade deal"),
    ("geopolitics", "Oceania", "RNZ", "Sample: Pacific forum issues joint statement"),
]
items = [{
    "title": t, "link": "https://example.com/", "summary": "Demo tile. Real summaries come from each newspaper's feed.",
    "published": (now - timedelta(minutes=25 * (i + 1))).isoformat(),
    "source": s, "continent": c, "category": cat,
} for i, (cat, c, s, t) in enumerate(demo)]
Path("site/news.json").write_text(json.dumps(
    {"generated_at": now.isoformat(), "demo": True, "items": items, "feeds": []}, indent=1))
print("demo news.json written")
