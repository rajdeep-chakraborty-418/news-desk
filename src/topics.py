"""Topic buttons for a section page, built from the keywords (feed tags) of the stories that are actually there.

external_config/topics/<section key>.json switches this on for one section:
  {"min_count": 5, "max_topics": 12,
   "merge": {"Sports · খেলা": ["Sports", "খেলা", "Cricket", ...]},      one button for several names of the same topic
   "hide": ["Top Stories", ...]}                                          tags that are never a topic
A story's keywords are its feed tags (a tag such as "Sports,Cricket" counts as two) and, for the names listed under "merge" only,
the folders of its web address (/sports/cricket/...). A name that is not merged and not hidden is a topic of its own. The
most frequent topics with at least min_count stories (at most max_topics) become the buttons; each story gets "topics" =
the buttons it belongs to. Names compare without case, punctuation or a trailing 'news', in any script.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

import config

MAX_NAME = 40


def folders_of(link):
    """The folders in a story's web address, lowercased (Google News links carry none)."""
    if not link or "news.google.com" in link:
        return []
    return [p.lower() for p in urlparse(link).path.split("/")[:-1] if p]


def split_tags(tags):
    out = []
    for t in tags or []:
        for x in ([t] + [p for p in t.split(",")] if "," in t else [t]):
            x = x.strip()
            if x and x not in out:
                out.append(x)
    return out


def load_topics(sections, directory=None):
    """{section key: {"min_count", "max_topics", "alias": {normalised name: [button labels]}, "hide": {normalised names}}}."""
    folder = Path(directory or config.config_dir()) / "topics"
    if not folder.is_dir():
        return {}
    keys = {s["key"] for s in sections}
    specs = {}
    for path in sorted(folder.glob("*.json")):
        where = f"topics/{path.name}"
        if path.stem not in keys:
            raise config.ConfigError(f"{where}: '{path.stem}' is not a section in sections.json (known: {', '.join(sorted(keys))})")
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise config.ConfigError(f"{where} is not valid JSON: {e}")
        if not isinstance(d, dict):
            raise config.ConfigError(f"{where} must be an object")
        for field, lo, hi, default in (("min_count", 1, 100000, 5), ("max_topics", 1, 40, 12)):
            v = d.get(field, default)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise config.ConfigError(f"{where}: '{field}' must be a whole number from {lo} to {hi}")
        merge, hide = d.get("merge") or {}, d.get("hide") or []
        if not isinstance(merge, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, list) and all(isinstance(n, str) for n in v)
                                                 for k, v in merge.items()):
            raise config.ConfigError(f'{where}: "merge" must map a button label to a list of names')
        if not isinstance(hide, list) or not all(isinstance(n, str) for n in hide):
            raise config.ConfigError(f'{where}: "hide" must be a list of names')
        alias = {}
        for label, names in merge.items():
            for n in [label] + names:
                labels = alias.setdefault(config.norm_label(n), [])          # a name may feed several buttons (Cricket and Sports)
                if label.strip() not in labels:
                    labels.append(label.strip())
        specs[path.stem] = {"min_count": d.get("min_count", 5), "max_topics": d.get("max_topics", 12), "alias": alias,
                            "hide": {config.norm_label(n) for n in hide}}
    return specs


def _topics_of(item, spec):
    """The (key, label) pairs a story belongs to before the most frequent are chosen."""
    found = {}
    for tag in item.get("_tags") or []:
        k = config.norm_label(tag)
        if not k or k in spec["hide"]:
            continue
        if k in spec["alias"]:
            for lab in spec["alias"][k]:
                found.setdefault(("m", lab), lab)
        elif 2 <= len(k) and len(tag) <= MAX_NAME and not k.isdigit():
            found.setdefault(("t", k), tag)
    for folder in item.get("_folders") or []:
        k = config.norm_label(folder)
        if k in spec["alias"] and k not in spec["hide"]:
            for lab in spec["alias"][k]:
                found.setdefault(("m", lab), lab)
    return found


def apply(items, specs):
    """Sets item["topics"] on the stories of the sections that have a topics file, removes the working keywords from every
    story and returns {section key: [{"label", "count"}, ...]} in button order (most stories first)."""
    result = {}
    for key, spec in (specs or {}).items():
        members = [(i, _topics_of(i, spec)) for i in items if key in i.get("sections", ())]
        count, label = {}, {}
        for _, found in members:
            for k, lab in found.items():
                count[k] = count.get(k, 0) + 1
                label.setdefault(k, lab)
        kept = sorted((k for k, n in count.items() if n >= spec["min_count"]), key=lambda k: (-count[k], label[k].lower()))[:spec["max_topics"]]
        order = {k: n for n, k in enumerate(kept)}
        for item, found in members:
            item["topics"] = [label[k] for k in sorted((k for k in found if k in order), key=order.get)]
        result[key] = [{"label": label[k], "count": count[k]} for k in kept]
    for item in items:
        item.pop("_tags", None)
        item.pop("_folders", None)
    return result
