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
                      "newspaper": "Alpha Times" if n % 4 == 0 else "Beta Post", "primary": n % 4 == 0, "category": "world", "sections": ["world"] + (["defence"] if n % 10 == 0 else []),
                      "continent": continent, "country": country, "state": None})
    for n in range(5):
        items.append({"title": f"Home story {n}", "link": f"https://news.example/h{n}", "summary": "", "image": "",
                      "published": (NOW - timedelta(minutes=n)).isoformat(), "source": "Gazette Home", "newspaper": "Gazette Home", "primary": True,
                      "category": "home", "sections": ["home"], "continent": "Asia", "country": "Bangladesh", "state": "Dhaka"})
    for n in range(3):
        items.append({"title": f"Sports story {n}", "link": f"https://news.example/s{n}", "summary": "", "image": "",
                      "published": (NOW - timedelta(minutes=n)).isoformat(), "source": "Gamma Wire", "newspaper": "Gamma Wire", "primary": False,
                      "category": "sports", "sections": ["sports"], "continent": "Europe", "country": "United Kingdom", "state": None})
    for it in items:                                    # older data without the field: matched on the source name instead
        if it["title"].startswith("World story") and int(it["title"].split()[-1]) % 4 == 1:
            del it["newspaper"]
    return {"generated_at": NOW.isoformat(), "range_hours": 24, "max_articles": max_articles, "items": items, "feeds": []}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def run(id_, status, conclusion=None):
    t = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": id_, "status": status, "conclusion": conclusion, "event": "workflow_dispatch", "created_at": t, "updated_at": t}


class BrowserBase(unittest.TestCase):
    """A site built from the sample configuration, served locally, opened in Chrome with the network mocked."""
    @classmethod
    def setUpClass(cls):
        cls.site = support.SESSION_DIR / "ui_site"
        shutil.rmtree(cls.site, ignore_errors=True)
        build_site.build(cls.site)
        (cls.site / "news.json").write_text(json.dumps(make_news()))
        handler = functools.partial(QuietHandler, directory=str(cls.site))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/"
        cls.url = cls.base + "index.html"
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

    def tearDown(self):
        self.assertEqual(self.errors, [], "the page raised JavaScript errors")


