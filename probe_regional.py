"""TEMPORARY: finds working feeds for regional-language newspapers (run from GitHub's runners)."""
import re, sys, json, time
sys.path.insert(0, "src")
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin
import fetch_news as fn

PAPERS = {
 "Dainik Jagran": ["https://www.jagran.com"], "Hindustan (Live Hindustan)": ["https://www.livehindustan.com"],
 "Navbharat Times": ["https://navbharattimes.indiatimes.com"], "Patrika": ["https://www.patrika.com"],
 "Jansatta": ["https://www.jansatta.com"], "Punjab Kesari": ["https://www.punjabkesari.in"], "Prabhat Khabar": ["https://www.prabhatkhabar.com"],
 "Dainik Bhaskar": ["https://www.bhaskar.com"], "Amar Ujala": ["https://www.amarujala.com"],
 "Anandabazar Patrika": ["https://www.anandabazar.com"], "Bartaman": ["https://bartamanpatrika.com"], "Aajkaal": ["https://www.aajkaal.in"],
 "Ei Samay": ["https://eisamay.com"], "Ganashakti": ["https://www.ganashakti.com"], "Sangbad Pratidin": ["https://www.sangbadpratidin.in"],
 "Uttarbanga Sambad": ["https://uttarbangasambad.com"],
 "Lokmat": ["https://www.lokmat.com"], "Maharashtra Times": ["https://maharashtratimes.com"], "Sakal": ["https://www.esakal.com"],
 "Loksatta": ["https://www.loksatta.com"], "Pudhari": ["https://pudhari.news"], "Saamana": ["https://www.saamana.com"],
 "Gujarat Samachar": ["https://www.gujaratsamachar.com"], "Sandesh": ["https://sandesh.com"], "Divya Bhaskar": ["https://www.divyabhaskar.co.in"],
 "Gujarat Mitra": ["https://www.gujaratmitra.in"], "Abtak": ["https://www.abtakmedia.com"],
 "Dina Thanthi": ["https://www.dailythanthi.com"], "Dinamalar": ["https://www.dinamalar.com"], "Dinakaran": ["https://www.dinakaran.com"],
 "Dinamani": ["https://www.dinamani.com"], "The Hindu Tamil": ["https://www.hindutamil.in"],
 "Eenadu": ["https://www.eenadu.net"], "Sakshi": ["https://www.sakshi.com"], "Andhra Jyothy": ["https://www.andhrajyothy.com"],
 "Namasthe Telangana": ["https://www.ntnews.com"], "Vaartha": ["https://www.vaartha.com"],
 "Prajavani": ["https://www.prajavani.net"], "Vijay Karnataka": ["https://vijaykarnataka.com"], "Vijayavani": ["https://www.vijayavani.net"],
 "Kannada Prabha": ["https://www.kannadaprabha.com"], "Udayavani": ["https://www.udayavani.com"],
 "Malayala Manorama": ["https://www.manoramaonline.com"], "Mathrubhumi": ["https://www.mathrubhumi.com"], "Deshabhimani": ["https://www.deshabhimani.com"],
 "Madhyamam": ["https://www.madhyamam.com"], "Mangalam": ["https://www.mangalam.com"], "Kerala Kaumudi": ["https://keralakaumudi.com"],
 "Sambad": ["https://sambad.in"], "Dharitri": ["https://www.dharitri.com"], "Samaja": ["https://thesamaja.in"], "Pragativadi": ["https://pragativadi.com"],
 "Jagbani": ["https://jagbani.punjabkesari.in"], "Ajit": ["https://www.ajitjalandhar.com"], "Rozana Spokesman": ["https://www.rozanaspokesman.com"],
 "Asomiya Pratidin": ["https://www.asomiyapratidin.in"], "Amar Asom": ["https://www.amarasom.com"], "Dainik Janambhumi": ["https://www.dainikjanambhumi.co.in"],
}
PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/rss/", "/feeds", "/feeds/rss", "/rssfeeds", "/feed.xml", "/rss/feed", "/rssfeed.xml", "/news/rss", "/rss/latest.xml"]
HDR = {"User-Agent": fn.USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*"}

def get(url, limit=400000):
    with urlopen(Request(url, headers=HDR), timeout=20) as r:
        return r.read(limit)

def try_feed(url):
    try:
        items = fn.parse_feed(get(url, 3000000))
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:60]}"
    if not items:
        return None, "empty"
    dates = [i["date"] for i in items if i["date"]]
    age = round((datetime.now(timezone.utc) - max(dates)).total_seconds() / 3600, 1) if dates else None
    return {"url": url, "n": len(items), "age_h": age, "sample": items[0]["title"][:70]}, ""

def probe(name):
    home = PAPERS[name][0]; cands = []; note = ""
    try:
        html = get(home).decode("utf-8", "ignore")
        for m in re.finditer(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', html, re.I):
            h = re.search(r'href=["\']([^"\']+)', m.group(0))
            if h: cands.append(urljoin(home, h.group(1)))
        for m in re.finditer(r'href=["\']([^"\']*(?:rss|feed)[^"\']*\.(?:xml|rss)[^"\']*)["\']', html, re.I):
            cands.append(urljoin(home, m.group(1)))
    except Exception as e:
        note = f"homepage {type(e).__name__}: {str(e)[:50]}"
    cands += [home + p for p in PATHS]
    seen, good, errs = set(), [], []
    for c in cands:
        if c in seen: continue
        seen.add(c)
        ok, err = try_feed(c)
        if ok: good.append(ok)
        else: errs.append(err)
        if len(good) >= 4: break
    return {"name": name, "note": note, "good": good, "tried": len(seen), "errs": sorted(set(errs))[:3]}

with ThreadPoolExecutor(12) as ex:
    for r in ex.map(probe, list(PAPERS)):
        print("RESULT|" + json.dumps(r, ensure_ascii=False), flush=True)
