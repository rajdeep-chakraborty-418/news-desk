"""TEMPORARY: share of non-English (non-Latin script) headlines in each Indian newspaper's feeds."""
import sys, json, unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
import config, fetch_news as fn

def nonlatin(t):
    letters = [c for c in t if c.isalpha()]
    return sum(1 for c in letters if ord(c) > 0x24F) / len(letters) if letters else 0

raw = config.load_newspapers(config.load_sections())
rows = [(n["name"], f["url"], f["section"]) for t in ("primary", "secondary") for n in raw[t] if n.get("country") == "India" for f in n["feeds"]]
def one(r):
    name, url, sec = r
    try:
        req = Request(url, headers={"User-Agent": fn.USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        items = fn.parse_feed(urlopen(req, timeout=25).read())
    except Exception as e:
        return name, url, sec, None, 0, str(e)[:40], ""
    t = [i["title"] for i in items if i["title"]]
    share = sum(1 for x in t if nonlatin(x) > 0.5) / len(t) if t else None
    return name, url, sec, share, len(t), "", (t[0][:50] if t else "")
with ThreadPoolExecutor(12) as ex:
    for r in ex.map(one, rows):
        print("LANG|" + json.dumps(r, ensure_ascii=False), flush=True)
