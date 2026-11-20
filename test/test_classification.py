"""fetch_news.classify / place, driven by the sample sections (never the real ones)."""
import copy

import support
from support import SAMPLE_SECTIONS, TestCase

import config
import fetch_news as fn


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

    def test_no_keyword_guessing(self):
        for text in ("Army chief warns", "Sensex and inflation", "Cricket final tonight", "A film festival"):
            self.assertEqual(fn.classify({"category": "world", "general": True}, text, "the navy actor"), ["world"])

    def test_sections_json_no_longer_accepts_keyword_rules(self):
        data = copy.deepcopy(SAMPLE_SECTIONS)
        data["sections"][3]["keywords"] = ["cricket"]
        import pathlib, tempfile
        d = support.write_config(pathlib.Path(tempfile.mkdtemp()), sections=data)
        with self.assertRaises(config.ConfigError):
            config.load_sections(d)


class PlaceTest(TestCase):
    def test_country_and_continent_are_always_the_newspapers(self):
        feed = {"category": "world", "country": "France", "continent": "Europe"}
        self.assertEqual(fn.place(feed), ("France", "Europe"))                 # whatever the headline is about
        self.assertEqual(fn.place({"category": "india", "country": "Bangladesh", "continent": "Asia"}), ("Bangladesh", "Asia"))
        self.assertEqual(fn.place({"category": "world"}), ("Other", "Other"))


class NewspaperSectionMapTest(TestCase):
    """external_config/newspaper_sections/<paper>.json: many newspaper sections -> one UI section."""

    def setUp(self):
        super().setUp()
        import json, pathlib, tempfile
        self.dir = pathlib.Path(tempfile.mkdtemp())
        support.write_config(self.dir)
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
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/videos/v1", ["Sports"]), ["india", "sports"])   # a topic wins over Other

    def test_labels_compare_loosely(self):
        self.assertEqual(config.norm_label("India-News"), config.norm_label("india news"))
        self.assertEqual(config.norm_label("Cities"), "cities")

    def test_names_in_any_script_stay_distinct(self):
        self.assertNotEqual(config.norm_label("খেলা"), config.norm_label("বিনোদন"))          # Bengali: sports vs entertainment
        self.assertEqual(config.norm_label("விளையாட்டு "), "விளையாட்டு")                        # Tamil: the vowel signs are kept
        self.assertEqual(config.norm_label("खेल"), "खेल")                                        # Devanagari
        self.assertEqual(config.norm_label("தேசிய செய்திகள் (National News)"), "தேசிய செய்திகள் national")
        self.assertEqual(config.norm_label("%%"), "")

    def test_a_regional_language_map_places_stories_by_native_tags_and_comma_tags(self):
        self.write("p.json", {"newspaper": "Paper", "section_map": {"sports": ["খেলা", "Sports"], "showbiz": ["বিনোদন"]}})
        maps = config.load_section_maps(self.sections, self.dir)
        fn.configure(self.sections, maps=maps)
        feed = {"category": "india", "newspaper": "Paper"}
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/a/b", ["খেলা"]), ["india", "sports"])
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/a/b", ["বিনোদন"]), ["india", "showbiz"])
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/a/b", ["অন্য"]), ["india"])             # unmapped: only its own section
        self.assertEqual(fn.classify(feed, "x", "", "https://p.com/a/b", ["India,Sports,Top News"]), ["india", "sports"])

    def test_unknown_destination_section_is_an_error(self):
        self.write("p.json", {"newspaper": "Paper", "section_map": {"nope": ["X"]}})
        with self.assertRaises(config.ConfigError):
            config.load_section_maps(self.sections, self.dir)

    def test_missing_folder_means_no_maps(self):
        import shutil
        shutil.rmtree(self.dir / "newspaper_sections")
        self.assertEqual(config.load_section_maps(self.sections, self.dir), {})
        with self.assertRaises(config.ConfigError):                      # and without files there are no newspapers at all
            config.load_newspapers(self.sections, self.dir)

