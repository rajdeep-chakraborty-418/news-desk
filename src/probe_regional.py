"""TEMPORARY: menu, advertised feeds and feed tags of the new regional newspapers (run from GitHub's runners)."""
import sys, json
sys.path.insert(0, "src")
import config, discover_sections as ds
NAMES = {"Navbharat Times","Prabhat Khabar","Aajkaal","Ei Samay","Maharashtra Times","Dina Thanthi","Dinamani","Vaartha","Prajavani","Vijay Karnataka","Kannada Prabha","Mathrubhumi","Madhyamam","Sambad","Dharitri","Asomiya Pratidin"}
raw = config.load_newspapers(config.load_sections())
papers = [dict(n, tier=t) for t in ("primary", "secondary") for n in raw[t] if n["name"] in NAMES]
print("PAPERS", len(papers))
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(8) as ex:
    for r in ex.map(ds.discover, papers):
        print("DISC|" + json.dumps({"n": r["name"], "e": r["error"][:80], "m": [[m["text"], m["url"]] for m in r["menu"]][:60], "r": [x["url"] for x in r["rss"]][:12], "c": r["feed_categories"][:40]}, ensure_ascii=False, separators=(",", ":")), flush=True)
