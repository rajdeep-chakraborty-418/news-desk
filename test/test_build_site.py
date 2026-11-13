"""build_site.py: assembles the published folder from src/web plus the sample configuration."""
import json
import os
from unittest import mock

import support
from support import TestCase, write_config

import build_site
import config


class BuildSiteTest(TestCase):
    def test_writes_page_and_the_three_data_files(self):
        n_sections, n_papers, out = build_site.build(self.tmp / "site")
        self.assertEqual((n_sections, n_papers), (7, 4))
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["index.html", "papers.json", "sections.json", "settings.json"])
        self.assertEqual((out / "index.html").read_bytes(), (support.SRC / "web" / "index.html").read_bytes())

    def test_sections_json_for_the_page(self):
        build_site.build(self.tmp / "site")
        secs = json.loads((self.tmp / "site" / "sections.json").read_text())
        self.assertEqual([s["key"] for s in secs], ["home", "india", "world", "sports", "showbiz", "defence", "money"])
        self.assertEqual(secs[0], {"key": "home", "label": "Home News", "color": {"light": "#b0123a", "dark": "#ff7a9a"}})
        self.assertTrue(all(set(s) == {"key", "label", "color"} for s in secs))

    def test_papers_json_for_the_dropdown(self):
        build_site.build(self.tmp / "site")
        papers = json.loads((self.tmp / "site" / "papers.json").read_text())
        self.assertEqual([p["name"] for p in papers], ["Alpha Times", "Beta Post", "Gamma Wire", "Gazette Home"])

    def test_settings_json_for_the_page(self):
        build_site.build(self.tmp / "site")
        st = json.loads((self.tmp / "site" / "settings.json").read_text())
        self.assertEqual(st["request_topic"], "test-topic-abc")
        self.assertEqual(st["default_hours"], 24)
        self.assertEqual(st["article_counts"], [50, 150, 250])
        self.assertEqual([r["label"] for r in st["time_ranges"]], ["Six hours", "One day", "Three days", "One week"])

    def test_follows_the_config_folder(self):
        small = {"sections": [support.SAMPLE_SECTIONS["sections"][2]]}
        d = write_config(self.tmp / "cfg", sections=small, newspapers={"primary": [], "secondary": support.SAMPLE_NEWSPAPERS["secondary"][:1]})
        with mock.patch.dict(os.environ, {"NEWSDESK_CONFIG_DIR": str(d)}):
            n_sections, n_papers, _ = build_site.build(self.tmp / "site")
        self.assertEqual((n_sections, n_papers), (1, 1))

    def test_bad_configuration_raises_before_writing_anything(self):
        bad = json.loads(json.dumps(support.SAMPLE_NEWSPAPERS)); bad["primary"][0]["homepage"] = "nope"
        d = write_config(self.tmp / "cfg", newspapers=bad)
        with mock.patch.dict(os.environ, {"NEWSDESK_CONFIG_DIR": str(d)}), self.assertRaises(config.ConfigError):
            build_site.build(self.tmp / "site")
        self.assertFalse((self.tmp / "site" / "sections.json").exists())

    def test_rebuilding_overwrites_cleanly(self):
        build_site.build(self.tmp / "site"); build_site.build(self.tmp / "site")
        self.assertEqual(len(list((self.tmp / "site").iterdir())), 4)

    def test_the_page_itself_has_no_built_in_sections_or_refresh_choices(self):
        page = (support.SRC / "web" / "index.html").read_text()
        for leftover in ("Bengali News", "Geo Politics", "--c-india", "Last 6 hours", "Last 90 days", 'value="1000"', "rcnd-d6930e74"):
            self.assertNotIn(leftover, page, f"{leftover!r} should come from external_config, not the page")
        for fetch in ("sections.json", "settings.json", "papers.json", "news.json"):
            self.assertIn(fetch, page)
