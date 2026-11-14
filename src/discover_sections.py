"""Finds out which sections each configured newspaper has, so they can be mapped onto our own sections.

For every newspaper in legacy_newspapers.json it reads
  * the menu links on the newspaper's home page (the section names a reader sees),
  * the RSS addresses the home page advertises,
  * the <category> tags used by the newspaper's configured feeds (a second view of its own section names),
and writes everything to one JSON file (default: discovered_sections.json).
Run by .github/workflows/discover_sections.yml: the sites can only be reached from GitHub's runners.
"""
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import config
import fetch_news as fn

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NOISE = re.compile(r"\b(log ?in|sign ?(in|up)|subscribe|subscription|newsletters?|search|about( us)?|contact( us)?|privacy|terms|"
                   r"advertis\w*|careers?|jobs?|home|menu|follow|e-?paper|epaper|donate|support|help|faq|cookie\w*|"
                   r"my account|register|download|app|apps|podcasts?|rss|feeds?|more|skip|close|back|top|share|"
                   r"facebook|twitter|instagram|youtube|whatsapp|telegram|linkedin|mobile|sitemap|archive|"
                   r"membership|store|shop|events?|webinars?|write for us|our team|ethics|policies|licens\w*)\b", re.I)


class Menu(HTMLParser):
    """Collects <a> links that sit inside navigation-like containers, plus advertised RSS links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.links, self.rss = [], [], []
        self.href = self.text = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or "").lower() and "rss" in (a.get("type") or "").lower() or \
           tag == "link" and "alternate" in (a.get("rel") or "").lower() and "atom" in (a.get("type") or "").lower():
            if a.get("href"):
                self.rss.append({"url": a["href"], "title": (a.get("title") or "").strip()})
        if tag in ("script", "style", "noscript", "svg", "footer"):
            self.stack.append((tag, False, True))
            return
        ident = ((a.get("class") or "") + " " + (a.get("id") or "") + " " + (a.get("role") or "") + " " + (a.get("aria-label") or "")).lower()
        navlike = tag == "nav" or bool(re.search(r"\b(nav|menu|topbar|mainmenu|sections?|categories|header-links)", ident)) or tag == "header"
        foot = bool(re.search(r"footer|foot-", ident))
        if tag not in ("br", "img", "meta", "link", "input", "hr"):
            self.stack.append((tag, navlike, foot))
        if tag == "a" and a.get("href") and any(n for _, n, _ in self.stack) and not any(f for _, _, f in self.stack):
            self.href, self.text = a["href"], []

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join("".join(self.text).split())))
            self.href = self.text = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)


def host(u):
    h = urlparse(u).netloc.lower()
    return re.sub(r"^(www|m|amp)\.", "", h)


def get(url, limit=1_500_000):
    req = Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,application/xml,*/*"})
    with urlopen(req, timeout=25) as resp:
        return resp.read(limit).decode(resp.headers.get_content_charset() or "utf-8", "replace"), resp.geturl()


def menu_links(html, base):
    p = Menu()
    try:
        p.feed(html)
    except Exception:
        pass
    root = host(base)
    out, seen = [], set()
    for href, text in p.links:
        if not (2 <= len(text) <= 34) or NOISE.search(text) or re.fullmatch(r"[\W\d_]+", text):
            continue
        url = urljoin(base, href)
        u = urlparse(url)
        if u.scheme not in ("http", "https") or url.rstrip("/") == base.rstrip("/"):
            continue
        # same site (or a subdomain of it); skip pure anchors and deep article-looking paths
        if not (host(url) == root or host(url).endswith("." + root) or root.endswith("." + host(url))):
            continue
        if len([s for s in u.path.split("/") if s]) > 3 or u.path in ("", "/"):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text, "url": url})
        if len(out) >= 70:
            break
    rss = []
    for r in p.rss:
        r["url"] = urljoin(base, r["url"])
        if r not in rss:
            rss.append(r)
    return out, rss[:12]


def feed_categories(feeds):
    """The <category> tags of the newspaper's configured feeds, most common first."""
    cnt = Counter()
    for f in feeds:
        if "news.google.com" in f["url"]:
            continue
        try:
            req = Request(f["url"], headers={"User-Agent": fn.USER_AGENT})
            with urlopen(req, timeout=20) as resp:
                data = resp.read(3_000_000)
            import xml.etree.ElementTree as ET
            for e in ET.fromstring(data).iter():
                if fn.local(e.tag) == "category":
                    t = (e.text or e.attrib.get("term") or "").strip()
                    if t and len(t) < 40:
                        cnt[t] += 1
        except Exception:
            continue
    return cnt.most_common(25)


def discover(paper):
    res = {"name": paper["name"], "tier": paper["tier"], "homepage": paper["homepage"], "country": paper.get("country", ""),
           "configured": [{"section": f["section"], "url": f["url"]} for f in paper["feeds"]], "menu": [], "rss": [],
           "feed_categories": [], "error": ""}
    try:
        html, final = get(paper["homepage"])
        res["menu"], res["rss"] = menu_links(html, final)
    except Exception as exc:
        res["error"] = f"{type(exc).__name__}: {exc}"[:160]
    try:
        res["feed_categories"] = feed_categories(paper["feeds"][:6])
    except Exception:
        pass
    return res


def main(out="discovered_sections.json"):
    raw = json.load(open(config.config_dir() / "legacy_newspapers.json", encoding="utf-8"))
    papers = [dict(n, tier=t) for t in ("primary", "secondary") for n in raw[t]]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(discover, papers))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in results:      # one compact line per newspaper, so the result can be read from the workflow log
        print("DISC|" + json.dumps({"n": r["name"], "t": r["tier"], "e": r["error"][:60],
              "m": [[m["text"], urlparse(m["url"]).path] for m in r["menu"]], "r": [x["url"] for x in r["rss"]][:6],
              "c": r["feed_categories"][:20]}, ensure_ascii=False, separators=(",", ":")))
    ok = sum(1 for r in results if r["menu"])
    print(f"{len(results)} newspapers; {ok} with menu links; "
          f"{sum(1 for r in results if r['error'])} home pages unreachable; {sum(1 for r in results if r['feed_categories'])} with feed categories")


if __name__ == "__main__":
    main(*sys.argv[1:])
