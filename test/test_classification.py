"""fetch_news.classify / place and geo.find_country, driven by the sample sections (never the real ones)."""
import copy

import support
from support import SAMPLE_SECTIONS, TestCase

import config
import fetch_news as fn
import geo


def configure(sections_dict=None):
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    fn.configure(config.load_sections(support.write_config(d, sections=sections_dict) if sections_dict else support.SAMPLE_CONFIG))


class ClassifyTest(TestCase):
    def setUp(self):
        super().setUp()
        configure()
        self.addCleanup(configure)

    def test_own_section_is_always_first_and_always_included(self):
        self.assertEqual(fn.classify({"category": "india"}, "Nothing special", ""), ["india"])
        self.assertEqual(fn.classify({"category": "sports"}, "Budget talks", ""), ["sports"])

    def test_also_from_sections_matches_keywords_in_title_or_summary(self):
        self.assertEqual(fn.classify({"category": "world"}, "Army chief warns", ""), ["world", "defence"])
        self.assertEqual(fn.classify({"category": "india"}, "Quiet", "the navy was out"), ["india", "defence"])
        self.assertEqual(fn.classify({"category": "world"}, "Sensex and inflation", ""), ["world", "money"])

    def test_a_section_not_listed_in_also_from_is_not_matched(self):
        self.assertEqual(fn.classify({"category": "home"}, "army and sensex", ""), ["home"])
        self.assertEqual(fn.classify({"category": "sports"}, "army", ""), ["sports"])

    def test_general_newspapers_get_keyword_sections_without_also_from(self):
        self.assertEqual(fn.classify({"category": "home", "general": True}, "Cricket final tonight", ""), ["home", "sports"])
        self.assertEqual(fn.classify({"category": "home", "general": True}, "Sensex rallies", ""), ["home", "money"])
        self.assertEqual(fn.classify({"category": "home"}, "Cricket final tonight", ""), ["home"])      # not general

    def test_sections_without_the_general_flag_ignore_general_newspapers(self):
        self.assertEqual(fn.classify({"category": "home", "general": True}, "The army marched", ""), ["home"])

    def test_extra_keywords_apply_only_to_general_newspapers(self):
        self.assertIn("showbiz", fn.classify({"category": "home", "general": True}, "Film festival opens", ""))
        self.assertNotIn("showbiz", fn.classify({"category": "world"}, "Celebrity festival opens", ""))
        self.assertIn("showbiz", fn.classify({"category": "world"}, "An actor speaks", ""))

    def test_matching_is_whole_word_and_case_insensitive(self):
        self.assertEqual(fn.classify({"category": "world"}, "ARMY exercise", ""), ["world", "defence"])
        self.assertEqual(fn.classify({"category": "world"}, "armyworm outbreak", ""), ["world"])
        self.assertEqual(fn.classify({"category": "world"}, "STOCK MARKET slides", ""), ["world", "money"])

    def test_order_follows_sections_json(self):
        self.assertEqual(fn.classify({"category": "world"}, "army actor sensex", ""), ["world", "showbiz", "defence", "money"])

    def test_changing_sections_json_changes_the_result(self):
        data = copy.deepcopy(SAMPLE_SECTIONS)
        data["sections"].append({"key": "food", "label": "Food", "color": {"light": "#111111", "dark": "#eeeeee"},
                                 "keywords": ["recipe"], "also_from_sections": ["world"]})
        data["sections"] = [s for s in data["sections"] if s["key"] != "defence"]
        for s in data["sections"]:
            s["also_from_sections"] = [k for k in s.get("also_from_sections", []) if k != "defence"]
        configure(data)
        self.assertEqual(fn.classify({"category": "world"}, "A winter recipe, and the army", ""), ["world", "food"])


class PlaceTest(TestCase):
    def setUp(self):
        super().setUp()
        configure()

    def test_fixed_place_for_a_section(self):
        self.assertEqual(fn.place({"category": "india"}, "Anything about Pakistan", ""), ("India", "Asia"))

    def test_newspaper_place_for_a_section(self):
        feed = {"category": "home", "country": "Bangladesh", "continent": "Asia"}
        self.assertEqual(fn.place(feed, "Putin warns Kyiv", ""), ("Bangladesh", "Asia"))
        self.assertEqual(fn.place({"category": "home"}, "x", ""), ("Other", "Other"))

    def test_detected_from_text_otherwise(self):
        feed = {"category": "world", "country": "France", "continent": "Europe"}
        self.assertEqual(fn.place(feed, "Putin warns Kyiv over missile strikes", ""), ("Russia", "Europe"))

    def test_falls_back_to_the_newspapers_country_then_other(self):
        self.assertEqual(fn.place({"category": "world", "country": "France", "continent": "Europe"}, "Quiet day", ""), ("France", "Europe"))
        self.assertEqual(fn.place({"category": "world"}, "Quiet day", ""), ("Other", "Other"))


class GeoTest(TestCase):
    def test_country_and_continent(self):
        self.assertEqual(geo.find_country("Putin warns Kyiv over missile strikes"), ("Russia", "Europe"))
        self.assertEqual(geo.find_country("nothing here", "Israeli forces enter Gaza"), ("Israel", "Asia"))
        self.assertEqual(geo.find_country("Quiet day in the markets"), (None, None))
        self.assertEqual(geo.find_country(None, ""), (None, None))

    def test_earliest_match_wins_and_whole_words_only(self):
        self.assertEqual(geo.find_country("Talks between Delhi and Islamabad")[0], "India")
        self.assertEqual(geo.find_country("Indiana storms")[0], None)
