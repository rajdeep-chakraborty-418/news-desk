"""topics.py: topic buttons built from the stories' own keywords, and the optional continent_filter of a section."""
import json
import pathlib
import tempfile

import support
from support import TestCase

import config
import topics


def spec(**kw):
    d = pathlib.Path(tempfile.mkdtemp())
    support.write_config(d)
    (d / "topics").mkdir()
    (d / "topics" / "sports.json").write_text(json.dumps(kw))
    return topics.load_topics(config.load_sections(d), d)["sports"]


def story(link, tags=(), sections=("sports",)):
    return {"link": link, "sections": list(sections), "_tags": topics.split_tags(tags), "_folders": topics.folders_of(link)}


class LoadTest(TestCase):
    def test_merge_names_compare_loosely_and_a_name_can_feed_two_buttons(self):
        sp = spec(merge={"Cricket · ক্রিকেট": ["ক্রিকেট", "Cricket"], "Sports · খেলা": ["খেলা", "ক্রিকেট"]}, hide=["Top Stories"])
        self.assertEqual(sp["alias"][config.norm_label("ক্রিকেট")], ["Cricket · ক্রিকেট", "Sports · খেলা"])
        self.assertEqual(sp["alias"]["cricket"], ["Cricket · ক্রিকেট"])
        self.assertEqual(sp["hide"], {"top stories"})
        self.assertEqual((sp["min_count"], sp["max_topics"]), (5, 12))

    def test_bad_files_are_configuration_errors(self):
        d = pathlib.Path(tempfile.mkdtemp())
        support.write_config(d)
        (d / "topics").mkdir()
        sections = config.load_sections(d)
        for name, body in (("nope.json", "{}"), ("sports.json", "[]"), ("sports.json", '{"min_count": 0}'),
                           ("sports.json", '{"merge": {"A": "x"}}'), ("sports.json", '{"hide": [1]}'), ("sports.json", "{oops")):
            for f in (d / "topics").glob("*.json"):
                f.unlink()
            (d / "topics" / name).write_text(body)
            with self.assertRaises(config.ConfigError, msg=name):
                topics.load_topics(sections, d)

    def test_no_topics_folder_means_no_topics(self):
        d = pathlib.Path(tempfile.mkdtemp())
        support.write_config(d)
        self.assertEqual(topics.load_topics(config.load_sections(d), d), {})


class ApplyTest(TestCase):
    def test_buttons_are_the_most_frequent_topics_with_merged_names_counted_once(self):
        sp = spec(min_count=2, max_topics=3, merge={"Sports": ["খেলা", "Sports"], "Cricket": ["ক্রিকেট", "Cricket"]}, hide=["Top Stories"])
        items = [story("https://p.example/a/1", ["Cricket", "খেলা", "Top Stories"]),
                 story("https://p.example/sports/2", ["ক্রিকেট"]),
                 story("https://p.example/a/3", ["Sports,Mamata Banerjee"]),
                 story("https://p.example/a/4", ["Mamata Banerjee", "One-off"]),
                 story("https://p.example/a/5", ["Cricket"], sections=("world",))]            # not in the section: ignored
        result = topics.apply(items, {"sports": sp})
        self.assertEqual(result["sports"], [{"label": "Sports", "count": 3}, {"label": "Cricket", "count": 2}, {"label": "Mamata Banerjee", "count": 2}])
        self.assertEqual(items[0]["topics"], ["Sports", "Cricket"])
        self.assertEqual(items[1]["topics"], ["Sports", "Cricket"])                           # /sports/ in its address + the tag ক্রিকেট
        self.assertEqual(items[3]["topics"], ["Mamata Banerjee"])                            # "One-off" is below min_count, "Top Stories" is hidden
        self.assertEqual(items[2]["topics"], ["Sports", "Mamata Banerjee"])                  # a comma tag is two tags
        self.assertNotIn("topics", items[4])
        self.assertTrue(all("_tags" not in i and "_folders" not in i for i in items))        # working keys never reach news.json

    def test_folders_only_count_when_the_name_is_merged(self):
        sp = spec(min_count=1, merge={"Sports": ["sports"]})
        items = [story("https://p.example/sports/x/1"), story("https://p.example/opinion/x/2"), story("https://p.example/x/3")]
        result = topics.apply(items, {"sports": sp})
        self.assertEqual(result["sports"], [{"label": "Sports", "count": 1}])
        self.assertEqual([i["topics"] for i in items], [["Sports"], [], []])

    def test_other_sections_are_untouched_and_working_keys_removed(self):
        items = [story("https://p.example/a", ["X"], sections=("world",))]
        self.assertEqual(topics.apply(items, {}), {})
        self.assertEqual(items, [{"link": "https://p.example/a", "sections": ["world"]}])


class ContinentFilterTest(TestCase):
    def test_continent_filter_is_optional_and_must_be_true_or_false(self):
        d = pathlib.Path(tempfile.mkdtemp())
        data = json.loads(json.dumps(support.SAMPLE_SECTIONS))
        data["sections"][1]["continent_filter"] = False
        support.write_config(d, sections=data)
        sections = config.load_sections(d)
        self.assertEqual([s.get("continent_filter") for s in sections][:3], [None, False, None])
        self.assertEqual(config.public_sections(sections)[1]["continent_filter"], False)
        self.assertNotIn("continent_filter", config.public_sections(sections)[0])
        data["sections"][1]["continent_filter"] = "no"
        support.write_config(d, sections=data)
        with self.assertRaises(config.ConfigError):
            config.load_sections(d)
