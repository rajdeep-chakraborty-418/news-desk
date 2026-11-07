"""Offline checks for the parser, image finder, country detection and section classifier.
Also writes a demo site/news.json (for previewing the page before the first real run)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fetch_news as fn
import geo

RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Test &amp; headline</title><link>https://example.com/a</link>
<pubDate>Sat, 07 Nov 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
<media:content url="http://img.example.com/a.jpg" medium="image"/></item>
<item><title>Body image</title><link>https://example.com/b</link>
<description>&lt;img src="//img.example.com/b.png" /&gt; text</description></item>
<item><title>Tracking pixel only</title><link>https://example.com/c</link>
<description>&lt;img src="https://x.com/pixel.gif"&gt;</description>
<enclosure url="https://img.example.com/c.jpg" type="image/jpeg"/></item></channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title><link rel="alternate" href="https://example.com/d"/>
<updated>2026-11-07T09:30:00Z</updated><summary>Short summary</summary></entry></feed>"""

a, b, c = fn.parse_feed(RSS)
assert a["title"] == "Test & headline" and a["summary"] == "Hello world" and a["date"].hour == 10
assert a["image"] == "https://img.example.com/a.jpg", a["image"]          # http -> https
assert b["image"] == "https://img.example.com/b.png", b["image"]          # image found in body html
assert c["image"] == "https://img.example.com/c.jpg", c["image"]          # tracking pixel skipped
d = fn.parse_feed(ATOM)[0]
assert d["link"] == "https://example.com/d" and d["date"].minute == 30 and d["image"] is None

assert geo.find_country("Putin warns Kyiv over missile strikes") == ("Russia", "Europe")
assert geo.find_country("nothing here", "Israeli forces enter Gaza") == ("Israel", "Asia")
assert geo.find_country("Quiet day in the markets") == (None, None)

feed_world = {"category": "world", "country": "United Kingdom", "continent": "Europe"}
assert fn.classify(feed_world, "Army chief warns of missile threat at border", "") == ["world", "geopolitics", "defence"]
assert fn.classify({"category": "india"}, "Budget session begins", "") == ["india"]
assert fn.classify({"category": "world", "general": True}, "Cricket final tonight", "") == ["world", "sports"]
assert fn.classify({"category": "world", "general": True}, "Ten recipes for winter wellness", "") == ["world", "lifestyle"]
assert fn.classify({"category": "world"}, "Sensex falls as investors watch inflation", "") == ["world", "business"]
assert fn.classify({"category": "world"}, "Researchers say ancient ruins found near river", "") == ["world", "science", "geography", "history"]
assert fn.classify({"category": "science"}, "Telescope finds new planet", "") == ["science"]
assert fn.classify({"category": "lifestyle"}, "Best travel spots", "") == ["lifestyle"]
assert fn.place({"category": "india"}, "Anything about Pakistan", "") == ("India", "Asia")
assert fn.place(feed_world, "Quiet day", "") == ("United Kingdom", "Europe")
print("all parser, image, country and section checks passed")

now = datetime.now(timezone.utc)
rows = [  # section(s), country, continent, source, primary, title
    (["india"], "India", "Asia", "Times of India", True, "Sample: Parliament session opens with budget debate"),
    (["india"], "India", "Asia", "The Hindu", True, "Sample: Monsoon recovery plan announced for southern states"),
    (["world"], "France", "Europe", "BBC", True, "Sample: European leaders meet in Paris on energy"),
    (["world", "geopolitics"], "United States", "North America", "New York Times", True, "Sample: Talks resume between Washington and allies"),
    (["world"], "Brazil", "South America", "The Rio Times", False, "Sample: Brazil confirms new trade partnership"),
    (["world"], "Kenya", "Africa", "AllAfrica", False, "Sample: Regional summit opens in Nairobi"),
    (["sports"], "India", "Asia", "Sportstar", True, "Sample: India name squad for the home series"),
    (["sports"], "United Kingdom", "Europe", "Goal.com", True, "Sample: Title race tightens after weekend fixtures"),
    (["sports"], "Australia", "Oceania", "Sydney Morning Herald", True, "Sample: Wallabies prepare for northern tour"),
    (["entertainment"], "India", "Asia", "NDTV", True, "Sample: Festival season releases line up at the box office"),
    (["entertainment"], "United States", "North America", "Variety", False, "Sample: Streaming awards nominations announced"),
    (["lifestyle"], "United Kingdom", "Europe", "The Guardian", True, "Sample: Winter wellness habits that actually stick"),
    (["lifestyle"], "India", "Asia", "Hindustan Times", True, "Sample: Five festive recipes for the long weekend"),
    (["business"], "India", "Asia", "The Hindu", True, "Sample: Markets close higher on banking gains"),
    (["technology"], "United States", "North America", "TechCrunch", False, "Sample: New chip design promises faster AI training"),
    (["history"], "Egypt", "Africa", "Smithsonian Magazine", False, "Sample: Archaeologists uncover ancient workshop"),
    (["geography"], "Iceland", "Europe", "Atlas Obscura", False, "Sample: Mapping the island's shifting glaciers"),
    (["science"], "United Kingdom", "Europe", "New Scientist", False, "Sample: Telescope spots a distant ocean world"),
    (["nature"], "Brazil", "South America", "Mongabay", False, "Sample: Rainforest recovery study shows steady gains"),
    (["defence"], "India", "Asia", "IDRW", False, "Sample: Navy commissions new patrol vessel"),
    (["defence", "geopolitics"], "Ukraine", "Europe", "Defense News", False, "Sample: Air defence deliveries discussed by allies"),
    (["geopolitics", "world"], "Egypt", "Africa", "Egypt Independent", False, "Sample: Diplomats meet in Cairo on regional security"),
]
items = [{
    "title": t, "link": "https://example.com/", "summary": "Demo tile. Real summaries come from each newspaper's feed.",
    "image": None, "published": (now - timedelta(minutes=25 * (i + 1))).isoformat(), "source": s, "primary": p,
    "category": secs[0], "sections": secs, "continent": cont, "country": ctry, "state": None,
} for i, (secs, ctry, cont, s, p, t) in enumerate(rows)]
Path("site/news.json").write_text(json.dumps(
    {"generated_at": now.isoformat(), "demo": True, "items": items, "feeds": []}, indent=1))
print("demo news.json written")