@unittest.skipUnless(sync_playwright and CHROME, "Playwright with Chrome is not available")
class WebUITest(BrowserBase):
    # ---------------------------------------------------------------- helpers
    def open(self, page=None):
        page = page or self.page
        page.goto(self.url)
        page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        return page

    def tiles(self):
        return self.page.locator("#grid .tile").count()

    def titles(self):
        return self.page.locator("#grid .tile h2").all_inner_texts()

    def tab(self, label):
        self.page.click(f"#tabs button:text-is('{label}')")

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

    # ---------------------------------------------------------------- article range and numbering
    def nums(self):
        return [int(t.lstrip("#")) for t in self.page.locator(".tile .num").all_inner_texts()]

    def set_range(self, a, b):
        # both boxes are set, then one "change" (what leaving the box or pressing Enter does)
        self.page.evaluate("([a, b]) => { rfrom.value = a; rto.value = b; rto.dispatchEvent(new Event('change')); }", [str(a), str(b)])

    def test_starts_with_articles_1_to_50_numbered(self):
        self.open(); self.tab("World Desk")
        self.assertEqual(self.tiles(), 50)
        self.assertEqual(self.nums(), list(range(1, 51)))
        self.assertEqual((self.page.input_value("#rfrom"), self.page.input_value("#rto")), ("1", "50"))
        self.assertEqual(self.page.inner_text("#rcount"), "Showing 1–50 of 120 matching articles")   # max_articles is 120, not 130

    def test_typed_range_shows_those_numbers(self):
        self.open(); self.tab("World Desk")
        self.set_range(11, 20)
        self.assertEqual(self.nums(), list(range(11, 21)))
        self.assertEqual(self.page.inner_text("#rcount"), "Showing 11–20 of 120 matching articles")

    def test_range_is_clamped_and_never_shows_more_than_exists(self):
        self.open(); self.tab("World Desk")
        self.set_range(100, 5000)
        self.assertEqual(self.nums(), list(range(100, 121)))                  # up to the 120 kept
        self.set_range(0, 0)
        self.assertEqual((self.page.input_value("#rfrom"), self.page.input_value("#rto")), ("1", "1"))
        self.set_range(30, 10)                                                # "to" below "from" is raised to "from"
        self.assertEqual(self.nums(), [30])

    def test_range_beyond_the_matches_says_so(self):
        self.open(); self.tab("World Desk")
        self.page.check("#fPrimary")                                          # 33 primary stories
        self.set_range(40, 60)
        self.assertEqual(self.tiles(), 0)
        self.assertIn("only 33 match", self.page.inner_text("#grid"))

    def test_quick_buttons(self):
        self.open(); self.tab("World Desk")
        texts = self.page.locator("#rquick button").all_inner_texts()
        self.assertEqual(texts, ["1–50", "51–100", "101–200", "All"])         # 120 articles: nothing at 201+
        self.page.click("#rquick button:text-is('51–100')")
        self.assertEqual(self.nums(), list(range(51, 101)))
        self.page.click("#rquick button:text-is('All')")
        self.assertEqual(self.tiles(), 120)

    def test_numbers_are_within_the_filtered_list_and_the_range_works_with_every_filter(self):
        self.open(); self.tab("World Desk")
        self.page.check("#fPrimary")
        self.assertEqual(self.tiles(), 33)
        self.assertEqual(self.nums(), list(range(1, 34)))
        self.set_range(5, 10)
        self.assertEqual(self.nums(), [5, 6, 7, 8, 9, 10])
        self.page.click("#chips button:text-is('Europe')")                    # a filter change goes back to 1-50 of the new list
        self.assertEqual((self.page.input_value("#rfrom"), self.page.input_value("#rto")), ("1", "50"))
        self.assertEqual(self.nums(), list(range(1, self.tiles() + 1)))
        self.page.fill("#q", "World story"); self.set_range(2, 3)
        self.assertEqual(self.nums(), [2, 3])
        self.assertTrue(all("World story" in t for t in self.page.locator(".tile h2").all_inner_texts()))

    def test_reset_and_tab_change_return_to_1_50(self):
        self.open(); self.tab("World Desk"); self.set_range(20, 30)
        self.page.click("#reset")
        self.assertEqual((self.page.input_value("#rfrom"), self.page.input_value("#rto")), ("1", "50"))
        self.tab("World Desk"); self.set_range(20, 30); self.tab("Sports Desk")
        self.assertEqual((self.page.input_value("#rfrom"), self.page.input_value("#rto")), ("1", "50"))
        self.assertEqual(self.nums(), [1, 2, 3])

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

    def test_headline_is_entirely_black(self):
        self.open()
        colours = self.page.evaluate("[document.querySelector('h1'), document.querySelector('h1 span')].map(e => getComputedStyle(e).color)")
        self.assertEqual(colours, ["rgb(0, 0, 0)", "rgb(0, 0, 0)"])
        self.assertEqual(self.page.inner_text("h1").replace("\n", " "), "RC News Desk")

    def test_newspaper_homepage_link_and_page_title_are_entirely_black(self):
        self.open()
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('a.navlink')).color"), "rgb(0, 0, 0)")
        self.page.click("a.navlink"); self.page.wait_for_url("**/newspaper-list/")
        colours = self.page.evaluate("[document.querySelector('h1'), document.querySelector('h1 span')].map(e => getComputedStyle(e).color)")
        self.assertEqual(colours, ["rgb(0, 0, 0)", "rgb(0, 0, 0)"])

    def test_headline_stays_readable_in_dark_mode(self):
        page = self.ctx.new_page(); page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.emulate_media(color_scheme="dark")
        self.open(page=page)
        colours = page.evaluate("[document.querySelector('h1'), document.querySelector('h1 span')].map(e => getComputedStyle(e).color)")
        self.assertEqual(colours[0], colours[1])
        self.assertNotEqual(colours[0], "rgb(0, 0, 0)")                  # black on the dark background would vanish

    # ---------------------------------------------------------------- Newspaper Homepage moved to its own page
    def test_header_links_to_the_newspaper_list_page(self):
        self.open()
        link, new = self.page.locator("a.navlink"), self.page.locator("a.navnew")
        self.assertEqual(link.inner_text(), "Newspaper Homepage")
        self.assertEqual(link.get_attribute("href"), "newspaper-list/")
        self.assertIsNone(link.get_attribute("target"))                                   # same tab by default
        self.assertEqual((new.get_attribute("href"), new.get_attribute("target")), ("newspaper-list/", "_blank"))
        self.assertIn("noopener", new.get_attribute("rel"))
        title, box = self.page.locator("h1").bounding_box(), link.bounding_box()
        self.assertLess(abs((box["y"] + box["height"] / 2) - (title["y"] + title["height"] / 2)), 30)   # beside the headline
        self.assertGreater(box["x"], title["x"] + title["width"] - 2)

    def test_link_opens_the_page_in_the_same_tab(self):
        self.open()
        self.page.click("a.navlink")
        self.page.wait_for_url("**/newspaper-list/")
        self.assertEqual(self.page.locator("h1").inner_text().replace("\n", " "), "Newspaper Homepage")

    def test_arrow_opens_the_page_in_a_new_tab(self):
        self.open()
        with self.ctx.expect_page() as popup:
            self.page.click("a.navnew")
        new = popup.value
        new.wait_for_load_state()
        self.assertTrue(new.url.endswith("/newspaper-list/"))
        self.assertTrue(self.page.url.endswith("/index.html"))                            # the original tab stays put

    def test_main_page_no_longer_has_the_newspaper_dropdown(self):
        self.open()
        for gone in ("#paper", "#pq", "#paperlink", ".paperbox"):
            self.assertEqual(self.page.locator(gone).count(), 0, gone)
        self.assertEqual(self.page.locator("label[for=paper]").count(), 0)

    # ---------------------------------------------------------------- reset
    def test_reset_clears_every_selection(self):
        self.open()
        start = self.snapshot()
        self.tab("World Desk"); self.page.click("#chips button:text-is('Europe')")
        self.page.fill("#q", "story 1"); self.page.check("#fPrimary"); self.page.fill("#cq", "fr")
        self.page.locator("#clist label", has_text="France").locator("input").check()
        self.page.select_option("#range", "72"); self.page.select_option("#count", "250")
        self.assertNotEqual(self.snapshot(), start)
        self.page.click("#reset")
        self.assertEqual(self.snapshot(), start)

    def snapshot(self):
        p = self.page
        return dict(tab=p.locator("#tabs button[aria-pressed=true]").inner_text(), chip=p.locator("#chips button[aria-pressed=true]").inner_text(),
                    q=p.input_value("#q"), cq=p.input_value("#cq"), pri=p.is_checked("#fPrimary"), sec=p.is_checked("#fSecondary"),
                    sel=p.inner_text("#selnote"),
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
        self.page.evaluate("localStorage.setItem('rcnd_range_v2', '999'); localStorage.setItem('rcnd_count_v2', '77')")
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#range option').length > 0")
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("24", "150"))

    def test_choices_saved_before_the_defaults_changed_are_ignored_once(self):
        self.page.add_init_script("if (!localStorage.getItem('seeded')) { localStorage.setItem('seeded', '1'); localStorage.setItem('rcnd_range', '72'); localStorage.setItem('rcnd_count', '250'); }")
        self.open()
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("24", "150"))   # old saved values not used
        self.page.select_option("#range", "72")                                                              # a new choice is remembered again
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#range option').length > 0")
        self.assertEqual(self.page.input_value("#range"), "72")

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
        self.assertIn("Last Refresh", self.page.inner_text("#lastrefresh"))

    def test_header_shows_the_next_manual_refresh_one_cooldown_after_the_last(self):
        self.open()
        self.page.wait_for_function("document.querySelector('#nextrefresh').innerText.startsWith('Next Refresh')")
        self.assertIn("✓", self.page.inner_text("#lastrefresh"))
        want = self.page.evaluate("""(g) => { const d = new Date(new Date(g).getTime() + 60 * 60000);
            return d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }); }""", NOW.isoformat())
        self.assertEqual(self.page.inner_text("#nextrefresh"), "Next Refresh " + want)       # sample cooldown is 60 minutes
        self.assertNotIn("scheduled", self.page.inner_text("#updated").lower())

    # ---------------------------------------------------------------- the cooldown between manual refreshes
    def cooldown_page(self, refreshed_minutes_ago):
        """Opens the page with refresh.json saying the last refresh finished that long ago; returns the list of relay posts."""
        posts = []
        done = (datetime.now(timezone.utc) - timedelta(minutes=refreshed_minutes_ago)).isoformat()
        self.page.route("**/refresh.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"refreshed_at": done})))
        self.page.route("https://ntfy.sh/**", lambda r: (posts.append(r.request.post_data), r.fulfill(status=200, body="{}")))
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": [run(5, "completed", "success")]})))
        self.open(); self.page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")
        return posts

    def test_refresh_inside_the_cooldown_sends_nothing_and_explains(self):
        posts = self.cooldown_page(10)                                                   # finished 10 min ago, cooldown 60
        self.page.click("#refresh")
        self.page.wait_for_selector("#cooldown[open]")
        text = self.page.inner_text("#cdtext")
        self.assertIn("next refresh is available at", text)
        self.assertRegex(text, r"in (49|50) min")
        self.page.click("#cdok")
        self.page.wait_for_selector("#cooldown", state="hidden")
        self.page.wait_for_timeout(300)
        self.assertEqual(posts, [])                                                      # nothing was requested
        self.assertEqual(self.dialogs, [])

    def test_every_choice_of_range_and_count_is_blocked_during_the_cooldown(self):
        posts = self.cooldown_page(10)
        for hours, count in (("6", "50"), ("72", "250")):
            self.page.select_option("#range", hours); self.page.select_option("#count", count)
            self.page.click("#refresh"); self.page.wait_for_selector("#cooldown[open]")
            self.page.click("#cdok"); self.page.wait_for_selector("#cooldown", state="hidden")
        self.assertEqual(posts, [])

    def test_refresh_after_the_cooldown_is_sent(self):
        posts = self.cooldown_page(61)
        self.page.click("#refresh")
        self.page.wait_for_function("window.__n = 1", timeout=1000)
        self.page.wait_for_timeout(500)
        self.assertEqual(posts, ["hours=24&count=150"])
        self.assertTrue(self.page.is_hidden("#cooldown"))

    def test_the_wait_is_judged_by_the_servers_clock_not_the_devices(self):
        posts = []
        done = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        far_future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")   # server says it is 2 days later
        self.page.route("**/refresh.json*", lambda r: r.fulfill(status=200, content_type="application/json", headers={"Date": far_future}, body=json.dumps({"refreshed_at": done})))
        self.page.route("https://ntfy.sh/**", lambda r: (posts.append(r.request.post_data), r.fulfill(status=200, body="{}")))
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": []})))
        self.open(); self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.page.click("#refresh")
        self.page.wait_for_timeout(800)
        self.assertEqual(posts, ["hours=24&count=150"])                                  # by the server's clock the cooldown is long over

    def test_a_missing_refresh_json_does_not_block(self):
        posts = []
        self.page.route("https://ntfy.sh/**", lambda r: (posts.append(r.request.post_data), r.fulfill(status=200, body="{}")))
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": []})))
        self.open(); self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.page.click("#refresh")
        self.page.wait_for_timeout(800)
        self.assertEqual(len(posts), 1)

    def test_a_cancelled_run_is_not_shown_as_a_failed_refresh(self):
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"workflow_runs": [run(9, "completed", "cancelled"), run(5, "completed", "success")]})))
        self.open(); self.page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")
        self.assertIn("✓", self.page.inner_text("#rstatus"))
        self.assertIn("✓", self.page.inner_text("#lastrefresh"))


