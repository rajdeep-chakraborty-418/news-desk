"""TEMPORARY: tag frequencies across all Bengali feeds."""
import json, collections
from urllib.request import Request, urlopen
import config, fetch_news as fn
raw = config.load_newspapers(config.load_sections())
total = collections.Counter(); per = collections.defaultdict(collections.Counter); n_items = collections.Counter()
for t in ("primary", "secondary"):
    for n in raw[t]:
        for f in n["feeds"]:
            if f["section"] != "bengali": continue
            try:
                req = Request(f["url"], headers={"User-Agent": fn.USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
                items = fn.parse_feed(urlopen(req, timeout=25).read())
            except Exception as e:
                print("TAGS|" + json.dumps({"n": n["name"], "err": str(e)[:50]}, ensure_ascii=False)); continue
            n_items[n["name"]] += len(items)
            for it in items:
                for tg in it.get("tags") or []:
                    tg = tg.strip()
                    if tg: total[tg] += 1; per[n["name"]][tg] += 1
print("TAGS|" + json.dumps({"items": dict(n_items), "top": total.most_common(150), "per": {k: v.most_common(25) for k, v in per.items()}}, ensure_ascii=False))
