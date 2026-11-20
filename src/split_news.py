"""Splits site/news.json into small files so a page downloads only what it shows.

    site/data/<section key>.json   every story of that section (a section page loads only this)
    site/data/home.json            a pool per section for the Home page's Today's Picks: the newest HOME_WITH_PICTURE stories with
                                   a picture and the newest HOME_WITHOUT_PICTURE without (the picks are drawn at random from them)

Each file has the same shape as news.json (generated_at, range_hours, max_articles, topics, items) without the feed statuses.
site/news.json stays: the newspaper-list page and older pages still read it, and every data file can be rebuilt from it.
Run after the translation step, so the English headlines are in the files too.   Usage: python3 src/split_news.py [site_dir]"""
import json
import sys
from pathlib import Path

HOME_WITH_PICTURE = 40
HOME_WITHOUT_PICTURE = 20


def has_picture(item):
    return bool(item.get("image")) and item["image"].startswith("https://")


def split(news):
    """Returns {file name (without .json): payload} for every section found in the stories, plus 'home'."""
    items = news.get("items", [])
    head = {k: news[k] for k in ("generated_at", "range_hours", "max_articles", "demo") if k in news}
    topics = news.get("topics") or {}
    keys = []
    for i in items:
        for s in i.get("sections", ()):
            if s not in keys:
                keys.append(s)
    out = {}
    for key in keys:
        out[key] = dict(head, topics={key: topics[key]} if key in topics else {}, items=[i for i in items if key in i.get("sections", ())])
    pool, seen = [], set()
    for key in keys:
        mine = sorted((i for i in items if key in i.get("sections", ())), key=lambda i: i.get("published", ""), reverse=True)
        pics = [i for i in mine if has_picture(i)][:HOME_WITH_PICTURE]
        plain = [i for i in mine if not has_picture(i)][:HOME_WITHOUT_PICTURE]
        for i in pics + plain:
            if i.get("link") not in seen:
                seen.add(i.get("link"))
                pool.append(i)
    out["home"] = dict(head, topics={}, items=pool)
    return out


def write(news, directory):
    folder = Path(directory) / "data"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.json"):                       # a section that no longer has stories must not keep its old file
        old.unlink()
    files = split(news)
    for name, payload in files.items():
        (folder / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return files


def main(argv):
    site = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "site"
    path = site / "news.json"
    if not path.exists():
        print("No news.json: nothing to split.")
        return 0
    files = write(json.loads(path.read_text(encoding="utf-8")), site)
    sizes = {n: (site / "data" / f"{n}.json").stat().st_size for n in files}
    print(f"Split into {len(files)} files; largest {max(sizes, key=sizes.get)} {max(sizes.values()) / 1e6:.2f} MB, home {sizes['home'] / 1e6:.2f} MB "
          f"(news.json {path.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
