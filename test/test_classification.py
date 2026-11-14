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


class NewspaperSectionMapTest(TestCase):
    """external_config/newspaper_sections/<paper>.json: many newspaper sections -> one UI section."""

    def setUp(self):
        super().setUp()
        import json, pathlib, tempfile
        self.dir = pathlib.Path(tempfile.mkdtemp())
        support.write_config(self.dir)
        (self.dir / "newspaper_sections").mkdir()
        self.write = lambda name, data: (self.dir / "newspaper_sections" / name).write_text(json.dumps(data))
        self.sections = config.load_sections(self.dir)
        self.addCleanup(configure)

    def keys(self):
        return [s["key"] for s in self.sections]

    def test_many_source_sections_map_to_one(self):
        self.write("p.json", {"newspaper": "Paper", "section_map": {"sports": ["Sports", "AFL", "NFL"]}, "other": ["Opinion"]})
        maps = config.load_section_maps(self.sections, self.dir)
        self.assertEqual(maps["Paper"], {"sports": ["sports"], "afl": ["sports"], "nfl": ["sports"]})
        fn.configure(self.sections, maps=maps)
        feed = {"category": "india", "newspaper": "Paper"}
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/afl/story-1"), ["india", "sports"])
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/a/b", ["NFL"]), ["india", "sports"])
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/opinion/story-1"), ["india"])
        self.assertEqual(fn.classify({"category": "india", "newspaper": "Other Paper"}, "x", "", "https://p.com/afl/s"), ["india"])

    def test_names_under_other_put_the_story_in_other(self):
        sections = config.load_sections(self.dir) + [dict(self.sections[0], key="other", label="Other")]
        self.write("p.json", {"newspaper": "Paper", "section_map": {"sports": ["Sports"]}, "other": ["Videos", "Sports"]})
        maps = config.load_section_maps(sections, self.dir)
        self.assertEqual(maps["Paper"], {"sports": ["sports"], "videos": ["other"]})
        fn.configure(sections, maps=maps)
        feed = {"category": "india", "newspaper": "Paper"}
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/videos/v1"), ["india", "other"])

    def test_labels_compare_loosely(self):
        self.assertEqual(config.norm_label("India-News"), config.norm_label("india news"))
        self.assertEqual(config.norm_label("Cities"), "cities")

    def test_unknown_destination_section_is_an_error(self):
        self.write("p.json", {"newspaper": "Paper", "section_map": {"nope": ["X"]}})
        with self.assertRaises(config.ConfigError):
            config.load_section_maps(self.sections, self.dir)

    def test_missing_folder_means_no_maps(self):
        import shutil
        shutil.rmtree(self.dir / "newspaper_sections")
        self.assertEqual(config.load_section_maps(self.sections, self.dir), {})
