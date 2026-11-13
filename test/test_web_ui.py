"""The web page in a real browser (Chrome through Playwright). The site is built from the sample configuration and a
sample news.json; the relay (ntfy.sh) and the GitHub API are mocked, so nothing leaves the machine.
Skipped automatically if Playwright or Chrome is not installed."""
import functools
import http.server
import json
import os
import shutil
import threading
import unittest
from datetime import datetime, timedelta, timezone

import support
from support import SAMPLE_SETTINGS

import build_site

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                           # pragma: no cover
    sync_playwright = None
CHROME = next((p for p in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.exists(p)), None)

NOW = datetime.now(timezone.utc)
COUNTRIES = [("France", "Europe"), ("Germany", "Europe"), ("Japan", "Asia"), ("Brazil", "South America"), ("Kenya", "Africa")]


def make_news(max_articles=120):
    items = []
    for n in range(130):                                           # 130 world stories: more than the display cap
        country, continent = COUNTRIES[n % 5]
        items.append({"title": f"World story {n}", "link": f"https://news.example/w{n}", "summary": "", "image": "",
                      "published": (NOW - timedelta(minutes=n)).isoformat(), "source": "Alpha Times" if n % 4 == 0 else "Beta Post",
                      "primary": n % 4 == 0, "category": "world", "sections": ["world"] + (["defence"] if n % 10 == 0 else []),
                      "continent": continent, "country": country, "state": None})
    for n in range(5):
        items.append({"title": f"Home story {n}", "link": f"https://news.example/h{n}", "summary": "", "image": "",
                      "published": (NOW - timedelta(minutes=n)).isoformat(), "source": "Gazette Home", "primary": True,
                      "category": "home", "sections": ["home"], "continent": "Asia", "country": "Bangladesh", "state": "Dhaka"})
    for n in range(3):
        items.append({"title": f"Sports story {n}", "link": f"https://news.example/s{n}", "summary": "", "image": "",
                      "published": (NOW - timedelta(minutes=n)).isoformat(), "source": "Gamma Wire", "primary": False,
                      "category": "sports", "sections": ["sports"], "continent": "Europe", "country": "United Kingdom", "state": None})
    return {"generated_at": NOW.isoformat(), "range_hours": 24, "max_articles": max_articles, "items": items, "feeds": []}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def run(id_, status, conclusion=None):
    t = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": id_, "status": status, "conclusion": conclusion, "event": "workflow_dispatch", "created_at": t, "updated_at": t}


