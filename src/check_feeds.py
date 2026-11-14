"""Checks every feed in external_config/newspaper_sections/: does the address answer, and does it hold stories?

  python3 src/check_feeds.py                 all feeds
  python3 src/check_feeds.py Marca ESPN      only feeds of newspapers whose name contains one of these words
  python3 src/check_feeds.py https://...     try these addresses directly (to find a replacement for a broken feed)

Prints one line per feed (OK / EMPTY / FAIL, how many stories it holds, the newest story's age) and a summary.
Run by .github/workflows/check_feeds.yml, because the feeds can only be reached from GitHub's runners.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import config
import fetch_news as fn


ITEMS = {}      # feed url -> its parsed stories (used for the detail lines)


def check(feed):
    t0 = time.time()
    try:
        req = Request(feed["url"], headers={"User-Agent": fn.USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urlopen(req, timeout=fn.TIMEOUT) as resp:
            items = fn.parse_feed(resp.read())
    except Exception as exc:
        return "FAIL", 0, None, f"{type(exc).__name__}: {exc}"[:120]
    ITEMS[feed["url"]] = items
    dates = [i["date"] for i in items if i["date"]]
    newest = (datetime.now(timezone.utc) - max(dates)).total_seconds() / 3600 if dates else None
    return ("OK" if items else "EMPTY"), len(items), newest, ""


def main(words):
    detail = bool(words) and words[0] == "detail"          # "detail": every feed, with tags and classification
    if detail:
        words = words[1:]
    sections, feeds = config.load_all()
    if words and all(w.startswith("http") for w in words):
        feeds = [{"newspaper": "candidate", "section": "-", "url": w} for w in words]
    elif words:
        feeds = [f for f in feeds if any(w.lower() in f["newspaper"].lower() for w in words)]
    plain = [f for f in feeds if "news.google.com" not in f["url"]]
    google = [f for f in feeds if "news.google.com" in f["url"]]
    results = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for f, r in zip(plain, pool.map(check, plain)):
            results[id(f)] = r
    for f in google:                                   # Google News throttles: one at a time with a pause
        results[id(f)] = check(f)
        time.sleep(1.5)
    counts = {"OK": 0, "EMPTY": 0, "FAIL": 0}
    for f in feeds:
        state, n, newest, err = results[id(f)]
        counts[state] += 1
        age = f"newest {newest:.0f}h old" if newest is not None else "no dates"
        print(f"{state:5} {f['newspaper'][:28]:28} {f['section']:13} {n:4} stories, {age}  {f['url']}  {err}")
    if detail or (words and not all(w.startswith("http") for w in words)):     # newspaper names given (or "detail"): show how its stories are classified
        maps = config.load_section_maps(sections)
        fn.configure(sections, maps=maps)
        for f in feeds:
            items = ITEMS.get(f["url"], [])
            tags = {}
            for i in items:
                for t in i.get("tags", []):
                    tags[t] = tags.get(t, 0) + 1
            print(f"DETAIL {f['newspaper']} | {f['url']}: {len(items)} stories; tags: {sorted(tags.items(), key=lambda x: -x[1])[:25]}")
            by = {}
            for i in items:
                for sec in fn.classify(f, i["title"], i["summary"], i["link"], i.get("tags")):
                    by[sec] = by.get(sec, 0) + 1
            print(f"DETAIL   sections: {by}")
            for i in items[:4]:
                print(f"DETAIL   e.g. {i['link']}  tags={i.get('tags')}")
    print(f"\n{len(feeds)} feeds: {counts['OK']} OK, {counts['EMPTY']} empty, {counts['FAIL']} failed")


if __name__ == "__main__":
    main(sys.argv[1:])
