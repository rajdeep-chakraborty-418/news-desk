#!/usr/bin/env python3
"""Assemble the site/ folder that gets published: the page from src/web/, plus the lists the page reads at load time,
generated from external_config/ (sections.json -> site/sections.json, newspapers.json -> site/papers.json, settings.json -> site/settings.json).
fetch_news.py then adds site/news.json.   Usage: python3 src/build_site.py [output_dir]"""
import json
import shutil
import sys
from pathlib import Path

import config
import settings

ROOT = Path(__file__).resolve().parent.parent


def build(out_dir=None, web_dir=None):
    out = Path(out_dir or ROOT / "site")
    web = Path(web_dir or ROOT / "src" / "web")
    sections = config.load_sections()
    newspapers = config.load_newspapers(sections)
    out.mkdir(parents=True, exist_ok=True)
    for f in web.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    st = settings.load_settings()
    (out / "settings.json").write_text(json.dumps(settings.public_settings(st), separators=(",", ":")))
    papers = config.public_newspapers(newspapers)
    (out / "sections.json").write_text(json.dumps(config.public_sections(sections), ensure_ascii=False, separators=(",", ":")))
    (out / "papers.json").write_text(json.dumps(papers, ensure_ascii=False, separators=(",", ":")))
    return len(sections), len(papers), out


if __name__ == "__main__":
    try:
        n_sections, n_papers, out = build(sys.argv[1] if len(sys.argv) > 1 else None)
    except config.ConfigError as e:
        sys.exit(f"Configuration error: {e}")
    print(f"{n_sections} sections, {n_papers} newspapers in the dropdown -> {out}")
