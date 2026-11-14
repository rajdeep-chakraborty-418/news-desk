"""fetch_news: time window, story count, per-feed limits, fetch_one, enrichment, trimming, and the whole run (main)."""
import contextlib
import io
import json
import os
from unittest import mock

import support
from support import FakeResp, TestCase, hours_ago, rss, story

import config
import fetch_news as fn
import settings


def setup_module_state():
    sections, _ = config.load_all(support.SAMPLE_CONFIG)
    fn.configure(sections)


class EnvTestCase(TestCase):
    def setUp(self):
        super().setUp()
        setup_module_state()
        for k in ("WINDOW_HOURS", "ARTICLE_COUNT"):
            os.environ.pop(k, None)
            self.addCleanup(os.environ.pop, k, None)
        self.addCleanup(setattr, fn, "WINDOW_HOURS", 24)
        self.addCleanup(setattr, fn, "ARTICLE_COUNT", 300)


class WindowAndCountTest(EnvTestCase):
    """The allowed values and defaults come from settings.json (the sample allows 6/24/72/168 and 50/150/250)."""

    def test_window_hours_uses_the_configured_choices(self):
        for val, want in (("6", 6), ("24", 24), ("72", 72), ("168", 168),
                          ("12", 24), ("720", 24), ("abc", 24), ("", 24), ("-1", 24)):   # 12 and 720 are not in the sample
            os.environ["WINDOW_HOURS"] = val
            self.assertEqual(fn.window_hours(), want, val)
        del os.environ["WINDOW_HOURS"]
        self.assertEqual(fn.window_hours(), 24)

    def test_article_count_uses_the_configured_choices(self):
        for val, want in (("50", 50), ("150", 150), ("250", 250), ("300", 150), ("1000", 150), ("x", 150), ("", 150)):
            os.environ["ARTICLE_COUNT"] = val
            self.assertEqual(fn.article_count(), want, val)
        del os.environ["ARTICLE_COUNT"]
        self.assertEqual(fn.article_count(), 150)

    def test_a_different_settings_file_changes_the_choices(self):
        data = json.loads(json.dumps(support.SAMPLE_SETTINGS))
        data["time_ranges"]["options"].append({"hours": 12, "label": "Half day"})
        data["article_counts"].update(options=[10, 20], default=20)
        st = settings.load_settings(support.write_config(self.tmp / "c", settings=data))
        fn.configure(config.load_sections(support.SAMPLE_CONFIG), st)
        os.environ["WINDOW_HOURS"], os.environ["ARTICLE_COUNT"] = "12", "10"
        self.assertEqual((fn.window_hours(), fn.article_count()), (12, 10))
        os.environ["ARTICLE_COUNT"] = "150"
        self.assertEqual(fn.article_count(), 20)          # no longer allowed -> the new default

    def test_per_feed_limit_grows_with_the_window_and_the_requested_count(self):
        self.assertEqual([fn.per_feed_limit(h, 150) for h in (6, 24, 72, 168, 720, 2160)], [20, 20, 30, 50, 80, 100])
        self.assertEqual(fn.per_feed_limit(24, 300), 40)            # twice the default count -> twice the allowance
        self.assertEqual(fn.per_feed_limit(24, 50), 20)             # never below the base
        self.assertEqual(fn.per_feed_limit(24), 20)                 # default count

    def test_google_news_window_is_rewritten(self):
        g = "https://news.google.com/rss/search?q=site%3Agoal.com%20when%3A3d&hl=en-US&gl=US&ceid=US:en"
        self.assertIn("when%3A6h", fn.window_url(g, 6))
        self.assertIn("when%3A72h", fn.window_url(g, 72))
        self.assertIn("when%3A7d", fn.window_url(g, 168))
        self.assertIn("when%3A30d", fn.window_url(g, 720))
        self.assertIn("when%3A90d", fn.window_url(g, 2160))
        self.assertEqual(fn.window_url("https://x.example/feed", 6), "https://x.example/feed")


