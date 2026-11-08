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
assert fn.classify({"category": "bengali"}, "army and budget", "") == ["bengali"]
assert fn.place({"category": "bengali", "country": "Bangladesh", "continent": "Asia"}, "শিরোনাম", "") == ("Bangladesh", "Asia")
assert fn.parse_feed(b'<rss><channel><item><title>Ancient city - National Geographic</title><link>https://n.example/1</link><source url="x">National Geographic</source></item></channel></rss>')[0]["title"] == "Ancient city"
assert fn.classify({"category": "india"}, "Bollywood actor announces new film", "") == ["india", "entertainment"]
assert fn.classify({"category": "world"}, "Budget session begins in parliament", "") == ["world"]
assert "entertainment" in fn.classify({"category": "world"}, "Grammy nominations announced", "")
assert fn.classify({"category": "lifestyle"}, "Best travel spots", "") == ["lifestyle"]
assert fn.place({"category": "india"}, "Anything about Pakistan", "") == ("India", "Asia")
assert fn.place(feed_world, "Quiet day", "") == ("United Kingdom", "Europe")
# --- image choice: largest wins, BBC thumbnails upgraded, article-page image parsing ---
GUARDIAN = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>G</title><link>https://g.example/1</link>
<media:content width="140" url="https://i.guim.co.uk/img/a.jpg?width=140&amp;s=1"/><media:content width="460" url="https://i.guim.co.uk/img/a.jpg?width=460&amp;s=2"/></item></channel></rss>"""
assert fn.parse_feed(GUARDIAN)[0]["image"].endswith("width=460&s=2"), fn.parse_feed(GUARDIAN)[0]["image"]
BBC = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>B</title><link>https://b.example/1</link>
<media:thumbnail width="240" height="135" url="https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/ab12/live/x.jpg"/></item></channel></rss>"""
assert fn.parse_feed(BBC)[0]["image"] == "https://ichef.bbci.co.uk/ace/standard/800/cpsprodpb/ab12/live/x.jpg"
UNKNOWN_VS_SMALL = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>U</title><link>https://u.example/1</link>
<media:content width="100" url="https://x.example/tiny.jpg"/><media:content url="https://x.example/unknown.jpg"/></item></channel></rss>"""
assert fn.parse_feed(UNKNOWN_VS_SMALL)[0]["image"].endswith("unknown.jpg")
OG = ('<html><head><meta property="og:title" content="t"><meta content="/img/lead.jpg?x=1&amp;y=2" property="og:image">'
      '<meta name="twitter:image" content="https://t.example/other.jpg"></head></html>')
assert fn.og_image(OG, "https://news.example/a/b") == "https://news.example/img/lead.jpg?x=1&y=2"
assert fn.og_image("<html><head></head></html>", "https://news.example/") is None

# --- time window: allowed values, default, Google News rewrite, per-feed limit ---
import os
for val, want in (("6", 6), ("12", 12), ("24", 24), ("72", 72), ("168", 168), ("720", 720), ("2160", 2160),
                  ("5", 24), ("abc", 24), ("", 24), ("-1", 24)):
    os.environ["WINDOW_HOURS"] = val
    assert fn.window_hours() == want, (val, fn.window_hours())
del os.environ["WINDOW_HOURS"]
assert fn.window_hours() == 24
g = "https://news.google.com/rss/search?q=site%3Agoal.com%20when%3A3d&hl=en-US&gl=US&ceid=US:en"
assert "when%3A6h" in fn.window_url(g, 6) and "when%3A72h" in fn.window_url(g, 72)
assert "when%3A7d" in fn.window_url(g, 168) and "when%3A30d" in fn.window_url(g, 720) and "when%3A90d" in fn.window_url(g, 2160)
assert fn.window_url("https://x.example/feed", 6) == "https://x.example/feed"
assert [fn.per_feed_limit(h) for h in (6, 24, 72, 168, 720, 2160)] == [20, 20, 30, 50, 80, 100]

# --- the window really filters stories ---
from unittest import mock
def feed_xml(ages_hours):
    items = "".join(f"<item><title>S{h}</title><link>https://n.example/{h}</link><pubDate>"
                    f"{(datetime.now(timezone.utc) - timedelta(hours=h)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
                    for h in ages_hours)
    return f"<rss><channel>{items}</channel></rss>".encode()
class FakeResp:
    def __init__(self, data): self.data = data
    def read(self, n=-1): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False
feed = {"source": "T", "category": "world", "url": "https://n.example/feed", "country": "India", "continent": "Asia", "primary": True}
with mock.patch.object(fn, "urlopen", lambda *a, **k: FakeResp(feed_xml([1, 5, 11, 20, 50, 100, 400, 1000, 3000]))):
    for hours, expect in ((6, 2), (12, 3), (24, 4), (72, 5), (168, 6), (720, 7), (2160, 8)):
        fn.WINDOW_HOURS = hours
        out, st = fn.fetch_one(feed)
        assert len(out) == expect, (hours, len(out), expect)
fn.WINDOW_HOURS = 24

# --- trimming keeps each section's newest stories ---
def mk(n, secs, primary=False, hours=0):
    return {"link": f"l{n}", "sections": secs, "primary": primary, "published": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}
many = [mk(i, ["world"], hours=i) for i in range(10)] + [mk(100 + i, ["nature"], hours=i) for i in range(3)]
kept = fn.trim_sections(many, keep=4)
assert sum("world" in i["sections"] for i in kept) == 4 and sum("nature" in i["sections"] for i in kept) == 3
assert {i["link"] for i in kept if "world" in i["sections"]} == {"l0", "l1", "l2", "l3"}

print("all parser, image, country and section checks passed")

now = datetime.now(timezone.utc)
rows = [  # section(s), country, continent, source, primary, title
    (["bengali"], "India", "Asia", "Anandabazar Patrika", True, "নমুনা: কলকাতায় শীতের আমেজ, তাপমাত্রা নামল"),
    (["bengali"], "India", "Asia", "ABP Ananda (ABP Live Bangla)", True, "নমুনা: রাজ্যের বিভিন্ন জেলায় ভোট প্রস্তুতি শুরু"),
    (["bengali"], "Bangladesh", "Asia", "Prothom Alo", False, "নমুনা: ঢাকায় নতুন মেট্রোরেল পরিষেবার ঘোষণা"),
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
