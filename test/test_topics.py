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


class HeadlineTopicsTest(TestCase):
    SPEC = {"min_count": 8, "min_newspapers": 2, "max_topics": 12, "stopwords": set(), "hide": set(), "native_only": True}

    def stories(self, titles_per_paper):
        return [{"title": t, "newspaper": p} for p, titles in titles_per_paper.items() for t in titles]

    def test_stem_joins_case_endings(self):
        self.assertEqual({topics.stem(w) for w in ("কলকাতার", "কলকাতায়", "কলকাতাকে")}, {"কলকাতা"})
        self.assertEqual(topics.stem("বৃষ্টি"), "বৃষ্টি")

    def test_trending_word_needs_stories_and_newspapers(self):
        items = self.stories({"A": ["আকভান ঝড় %d" % i for i in range(6)], "B": ["আকভানের প্রভাব %d" % i for i in range(4)]})
        items += [{"title": "অন্য খবর %d" % i, "newspaper": "A"} for i in range(40)]
        found, order = topics.headline_topics(items, self.SPEC)
        self.assertIn("আকভান", order)
        self.assertEqual(len(found["আকভান"]), 10)
        one_paper = [{"title": "শুধু এক কাগজ", "newspaper": "A"}] * 12 + [{"title": "অন্য %d" % i, "newspaper": "B"} for i in range(40)]
        self.assertNotIn("কাগজ", topics.headline_topics(one_paper, self.SPEC)[1])

    def test_filler_words_and_english_are_not_topics(self):
        items = [{"title": "Cyclone: নিয়ে নয় আকভান %d" % i, "newspaper": "AB"[i % 2]} for i in range(10)]
        items += [{"title": "অন্য খবর %d" % i, "newspaper": "A"} for i in range(40)]
        order = topics.headline_topics(items, self.SPEC)[1]
        self.assertEqual(order, ["আকভান"])


class StatesModeTest(TestCase):
    def test_buttons_are_the_states_of_the_newspapers(self):
        spec = {"mode": "states", "min_count": 1, "max_topics": 40, "newspaper_states": {"Pudhari": ["Maharashtra (महाराष्ट्र)"], "Sambad": ["Odisha (ଓଡ଼ିଶା)"],
                "Vaartha": ["Telangana (తెలంగాణ)", "Andhra Pradesh (ఆంధ్రప్రదేశ్)"]}}
        items = [{"newspaper": "Pudhari", "sections": ["regional"]}, {"source": "Pudhari", "sections": ["regional"]},
                 {"newspaper": "Sambad", "sections": ["regional"]}, {"newspaper": "Vaartha", "sections": ["regional"]},
                 {"newspaper": "Navbharat Times", "sections": ["regional"]}, {"newspaper": "Pudhari", "sections": ["world"]}]
        out = topics.apply(items, {"regional": spec})["regional"]
        self.assertEqual(out[0], {"label": "Maharashtra (महाराष्ट्र)", "count": 2})
        self.assertEqual(len(out), 4)
        self.assertEqual(items[3]["topics"], ["Telangana (తెలంగాణ)", "Andhra Pradesh (ఆంధ్రప్రదేశ్)"])
        self.assertEqual(items[4]["topics"], [])                       # a newspaper without a state: only under All
        self.assertNotIn("topics", items[5])                           # another section is untouched

    def test_state_in_a_newspaper_file_needs_both_names(self):
        import config
        for bad in ({"en": "Assam"}, {"en": "", "local": "অসম"}, [], "Assam"):
            with self.assertRaises(config.ConfigError):
                with tempfile.TemporaryDirectory() as d:
                    support.write_config(pathlib.Path(d), newspapers={"primary": [], "secondary": [{"name": "P", "homepage": "https://p.example/", "state": bad,
                                         "feeds": [{"url": "https://p.example/f", "section": "world"}]}]})
                    config.load_newspapers(config.load_sections(d), d)