class FetchOneTest(EnvTestCase):
    FEED = {"source": "Alpha Times", "category": "world", "url": "https://n.example/feed", "country": "France",
            "continent": "Europe", "primary": True}

    def fetch(self, items, feed=None, hours=24, count=150):
        fn.WINDOW_HOURS, fn.ARTICLE_COUNT = hours, count
        with mock.patch.object(fn, "urlopen", lambda *a, **k: FakeResp(rss(items))):
            return fn.fetch_one(feed or self.FEED)

    def test_window_filters_stories_by_age(self):
        ages = [1, 5, 11, 20, 50, 100, 400, 1000, 3000]
        items = [{"title": f"S{h}", "link": f"https://n.example/{h}", "hours_ago": h} for h in ages]
        for hours, expect in ((6, 2), (24, 4), (72, 5), (168, 6), (720, 7), (2160, 8)):
            out, st = self.fetch(items, hours=hours)
            self.assertEqual((len(out), st["ok"], st["count"]), (expect, True, expect), hours)

    def test_story_fields(self):
        out, st = self.fetch([{"title": "Army exercise", "link": "https://n.example/1", "hours_ago": 2, "summary": "&lt;b&gt;s&lt;/b&gt;"}])
        s = out[0]
        self.assertEqual((s["title"], s["summary"], s["source"], s["primary"], s["category"]),
                         ("Army exercise", "s", "Alpha Times", True, "world"))
        self.assertEqual(s["sections"], ["world", "defence"])
        self.assertEqual((s["country"], s["continent"], s["state"]), ("France", "Europe", None))
        self.assertEqual(s["newspaper"], "Alpha Times")                     # the paper in newspapers.json, for the Newspaper Homepage page
        self.assertTrue(s["published"].endswith("+00:00"))

    def test_state_is_carried(self):
        out, _ = self.fetch([{"title": "t", "link": "https://n.example/1", "hours_ago": 1}], feed={**self.FEED, "state": "Kerala"})
        self.assertEqual(out[0]["state"], "Kerala")

    def test_newest_first_and_limited_per_feed(self):
        items = [{"title": f"S{i}", "link": f"https://n.example/{i}", "hours_ago": i / 10} for i in range(1, 60)]
        out, _ = self.fetch(items, hours=24, count=150)
        self.assertEqual(len(out), 20)
        self.assertEqual(out[0]["title"], "S1")
        out, _ = self.fetch(items, hours=24, count=250)           # more stories requested -> a bigger allowance
        self.assertEqual(len(out), 34)

    def test_undated_stories_are_kept(self):
        out, _ = self.fetch([{"title": "No date", "link": "https://n.example/1"}])
        self.assertEqual(len(out), 1)

    def test_a_broken_feed_never_raises(self):
        for opener in (mock.Mock(side_effect=OSError("boom")), lambda *a, **k: FakeResp(b"<html>nope")):
            with mock.patch.object(fn, "urlopen", opener):
                out, st = fn.fetch_one(self.FEED)
            self.assertEqual(out, [])
            self.assertFalse(st["ok"])
            self.assertIn("error", st)

    def test_google_news_url_uses_the_chosen_window(self):
        seen = []
        def opener(req, **k):
            seen.append(req.full_url); return FakeResp(rss([]))
        fn.WINDOW_HOURS = 168
        feed = {**self.FEED, "url": "https://news.google.com/rss/search?q=site%3Ax.example%20when%3A3d"}
        with mock.patch.object(fn, "urlopen", opener):
            fn.fetch_one(feed)
        self.assertIn("when%3A7d", seen[0])


class TrimTest(EnvTestCase):
    def test_keeps_each_sections_newest_stories(self):
        many = [story(i, ["world"], hours=i) for i in range(10)] + [story(100 + i, ["nature"], hours=i) for i in range(3)]
        kept = fn.trim_sections(many, keep=4)
        self.assertEqual(sum("world" in i["sections"] for i in kept), 4)
        self.assertEqual(sum("nature" in i["sections"] for i in kept), 3)
        self.assertEqual({i["link"] for i in kept if "world" in i["sections"]}, {f"https://news.example/{i}" for i in range(4)})

    def test_primary_papers_get_a_six_hour_boost(self):
        items = [story(1, ["world"], primary=False, hours=1), story(2, ["world"], primary=True, hours=5)]
        self.assertEqual([i["link"] for i in fn.trim_sections(items, keep=1)], ["https://news.example/2"])
        items = [story(1, ["world"], primary=False, hours=1), story(2, ["world"], primary=True, hours=8)]
        self.assertEqual([i["link"] for i in fn.trim_sections(items, keep=1)], ["https://news.example/1"])

    def test_a_story_in_two_sections_survives_if_either_keeps_it(self):
        items = [story(1, ["world", "defence"], hours=9)] + [story(10 + i, ["world"], hours=i) for i in range(3)]
        kept = fn.trim_sections(items, keep=3)
        self.assertIn("https://news.example/1", [i["link"] for i in kept])        # kept by "defence"

    def test_default_keep_is_the_configured_default_count(self):
        items = [story(i, ["world"], hours=i) for i in range(200)]
        self.assertEqual(len(fn.trim_sections(items)), 150)


