"""TEMPORARY: what the headline engine would produce for India and World on the deployed data."""
import json, sys, urllib.request
import topics
BASE = "https://rajdeep-chakraborty-418.github.io/news-desk/data/"
for key in ("india", "world"):
    d = json.load(urllib.request.urlopen(BASE + key + ".json"))
    items = [i for i in d["items"] if key in i["sections"]]
    spec = {"min_count": 8, "min_newspapers": 2, "max_topics": 30, "stopwords": set(), "hide": set(), "native_only": False}
    found, order = topics.headline_topics(items, spec)
    print("PROBE|%s stories=%d papers=%d" % (key, len(items), len({i.get('newspaper') or i.get('source') for i in items})))
    for t in order:
        mem = [items[j] for j in sorted(found[t])]
        ex = [i["title"] for i in mem][:3]
        print("PROBE|%s|%s|%d|%d|%s" % (key, t, len(mem), len({i.get('newspaper') or i.get('source') for i in mem}), " || ".join(ex)))
