"""split_news.py: one small data file per section plus a pool for the Home page."""
import json
import pathlib
import tempfile

import support
from support import TestCase

import split_news


def item(n, sections, image=True, published=None):
    return {"title": f"T{n}", "link": f"https://x/{n}", "image": "https://i/p.jpg" if image else "", "sections": sections,
            "published": published or f"2026-11-20T{n % 24:02d}:00:00Z"}


NEWS = {"generated_at": "g", "range_hours": 24, "max_articles": 3000, "topics": {"regional": [{"label": "Assam", "count": 1}]},
        "feeds": [{"x": 1}], "items": [item(1, ["world"]), item(2, ["world", "defence"]), item(3, ["regional"], image=False)]}


class SplitTest(TestCase):
    def test_every_section_gets_its_own_stories_and_nothing_else(self):
        files = split_news.split(NEWS)
        self.assertEqual(sorted(files), ["defence", "home", "regional", "world"])
        self.assertEqual([i["title"] for i in files["world"]["items"]], ["T1", "T2"])
        self.assertEqual([i["title"] for i in files["defence"]["items"]], ["T2"])
        self.assertEqual(files["regional"]["topics"], {"regional": [{"label": "Assam", "count": 1}]})
        self.assertEqual(files["world"]["topics"], {})
        self.assertNotIn("feeds", files["world"])
        self.assertEqual((files["world"]["generated_at"], files["world"]["range_hours"], files["world"]["max_articles"]), ("g", 24, 3000))

    def test_home_pool_prefers_pictures_and_lists_a_story_once(self):
        news = {"items": [item(n, ["world"], image=n % 2 == 0, published=f"2026-11-{10 + n // 24:02d}T{n % 24:02d}:00:00Z") for n in range(200)]}
        news["items"].append(dict(item(500, ["world", "defence"]), published="2026-11-25T00:00:00Z"))
        pool = split_news.split(news)["home"]["items"]
        world = [i for i in pool if "world" in i["sections"]]
        self.assertEqual(sum(1 for i in world if i["image"]), split_news.HOME_WITH_PICTURE)
        self.assertEqual(sum(1 for i in world if not i["image"]), split_news.HOME_WITHOUT_PICTURE)
        self.assertEqual(len({i["link"] for i in pool}), len(pool))

    def test_write_replaces_old_files(self):
        with tempfile.TemporaryDirectory() as d:
            split_news.write(NEWS, d)
            self.assertTrue((pathlib.Path(d) / "data" / "regional.json").exists())
            split_news.write({"items": [item(1, ["world"])]}, d)
            self.assertFalse((pathlib.Path(d) / "data" / "regional.json").exists())
            self.assertEqual(json.loads((pathlib.Path(d) / "data" / "world.json").read_text())["items"][0]["title"], "T1")
