#!/usr/bin/env python3
"""Diagnostic: fetch a sample of the image URLs in site/news.json the way a browser would (no Referer)
and report, per source, whether they load and how big they are. Output goes to the workflow log."""
import json
import struct
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

NEWS = Path(__file__).resolve().parent.parent / "site" / "news.json"
# Mimic what a reader's browser sends for an <img> (no Referer), since that is what decides if a tile shows a photo.
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PER_SOURCE = 3
MAX_TOTAL = 260


def image_size(b):
    try:
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", b[16:24])
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", b[6:10])
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            k = b[12:16]
            if k == b"VP8 ":
                return struct.unpack("<HH", b[26:30])[0] & 0x3FFF, struct.unpack("<HH", b[26:30])[1] & 0x3FFF
            if k == b"VP8L":
                v = struct.unpack("<I", b[21:25])[0]
                return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
            if k == b"VP8X":
                return int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
        if b[:2] == b"\xff\xd8":
            i = 2
            while i < len(b) - 9:
                if b[i] != 0xFF:
                    i += 1
                    continue
                m = b[i + 1]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", b[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    except Exception:
        pass
    return None


def sniff(b):
    """True when the bytes are an image a browser can show, whatever Content-Type the server claims."""
    return (b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n" or b[:6] in (b"GIF87a", b"GIF89a")
            or (b[:4] == b"RIFF" and b[8:12] == b"WEBP") or b[4:8] == b"ftyp" or b[:5] == b"<?xml" or b[:4] == b"<svg")


def check(item):
    try:
        req = Request(item["image"], headers={"User-Agent": UA, "Accept": "image/*"})
        with urlopen(req, timeout=15) as r:
            data = r.read(400_000)
            return item, r.status, r.headers.get("Content-Type", ""), len(data), image_size(data), None, sniff(data)
    except Exception as e:
        return item, getattr(e, "code", None), "", 0, None, f"{type(e).__name__}", False


def main():
    items = json.loads(NEWS.read_text())["items"]
    with_img = [i for i in items if i.get("image")]
    print(f"IMAGES: {len(with_img)} of {len(items)} stories have an image")
    seen = defaultdict(int)
    sample = []
    for i in with_img:
        if seen[i["source"]] < PER_SOURCE:
            seen[i["source"]] += 1
            sample.append(i)
    sample = sample[:MAX_TOTAL]
    with ThreadPoolExecutor(max_workers=12) as pool:
        res = list(pool.map(check, sample))
    per = defaultdict(list)
    for item, status, ctype, n, size, err, is_img in res:
        per[item["source"]].append((status, ctype, n, size, err, item["image"], is_img))
    bad = small = 0
    for src in sorted(per):
        rows = per[src]
        ok = [r for r in rows if r[0] == 200 and (r[1].startswith("image") or r[6])]
        widths = [r[3][0] for r in ok if r[3]]
        bad += len(rows) - len(ok)
        small += sum(1 for w in widths if w < 320)
        line = f"IMGCHECK {src}: {len(ok)}/{len(rows)} load; widths={widths}"
        if len(ok) == len(rows) and not any(w < 320 for w in widths):
            continue                       # healthy source: stay quiet
        if len(ok) < len(rows):
            f = next(r for r in rows if r not in ok)
            line += f" | FAIL status={f[0]} type={f[1] or f[4]} url={f[5][:100]}"
        print(line)
    # For sources whose images fail directly: does a Referer matter, and does the page's proxy fallback recover them?
    from urllib.parse import quote, urlparse
    for src in sorted(per):
        failed = [r for r in per[src] if not (r[0] == 200 and (r[1].startswith("image") or r[6]))]
        if not failed:
            continue
        url = failed[0][5]
        item = next(i for i in sample if i["image"] == url)
        origin = "{0.scheme}://{0.netloc}/".format(urlparse(item["link"]))
        out = []
        for label, req_url, hdr in (
            ("with-referer", url, {"User-Agent": UA, "Referer": origin, "Accept": "image/*"}),
            ("via-proxy", "https://wsrv.nl/?url=" + quote(url, safe="") + "&w=800&h=450&fit=cover&a=attention", {"User-Agent": UA}),
        ):
            try:
                with urlopen(Request(req_url, headers=hdr), timeout=20) as r:
                    d = r.read(400_000)
                    out.append(f"{label}: {r.status} {r.headers.get('Content-Type', '')} {image_size(d)}")
            except Exception as e:
                out.append(f"{label}: {getattr(e, 'code', type(e).__name__)}")
        print(f"PROXYTEST {src}: " + " | ".join(out))
    counts = defaultdict(int)
    for i in items:
        for sec in i["sections"]:
            counts[sec] += 1
    print("SECTIONS:", ", ".join(f"{k}={counts[k]}" for k in sorted(counts, key=lambda k: -counts[k])))
    print(f"IMGSUMMARY: tested {len(res)}, failed {bad}, narrower than 320px: {small}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("image check skipped:", e)
        sys.exit(0)
