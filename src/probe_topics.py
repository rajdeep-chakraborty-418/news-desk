"""TEMPORARY: headline topics on live Bengali headlines (run from GitHub's runners)."""
import json, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import config, fetch_news as fn, topics, topic_words

sections, feeds = config.load_all()
fn.configure(sections, maps=config.load_section_maps(sections))
fn.WINDOW_HOURS, fn.ARTICLE_COUNT = 24, 3000
bn = [f for f in feeds if f["category"] == "bengali"]
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(fn.fetch_one, bn))
by = {}
for out, st in res:
    for it in out:
        by.setdefault(it["link"], it)
items = [i for i in by.values() if "bengali" in i["sections"]]
print("PROBE|" + json.dumps({"stories": len(items), "papers": dict(Counter(i["newspaper"] for i in items))}, ensure_ascii=False))
spec = {"min_count": 8, "min_newspapers": 2, "max_topics": 12, "stopwords": set(), "hide": set(), "native_only": True}
found, order = topics.headline_topics(items, spec)
for label in order:
    ids = sorted(found[label])[:4]
    print("PROBE|" + json.dumps({"topic": label, "n": len(found[label]), "papers": len({items[p]["newspaper"] for p in found[label]}),
                                 "ex": [items[p]["title"][:70] for p in ids]}, ensure_ascii=False))
# the commonest stems overall, to spot filler words that should be stopwords
stop = set(topic_words.BENGALI_STOP) | set(topic_words.ENGLISH_STOP)
df = Counter()
for it in items:
    seen = set()
    for w in topics._words(it["title"]):
        low = w.lower(); st = topics.stem(low)
        if low in stop or st in stop or st in seen: continue
        seen.add(st); df[st] += 1
print("PROBE|" + json.dumps({"top_stems": df.most_common(70)}, ensure_ascii=False))