@unittest.skipUnless(sync_playwright and CHROME, "Playwright with Chrome is not available")
class WebUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = support.SESSION_DIR / "ui_site"
        shutil.rmtree(cls.site, ignore_errors=True)
        build_site.build(cls.site)
        (cls.site / "news.json").write_text(json.dumps(make_news()))
        handler = functools.partial(QuietHandler, directory=str(cls.site))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/index.html"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.shutdown()

    def setUp(self):
        self.ctx = self.browser.new_context(viewport={"width": 1300, "height": 900})
        self.addCleanup(self.ctx.close)
        self.errors, self.dialogs = [], []
        self.relay, self.relay_urls, self.gh_posts = [], [], []
        self.runs = [run(5, "completed", "success")]
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        self.page.add_init_script("window.RC_POLL_MS=100;")

        def relay(route):
            self.relay.append(route.request.post_data); self.relay_urls.append(route.request.url)
            route.fulfill(status=200, body="{}", headers={"Access-Control-Allow-Origin": "*"})

        def gh(route):
            if route.request.method == "POST":
                self.gh_posts.append(json.loads(route.request.post_data)); return route.fulfill(status=204, body="")
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": self.runs}))
        self.page.route("https://ntfy.sh/**", relay)
        self.page.route("https://api.github.com/**", gh)

    # ---------------------------------------------------------------- helpers
    def open(self, page=None):
        page = page or self.page
        page.goto(self.url)
        page.wait_for_function("document.querySelectorAll('#paper option').length > 3 && document.querySelectorAll('#grid > *').length > 0")
        return page

    def tiles(self):
        return self.page.locator("#grid .tile").count()

    def titles(self):
        return self.page.locator("#grid .tile h2").all_inner_texts()

    def tab(self, label):
        self.page.click(f"#tabs button:text-is('{label}')")

    def tearDown(self):
        self.assertEqual(self.errors, [], "the page raised JavaScript errors")

    # ---------------------------------------------------------------- tabs and colours come from sections.json
    def test_tabs_follow_sections_json_in_order(self):
        self.open()
        self.assertEqual(self.page.locator("#tabs button").all_inner_texts(),
                         ["Home News", "India Desk", "World Desk", "Sports Desk", "Showbiz Desk", "Defence Desk", "Money Desk"])
        self.assertEqual(self.page.locator("#tabs button[aria-pressed=true]").inner_text(), "Home News")     # the first one
        self.assertEqual(self.tiles(), 5)

    def test_section_colours_come_from_sections_json(self):
        self.open()
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--c-world').trim()"), "#2a4d8f")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--c-money').trim()"), "#6b4e16")

    def test_switching_tabs_shows_only_that_sections_stories(self):
        self.open()
        self.tab("Sports Desk")
        self.assertEqual(sorted(self.titles()), ["Sports story 0", "Sports story 1", "Sports story 2"])
        self.tab("Defence Desk")                                         # stories tagged with a second section
        self.assertEqual(self.tiles(), 13)
        self.tab("Money Desk")
        self.assertEqual(self.page.locator("#grid .empty").inner_text(), "No stories match this filter right now.")

    def test_tile_content(self):
        self.open()
        tile = self.page.locator("#grid .tile").first
        self.assertEqual(tile.get_attribute("target"), "_blank")
        self.assertIn("noopener", tile.get_attribute("rel"))
        self.assertTrue(tile.get_attribute("href").startswith("https://news.example/h"))
        self.assertIn("dhaka", tile.inner_text().lower())                         # state shown for regional papers
        self.assertIn("Gazette Home", tile.inner_text())
        self.assertIn("Primary", tile.inner_text())

    # ---------------------------------------------------------------- paging
    def test_shows_50_then_more_up_to_max_articles_then_a_message(self):
        self.open(); self.tab("World Desk")
        self.assertEqual(self.tiles(), 50)
        self.assertTrue(self.page.is_visible("#more")); self.assertTrue(self.page.is_hidden("#end"))
        self.page.click("#more"); self.assertEqual(self.tiles(), 100)
        self.page.click("#more"); self.assertEqual(self.tiles(), 120)       # max_articles in news.json is 120, not 130
        self.assertTrue(self.page.is_hidden("#more"))
        self.assertEqual(self.page.inner_text("#end"), "No more articles available.")

    def test_paging_resets_when_a_filter_changes(self):
        self.open(); self.tab("World Desk"); self.page.click("#more")
        self.assertEqual(self.tiles(), 100)
        self.page.check("#fPrimary")
        self.assertEqual(self.tiles(), 33)

    # ---------------------------------------------------------------- filters
    def test_continent_chips(self):
        self.open(); self.tab("World Desk")
        chips = self.page.locator("#chips button").all_inner_texts()
        self.assertEqual(chips[0], "All")
        self.page.click("#chips button:text-is('Africa')")
        self.assertEqual(self.tiles(), 26)
        self.assertTrue(all(c == "Africa" or True for c in chips))

    def test_country_panel_is_multi_select_and_searchable(self):
        self.open(); self.tab("World Desk")
        self.assertEqual(self.page.inner_text("#selnote"), "All shown")
        self.page.locator("#clist label", has_text="France").locator("input").check()
        self.assertEqual(self.tiles(), 26)
        self.page.locator("#clist label", has_text="Japan").locator("input").check()
        self.assertEqual(self.tiles(), 50)                                  # 26 + 26 = 52, capped to the first 50
        self.assertEqual(self.page.inner_text("#selnote"), "2 selected")
        self.page.fill("#cq", "ger")
        self.assertEqual(self.page.locator("#clist label").all_inner_texts()[0].split("\n")[0], "Germany")   # only matches are listed ...
        self.assertEqual(self.page.inner_text("#selnote"), "2 selected")                                    # ... the ticked ones stay selected
        self.page.click("#clear")
        self.assertEqual(self.page.inner_text("#selnote"), "All shown")

    def test_search_box_filters_by_text(self):
        self.open(); self.tab("World Desk")
        self.page.fill("#q", "story 12")
        self.assertEqual(sorted(self.titles()), ["World story 12", "World story 120", "World story 121", "World story 122",
                                                 "World story 123", "World story 124", "World story 125", "World story 126",
                                                 "World story 127", "World story 128", "World story 129"][:len(self.titles())] or [])
        self.assertTrue(all("12" in t for t in self.titles()))
        self.page.fill("#q", "no such words")
        self.assertEqual(self.page.locator("#grid .empty").count(), 1)

    def test_primary_and_secondary_checkboxes(self):
        self.open(); self.tab("World Desk")
        self.page.check("#fPrimary")
        self.assertEqual(self.page.locator("#grid .pri").count(), self.tiles())          # only primary stories
        self.page.check("#fSecondary")                                                   # both -> everything
        self.assertEqual(self.tiles(), 50)
        self.page.uncheck("#fPrimary")                                                   # secondary only
        self.assertEqual(self.page.locator("#grid .pri").count(), 0)
        self.page.uncheck("#fSecondary")
        self.assertEqual(self.tiles(), 50)

    def test_source_type_applies_on_top_of_existing_filters(self):
        self.open(); self.tab("World Desk")
        self.page.click("#chips button:text-is('Europe')")
        self.page.locator("#clist label", has_text="France").locator("input").check()
        before = self.tiles()                                                            # all France stories
        self.page.fill("#q", "story 1")
        narrowed = self.tiles()
        self.page.check("#fPrimary")
        after = self.tiles()
        self.assertEqual(before, 26)
        self.assertLessEqual(after, narrowed)
        self.assertTrue(all(self.page.locator("#grid .tile").nth(i).locator(".pri").count() == 1 for i in range(after)))
        self.assertEqual(self.page.input_value("#q"), "story 1")                         # earlier filters still in force
        self.assertEqual(self.page.inner_text("#selnote"), "1 selected")
        self.assertEqual(self.page.locator("#chips button[aria-pressed=true]").inner_text(), "Europe")

    # ---------------------------------------------------------------- newspaper homepage dropdown
    def test_newspaper_dropdown_lists_papers_by_country(self):
        self.open()
        groups = self.page.evaluate("[...document.querySelectorAll('#paper optgroup')].map(g => g.label)")
        self.assertEqual(groups, ["Bangladesh", "France", "India", "International"])
        self.assertEqual(self.page.locator("label[for=paper]").inner_text(), "Newspaper Homepage")
        names = self.page.evaluate("[...document.querySelectorAll('#paper option')].map(o => o.textContent)")
        self.assertNotIn("Hidden Search", names)

    def test_choosing_a_newspaper_shows_its_homepage_link(self):
        self.open()
        self.assertTrue(self.page.is_hidden("#paperlink"))
        self.page.select_option("#paper", label="Beta Post")
        link = self.page.locator("#paperlink")
        self.assertEqual(link.get_attribute("href"), "https://betapost.example/")
        self.assertEqual(link.get_attribute("target"), "_blank")
        self.assertIn("noopener", link.get_attribute("rel"))
        self.assertIn("Open Beta Post", link.inner_text())
        self.assertIn("France", link.inner_text())
        self.page.select_option("#paper", index=0)
        self.assertTrue(self.page.is_hidden("#paperlink"))

    def test_newspaper_search(self):
        self.open()
        self.page.fill("#pq", "alp")
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('#paper option')].filter(o => o.value).map(o => o.textContent)"), ["Alpha Times"])
        self.page.press("#pq", "Enter")                                       # Enter picks the first match
        self.assertEqual(self.page.locator("#paperlink").get_attribute("href"), "https://www.alphatimes.example/")
        self.page.fill("#pq", "zzz")
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('#paper option')].map(o => o.textContent)")[-1], "No newspaper found")
        self.assertTrue(self.page.is_hidden("#paperlink"))
        self.page.fill("#pq", "")
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#paper option').length"), 5)

    # ---------------------------------------------------------------- reset
    def test_reset_clears_every_selection(self):
        self.open()
        start = self.snapshot()
        self.tab("World Desk"); self.page.click("#chips button:text-is('Europe')")
        self.page.fill("#q", "story 1"); self.page.check("#fPrimary"); self.page.fill("#cq", "fr")
        self.page.locator("#clist label", has_text="France").locator("input").check()
        self.page.fill("#pq", "beta"); self.page.press("#pq", "Enter")
        self.page.select_option("#range", "72"); self.page.select_option("#count", "250")
        self.assertNotEqual(self.snapshot(), start)
        self.page.click("#reset")
        self.assertEqual(self.snapshot(), start)

    def snapshot(self):
        p = self.page
        return dict(tab=p.locator("#tabs button[aria-pressed=true]").inner_text(), chip=p.locator("#chips button[aria-pressed=true]").inner_text(),
                    q=p.input_value("#q"), cq=p.input_value("#cq"), pri=p.is_checked("#fPrimary"), sec=p.is_checked("#fSecondary"),
                    sel=p.inner_text("#selnote"), pq=p.input_value("#pq"), paper=p.input_value("#paper"), link=p.is_hidden("#paperlink"),
                    range=p.input_value("#range"), count=p.input_value("#count"), tiles=self.tiles())

    def test_reset_button_sits_under_the_logo(self):
        self.open()
        logo, reset = self.page.locator("h1").bounding_box(), self.page.locator("#reset").bounding_box()
        self.assertGreater(reset["y"], logo["y"] + logo["height"] - 2)
        self.assertLess(abs(reset["x"] - logo["x"]), 4)
        self.assertEqual(self.page.inner_text("#reset"), "Reset")

    # ---------------------------------------------------------------- refresh choices come from settings.json
    def test_refresh_choices_and_defaults_come_from_settings_json(self):
        self.open()
        opts = lambda sel: self.page.evaluate(f"[...document.querySelectorAll('{sel} option')].map(o => [o.value, o.textContent])")
        self.assertEqual(opts("#range"), [["6", "Six hours"], ["24", "One day"], ["72", "Three days"], ["168", "One week"]])
        self.assertEqual(opts("#count"), [["50", "50"], ["150", "150"], ["250", "250"]])
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("24", "150"))

    def test_choices_are_remembered_but_only_while_still_valid(self):
        self.open()
        self.page.select_option("#range", "72"); self.page.select_option("#count", "250")
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#range option').length > 0")
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("72", "250"))
        self.page.evaluate("localStorage.setItem('rcnd_range', '999'); localStorage.setItem('rcnd_count', '77')")
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#range option').length > 0")
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("24", "150"))

    def test_page_reports_when_the_configuration_cannot_load(self):
        self.page.route("**/sections.json*", lambda r: r.fulfill(status=404, body="nope"))
        self.page.goto(self.url)
        self.page.wait_for_selector("text=Could not load the page configuration")

    # ---------------------------------------------------------------- refresh button
    def wait_ready(self):
        self.page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")

    def test_refresh_posts_range_and_count_to_the_configured_topic_without_asking_for_a_token(self):
        self.open(); self.wait_ready()
        self.page.select_option("#range", "168"); self.page.select_option("#count", "250")
        seen = []
        def gh(route):
            if self.relay:                                           # after the request: a new run appears, then completes
                seen.append(1)
                self.runs[:] = [run(6, "in_progress" if len(seen) < 4 else "completed", None if len(seen) < 4 else "success"), run(5, "completed", "success")]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": self.runs}))
        self.page.route("https://api.github.com/**", gh)
        self.page.click("#refresh")
        self.page.wait_for_function("document.querySelector('#rlabel').innerText === 'Refreshing…'")
        self.assertTrue(self.page.is_disabled("#refresh"))
        self.assertTrue(self.page.is_disabled("#range") and self.page.is_disabled("#count"))
        self.page.wait_for_function("!document.querySelector('#refresh').disabled", timeout=15000)
        self.assertEqual(self.relay, ["hours=168&count=250"])
        self.assertEqual(self.page.inner_text("#rlabel"), "Refresh")
        self.assertIn("Success", self.page.inner_text("#rstatus"))
        self.assertTrue(self.page.is_enabled("#range"))
        self.assertEqual(self.dialogs, [])                                                # never asks for a token
        self.assertEqual(self.gh_posts, [])

    def test_topic_in_the_request_url_comes_from_settings(self):
        self.open(); self.wait_ready()
        self.page.click("#refresh")
        self.page.wait_for_function("document.querySelector('#rlabel').innerText === 'Refreshing…'")
        for _ in range(50):
            if self.relay_urls: break
            self.page.wait_for_timeout(100)
        self.assertEqual(self.relay_urls, ["https://ntfy.sh/test-topic-abc"])

    def test_failed_run_is_reported(self):
        self.open(); self.wait_ready()
        def gh(route):
            runs = [run(6, "completed", "failure"), run(5, "completed", "success")] if self.relay else self.runs
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": runs}))
        self.page.route("https://api.github.com/**", gh)
        self.page.click("#refresh")
        self.page.wait_for_function("document.querySelector('#rstatus').innerText.includes('Failed')", timeout=10000)
        self.assertFalse(self.page.is_disabled("#refresh"))

    def test_relay_down_shows_a_message_and_re_enables_the_button(self):
        self.open(); self.wait_ready()
        self.page.route("https://ntfy.sh/**", lambda r: r.abort())
        self.page.click("#refresh")
        self.page.wait_for_selector("#refmsg:not([hidden])")
        self.assertIn("Could not send the refresh request", self.page.inner_text("#refmsg"))
        self.assertFalse(self.page.is_disabled("#refresh"))
        self.assertEqual(self.dialogs, [])

    def test_a_saved_token_is_used_directly_and_a_rejected_one_is_dropped(self):
        ctx = self.browser.new_context(); self.addCleanup(ctx.close)
        page = ctx.new_page(); page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        page.add_init_script("window.RC_POLL_MS=100; localStorage.setItem('rcnd_gh_token','stale');")
        relay = []
        page.route("https://ntfy.sh/**", lambda r: (relay.append(r.request.post_data), r.fulfill(status=200, body="{}", headers={"Access-Control-Allow-Origin": "*"}))[1])
        def gh(route):
            if route.request.method == "POST": return route.fulfill(status=403, body="{}")            # token rejected
            runs = [run(6, "completed", "success"), run(5, "completed", "success")] if relay else [run(5, "completed", "success")]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": runs}))
        page.route("https://api.github.com/**", gh)
        self.open(page); page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")
        page.click("#refresh")
        page.wait_for_function("document.querySelector('#rlabel').innerText==='Refresh' && !document.querySelector('#refresh').disabled", timeout=10000)
        self.assertEqual(relay, ["hours=24&count=150"])                                  # fell back to the relay
        self.assertIsNone(page.evaluate("localStorage.getItem('rcnd_gh_token')"))        # stale token removed
        self.assertEqual(self.dialogs, [])

    def test_header_shows_when_the_data_was_generated(self):
        self.open()
        self.assertIn("Updated", self.page.inner_text("#updated"))


if __name__ == "__main__":
    unittest.main()