class EnrichImagesTest(EnvTestCase):
    PAGE = b'<meta property="og:image" content="https://cdn.example/lead.jpg">'

    def run_enrich(self, items, opener):
        with mock.patch.object(fn, "urlopen", opener):
            return fn.enrich_images(items)

    def test_fills_missing_images_from_the_article_page(self):
        items = [story(1, ["world"]), story(2, ["world"], image="https://x.example/have.jpg")]
        got, tried = self.run_enrich(items, lambda *a, **k: FakeResp(self.PAGE))
        self.assertEqual((got, tried), (1, 1))
        self.assertEqual(items[0]["image"], "https://cdn.example/lead.jpg")
        self.assertEqual(items[1]["image"], "https://x.example/have.jpg")

    def test_google_news_links_are_not_fetched(self):
        calls = []
        items = [story(1, ["world"], link="https://news.google.com/rss/articles/abc")]
        self.run_enrich(items, lambda *a, **k: calls.append(a) or FakeResp(self.PAGE))
        self.assertEqual(calls, [])

    def test_failures_are_tolerated_and_a_failing_host_is_abandoned(self):
        calls = []
        def opener(req, **k):
            calls.append(req.full_url); raise OSError("down")
        items = [story(i, ["world"], link=f"https://dead.example/{i}") for i in range(10)]
        self.run_enrich(items, opener)
        self.assertTrue(all(not i["image"] for i in items))
        self.assertLess(len(calls), 10)               # after three failures with no success the host is skipped

    def test_the_number_tried_is_capped_in_proportion_to_the_count(self):
        items = [story(i, ["world"]) for i in range(30)]
        with mock.patch.object(fn, "OG_MAX_ITEMS", 10):
            fn.ARTICLE_COUNT = 150          # default count is 150 -> factor 1
            self.assertEqual(self.run_enrich(items, lambda *a, **k: FakeResp(b"<html></html>"))[1], 10)
            fn.ARTICLE_COUNT = 250          # 250/150 -> about 16
            self.assertEqual(self.run_enrich([story(i, ["world"]) for i in range(30)], lambda *a, **k: FakeResp(b"<html></html>"))[1], 16)


