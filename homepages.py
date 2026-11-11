"""Works out each newspaper's own homepage from feeds.json and builds the list for the page's Newspapers dropdown.

A feed's address often points at a feed host (feeds.bbci.co.uk, feedburner, an Amazon bucket) rather than the paper,
so HOST_HOME fixes those hosts and SOURCE_HOME fixes single sources; everything else is https://<host without feed prefixes>/.
Feeds of the same paper (e.g. Times of India city editions) collapse into one entry, labelled with the shortest name."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HOST_HOME = {
    "feeds.bbci.co.uk": "https://www.bbc.com/news", "rss.nytimes.com": "https://www.nytimes.com/",
    "feeds.arstechnica.com": "https://arstechnica.com/", "feeds.businessinsider.com": "https://www.businessinsider.com/",
    "feeds.ign.com": "https://www.ign.com/", "feeds.marketwatch.com": "https://www.marketwatch.com/",
    "feeds.npr.org": "https://www.npr.org/", "feeds.skynews.com": "https://news.sky.com/",
    "feeds.washingtonpost.com": "https://www.washingtonpost.com/", "rss.dw.com": "https://www.dw.com/en/",
    "rss.sciam.com": "https://www.scientificamerican.com/", "prod-qt-images.s3.amazonaws.com": "https://www.deccanherald.com/",
    "deccanherald.com": "https://www.deccanherald.com/", "cr-news-api-service.prd.crunchyrollsvc.com": "https://www.crunchyroll.com/news",
    "www3.nhk.or.jp": "https://www3.nhk.or.jp/nhkworld/", "www.news.cn": "https://english.news.cn/",
    "e.vnexpress.net": "https://e.vnexpress.net/", "en.prothomalo.com": "https://en.prothomalo.com/",
    "bengali.abplive.com": "https://bengali.abplive.com/", "news.abplive.com": "https://news.abplive.com/",
    "en.mercopress.com": "https://en.mercopress.com/", "en.yna.co.kr": "https://en.yna.co.kr/",
    "asia.nikkei.com": "https://asia.nikkei.com/", "daily.jstor.org": "https://daily.jstor.org/",
    "e360.yale.edu": "https://e360.yale.edu/", "earthquake.usgs.gov": "https://earthquake.usgs.gov/earthquakes/map/",
    "googlemapsmania.blogspot.com": "https://googlemapsmania.blogspot.com/", "india.mongabay.com": "https://india.mongabay.com/",
    "news.mongabay.com": "https://news.mongabay.com/", "sports.yahoo.com": "https://sports.yahoo.com/",
    "sportstar.thehindu.com": "https://sportstar.thehindu.com/", "economictimes.indiatimes.com": "https://economictimes.indiatimes.com/",
    "timesofindia.indiatimes.com": "https://timesofindia.indiatimes.com/", "zeenews.india.com": "https://zeenews.india.com/",
    "spectator.sme.sk": "https://spectator.sme.sk/", "www.thelocal.se": "https://www.thelocal.se/",
}
SOURCE_HOME = {
    "BBC Bangla": "https://www.bbc.com/bengali", "The Athletic": "https://www.nytimes.com/athletic/",
    "Zee 24 Ghanta (Zee Bangla)": "https://zeenews.india.com/bengali", "Mid-day": "https://www.mid-day.com/",
    "Mirror": "https://www.mirror.co.uk/", "India Today": "https://www.indiatoday.in/",
    "The Indian Express": "https://indianexpress.com/", "Firstpost": "https://www.firstpost.com/",
    "Hindustan Times Brunch": "https://www.hindustantimes.com/", "Archaeology News (Phys.org)": "https://phys.org/",
    "Earth Sciences (Phys.org)": "https://phys.org/", "Nikkei Asia Business": "https://asia.nikkei.com/",
    "The Guardian Australia": "https://www.theguardian.com/au", "RNZ Pacific": "https://www.rnz.co.nz/",
    "Deadline (Google News)": "https://deadline.com/", "Variety (Google News)": "https://variety.com/",
    "Hollywood Reporter (Google News)": "https://www.hollywoodreporter.com/",
    "NDTV": "https://www.ndtv.com/", "Vulture": "https://www.vulture.com/", "Gadgets 360": "https://www.gadgets360.com/", "Scroll.in": "https://scroll.in/",
    "Cannes/Film Festivals": None,   # a topic search, not a newspaper: left out of the dropdown
}
HOME_ALIASES = {"https://www.thehindu.com/": "https://www.thehindu.com/"}


def feed_host(url):
    p = urlparse(url)
    if "news.google.com" in p.netloc:
        m = re.search(r"site:([^\s/]+)", parse_qs(p.query).get("q", [""])[0])
        return m.group(1) if m else ""
    return p.netloc


def homepage(feed):
    name = feed["source"]
    if name in SOURCE_HOME:
        return SOURCE_HOME[name]
    host = feed_host(feed["url"])
    if not host:
        return None
    if host in HOST_HOME:
        return HOST_HOME[host]
    return "https://" + host + "/"


def build_papers(feeds):
    groups = {}
    for f in feeds:
        url = homepage(f)
        if not url:
            continue
        key = urlparse(url).netloc.removeprefix("www.") + urlparse(url).path.rstrip("/")
        g = groups.setdefault(key, {"name": f["source"], "url": url, "country": f["country"],
                                    "continent": f["continent"], "primary": False})
        if len(f["source"]) < len(g["name"]):
            g["name"] = f["source"]
        g["primary"] = g["primary"] or bool(f.get("primary"))
    papers = list(groups.values())
    for p in papers:   # "Variety (Google News)", "Daily Mail Showbiz" ... -> the paper's plain name
        p["name"] = re.sub(r"\s+(Entertainment|Showbiz|Brunch)$|\s+\(Google News\)$", "", p["name"])
    return sorted(papers, key=lambda p: re.sub(r"^the\s+", "", p["name"].lower()))


if __name__ == "__main__":
    feeds = json.loads(Path(__file__).with_name("feeds.json").read_text())
    papers = build_papers(feeds)
    out = Path(__file__).with_name("site") / "papers.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(papers, ensure_ascii=False, indent=0))
    print(len(papers), "newspapers ->", out)