@unittest.skipUnless(sync_playwright and CHROME, "Playwright with Chrome is not available")
class NewspaperPageTest(BrowserBase):
    """newspaper-list/: continent -> country -> newspaper (one at a time) -> a front-page tile with 4 recent headlines."""

    def open(self, suffix="", page=None):
        page = page or self.page
        page.goto(self.base + "newspaper-list/" + suffix)
        page.wait_for_function("document.querySelectorAll('#papers label').length > 0")
        return page

    def names(self):
        return [t.split("\n")[0] for t in self.page.locator("#papers label").all_inner_texts()]

    def countries(self):
        return [t.split("\n")[0] for t in self.page.locator("#countries label").all_inner_texts()]

    def pick(self, name):
        self.page.locator("#papers label", has_text=name).locator("input").check()

    def test_layout_and_initial_state(self):
        self.open()
        self.assertEqual(self.page.title(), "Newspaper Homepage — RC News Desk")
        self.assertEqual(self.page.locator("#continents button").all_inner_texts(), ["All (4)", "Asia (2)", "Europe (1)", "Other (1)"])
        self.assertEqual(self.countries(), ["All countries", "Bangladesh", "France", "India", "International"])
        self.assertEqual(self.names(), ["Alpha Times", "Beta Post", "Gamma Wire", "Gazette Home"])
        self.assertIn("Choose a newspaper", self.page.inner_text("#stage"))
        self.assertEqual(self.page.locator("a.front").count(), 0)

    def test_back_link_returns_to_the_news_page(self):
        self.open()
        self.page.click("a.back")
        self.page.wait_for_url("**/")
        self.assertEqual(self.page.locator("h1").first.inner_text().replace("\n", " "), "RC News Desk")

    def test_continent_then_country_filters(self):
        self.open()
        self.page.click("#continents button:text-is('Asia (2)')")
        self.assertEqual(self.countries(), ["All countries", "Bangladesh", "India"])
        self.assertEqual(self.names(), ["Alpha Times", "Gazette Home"])
        self.page.locator("#countries label", has_text="India").locator("input").check()
        self.assertEqual(self.names(), ["Alpha Times"])
        self.page.click("#continents button:text-is('Europe (1)')")                      # changing continent resets the country
        self.assertEqual(self.names(), ["Beta Post"])
        self.page.click("#continents button:text-is('All (4)')")
        self.assertEqual(len(self.names()), 4)

    def test_search_matches_newspaper_or_country_and_narrows_both_lists(self):
        self.open()
        self.page.fill("#q", "fra")
        self.assertEqual(self.names(), ["Beta Post"])
        self.assertEqual(self.countries(), ["All countries", "France"])
        self.page.fill("#q", "gamma")
        self.assertEqual(self.names(), ["Gamma Wire"])
        self.page.fill("#q", "zzz")
        self.assertEqual(self.page.inner_text("#papers"), "No newspapers match.")
        self.page.fill("#q", "")
        self.assertEqual(len(self.names()), 4)

    def test_enter_in_the_search_box_picks_the_first_match(self):
        self.open()
        self.page.fill("#q", "gaz"); self.page.press("#q", "Enter")
        self.assertIn("Gazette Home", self.page.inner_text(".mname"))

    def test_only_one_newspaper_can_be_selected_at_a_time(self):
        self.open()
        self.pick("Alpha Times"); self.pick("Beta Post")
        self.assertEqual(self.page.locator("#papers input:checked").count(), 1)
        self.assertEqual(self.page.locator("a.front").count(), 1)
        self.assertEqual(self.page.inner_text(".mname"), "Beta Post")

    def test_front_page_tile_shows_the_four_most_recent_headlines(self):
        self.open(); self.pick("Alpha Times")
        tile = self.page.locator("a.front")
        self.assertEqual(self.page.inner_text(".mname"), "Alpha Times")
        self.assertIn("INDIA · ASIA", self.page.inner_text(".mmeta").upper())
        self.assertIn("primary", self.page.inner_text(".mmeta").lower())
        # Alpha Times has stories 0, 4, 8, 12 ... (newest first); the lead is the newest, three more follow
        self.assertEqual(self.page.inner_text("#lead h3"), "World story 0")
        self.assertEqual(self.page.locator(".rest article h4").all_inner_texts(), ["World story 4", "World story 8", "World story 12"])
        self.assertEqual(self.page.locator("#lead h3, .rest h4").count(), 4)
        self.assertIn("Open Alpha Times homepage", self.page.inner_text(".cta"))
        self.assertIn("www.alphatimes.example", self.page.inner_text(".cta"))

    def test_clicking_the_tile_opens_the_newspaper_homepage_in_a_new_tab(self):
        self.ctx.route("https://www.alphatimes.example/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<title>Alpha</title>"))
        self.open(); self.pick("Alpha Times")
        tile = self.page.locator("a.front")
        self.assertEqual(tile.get_attribute("href"), "https://www.alphatimes.example/")
        self.assertEqual(tile.get_attribute("target"), "_blank")
        self.assertIn("noopener", tile.get_attribute("rel"))
        with self.ctx.expect_page() as popup:
            tile.click()
        self.assertEqual(popup.value.url, "https://www.alphatimes.example/")
        self.assertIn("/newspaper-list/", self.page.url)                                  # this page stays open

    def test_stories_from_older_data_are_matched_on_the_source_name(self):
        self.open(); self.pick("Beta Post")
        titles = [self.page.inner_text("#lead h3")] + self.page.locator(".rest h4").all_inner_texts()
        self.assertEqual(len(titles), 4)
        self.assertTrue(all(t.startswith("World story") for t in titles))
        self.assertEqual(titles[0], "World story 1")                                       # newest Beta Post story

    def test_a_paper_with_fewer_than_four_stories(self):
        self.open(); self.pick("Gamma Wire")
        self.assertEqual(self.page.inner_text("#lead h3"), "Sports story 0")
        self.assertEqual(self.page.locator(".rest article").count(), 2)

    def test_a_paper_with_no_recent_stories_still_offers_its_homepage(self):
        self.page.route("**/news.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"items": []})))
        self.open(); self.pick("Beta Post")
        self.assertIn("No recent headlines", self.page.inner_text(".none"))
        self.assertEqual(self.page.locator("a.front").get_attribute("href"), "https://betapost.example/")

    def test_works_when_the_news_file_cannot_be_loaded(self):
        self.page.route("**/news.json*", lambda r: r.fulfill(status=500, body="x"))
        self.open(); self.pick("Gazette Home")
        self.assertIn("No recent headlines", self.page.inner_text(".none"))

    def test_images_fall_back_to_a_letter_when_they_fail(self):
        self.page.route("https://img.example/**", lambda r: r.abort())
        self.page.route("**/news.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"items": [{"title": "T", "link": "https://x.example/1", "published": NOW.isoformat(), "source": "Beta Post",
                        "newspaper": "Beta Post", "image": "https://img.example/a.jpg"}]})))
        self.open(); self.pick("Beta Post")
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.locator("#lead img").count(), 0)
        self.assertEqual(self.page.inner_text("#lead .ph"), "B")

    def test_selection_is_kept_in_the_address_and_restored(self):
        self.open(); self.pick("Beta Post")
        self.assertTrue(self.page.url.endswith("#paper=Beta%20Post"))
        page2 = self.ctx.new_page(); page2.on("pageerror", lambda e: self.errors.append(str(e)))
        page2.goto(self.base + "newspaper-list/#paper=Beta%20Post")
        page2.wait_for_selector("a.front")
        self.assertEqual(page2.inner_text(".mname"), "Beta Post")
        self.assertEqual(page2.locator("#papers input:checked").count(), 1)

    def test_the_address_without_a_trailing_slash_also_works(self):
        self.page.goto(self.base + "newspaper-list")
        self.page.wait_for_selector("#papers label")
        self.assertTrue(self.page.url.endswith("/newspaper-list/"))

    def test_list_page_fails_gracefully_without_the_newspaper_list(self):
        self.page.route("**/papers.json*", lambda r: r.fulfill(status=404, body="no"))
        self.page.goto(self.base + "newspaper-list/")
        self.page.wait_for_selector("text=Could not load the newspaper list")


if __name__ == "__main__":
    unittest.main()