class SectionTierTest(TestCase):
    def load(self, **extra):
        import config
        with tempfile.TemporaryDirectory() as d:
            sec = {"key": "a", "label": "A", "color": {"light": "#112233", "dark": "#aabbcc"}, **extra}
            support.write_config(pathlib.Path(d), sections={"sections": [sec]})
            return config.load_sections(d)[0]

    def test_tier_rank_and_description_are_kept_only_when_set(self):
        self.assertNotIn("tier", self.load())
        got = self.load(tier=1, rank=2, description=" One line. ")
        self.assertEqual((got["tier"], got["rank"], got["description"]), (1, 2, "One line."))

    def test_bad_values_are_rejected(self):
        import config
        for bad in ({"tier": 4}, {"tier": "1"}, {"tier": True}, {"rank": "x"}, {"description": ""}, {"description": 5}):
            with self.assertRaises(config.ConfigError):
                self.load(**bad)


class EnglishHeadlineTopics(TestCase):
    def spec(self, **kw):
        s = {"mode": "headlines", "language": "english", "min_count": 3, "min_newspapers": 3, "max_topics": 20,
             "stopwords": set(), "hide": set(), "alias": {}, "native_only": False, "rank": "newspapers"}
        s.update(kw)
        return s

    def stories(self, titles):
        return [{"title": t, "newspaper": "P%d" % (i % 5)} for i, t in enumerate(titles)]

    def test_filler_words_are_not_topics_and_plurals_merge(self):
        titles = ["Nepal earthquake strikes villages", "Nepal earthquakes hit again", "Against all odds Nepal quake", "Nepal earthquake toll rises",
                  "Rs 5 lakh seized", "Rs 2 lakh bribe", "Lakh Rs fine", "Market opens flat", "Weather turns cold", "Cricket final today"]
        found, order = topics.headline_topics(self.stories(titles), self.spec())
        self.assertTrue([l for l in order if "Nepal" in l])
        self.assertNotIn("Against", order)
        self.assertNotIn("Rs", order)
        self.assertFalse([l for l in order if l.lower() == "earthquakes"])

    def test_acronym_and_companion_names(self):
        titles = ["US sanctions Nvidia", "Jensen Huang returns to Nvidia", "Nvidia chief Jensen Huang speaks", "Nvidia: Jensen Huang back",
                  "US mulls tariffs", "US vote delayed", "US border row", "US jobs data", "Weather in Oslo", "Football news", "Chess finals"]
        found, order = topics.headline_topics(self.stories(titles), self.spec())
        self.assertIn("US", order)
        joined = [l for l in order if "Nvidia" in l]
        self.assertEqual(len(joined), 1)
        self.assertIn("Jensen Huang", joined[0])

    def test_hide_and_max_topics_are_parameters(self):
        titles = ["Kallakurichi row grows", "Kallakurichi MLA booked", "Kallakurichi protest", "Kallakurichi inquiry",
                  "Sabarimala rush", "Sabarimala slots", "Sabarimala queue", "Sabarimala pilgrims", "Delhi smog", "Delhi smog again", "Delhi smog worse"]
        s = self.stories(titles)
        _, order = topics.headline_topics(s, self.spec(hide={"delhi"}))
        self.assertNotIn("Delhi", order)
        _, order = topics.headline_topics(s, self.spec(max_topics=1))
        self.assertEqual(len(order), 1)

    def test_ranked_by_newspapers_not_stories(self):
        many = [{"title": "Alpha storm hits", "newspaper": "A"} for _ in range(10)]
        wide = [{"title": "Beta flood hits", "newspaper": "P%d" % i} for i in range(6)]
        _, order = topics.headline_topics(many + wide, self.spec(min_count=5, min_newspapers=1))
        self.assertTrue(order[0].startswith("Beta"))

    def test_common_nouns_are_not_names(self):
        titles = ["Govt opens hospital in Pune", "Big hospital fee hike", "Parents protest hospital rules", "New hospital bus norms", "Chennai hospital reopens",
                  "Modi visits Bihar", "Narendra Modi in Delhi", "PM Modi addresses rally", "Modi government plan", "Rahul slams Modi"]
        _, order = topics.headline_topics(self.stories(titles), self.spec(min_count=4))
        self.assertIn("Modi", order)
        self.assertNotIn("Hospital", order)
        _, order = topics.headline_topics(self.stories(titles), self.spec(min_count=4, names_only=False))
        self.assertIn("Hospital", order)
