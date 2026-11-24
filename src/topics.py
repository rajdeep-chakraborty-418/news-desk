"""Topic buttons for a section page, built from the stories that are actually there.

Two modes, set by "mode" in external_config/topics/<section key>.json:
  "headlines": the names, places and events that recur in the HEADLINES of the section's stories (see headline_topics()).
      {"mode": "headlines", "min_count": 8, "min_newspapers": 2, "max_topics": 12, "stopwords": [...], "hide": [...]}
  "tags" (the default, described below): the feed tags of the stories, merged by a list you write.

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
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import config
import topic_english
import topic_words

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
        for field, lo, hi, default in (("min_count", 1, 100000, {"headlines": 8, "states": 1}.get(d.get("mode"), 5)), ("max_topics", 1, 40, 12)):
            v = d.get(field, default)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise config.ConfigError(f"{where}: '{field}' must be a whole number from {lo} to {hi}")
        mode = d.get("mode", "tags")
        if d.get("language", "english") not in ("english", "bengali") or d.get("rank", "newspapers") not in ("newspapers", "stories"):
            raise config.ConfigError(f'{where}: "language" must be "english" or "bengali" and "rank" "newspapers" or "stories"')
        if mode not in ("tags", "headlines", "states"):
            raise config.ConfigError(f'{where}: "mode" must be "tags", "headlines" or "states"')
        min_papers = d.get("min_newspapers", 1)
        if not isinstance(min_papers, int) or isinstance(min_papers, bool) or not 1 <= min_papers <= 100:
            raise config.ConfigError(f"{where}: 'min_newspapers' must be a whole number from 1 to 100")
        extra_stop = d.get("stopwords") or []
        if not isinstance(extra_stop, list) or not all(isinstance(n, str) for n in extra_stop):
            raise config.ConfigError(f'{where}: "stopwords" must be a list of words')
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
        specs[path.stem] = {"mode": mode, "min_count": d.get("min_count", {"headlines": 8, "states": 1}.get(mode, 5)),
                            "max_topics": d.get("max_topics", 12), "min_newspapers": min_papers, "alias": alias,
                            "hide": {config.norm_label(n) for n in hide},
                            "stopwords": {w.lower() for w in extra_stop}, "native_only": bool(d.get("native_only", False)),
                            "language": d.get("language", "bengali" if d.get("native_only") else "english"), "rank": d.get("rank", "newspapers")}
        if mode == "states":                                   # the buttons are the states of the newspapers: "English (local name)"
            specs[path.stem]["newspaper_states"] = newspaper_states(sections, directory)
    return specs


def newspaper_states(sections, directory=None):
    """{newspaper name: ["Maharashtra (महाराष्ट्र)", ...]} from the 'state' of each newspaper file."""
    books = config.load_newspapers(sections, directory)
    return {p["name"]: [f'{x["en"]} ({x["local"]})' for x in p["states"]] for node in books.values() for p in node if p.get("states")}


# ---------------------------------------------------------------- headlines mode
def _words(text):
    """The words of a headline in their written form (punctuation, digits and invisible joiners removed)."""
    text = unicodedata.normalize("NFD", text).replace("\u200c", "").replace("\u200d", "")   # য় is one character or two depending on the keyboard
    t = "".join(c if unicodedata.category(c)[0] in "LMN" else " " for c in text)
    return [w for w in t.split() if len(w) >= 2 and not w.isdigit()]


ENDINGS = [unicodedata.normalize("NFD", e) for e in topic_words.BENGALI_ENDINGS]


def stem(word):
    """A Bengali word without its case/plural ending (কলকাতার, কলকাতায়, কলকাতাকে -> কলকাতা); other scripts are left alone."""
    if not ("\u0980" <= word[0] <= "\u09ff") or len(word) <= 3:
        return word
    word = unicodedata.normalize("NFD", word)
    for suffix in ENDINGS:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return word[:-len(suffix)]
    return word


def _show(forms, key, english=False):
    """The form of a word to show on a button: the plain stem if it occurs, else the commonest written form."""
    if english and key in topic_words.ACRONYMS:
        return key.upper()
    best = key if key in forms else max(forms, key=lambda f: (forms[f], -len(f)))
    return best[:1].upper() + best[1:] if best.islower() and best.isascii() else best


def headline_topics(members, spec):
    """members: the stories of one section. Returns ({label: set of story positions}, ordered labels) - the names, places and
    events that occur in at least min_count headlines from at least min_newspapers newspapers, most frequent first, at most
    max_topics. A phrase of two words that nearly always go together (শুভেন্দু অধিকারী) replaces its single words, and topics
    that cover almost the same stories are shown once. Words everybody uses (more than a third of the headlines) are skipped.
    With "language": "english" (see topic_english.py) plurals are merged, acronyms stay capitals, newsroom filler words are
    skipped, names that always appear together (Nvidia / Jensen Huang) become one button and the buttons are ranked by the
    number of newspapers that carry them."""
    english = spec.get("language") == "english"
    stop = {unicodedata.normalize("NFD", w) for w in set(topic_words.BENGALI_STOP) | set(topic_words.ENGLISH_STOP) | spec.get("stopwords", set())}
    if english:
        stop |= {w.lower() for w in topic_words.ENGLISH_NOISE}
        stemmer = topic_english.make_stemmer(members)
    else:
        stemmer = stem
    n = len(members)
    uni, bi = defaultdict(set), defaultdict(set)                     # stem or "stem stem" -> story positions
    papers = defaultdict(set)
    forms = defaultdict(Counter)                                     # stem -> written form -> count
    for pos, item in enumerate(members):
        who = item.get("newspaper") or item.get("source") or ""
        previous = None
        for word in _words(item.get("title", "")):
            low = word.lower()
            st = stemmer(low)
            if spec.get("native_only") and word.isascii():          # English tags in front of the headline repeat the Bengali words
                previous = None
                continue
            if low in stop or st in stop:
                previous = None
                continue
            uni[st].add(pos); papers[st].add(who); forms[st][word if not word.islower() else low] += 1
            if previous is not None:
                key = previous + " " + st
                bi[key].add(pos); papers[key].add(who)
            previous = st
    too_common = 0.35 * n if n >= 30 else n + 1

    def ok(key, stories):
        return (len(stories) >= spec["min_count"] and len(papers[key]) >= spec["min_newspapers"] and len(stories) <= too_common
                and config.norm_label(key) not in spec["hide"])
    cands = {k: v for k, v in uni.items() if ok(k, v)}
    phrases = {k: v for k, v in bi.items() if ok(k, v)}
    for phrase, stories in phrases.items():                          # a phrase takes over from a single word it nearly always accompanies
        for word in phrase.split():
            if word in cands and len(stories) >= 0.6 * len(cands[word]):
                del cands[word]
    chosen = {}                                                      # label -> [story positions, newspapers]
    for key, stories in list(cands.items()) + list(phrases.items()):
        label = " ".join(_show(forms[w], w, english) for w in key.split())
        chosen[label] = [stories, papers[key]]
    if english:
        chosen = topic_english.merge_named(chosen, spec.get("alias", {}))
    if english and spec.get("rank") != "stories":
        order_key = lambda kv: (-len(kv[1][1]), -len(kv[1][0]), kv[0])
    else:
        order_key = lambda kv: (-len(kv[1][0]), -len(kv[0]), kv[0])
    kept = []
    for label, (stories, _) in sorted(chosen.items(), key=order_key):
        if all(len(stories & other) / len(stories | other) < 0.8 for _, other in kept):
            kept.append((label, stories))
    if english:
        kept = topic_english.join_companions(kept)
    kept = kept[:spec["max_topics"]]
    return {label: stories for label, stories in kept}, [label for label, _ in kept]


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
        if spec.get("mode") == "states":
            by_paper = spec.get("newspaper_states", {})
            story_list = [i for i in items if key in i.get("sections", ())]
            count = {}
            for item in story_list:
                item["topics"] = list(by_paper.get(item.get("newspaper") or item.get("source"), []))
                for label in item["topics"]:
                    count[label] = count.get(label, 0) + 1
            order = sorted((l for l, n in count.items() if n >= spec["min_count"]), key=lambda l: (-count[l], l))[:spec["max_topics"]]
            for item in story_list:
                item["topics"] = [l for l in item["topics"] if l in order]
            result[key] = [{"label": l, "count": count[l]} for l in order]
            continue
        if spec.get("mode") == "headlines":
            story_list = [i for i in items if key in i.get("sections", ())]
            found, order = headline_topics(story_list, spec)
            for pos, item in enumerate(story_list):
                item["topics"] = [label for label in order if pos in found[label]]
            result[key] = [{"label": label, "count": len(found[label])} for label in order]
            continue
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
