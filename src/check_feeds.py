"""Checks every feed in newspapers.json: does the address answer, and does it hold stories?

  python3 src/check_feeds.py                 all feeds
  python3 src/check_feeds.py Marca ESPN      only feeds of newspapers whose name contains one of these words

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


def check(feed):
    t0 = time.time()
    try:
        req = Request(feed["url"], headers={"User-Agent": fn.USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urlopen(req, timeout=fn.TIMEOUT) as resp:
            items = fn.parse_feed(resp.read())
    except Exception as exc:
        return "FAIL", 0, None, f"{type(exc).__name__}: {exc}"[:120]
    dates = [i["date"] for i in items if i["date"]]
    newest = (datetime.now(timezone.utc) - max(dates)).total_seconds() / 3600 if dates else None
    return ("OK" if items else "EMPTY"), len(items), newest, ""


def main(words):
    sections, newspapers = config.load_all()
    feeds = config.load_feeds(sections, newspapers)
    if words:
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
    print(f"\n{len(feeds)} feeds: {counts['OK']} OK, {counts['EMPTY']} empty, {counts['FAIL']} failed")


if __name__ == "__main__":
    main(sys.argv[1:])
