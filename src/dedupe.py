"""Removes repeated headlines inside each section.

Two stories in the same section whose headlines are at least THRESHOLD similar (character based, difflib) count as the
same story, whatever newspaper they came from; only one is kept: a primary source beats a secondary one, then the copy
with an image, the longer summary and the longer headline wins, and any remaining tie keeps whichever came first.

Comparing every pair would take minutes for thousands of stories, so each section is processed best-copy-first and a
story is compared only with the copies already kept that could possibly match it:
  1. an identical cleaned headline is found by a dictionary lookup;
  2. otherwise only kept headlines sharing a (not too common) word are candidates, found through a word index;
  3. a pair is skipped when the lengths alone, or the characters the two share, cannot reach the threshold;
  4. only then is the full ratio worked out.
The skipped pairs could never have reached the threshold, so steps 3 and 4 give the same answer as comparing everything."""
import re
import unicodedata
from difflib import SequenceMatcher

THRESHOLD = 0.90          # headlines at least this similar are the same story
COMMON_SHARE = 0.05       # a word in more than this share of a section's headlines is too common to find candidates with
COMMON_FLOOR = 10         # ... and never counts as common in a section with fewer such headlines than this

_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")      # " - The Hindu" at the end of a headline


def normalise(title):
    """The headline as compared: no newspaper suffix, lower case, punctuation as spaces, single spaces.
    Letters of every script are kept (Bengali and Hindi vowel signs are marks, not punctuation)."""
    t = (title or "").strip()
    cut = _SUFFIX.sub("", t)
    if len(cut) >= 15:
        t = cut
    t = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in t.lower())
    return " ".join(t.split())


def _quality(it):
    return (bool(it.get("primary")), bool(it.get("image")), len(it.get("summary") or ""), len(it.get("title") or ""))


def _losers(group, threshold=THRESHOLD):
    """group: the stories of one section. Returns the ids (positions in group) of the stories to drop."""
    order = sorted(range(len(group)), key=lambda k: _quality(group[k]), reverse=True)    # stable: ties keep their order
    norm = {k: normalise(group[k].get("title")) for k in order}
    words = {k: set(norm[k].split()) for k in order}
    df = {}
    for k in order:
        for w in words[k]:
            df[w] = df.get(w, 0) + 1
    common = max(COMMON_FLOOR, COMMON_SHARE * len(group))
    kept_text, index, exact, dropped = {}, {}, {}, set()
    sm = SequenceMatcher(None, autojunk=False)
    for k in order:
        h = norm[k]
        if not h:
            kept_text[k] = h
            continue
        if h in exact:
            dropped.add(k)
            continue
        ws = [w for w in words[k] if df[w] <= common] or list(words[k])     # every word too common: use them all
        cands = set()
        for w in ws:
            cands.update(index.get(w, ()))
        sm.set_seq2(h)                                                       # its tables are reused for every candidate
        dup = False
        for c in sorted(cands):
            o = kept_text[c]
            if 2 * min(len(o), len(h)) / (len(o) + len(h)) < threshold:       # lengths alone cannot reach it
                continue
            sm.set_seq1(o)
            if sm.quick_ratio() >= threshold and sm.ratio() >= threshold:
                dup = True
                break
        if dup:
            dropped.add(k)
            continue
        kept_text[k] = h
        exact[h] = k
        for w in words[k]:
            index.setdefault(w, []).append(k)
    return dropped


def dedupe(items, threshold=THRESHOLD):
    """Drops repeated headlines section by section. A story that loses in one section but is kept in another stays, in
    the sections where it was kept; one that loses everywhere is removed. Returns (items, number removed)."""
    by_section = {}
    for n, it in enumerate(items):
        for s in it["sections"]:
            by_section.setdefault(s, []).append(n)
    lost = set()                                                              # (story position, section)
    for s, ids in by_section.items():
        for k in _losers([items[n] for n in ids], threshold):
            lost.add((ids[k], s))
    out = []
    for n, it in enumerate(items):
        keep = [s for s in it["sections"] if (n, s) not in lost]
        if keep:
            it["sections"] = keep
            out.append(it)
    return out, len(items) - len(out)
