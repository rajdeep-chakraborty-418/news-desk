"""English-headline helpers for the topic buttons of India, World and any other English section (language = "english").

Kept apart from topics.py so the English rules can change without touching the engine the Bengali section uses:
  make_stemmer(members)   merges a plural with its singular (strikes -> strike) only when both occur in the section
  merge_named(chosen, alias)  the names a section's file lists under "merge" become one button
  join_companions(kept)   names that nearly always appear in the same stories become one button (Nvidia / Jensen Huang)
"""
import re

import config

NAME_SHARE = 0.8             # a topic word must be capitalised at least this often away from the start of a headline ...
MIN_SEEN = 4                 # ... judged once it has been seen this many times away from the start
COMPANION_SHARE = 0.85       # this share of the smaller topic's stories also carry the bigger topic -> one button
COMPANION_RATIO = 3          # ... and the bigger topic has at most this many times the stories (else it is just a common word)


def make_stemmer(members):
    """A function word -> word with its plural 's' removed when the singular also occurs in the headlines of this section."""
    vocab = set()
    for item in members:
        vocab.update(w.lower() for w in re.findall(r"[^\W\d_]+", item.get("title", "")))

    def stem(word):
        if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")) and word[:-1] in vocab:
            return word[:-1]
        return word
    return stem


def merge_named(chosen, alias):
    """chosen: {label: [stories, newspapers]}; alias: {normalised name: [button label]} from the section's "merge"."""
    out = {}
    for label, (stories, papers) in chosen.items():
        target = (alias.get(config.norm_label(label)) or [label])[0]
        if target in out:
            out[target][0] = out[target][0] | stories
            out[target][1] = out[target][1] | papers
        else:
            out[target] = [set(stories), set(papers)]
    return out


def join_companions(kept):
    """kept: [(label, stories)] best first. A smaller topic whose stories are nearly all in a bigger one is added to that
    button's label ("Nvidia / Jensen Huang"); at most two names per button."""
    groups = []
    for label, stories in kept:
        for g in groups:
            if label.lower() in g["labels"][0].lower() or g["labels"][0].lower() in label.lower():
                continue
            if len(g["labels"]) < 2 and len(stories & g["stories"]) >= COMPANION_SHARE * len(stories) and len(g["stories"]) <= COMPANION_RATIO * len(stories):
                g["labels"].append(label)
                g["stories"] = g["stories"] | stories
                break
        else:
            groups.append({"labels": [label], "stories": set(stories)})
    return [(" / ".join(g["labels"]), g["stories"]) for g in groups]
