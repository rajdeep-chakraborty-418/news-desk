"""Background images for the landing page and the section pages. The images live in external_config/backgrounds/, one
folder per place:   landing/   (the landing page)   and   <section key>/   (each section page, e.g. bengali/, sports/).
Every image file in a folder (.svg .jpg .jpeg .png .webp .avif .gif) is part of that place's image set: add a file to
add an image, delete a file to remove it. Each refresh/build copies the sets into site/backgrounds/ and writes
site/backgrounds.json  {"landing": ["backgrounds/landing/a.svg", ...], "<section key>": [...]}  which the page reads
(src/web/backdrop.js picks one image at random per visit). A folder that is missing or empty means a plain header.

Contract:  build(out_dir, section_keys, directory=None) -> {place: [published paths]}.   Nothing else in the code
knows where images come from, so this module can be replaced without touching the page or the build."""
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import config

LANDING = "landing"
EXTENSIONS = {".svg", ".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
MAX_BYTES = 2_000_000          # bigger files are skipped with a warning: they would slow every page load


def build(out_dir, section_keys, directory=None):
    src = Path(directory) if directory else config.config_dir() / "backgrounds"
    out = Path(out_dir)
    target = out / "backgrounds"
    shutil.rmtree(target, ignore_errors=True)                   # images removed from the config disappear from the site
    manifest = {}
    if src.is_dir():
        for folder in sorted(p for p in src.iterdir() if p.is_dir()):
            if folder.name != LANDING and folder.name not in section_keys:
                print(f"Backgrounds: ignoring folder '{folder.name}' (not '{LANDING}' or a section key)", file=sys.stderr)
                continue
            paths = []
            for f in sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS):
                if f.stat().st_size > MAX_BYTES:
                    print(f"Backgrounds: skipping {folder.name}/{f.name} (over {MAX_BYTES // 1000} KB)", file=sys.stderr)
                    continue
                (target / folder.name).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, target / folder.name / f.name)
                paths.append(f"backgrounds/{folder.name}/{quote(f.name)}")
            if paths:
                manifest[folder.name] = paths
    out.mkdir(parents=True, exist_ok=True)
    (out / "backgrounds.json").write_text(json.dumps(manifest, separators=(",", ":")))
    return manifest
