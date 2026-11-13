"""config.py: loading, validating and flattening newspapers.json / sections.json."""
import copy
import json

import support
from support import SAMPLE_NEWSPAPERS, SAMPLE_SECTIONS, TestCase, write_config

import config


class LoadSectionsTest(TestCase):
    def test_loads_in_file_order_with_compiled_rules(self):
        secs = config.load_sections(support.SAMPLE_CONFIG)
        self.assertEqual([s["key"] for s in secs], ["home", "india", "world", "sports", "showbiz", "defence", "money"])
        sports = secs[3]
        self.assertTrue(sports["rx"].search("A Cricket final") and not sports["rx"].search("crickets sing"))   # whole words, any case
        self.assertTrue(sports["general"])
        showbiz = secs[4]
        self.assertFalse(showbiz["rx"].search("a festival"))                 # extra words only for general newspapers
        self.assertTrue(showbiz["rx_general"].search("a festival"))
        self.assertEqual(showbiz["also_from"], ["world", "india"])
        self.assertIsNone(secs[2]["rx"])                                     # a section without keywords has no rule

    def test_place_rules(self):
        secs = {s["key"]: s for s in config.load_sections(support.SAMPLE_CONFIG)}
        self.assertEqual(secs["home"]["place"], "newspaper")
        self.assertEqual(secs["india"]["place"], {"country": "India", "continent": "Asia"})
        self.assertIsNone(secs["world"]["place"])

    def _bad(self, mutate, message):
        data = copy.deepcopy(SAMPLE_SECTIONS)
        mutate(data["sections"])
        d = write_config(self.tmp / "c", sections=data)
        with self.assertRaises(config.ConfigError) as cm:
            config.load_sections(d)
        self.assertIn(message, str(cm.exception))

    def test_validation_errors_are_specific(self):
        self._bad(lambda s: s[0].update(key="Bad Key"), "'key' must be lowercase")
        self._bad(lambda s: s[1].update(key="home"), "listed twice")
        self._bad(lambda s: s[0].pop("label"), "'label' is required")
        self._bad(lambda s: s[0].update(color={"light": "red", "dark": "#000000"}), "'color' must be")
        self._bad(lambda s: s[0].update(place="elsewhere"), "'place' must be")
        self._bad(lambda s: s[3].update(keywords="cricket"), "'keywords' must be a list")
        self._bad(lambda s: s[4].update(also_from_sections=["nope"]), "names 'nope', which is not a section")

    def test_empty_or_wrong_shape(self):
        for bad in ({"sections": []}, {"nope": 1}, []):
            d = write_config(self.tmp / "c", sections=bad)
            with self.assertRaises(config.ConfigError):
                config.load_sections(d)

    def test_missing_and_malformed_files(self):
        with self.assertRaises(config.ConfigError) as cm:
            config.load_sections(self.tmp / "nowhere")
        self.assertIn("not found", str(cm.exception))
        d = write_config(self.tmp / "c")
        (d / "sections.json").write_text("{not json")
        with self.assertRaises(config.ConfigError) as cm:
            config.load_sections(d)
        self.assertIn("not valid JSON", str(cm.exception))


class LoadNewspapersTest(TestCase):
    def setUp(self):
        super().setUp()
        self.sections = config.load_sections(support.SAMPLE_CONFIG)

    def _bad(self, mutate, message):
        data = copy.deepcopy(SAMPLE_NEWSPAPERS)
        mutate(data)
        d = write_config(self.tmp / "c", newspapers=data)
        with self.assertRaises(config.ConfigError) as cm:
            config.load_newspapers(self.sections, d)
        self.assertIn(message, str(cm.exception))

    def test_loads_primary_and_secondary_nodes(self):
        data = config.load_newspapers(self.sections, support.SAMPLE_CONFIG)
        self.assertEqual([p["name"] for p in data["primary"]], ["Alpha Times", "Gazette Home"])
        self.assertEqual([p["name"] for p in data["secondary"]], ["Beta Post", "Gamma Wire", "Hidden Search"])

    def test_validation_errors_name_the_newspaper(self):
        self._bad(lambda d: d.pop("secondary"), 'must be {"primary"')
        self._bad(lambda d: d["primary"][0].pop("name"), "'name' is required")
        self._bad(lambda d: d["primary"][0].update(homepage="alphatimes.example"), "'homepage' must be a web address")
        self._bad(lambda d: d["primary"][0].update(continent="Atlantis"), "'continent' must be one of")
        self._bad(lambda d: d["primary"][0].update(feeds=[]), "needs at least one entry in 'feeds'")
        self._bad(lambda d: d["primary"][0]["feeds"][0].update(url="ftp://x"), "every feed needs a 'url'")
        self._bad(lambda d: d["primary"][0]["feeds"][0].update(section="cooking"), "'cooking', which is not in sections.json")
        self._bad(lambda d: d["secondary"][0]["feeds"][0].update(continent="Mars"), "unknown continent")
        with self.assertRaises(config.ConfigError) as cm:
            data = copy.deepcopy(SAMPLE_NEWSPAPERS); data["primary"][0]["feeds"][0]["section"] = "cooking"
            config.load_newspapers(self.sections, write_config(self.tmp / "d", newspapers=data))
        self.assertIn("Alpha Times", str(cm.exception))

    def test_feed_in_a_section_that_was_removed_from_sections_json_is_rejected(self):
        fewer = [s for s in self.sections if s["key"] != "defence"]
        data = copy.deepcopy(SAMPLE_NEWSPAPERS)
        data["secondary"][0]["feeds"][0]["section"] = "defence"
        d = write_config(self.tmp / "c", newspapers=data)
        with self.assertRaises(config.ConfigError):
            config.load_newspapers(fewer, d)


