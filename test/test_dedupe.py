"""dedupe: repeated headlines inside a section collapse to one story, keeping the best copy."""
import random
import string
import time
import unittest
from difflib import SequenceMatcher

import support  # noqa: F401  (puts src on the path)
import dedupe


def st(title, sections=("world",), primary=False, image="", summary="", name="Paper"):
    return {"title": title, "sections": list(sections), "primary": primary, "image": image, "summary": summary, "newspaper": name}


def titles(items):
    return sorted(i["title"] for i in items)


class NormaliseTest(unittest.TestCase):
    def test_case_punctuation_spaces_and_newspaper_suffix(self):
        self.assertEqual(dedupe.normalise("  Modi  to VISIT Japan, next week! - The Hindu "), "modi to visit japan next week")
        self.assertEqual(dedupe.normalise("Modi to visit Japan next week | NDTV"), "modi to visit japan next week")

    def test_a_short_headline_is_not_cut_at_a_dash(self):
        self.assertEqual(dedupe.normalise("Gold - Silver"), "gold silver")

    def test_other_scripts_keep_their_vowel_signs(self):
        self.assertEqual(dedupe.normalise("কলকাতায় বৃষ্টি, সতর্কতা জারি"), "কলকাতায় বৃষ্টি সতর্কতা জারি")


class ContractTest(unittest.TestCase):
    """What the rest of the program may rely on (see the top of src/dedupe.py)."""
    def items(self):
        return [{"title": "Floods hit the coast badly today", "sections": ["world", "india"], "primary": False, "image": "", "summary": "",
                 "link": "https://a/1", "published": "2026-01-01T00:00:00+00:00", "newspaper": "A", "extra": {"k": 1}},
                {"title": "Floods hit the coast badly today", "sections": ["world"], "primary": True, "image": "", "summary": "",
                 "link": "https://b/1", "published": "2026-01-01T01:00:00+00:00", "newspaper": "B", "extra": {"k": 2}},
                {"title": "Stocks close higher on strong earnings", "sections": ["business"], "primary": False, "image": "", "summary": "",
                 "link": "https://c/1", "published": "2026-01-01T02:00:00+00:00", "newspaper": "C", "extra": {"k": 3}}]

    def test_the_input_is_never_changed(self):
        import copy
        items = self.items(); before = copy.deepcopy(items)
        dedupe.apply(items)
        self.assertEqual(items, before)

    def test_survivors_keep_their_order_and_every_other_field(self):
        items = self.items()
        out, n = dedupe.apply(items)
        self.assertEqual(n, 0)
        self.assertEqual([i["link"] for i in out], ["https://a/1", "https://b/1", "https://c/1"])
        for a, b in zip(items, out):
            self.assertEqual({k: v for k, v in a.items() if k != "sections"}, {k: v for k, v in b.items() if k != "sections"})
        self.assertEqual(out[0]["sections"], ["india"])             # lost "world" to the primary copy, kept "india"

    def test_nothing_is_added_and_no_story_is_left_without_sections(self):
        out, n = dedupe.apply(self.items())
        self.assertLessEqual(len(out), 3)
        self.assertTrue(all(i["sections"] for i in out))

    def test_an_empty_list_is_fine(self):
        self.assertEqual(dedupe.apply([]), ([], 0))


