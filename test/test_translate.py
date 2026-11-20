"""translate_news.py: English headlines for Regional News (the model itself is replaced by a fake here)."""
import support
from support import TestCase

import translate_news as tn

CFG = {"section": "regional", "model": "x", "budget_minutes": 30, "max_new_per_run": 3000,
       "newspaper_language": {"Maharashtra Times": "mar_Deva", "Asomiya Pratidin": "asm_Beng"}}


def story(title, link, paper="Navbharat Times", sections=("regional",), published="2026-11-20T10:00:00Z"):
    return {"title": title, "link": link, "newspaper": paper, "sections": list(sections), "published": published}


class Fake:
    def __init__(self):
        self.calls = []

    def translate(self, sentences, src):
        self.calls.append((src, list(sentences)))
        return ["EN:" + s for s in sentences]


class LanguageTest(TestCase):
    def test_script_picks_the_language(self):
        self.assertEqual(tn.language_of(story("दिल्ली में बारिश", "a"), CFG["newspaper_language"]), "hin_Deva")
        self.assertEqual(tn.language_of(story("மழை எச்சரிக்கை", "a", "Dinamani"), CFG["newspaper_language"]), "tam_Taml")
        self.assertEqual(tn.language_of(story("ঝড়ের প্রভাব", "a", "Aajkaal"), CFG["newspaper_language"]), "ben_Beng")

    def test_newspaper_can_force_marathi_or_assamese(self):
        self.assertEqual(tn.language_of(story("मुंबईत पाऊस", "a", "Maharashtra Times"), CFG["newspaper_language"]), "mar_Deva")
        self.assertEqual(tn.language_of(story("বৰ্ষণ হ'ল", "a", "Asomiya Pratidin"), CFG["newspaper_language"]), "asm_Beng")
        self.assertEqual(tn.language_of(story("ঝড়", "a", "Maharashtra Times"), CFG["newspaper_language"]), "ben_Beng")   # wrong script: ignored

    def test_english_headlines_are_left_alone(self):
        self.assertIsNone(tn.language_of(story("Heavy rain in Delhi", "a"), CFG["newspaper_language"]))


class PlanAndRunTest(TestCase):
    def test_carry_over_needs_same_link_and_title(self):
        old = {"items": [dict(story("दिल्ली", "l1"), title_en="Delhi"), dict(story("पुराना शीर्षक", "l2"), title_en="Old")]}
        new = {"items": [story("दिल्ली", "l1"), story("नया शीर्षक", "l2"), story("मुंबई", "l3")]}
        pending = tn.carry_over(new, old, CFG)
        self.assertEqual(new["items"][0]["title_en"], "Delhi")
        self.assertEqual([i["link"] for i in pending], ["l2", "l3"])

    def test_only_the_configured_section_is_translated(self):
        news = {"items": [story("दिल्ली", "l1"), story("दिल्ली", "l2", sections=("world",))]}
        self.assertEqual([i["link"] for i in tn.carry_over(news, None, CFG)], ["l1"])

    def test_run_translates_newest_first_by_language_and_saves(self):
        news = {"items": [story("दिल्ली", "l1", published="2026-11-20T08:00:00Z"), story("मुंबई", "l2", published="2026-11-20T09:00:00Z"),
                          story("மழை", "l3", "Dinamani")]}
        saved = []
        tn.save = lambda n: saved.append(1)
        try:
            fake = Fake()
            done = tn.run(news, tn.carry_over(news, None, CFG), CFG, translator=fake)
        finally:
            import importlib; importlib.reload(tn)
        self.assertEqual(done, 3)
        self.assertEqual(news["items"][1]["title_en"], "EN:मुंबई")
        self.assertIn(("hin_Deva", ["मुंबई", "दिल्ली"]), fake.calls)
        self.assertTrue(saved)

    def test_budget_stops_the_run(self):
        news = {"items": [story("दिल्ली %d" % n, "l%d" % n) for n in range(40)]}
        ticks = iter([0, 0, 10 ** 6, 10 ** 6, 10 ** 6])
        tn.save = lambda n: None
        try:
            done = tn.run(news, tn.carry_over(news, None, CFG), CFG, translator=Fake(), batch_size=16, clock=lambda: next(ticks))
        finally:
            import importlib; importlib.reload(tn)
        self.assertEqual(done, 16)

    def test_a_failing_batch_is_skipped(self):
        class Boom:
            def translate(self, s, src): raise RuntimeError("bad")
        news = {"items": [story("दिल्ली", "l1")]}
        tn.save = lambda n: None
        try:
            self.assertEqual(tn.run(news, tn.carry_over(news, None, CFG), CFG, translator=Boom()), 0)
        finally:
            import importlib; importlib.reload(tn)