class FlattenTest(TestCase):
    def setUp(self):
        super().setUp()
        self.sections, self.feeds = config.load_all(support.SAMPLE_CONFIG)
        self.by_url = {f["url"]: f for f in self.feeds}

    def test_one_entry_per_feed_with_primary_from_the_node(self):
        self.assertEqual(len(self.feeds), 6)
        self.assertTrue(self.by_url["https://www.alphatimes.example/rss/india.xml"]["primary"])
        self.assertFalse(self.by_url["https://betapost.example/rss"]["primary"])

    def test_source_label_defaults_to_the_newspaper_name(self):
        self.assertEqual(self.by_url["https://www.alphatimes.example/rss/india.xml"]["source"], "Alpha Times")
        self.assertEqual(self.by_url["https://www.alphatimes.example/rss/world.xml"]["source"], "Alpha Times (World)")
        self.assertEqual(self.by_url["https://www.alphatimes.example/rss/world.xml"]["newspaper"], "Alpha Times")

    def test_country_and_continent_inherit_and_can_be_overridden_per_feed(self):
        self.assertEqual(self.by_url["https://betapost.example/rss"]["country"], "France")
        gamma = self.by_url["https://news.google.com/rss/search?q=site%3Agammawire.example%20when%3A3d&hl=en-US"]
        self.assertEqual((gamma["country"], gamma["continent"]), ("United Kingdom", "Europe"))
        hidden = self.by_url["https://news.google.com/rss/search?q=film%20festival%20when%3A3d"]
        self.assertEqual((hidden["country"], hidden["continent"]), (None, None))

    def test_flags_state_and_section(self):
        gazette = self.by_url["https://gazettehome.example/feed"]
        self.assertEqual(gazette["state"], "Dhaka")
        self.assertEqual((gazette["section"], gazette["category"]), ("home", "home"))
        self.assertTrue(self.by_url["https://www.alphatimes.example/rss/world.xml"]["general"])
        self.assertNotIn("general", self.by_url["https://betapost.example/rss"])


class PublicListsTest(TestCase):
    def setUp(self):
        super().setUp()
        sections, self.feeds = config.load_all(support.SAMPLE_CONFIG)
        self.newspapers = config.load_newspapers(sections, support.SAMPLE_CONFIG)
        self.sections = sections

    def test_public_sections_carry_only_what_the_page_needs(self):
        pub = config.public_sections(self.sections)
        self.assertEqual(pub[0], {"key": "home", "label": "Home News", "color": {"light": "#b0123a", "dark": "#ff7a9a"}})
        self.assertNotIn("keywords", pub[3])

    def test_dropdown_list_is_sorted_skips_unlisted_and_marks_primary(self):
        pub = config.public_newspapers(self.newspapers)
        self.assertEqual([p["name"] for p in pub], ["Alpha Times", "Beta Post", "Gamma Wire", "Gazette Home"])
        self.assertNotIn("Hidden Search", [p["name"] for p in pub])
        by = {p["name"]: p for p in pub}
        self.assertTrue(by["Alpha Times"]["primary"] and not by["Beta Post"]["primary"])
        self.assertEqual(by["Gamma Wire"]["country"], "International")          # no country given
        self.assertEqual(by["Gamma Wire"]["continent"], "Other")
        self.assertEqual(by["Alpha Times"]["url"], "https://www.alphatimes.example/")

    def test_a_homepage_listed_twice_appears_once_as_primary_and_keeps_both_names(self):
        data = copy.deepcopy(SAMPLE_NEWSPAPERS)
        dup = copy.deepcopy(data["primary"][0]); dup["name"] = "Alpha Times Brunch"
        data["secondary"].append(dup)
        pub = config.public_newspapers(data)
        alpha = [p for p in pub if "alphatimes" in p["url"]]
        self.assertEqual([p["name"] for p in alpha], ["Alpha Times"])
        self.assertEqual(alpha[0]["names"], ["Alpha Times", "Alpha Times Brunch"])      # stories from either name belong to it
        self.assertTrue(alpha[0]["primary"])

    def test_every_entry_lists_its_own_name(self):
        for p in config.public_newspapers(self.newspapers):
            self.assertIn(p["name"], p["names"])

    def test_sort_ignores_a_leading_the(self):
        data = copy.deepcopy(SAMPLE_NEWSPAPERS)
        data["secondary"][0]["name"] = "The Zebra Post"; data["secondary"][0]["homepage"] = "https://zebra.example/"
        names = [p["name"] for p in config.public_newspapers(data)]
        self.assertEqual(names[-1], "The Zebra Post")


class ConfigDirTest(TestCase):
    def test_environment_variable_selects_the_folder(self):
        import os
        d = write_config(self.tmp / "other", sections={"sections": [SAMPLE_SECTIONS["sections"][2]]},
                         newspapers={"primary": [], "secondary": SAMPLE_NEWSPAPERS["secondary"][:1]})
        old = os.environ["NEWSDESK_CONFIG_DIR"]
        os.environ["NEWSDESK_CONFIG_DIR"] = str(d)
        try:
            self.assertEqual(config.config_dir(), d)
            sections, feeds = config.load_all()
            self.assertEqual([s["key"] for s in sections], ["world"])
            self.assertEqual(len(feeds), 1)
        finally:
            os.environ["NEWSDESK_CONFIG_DIR"] = old

    def test_default_folder_is_external_config_next_to_src(self):
        import os
        old = os.environ.pop("NEWSDESK_CONFIG_DIR")
        try:
            self.assertEqual(config.config_dir(), support.REPO / "external_config")
        finally:
            os.environ["NEWSDESK_CONFIG_DIR"] = old