class MainRunTest(EnvTestCase):
    """The whole run with every network call mocked, writing into a temporary site folder."""

    def setUp(self):
        super().setUp()
        self.out = self.tmp / "site" / "news.json"
        for patcher in (mock.patch.object(fn, "OUT_FILE", self.out), mock.patch.object(fn.time, "sleep"),
                        mock.patch.object(fn, "enrich_images", lambda items: (0, 0))):
            patcher.start(); self.addCleanup(patcher.stop)
        self.requests = []

    def serve(self, table):
        """table: url substring -> bytes or Exception"""
        def opener(req, **k):
            self.requests.append(req.full_url)
            for key, val in table.items():
                if key in req.full_url:
                    if isinstance(val, Exception): raise val
                    return FakeResp(val)
            raise OSError("unexpected " + req.full_url)
        return mock.patch.object(fn, "urlopen", opener)

    def run_main(self, table, **env):
        with mock.patch.dict(os.environ, env), self.serve(table), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fn.main()
        return json.loads(self.out.read_text())

    def test_end_to_end(self):
        shared = {"title": "Army drill near border", "link": "https://shared.example/1", "hours_ago": 3}
        table = {
            "alphatimes.example/rss/india": rss([{"title": "Budget session opens", "link": "https://a.example/1", "hours_ago": 1}, shared]),
            "alphatimes.example/rss/world": rss([{"title": "Cricket final tonight", "link": "https://a.example/2", "hours_ago": 2,
                                                  "image": "https://img.example/2.jpg"}]),
            "gazettehome.example": rss([{"title": "Dhaka weather", "link": "https://g.example/1", "hours_ago": 4}]),
            "betapost.example": rss([{"title": "Army drill near border", "link": "https://shared.example/1", "hours_ago": 3,
                                      "image": "https://img.example/shared.jpg"}]),
            "gammawire.example": OSError("HTTP Error 503"),
            "film%20festival": rss([{"title": "Film festival opens", "link": "https://f.example/1", "hours_ago": 5}]),
        }
        data = self.run_main(table, WINDOW_HOURS="72", ARTICLE_COUNT="250")
        self.assertEqual((data["range_hours"], data["max_articles"]), (72, 250))
        self.assertTrue(data["generated_at"])
        small = json.loads((self.out.parent / "refresh.json").read_text())          # the tiny file the page reads for the cooldown
        self.assertEqual(small, {"refreshed_at": data["generated_at"], "range_hours": 72, "max_articles": 250})
        by_link = {i["link"]: i for i in data["items"]}
        self.assertEqual(set(by_link), {"https://a.example/1", "https://shared.example/1", "https://a.example/2",
                                        "https://g.example/1", "https://f.example/1"})
        self.assertEqual(data["items"][0]["link"], "https://a.example/1")                       # newest first
        # the same story from a primary and a secondary paper is merged: primary source, image from the other feed
        shared_item = by_link["https://shared.example/1"]
        self.assertEqual((shared_item["primary"], shared_item["source"], shared_item["newspaper"]), (True, "Alpha Times", "Alpha Times"))
        self.assertEqual(by_link["https://a.example/2"]["source"], "Alpha Times (World)")           # a feed label ...
        self.assertEqual(by_link["https://a.example/2"]["newspaper"], "Alpha Times")                # ... still maps to its newspaper
        self.assertEqual(shared_item["image"], "https://img.example/shared.jpg")
        self.assertEqual(shared_item["sections"], ["defence", "india", "world"])
        self.assertEqual(by_link["https://a.example/2"]["sections"], ["world", "sports"])      # general feed + keyword
        self.assertEqual(by_link["https://a.example/1"]["country"], "India")                    # pinned by the India section
        self.assertEqual(by_link["https://g.example/1"]["country"], "Bangladesh")               # taken from the newspaper
        self.assertEqual(by_link["https://g.example/1"]["state"], "Dhaka")
        # one status entry per feed; the 503 feed failed after a retry
        self.assertEqual(len(data["feeds"]), 6)
        bad = [f for f in data["feeds"] if not f["ok"]]
        self.assertEqual([f["source"] for f in bad], ["Gamma Wire"])
        self.assertEqual(sum("gammawire" in u for u in self.requests), 2)
        # Google News feeds use the 72-hour window
        self.assertTrue(any("when%3A72h" in u for u in self.requests if "film" in u))

    def test_defaults_when_no_environment_is_given(self):
        for k in ("WINDOW_HOURS", "ARTICLE_COUNT"):
            os.environ.pop(k, None)
        data = self.run_main({"": rss([{"title": "A story", "link": "https://a.example/1", "hours_ago": 1}])})
        self.assertEqual((data["range_hours"], data["max_articles"]), (24, 150))

    def test_invalid_environment_falls_back_to_the_defaults(self):
        data = self.run_main({"": rss([{"title": "A story", "link": "https://a.example/1", "hours_ago": 1}])},
                             WINDOW_HOURS="13", ARTICLE_COUNT="7")
        self.assertEqual((data["range_hours"], data["max_articles"]), (24, 150))

    def test_stories_per_section_are_capped_at_the_chosen_count(self):
        many = rss([{"title": f"Story {i}", "link": f"https://a.example/{i}", "hours_ago": i / 100} for i in range(1, 60)])
        data = self.run_main({"": many}, ARTICLE_COUNT="50", WINDOW_HOURS="24")
        per = {}
        for i in data["items"]:
            for s in i["sections"]:
                per[s] = per.get(s, 0) + 1
        self.assertTrue(per and all(n <= 50 for n in per.values()), per)

    def test_exits_with_an_error_when_nothing_could_be_fetched(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            self.run_main({"": OSError("offline")})
        self.assertEqual(cm.exception.code, 1)

    def test_a_configuration_error_stops_the_run_with_a_clear_message(self):
        bad = json.loads(json.dumps(support.SAMPLE_NEWSPAPERS)); bad["primary"][0]["feeds"][0]["section"] = "nope"
        d = support.write_config(self.tmp / "bad", newspapers=bad)
        with mock.patch.dict(os.environ, {"NEWSDESK_CONFIG_DIR": str(d)}), self.assertRaises(SystemExit) as cm, \
                contextlib.redirect_stdout(io.StringIO()):
            fn.main()
        self.assertIn("Configuration error", str(cm.exception.code))
        self.assertIn("nope", str(cm.exception.code))
        self.assertFalse(self.out.exists())

    def test_uses_whatever_config_folder_it_is_pointed_at(self):
        one = {"primary": [{"name": "Solo", "homepage": "https://solo.example/", "feeds": [
            {"section": "world", "url": "https://solo.example/feed"}]}], "secondary": []}
        d = support.write_config(self.tmp / "solo", newspapers=one)
        with mock.patch.dict(os.environ, {"NEWSDESK_CONFIG_DIR": str(d)}):
            data = self.run_main({"solo.example": rss([{"title": "Only story", "link": "https://solo.example/1", "hours_ago": 1}])})
        self.assertEqual([f["source"] for f in data["feeds"]], ["Solo"])
        self.assertEqual(len(data["items"]), 1)