class DedupeTest(unittest.TestCase):
    def test_identical_headlines_across_newspapers_keep_one(self):
        items = [st("Floods hit the coast badly today", name="A"), st("floods hit the coast badly today!", name="B")]
        out, n = dedupe.apply(items)
        self.assertEqual((len(out), n), (1, 1))

    def test_ninety_percent_is_a_duplicate_and_below_is_not(self):
        a = "Prime minister to visit Japan next week"
        near = "Prime minister to visit Japan next weeks"
        far = "Prime minister to visit Japan this month"
        self.assertGreaterEqual(SequenceMatcher(None, a.lower(), near.lower()).ratio(), 0.9)
        self.assertLess(SequenceMatcher(None, a.lower(), far.lower()).ratio(), 0.9)
        self.assertEqual(len(dedupe.apply([st(a), st(near)])[0]), 1)
        self.assertEqual(len(dedupe.apply([st(a), st(far)])[0]), 2)

    def test_primary_beats_secondary(self):
        out, _ = dedupe.apply([st("Floods hit the coast badly today", name="Second"),
                                st("Floods hit the coast badly today", primary=True, name="First")])
        self.assertEqual([i["newspaper"] for i in out], ["First"])

    def test_richer_copy_wins_inside_the_same_tier(self):
        plain = st("Floods hit the coast badly today", name="Plain")
        rich = st("Floods hit the coast badly today", image="https://x/i.jpg", summary="Long summary here", name="Rich")
        self.assertEqual([i["newspaper"] for i in dedupe.apply([plain, rich])[0]], ["Rich"])
        self.assertEqual([i["newspaper"] for i in dedupe.apply([rich, plain])[0]], ["Rich"])

    def test_primary_wins_even_against_a_richer_secondary(self):
        rich = st("Floods hit the coast badly today", image="https://x/i.jpg", summary="Long summary", name="Rich")
        prim = st("Floods hit the coast badly today", primary=True, name="Prim")
        self.assertEqual([i["newspaper"] for i in dedupe.apply([rich, prim])[0]], ["Prim"])

    def test_only_headlines_of_the_same_section_are_compared(self):
        a = st("Floods hit the coast badly today", sections=("world",))
        b = st("Floods hit the coast badly today", sections=("sports",))
        self.assertEqual(len(dedupe.apply([a, b])[0]), 2)

    def test_a_story_that_loses_in_one_section_stays_in_the_other(self):
        best = st("Floods hit the coast badly today", sections=("world",), primary=True)
        both = st("Floods hit the coast badly today", sections=("world", "india"))
        out, n = dedupe.apply([best, both])
        self.assertEqual(n, 0)
        self.assertEqual([i["sections"] for i in out], [["world"], ["india"]])

    def test_different_stories_are_kept(self):
        items = [st("Floods hit the coast badly today"), st("Stocks close higher on strong earnings"), st("")]
        self.assertEqual(len(dedupe.apply(items)[0]), 3)

    def test_empty_headlines_are_never_merged(self):
        self.assertEqual(len(dedupe.apply([st(""), st("")])[0]), 2)

    def test_the_shortcuts_give_the_same_answer_as_comparing_everything(self):
        rnd = random.Random(7)
        words = ["".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(3, 8))) for _ in range(300)]
        base = [" ".join(rnd.choice(words) for _ in range(rnd.randint(6, 12))) for _ in range(250)]
        heads = list(base)
        for _ in range(150):
            w = rnd.choice(base).split(); w[rnd.randrange(len(w))] = rnd.choice(words); heads.append(" ".join(w))
        items = [st(h, primary=(n % 3 == 0)) for n, h in enumerate(heads)]
        kept = []                                                          # brute force: best first, compare with all kept
        for i in sorted(items, key=dedupe._quality, reverse=True):
            h = dedupe.normalise(i["title"])
            if not any(SequenceMatcher(None, h, dedupe.normalise(k["title"]), autojunk=False).ratio() >= 0.9 for k in kept):
                kept.append(i)
        self.assertEqual(len(dedupe.apply([dict(i) for i in items])[0]), len(kept))

    def test_five_thousand_headlines_take_seconds_not_minutes(self):
        rnd = random.Random(3)
        words = ["".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(3, 9))) for _ in range(4000)]
        base = [" ".join(rnd.choice(words) for _ in range(rnd.randint(8, 14))) for _ in range(3500)]
        heads = base + [" ".join(w) for w in ([*(rnd.choice(base).split())] for _ in range(1500))]
        items = [st(h) for h in heads]
        t = time.time()
        out, n = dedupe.apply(items)
        self.assertLess(time.time() - t, 20)
        self.assertGreaterEqual(n, 1400)


if __name__ == "__main__":
    unittest.main()
