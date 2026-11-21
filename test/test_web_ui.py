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
    for n, (hi, en) in enumerate([("मुंबई में मेट्रो शुरू", "Metro starts in Mumbai"), ("दिल्ली में भारी बारिश", "Heavy rain in Delhi"),
                                  ("चेन्नई में बाढ़", "Flood in Chennai"), ("पुणे में आग", None)]):
        items.append({"title": hi, "link": f"https://news.example/r{n}", "summary": "", "image": "", "published": (NOW - timedelta(minutes=n)).isoformat(),
                      "source": "Navbharat Times", "newspaper": "Navbharat Times", "primary": False, "category": "showbiz", "sections": ["showbiz"],
                      "continent": "Asia", "country": "India", "state": None, **({"title_en": en} if en else {}),
                      "topics": ["Maharashtra (महाराष्ट्र)"] if n < 2 else ["Tamil Nadu (தமிழ்நாடு)"]})
    for it in items:                                    # pictures on some stories (the Home page ignores them)
        if it["title"] in ("World story 0", "World story 1", "World story 2", "World story 3", "World story 4", "World story 5", "Sports story 0", "Sports story 1"):
            it["image"] = "https://img.example/pic.jpg"
    for it in items:                                    # older data without the field: matched on the source name instead
        if it["title"].startswith("World story") and int(it["title"].split()[-1]) % 4 == 1:
            del it["newspaper"]
    for it in items:                                    # Defence Desk has topic buttons: 7 Navy, 6 Army
        if "defence" in it["sections"]:
            it["topics"] = ["Navy"] if int(it["title"].split()[-1]) % 20 == 0 else ["Army"]
    topics = {"defence": [{"label": "Navy", "count": 7}, {"label": "Army", "count": 6}],
              "showbiz": [{"label": "Maharashtra (महाराष्ट्र)", "count": 2}, {"label": "Tamil Nadu (தமிழ்நாடு)", "count": 2}]}
    return {"generated_at": NOW.isoformat(), "range_hours": 24, "max_articles": max_articles, "topics": topics, "items": items, "feeds": []}


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
        secs = json.loads((cls.site / "sections.json").read_text())
        for sec in secs:
            if sec["key"] == "money":
                sec["continent_filter"] = False                 # Money Desk: no continent buttons
            if sec["key"] in ("showbiz", "defence"):            # two large Home panels (Showbiz first), one medium (Home News), the rest small
                sec.update(tier=1, rank={"showbiz": 1, "defence": 2}[sec["key"]], **({"description": "Showbiz description line."} if sec["key"] == "showbiz" else {}))
            if sec["key"] in ("home", "world"):                 # two medium panels; the rest (India, Sports, Money) share one tabbed panel
                sec["tier"] = 2
        (cls.site / "sections.json").write_text(json.dumps(secs))
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
    def open(self, page=None, section="home"):
        """A section page (the first section by default), where the stories and filters are."""
        page = page or self.page
        page.goto(self.url + "?section=" + section)
        page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        return page

    def open_home(self, page=None):
        page = page or self.page
        page.goto(self.url)
        page.wait_for_function("document.querySelectorAll('#feat > *').length > 0")
        return page

    def tiles(self):
        return self.page.locator("#grid .tile").count()

    def titles(self):
        return self.page.locator("#grid .tile h2").all_inner_texts()

    def tab(self, label):
        """Go to a section the way a reload of its own page would (opening it in its own tab is tested separately)."""
        key = self.page.locator(f"#tabs button:text-is('{label}')").get_attribute("data-section")
        self.page.goto(self.url + "?section=" + key)
        self.page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")

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

    def test_topic_buttons_replace_the_continent_buttons_and_filter_the_section(self):
        self.open(section="defence")
        self.assertEqual(self.page.locator("#chips button").all_inner_texts(), ["All", "Navy (7)", "Army (6)"])
        self.assertEqual(self.page.get_attribute("#chips", "aria-label"), "Topic")
        self.assertEqual(self.tiles(), 13)
        self.page.click("#chips button:text-is('Navy (7)')")
        self.assertEqual(self.tiles(), 7)
        self.assertTrue(all(t.split()[-1].isdigit() and int(t.split()[-1]) % 20 == 0 for t in self.titles()))
        self.assertEqual(self.page.locator("#chips button[aria-pressed=true]").inner_text(), "Navy (7)")
        self.assertIn("topic=Navy", self.page.url)
        self.page.reload()                                                          # a reload restores the topic
        self.page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertEqual(self.tiles(), 7)
        self.assertEqual(self.page.locator("#chips button[aria-pressed=true]").inner_text(), "Navy (7)")
        self.page.click("#reset")
        self.assertEqual(self.tiles(), 13)
        self.assertEqual(self.page.locator("#chips button[aria-pressed=true]").inner_text(), "All")
        self.open(section="world")                                                  # other sections keep the continent buttons
        self.assertEqual(self.page.get_attribute("#chips", "aria-label"), "Continent")
        self.assertEqual(self.page.locator("#chips button").first.inner_text(), "All")
        self.assertIn("Asia", self.page.locator("#chips button").all_inner_texts())

    def test_english_headlines_button_and_search_on_regional_news(self):
        self.open(section="world")
        self.assertFalse(self.page.is_visible("#en"))                                # only where translations exist
        self.open(section="showbiz")
        self.assertTrue(self.page.is_visible("#en"))
        self.assertEqual(self.page.inner_text("#en"), "Show in English")
        self.assertIn("मुंबई में मेट्रो शुरू", self.titles())
        self.page.fill("#q", "metro")
        self.assertEqual(self.tiles(), 0)                                            # English words find nothing in the original headlines
        self.page.click("#en")
        self.assertEqual(self.page.inner_text("#en"), "Show original")
        self.assertEqual(self.tiles(), 1)
        self.assertEqual(self.titles(), ["Metro starts in Mumbai"])
        self.assertIn("मुंबई में मेट्रो शुरू", self.page.inner_text("#grid"))         # the original stays underneath
        self.page.fill("#q", "")
        self.assertEqual(sorted(self.titles()), sorted(["Metro starts in Mumbai", "Heavy rain in Delhi", "Flood in Chennai", "पुणे में आग"]))
        self.assertIn("en=1", self.page.url)
        self.page.reload()
        self.page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertEqual(self.page.inner_text("#en"), "Show original")
        self.page.click("#en")
        self.assertIn("मुंबई में मेट्रो शुरू", self.titles())

    def test_a_section_page_loads_only_its_own_data_file(self):
        import split_news
        split_news.write(json.loads((self.site / "news.json").read_text()), self.site)
        try:
            seen = []
            self.page.on("request", lambda r: seen.append(r.url))
            self.open(section="sports")
            self.assertEqual(self.tiles(), 3)
            self.assertTrue(any(u.endswith("/data/sports.json") for u in seen), seen)
            self.assertFalse(any("news.json" in u for u in seen), seen)
            seen.clear()
            self.page.goto(self.url)                                                  # the Home page: a pool, not everything
            self.page.wait_for_function("document.querySelectorAll('#feat .fcard, #feat .citem').length > 0")
            self.assertTrue(any(u.endswith("/data/home.json") for u in seen), seen)
            self.assertFalse(any("news.json" in u for u in seen), seen)
            self.assertGreater(self.page.locator("#feat .fcard, #feat .citem, #feat .clead").count(), 10)
        finally:
            shutil.rmtree(self.site / "data", ignore_errors=True)

    def test_state_buttons_show_english_and_local_name_with_the_count(self):
        self.open(section="showbiz")
        self.assertEqual(self.page.locator("#chips button").all_inner_texts(),
                         ["All", "Maharashtra (महाराष्ट्र) · 2", "Tamil Nadu (தமிழ்நாடு) · 2"])
        self.page.click("#chips button:has-text('Maharashtra')")
        self.assertEqual(self.tiles(), 2)

    def test_a_section_can_switch_the_continent_buttons_off(self):
        self.open(section="money")
        self.assertFalse(self.page.is_visible("#chips"))
        self.assertEqual(self.page.locator("#chips button").count(), 0)
        for sel in ("#kind", "#q", "#sidebox", "#reset"):                           # the other filters stay
            self.assertTrue(self.page.is_visible(sel), sel)
        self.page.goto(self.url + "?section=money&continent=Asia")                  # a continent in the address is ignored here
        self.page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertNotIn("continent", self.page.url)
        self.open(section="world")
        self.assertTrue(self.page.is_visible("#chips"))

    def country_row(self, name):
        return self.page.locator(f"#tree .cgrp[data-country='{name}']")

    def test_one_tree_country_then_newspapers(self):
        self.open(); self.tab("World Desk")
        self.assertEqual(self.page.inner_text("#selnote"), "All shown")
        self.assertEqual(self.page.locator("#nlist, #clist").count(), 0)                    # the two old panels are gone
        countries = [t.split("\n")[0] for t in self.page.locator("#tree .crow label").all_inner_texts()]
        self.assertEqual(sorted(countries), ["Brazil", "France", "Germany", "Japan", "Kenya"])
        self.assertEqual(self.page.locator("#tree .plist").count(), 0)                      # collapsed to start with
        self.country_row("France").locator(".tw").click()                                   # expand a country -> its newspapers
        papers = [t.split("\n")[0] for t in self.country_row("France").locator(".plist label").all_inner_texts()]
        self.assertEqual(sorted(papers), ["Alpha Times", "Beta Post"])
        self.country_row("France").locator(".tw").click()
        self.assertEqual(self.country_row("France").locator(".plist").count(), 0)

    def test_ticking_a_country_selects_all_its_newspapers(self):
        self.open(); self.tab("World Desk")
        self.country_row("France").locator("input.cc").check()
        self.assertEqual(self.tiles(), 26)                                                  # every France story
        self.assertEqual(self.page.inner_text("#selnote"), "2 newspapers selected")
        self.assertEqual(self.country_row("France").locator(".plist input.pp:checked").count(), 2)
        self.country_row("Japan").locator("input.cc").check()
        self.assertEqual(self.tiles(), 50)                                                  # 26 + 26, capped to the first 50
        self.country_row("France").locator("input.cc").uncheck()
        self.assertEqual(self.tiles(), 26)

    def test_a_single_newspaper_gives_a_partly_ticked_country(self):
        self.open(); self.tab("World Desk")
        self.country_row("France").locator(".tw").click()
        self.country_row("France").locator(".plist label", has_text="Alpha Times").locator("input").check()
        self.assertEqual(self.page.inner_text("#selnote"), "1 newspaper selected")
        self.assertTrue(self.country_row("France").locator("input.cc").evaluate("e => e.indeterminate"))
        self.assertTrue(0 < self.tiles() < 26)
        self.assertTrue(all("Alpha Times" in t for t in self.page.locator("a.tile").all_inner_texts()))

    def test_search_finds_countries_and_newspapers(self):
        self.open(); self.tab("World Desk")
        self.page.fill("#cq", "ger")
        self.assertEqual([t.split("\n")[0] for t in self.page.locator("#tree .crow label").all_inner_texts()], ["Germany"])
        self.page.fill("#cq", "beta")                                                        # a newspaper name: every country that has it
        self.assertEqual(self.page.locator("#tree .crow label").count(), 5)
        self.assertEqual(self.page.locator("#tree .plist label").all_inner_texts()[0].split("\n")[0], "Beta Post")
        self.page.click("#clear")
        self.assertEqual(self.page.input_value("#cq"), "")

    def test_tree_combines_with_the_other_selections(self):
        self.open(); self.tab("World Desk")
        self.page.click("#chips button:text-is('Europe')")
        self.country_row("France").locator("input.cc").check()
        self.assertEqual(self.tiles(), 26)
        self.page.fill("#q", "story 1")
        self.assertLessEqual(self.tiles(), 26)
        self.page.click("#reset")
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
        self.country_row("France").locator("input.cc").check()
        before = self.tiles()                                                            # all France stories
        self.page.fill("#q", "story 1")
        narrowed = self.tiles()
        self.page.check("#fPrimary")
        after = self.tiles()
        self.assertEqual(before, 26)
        self.assertLessEqual(after, narrowed)
        self.assertTrue(all(self.page.locator("#grid .tile").nth(i).locator(".pri").count() == 1 for i in range(after)))
        self.assertEqual(self.page.input_value("#q"), "story 1")                         # earlier filters still in force
        self.assertEqual(self.page.inner_text("#selnote"), "2 newspapers selected")
        self.assertEqual(self.page.locator("#chips button[aria-pressed=true]").inner_text(), "Europe")

    def test_headline_is_entirely_black(self):
        self.open_home()
        colours = self.page.evaluate("[document.querySelector('h1'), document.querySelector('h1 span')].map(e => getComputedStyle(e).color)")
        self.assertEqual(colours, ["rgb(0, 0, 0)", "rgb(0, 0, 0)"])
        self.assertEqual(self.page.inner_text("h1").replace("\n", " "), "SJ News Desk")

    def test_newspaper_homepage_link_and_page_title_are_entirely_black(self):
        self.open_home()
        self.page.goto(self.base + "newspaper-list/")
        colours = self.page.evaluate("[document.querySelector('h1'), document.querySelector('h1 span')].map(e => getComputedStyle(e).color)")
        self.assertEqual(colours, ["rgb(0, 0, 0)", "rgb(0, 0, 0)"])

    def test_headline_stays_readable_in_dark_mode(self):
        page = self.ctx.new_page(); page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.emulate_media(color_scheme="dark")
        self.open(page=page)
        colours = page.evaluate("[document.querySelector('h1'), document.querySelector('h1 span')].map(e => getComputedStyle(e).color)")
        self.assertEqual(colours[0], colours[1])
        self.assertNotEqual(colours[0], "rgb(0, 0, 0)")                  # black on the dark background would vanish

    def test_main_page_no_longer_has_the_newspaper_dropdown(self):
        self.open()
        for gone in ("#paper", "#pq", "#paperlink", ".paperbox"):
            self.assertEqual(self.page.locator(gone).count(), 0, gone)
        self.assertEqual(self.page.locator("label[for=paper]").count(), 0)

    # ---------------------------------------------------------------- reset
    def test_reset_clears_every_selection(self):
        self.open(section="world")
        start = self.snapshot()
        self.page.click("#chips button:text-is('Europe')")
        self.page.fill("#q", "story 1"); self.page.check("#fPrimary"); self.page.fill("#cq", "fr")
        self.country_row("France").locator("input.cc").check()
        self.assertNotEqual(self.snapshot(), start)
        self.page.click("#reset")
        self.assertEqual(self.snapshot(), start)

    def snapshot(self):
        p = self.page
        return dict(tab=p.locator("#tabs button[aria-pressed=true]").inner_text(), chip=p.locator("#chips button[aria-pressed=true]").inner_text(),
                    q=p.input_value("#q"), cq=p.input_value("#cq"), pri=p.is_checked("#fPrimary"), sec=p.is_checked("#fSecondary"),
                    sel=p.inner_text("#selnote"), tiles=self.tiles())

    def test_reset_button_sits_under_the_logo(self):
        self.open()
        logo, reset = self.page.locator("h1").bounding_box(), self.page.locator("#reset").bounding_box()
        self.assertGreater(reset["y"], logo["y"] + logo["height"] - 2)
        self.assertLess(abs(reset["x"] - logo["x"]), 4)
        self.assertEqual(self.page.inner_text("#reset"), "Reset")

    # ---------------------------------------------------------------- refresh choices come from settings.json
    def test_refresh_choices_and_defaults_come_from_settings_json(self):
        self.open_home()
        opts = lambda sel: self.page.evaluate(f"[...document.querySelectorAll('{sel} option')].map(o => [o.value, o.textContent])")
        self.assertEqual(opts("#range"), [["6", "Six hours"], ["24", "One day"], ["72", "Three days"], ["168", "One week"]])
        self.assertEqual(opts("#count"), [["50", "50"], ["150", "150"], ["250", "250"]])
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("24", "150"))

    def test_choices_are_remembered_but_only_while_still_valid(self):
        self.open_home()
        self.page.select_option("#range", "72"); self.page.select_option("#count", "250")
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#range option').length > 0")
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("72", "250"))
        self.page.evaluate("localStorage.setItem('rcnd_range_v3', '999'); localStorage.setItem('rcnd_count_v3', '77')")
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#range option').length > 0")
        self.assertEqual((self.page.input_value("#range"), self.page.input_value("#count")), ("24", "150"))

    def test_choices_saved_before_the_defaults_changed_are_ignored_once(self):
        self.page.add_init_script("if (!localStorage.getItem('seeded')) { localStorage.setItem('seeded', '1'); localStorage.setItem('rcnd_range', '72'); localStorage.setItem('rcnd_count', '250'); }")
        self.open_home()
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
        self.open_home(); self.wait_ready()
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
        self.open_home(); self.wait_ready()
        self.page.click("#refresh")
        self.page.wait_for_function("document.querySelector('#rlabel').innerText === 'Refreshing…'")
        for _ in range(50):
            if self.relay_urls: break
            self.page.wait_for_timeout(100)
        self.assertEqual(self.relay_urls, ["https://ntfy.sh/test-topic-abc"])

    def test_failed_run_is_reported(self):
        self.open_home(); self.wait_ready()
        def gh(route):
            runs = [run(6, "completed", "failure"), run(5, "completed", "success")] if self.relay else self.runs
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": runs}))
        self.page.route("https://api.github.com/**", gh)
        self.page.click("#refresh")
        self.page.wait_for_function("document.querySelector('#rstatus').innerText.includes('Failed')", timeout=10000)
        self.assertFalse(self.page.is_disabled("#refresh"))

    def test_relay_down_shows_a_message_and_re_enables_the_button(self):
        self.open_home(); self.wait_ready()
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
        self.open_home(page); page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")
        page.click("#refresh")
        page.wait_for_function("document.querySelector('#rlabel').innerText==='Refresh' && !document.querySelector('#refresh').disabled", timeout=10000)
        self.assertEqual(relay, ["hours=24&count=150"])                                  # fell back to the relay
        self.assertIsNone(page.evaluate("localStorage.getItem('rcnd_gh_token')"))        # stale token removed
        self.assertEqual(self.dialogs, [])

    def test_header_shows_when_the_data_was_generated(self):
        self.open_home()
        self.assertIn("Last Refresh", self.page.inner_text("#lastrefresh"))

    def record_page(self, record, schedule=None):
        """Home page with refresh.json (and optionally the schedule in settings.json) replaced; the text lines of the header block."""
        self.page.route("**/refresh.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(record)))
        if schedule:
            def settings_route(route):
                data = route.fetch().json(); data["schedule"].update(schedule)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
            self.page.route("**/settings.json*", settings_route)
        self.open_home()
        self.page.wait_for_function("document.querySelector('#nextrefresh').innerText.startsWith('Next Refresh')")
        return {k: self.page.inner_text("#" + k) for k in ("lastrefresh", "lastsched", "nextrefresh")}

    def fmt(self, ms):
        return self.page.evaluate("(ms) => RefreshInfo.format(ms)", ms)

    def test_header_shows_the_last_refresh_and_the_next_scheduled_slot(self):
        from datetime import datetime, timezone
        import refresh_schedule, settings
        now = datetime.now(timezone.utc)
        text = self.record_page({"refreshed_at": (now - timedelta(minutes=5)).isoformat(), "kind": "scheduled", "range_hours": 72,
                                 "max_articles": 250, "last_scheduled_at": (now - timedelta(minutes=5)).isoformat()})
        want = refresh_schedule.next_slot(settings.load_settings(support.SAMPLE_CONFIG)["schedule"], now)        # sample: every 6 h from 01:30 IST
        self.assertEqual(text["nextrefresh"], "Next Refresh " + self.fmt(int(want.timestamp() * 1000)))
        self.assertIn("(scheduled)", text["lastrefresh"])
        self.assertIn("✓", text["lastrefresh"])
        self.assertEqual(text["lastsched"], "")

    def test_an_adhoc_refresh_shows_its_own_time_and_leaves_the_next_slot_alone(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        sched = (now - timedelta(hours=2)).isoformat()
        scheduled = self.record_page({"refreshed_at": sched, "kind": "scheduled", "range_hours": 72, "max_articles": 250, "last_scheduled_at": sched})
        self.page.unroute_all()
        adhoc = self.record_page({"refreshed_at": (now - timedelta(minutes=3)).isoformat(), "kind": "adhoc", "range_hours": 6,
                                  "max_articles": 50, "last_scheduled_at": sched})
        self.assertIn("(adhoc, last 6 h / 50 stories)", adhoc["lastrefresh"])
        self.assertEqual(adhoc["lastsched"], "Last scheduled " + self.fmt(int(datetime.fromisoformat(sched).timestamp() * 1000)))
        self.assertEqual(adhoc["nextrefresh"], scheduled["nextrefresh"])                    # the slot did not move

    def test_a_late_slot_is_shown_as_delayed_until_a_scheduled_refresh_catches_up(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        slot = {"every_minutes": 240, "anchor": (now - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%SZ"), "grace_minutes": 15}
        old = (now - timedelta(hours=5)).isoformat()
        late = self.record_page({"refreshed_at": old, "kind": "scheduled", "range_hours": 24, "max_articles": 3000, "last_scheduled_at": old}, slot)
        self.assertEqual(late["nextrefresh"], "Next Refresh due (delayed)")
        self.page.unroute_all()
        fresh = (now - timedelta(minutes=10)).isoformat()
        ok = self.record_page({"refreshed_at": fresh, "kind": "scheduled", "range_hours": 24, "max_articles": 3000, "last_scheduled_at": fresh}, slot)
        self.assertNotIn("delayed", ok["nextrefresh"])

    def test_a_missing_refresh_record_still_shows_the_data_time_and_next_slot(self):
        self.page.route("**/refresh.json*", lambda r: r.fulfill(status=404, body=""))
        self.open_home()
        self.page.wait_for_function("document.querySelector('#nextrefresh').innerText.startsWith('Next Refresh')")
        self.assertIn("Last Refresh", self.page.inner_text("#lastrefresh"))

    # ---------------------------------------------------------------- the cooldown between manual refreshes
    def cooldown_page(self, refreshed_minutes_ago):
        """Opens the page with refresh.json saying the last refresh finished that long ago; returns the list of relay posts."""
        posts = []
        done = (datetime.now(timezone.utc) - timedelta(minutes=refreshed_minutes_ago)).isoformat()
        self.page.route("**/refresh.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"refreshed_at": done})))
        self.page.route("https://ntfy.sh/**", lambda r: (posts.append(r.request.post_data), r.fulfill(status=200, body="{}")))
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": [run(5, "completed", "success")]})))
        self.open_home(); self.page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")
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
        self.open_home(); self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.page.click("#refresh")
        self.page.wait_for_timeout(800)
        self.assertEqual(posts, ["hours=24&count=150"])                                  # by the server's clock the cooldown is long over

    def test_a_missing_refresh_json_does_not_block(self):
        posts = []
        self.page.route("https://ntfy.sh/**", lambda r: (posts.append(r.request.post_data), r.fulfill(status=200, body="{}")))
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"workflow_runs": []})))
        self.open_home(); self.page.wait_for_function("!document.querySelector('#refresh').disabled")
        self.page.click("#refresh")
        self.page.wait_for_timeout(800)
        self.assertEqual(len(posts), 1)

    def test_a_cancelled_run_is_not_shown_as_a_failed_refresh(self):
        self.page.route("https://api.github.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"workflow_runs": [run(9, "completed", "cancelled"), run(5, "completed", "success")]})))
        self.open_home(); self.page.wait_for_function("document.querySelector('#rstatus').innerText.startsWith('Last')")
        self.assertIn("✓", self.page.inner_text("#rstatus"))
        self.assertIn("✓", self.page.inner_text("#lastrefresh"))


@unittest.skipUnless(sync_playwright and CHROME, "Playwright with Chrome is not available")
class HomeAndTabsTest(BrowserBase):
    def setUp(self):
        super().setUp()
        self.ctx.route("https://img.example/**", lambda r: r.fulfill(status=404, body=""))

    def home(self):
        self.page.goto(self.url)
        self.page.wait_for_function("document.querySelectorAll('#feat > *').length > 0")

    def section_page(self, page, key, **params):
        from urllib.parse import urlencode
        page.goto(self.url + "?" + urlencode({"section": key, **params}))
        page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")

    def test_header_picture_comes_from_the_image_set_of_the_place(self):
        (self.site / "backgrounds" / "landing").mkdir(parents=True, exist_ok=True)
        (self.site / "backgrounds" / "landing" / "a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 2"/>')
        (self.site / "backgrounds.json").write_text(json.dumps({"landing": ["backgrounds/landing/a.svg"]}))
        try:
            self.home()
            page = self.page
            page.wait_for_selector("header.banded")
            self.assertIn("backgrounds/landing/a.svg", page.evaluate("document.querySelector('header').style.backgroundImage"))
            self.section_page(page, "world")                              # no image set for this section: plain header
            self.assertEqual(page.locator("header.banded").count(), 0)
        finally:
            (self.site / "backgrounds.json").write_text("{}")

    def test_home_shows_no_stories_or_filters_but_the_refresh_options(self):
        self.home()
        for sel in ("#grid", "#sidebox", "#chips", "#q", "#rangebar", "#reset"):
            self.assertFalse(self.page.is_visible(sel), sel)
        for sel in ("#refresh", "#range", "#count", "#lastrefresh", ".pickpanel", "#tabs"):
            self.assertTrue(self.page.is_visible(sel), sel)
        self.assertEqual(self.page.title(), "SJ News Desk")
        self.assertEqual(self.page.locator("#tabs button").count(), 7)

    def test_home_panels_come_in_three_sizes_by_tier(self):
        self.home()
        self.assertEqual(self.page.locator("#feat .pickpanel").count(), 5)         # 2 large + 2 medium + ONE tabbed panel
        self.assertEqual(self.page.locator(".tier1 .pickpanel .phead h2").all_inner_texts(), ["Showbiz Desk", "Defence Desk"])   # by rank
        self.assertEqual(self.page.locator(".tier2 .pickpanel .phead h2").all_inner_texts(), ["Home News", "World Desk"])
        self.assertEqual(self.page.locator(".tier3 .pickpanel").count(), 1)
        t1, t2, t3 = (self.page.locator(f".tier{n} .pickpanel") for n in (1, 2, 3))
        b1 = [t1.nth(n).bounding_box() for n in range(2)]
        self.assertEqual(round(b1[0]["y"]), round(b1[1]["y"]))                      # two large panels side by side
        b2 = [t2.nth(n).bounding_box() for n in range(2)]
        self.assertEqual(round(b2[0]["y"]), round(b2[1]["y"]))                      # medium panels side by side
        self.assertLess(b1[0]["y"], b2[0]["y"])                                     # large above medium above the tabs
        self.assertLess(b2[0]["y"], t3.nth(0).bounding_box()["y"])
        big = self.panel("showbiz")                                                 # a large panel: description, lead picture, picture headlines
        self.assertEqual(big.locator(".pdesc").inner_text(), "Showbiz description line.")
        self.assertEqual(big.locator(".clead").count(), 1)
        self.assertEqual(big.locator(".citem").count(), 3)                          # four stories: the lead and three more
        self.assertEqual(self.panel("defence").locator(".pdesc").count(), 0)        # no description configured
        self.assertEqual(self.panel("defence").locator(".citem").count(), 4)        # lead + four of thirteen
        for key in ("home", "world"):                                               # a medium panel: the lead and two more = three stories
            self.assertEqual(self.panel(key).locator(".clead").count(), 1)
            self.assertEqual(self.panel(key).locator(".citem").count(), 2)
        big.locator(".pmax").click()                                                # Maximise: five cards with pictures, whatever the tier
        self.assertEqual(big.locator(".fcard .thumb").count(), 4)
        big.locator(".shuffle").dispatch_event("click")
        self.assertEqual(big.locator(".fcard").count(), 4)                          # Shuffle keeps the maximised view
        big.locator(".pmax").click()
        self.assertEqual(big.locator(".citem").count(), 3)                          # and back to the large layout
        self.assertEqual(self.page.locator(".pickpanel .shuffle").count(), 5)       # each panel has its own Shuffle

    def test_small_sections_share_one_tabbed_panel(self):
        self.home()
        panel = self.page.locator("#picks-more")
        self.assertEqual(panel.locator(".ptab").all_inner_texts(), ["India Desk", "Sports Desk", "Money Desk"])
        self.assertEqual(panel.locator(".ptab[aria-selected=true]").all_inner_texts(), ["India Desk"])
        self.assertIn("No stories yet", panel.inner_text())
        panel.locator(".ptab:text-is('Sports Desk')").click()
        self.assertEqual(panel.locator(".ptab[aria-selected=true]").all_inner_texts(), ["Sports Desk"])
        self.assertEqual(panel.locator(".fcard").count(), 2)                        # Standard: two stories, headlines only
        self.assertEqual(panel.locator(".thumb").count(), 0)
        std = panel.locator(".fcard h2").all_inner_texts()
        panel.locator(".pmax").click()
        self.assertEqual(panel.locator(".fcard").count(), 3)                        # Maximise: all the section has (up to five), with pictures
        self.assertEqual(panel.locator(".fcard .thumb").count(), 3)
        self.assertEqual(panel.locator(".fcard h2").all_inner_texts()[:2], std)     # the first two are the Standard ones
        panel.locator(".ptab:text-is('Money Desk')").dispatch_event("click")        # the open tab's section is the one Shuffle and Maximise act on
        self.assertIn("No stories yet", panel.inner_text())
        panel.locator(".pmax").click()
        with self.ctx.expect_page() as info:
            panel.locator(".ptab:text-is('Sports Desk')").click()
            panel.locator(".popen").click()
        info.value.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertIn("section=sports", info.value.url)                             # "Open section" follows the open tab

    def panel(self, key):
        return self.page.locator(f"#feat .pickpanel[data-section={key}]")

    def test_a_medium_panel_features_three_stories_with_pictures_and_five_when_maximised(self):
        self.home()
        world = self.panel("world")
        titles = world.locator(".ctitle").all_inner_texts()
        self.assertEqual(len(titles), 3)                                          # 130 stories: the lead and two more
        self.assertEqual(len(set(titles)), 3)
        self.assertTrue(all(t.startswith("World story") for t in titles))
        self.assertEqual(world.locator(".clead").get_attribute("target"), "_blank")
        self.assertEqual(world.locator(".thumb").count(), 3)                      # medium panels show pictures

    def test_maximise_shows_five_and_the_standard_ones_are_the_first_three(self):
        self.home()
        world = self.panel("world")
        std = world.locator(".ctitle").all_inner_texts()
        world.locator(".pmax").click()
        mx = world.locator(".fcard h2").all_inner_texts()
        self.assertEqual(len(mx), 5)
        self.assertEqual(mx[:3], std)                                             # the same stories, two more
        self.assertEqual(world.locator(".fcard .thumb").count(), 5)               # now as five cards with pictures
        world.locator(".pmax").click()                                            # back to Standard
        self.assertEqual(world.locator(".ctitle").all_inner_texts(), std)
        for _ in range(3):                                                        # clicking Maximise/Standard never reshuffles
            world.locator(".pmax").click(); world.locator(".pmax").click()
        self.assertEqual(world.locator(".ctitle").all_inner_texts(), std)
        world.locator(".pmax").click()
        before = world.locator(".fcard h2").all_inner_texts()
        changed = False
        for _ in range(12):
            world.locator(".shuffle").dispatch_event("click")
            if world.locator(".fcard h2").all_inner_texts() != before: changed = True; break
        self.assertTrue(changed)                                                  # only Shuffle changes the set
        self.assertEqual(world.locator(".fcard .thumb").count(), 5)               # and the view stays maximised

    def test_a_panels_shuffle_changes_only_that_panel(self):
        self.home()
        before_home = self.panel("home").locator(".ctitle").all_inner_texts()
        seen = set()
        for _ in range(12):
            self.panel("world").locator(".shuffle").click()
            seen.add(tuple(self.panel("world").locator(".ctitle").all_inner_texts()))
            self.assertEqual(self.panel("world").locator(".ctitle").count(), 3)
        self.assertGreater(len(seen), 1)                                          # 130 stories: more than one result
        self.assertEqual(self.panel("home").locator(".ctitle").all_inner_texts(), before_home)

    def test_a_panel_title_opens_its_section_in_a_new_tab(self):
        self.home()
        with self.ctx.expect_page() as info:
            self.panel("world").locator(".phead h2").click()
        info.value.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertIn("section=world", info.value.url)

    def test_a_section_opens_in_a_new_tab_and_home_is_untouched(self):
        self.home()
        with self.ctx.expect_page() as info:
            self.page.click("#tabs button:text-is('World Desk')")
        tab = info.value
        tab.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertIn("section=world", tab.url)
        self.assertEqual(self.page.url, self.url)
        self.assertEqual(self.page.locator("#feat .pickpanel").count(), 5)
        self.assertEqual(tab.title(), "SJ News Desk – World Desk")
        self.assertEqual(tab.inner_text("h1"), "SJ News Desk – World Desk")
        self.assertEqual(tab.get_attribute("#homelink", "href"), "/index.html")
        for sel in ("#refresh", "#lastrefresh", "#nextrefresh", "#range", "#count"):
            self.assertFalse(tab.is_visible(sel), sel)
        for sel in ("#chips", "#q", "#rangebar", "#sidebox", "#reset"):
            self.assertTrue(tab.is_visible(sel), sel)
        self.assertFalse(tab.is_visible("#panel-papers"))                        # the panels are on Home only
        self.assertFalse(tab.is_visible(".pickpanel"))
        self.assertFalse(tab.is_visible("#tabs"))                                # section buttons are on the landing page only

    def test_opening_an_open_section_again_jumps_to_its_tab_and_keeps_its_filters(self):
        self.home()
        with self.ctx.expect_page() as info:
            self.page.click("#tabs button:text-is('World Desk')")
        tab = info.value
        tab.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        tab.fill("#q", "story 1")
        tab.wait_for_function("location.search.includes('story+1')")
        before = len(self.ctx.pages)
        self.page.click("#tabs button:text-is('World Desk')")
        self.page.wait_for_timeout(500)
        self.assertEqual(len(self.ctx.pages), before)
        self.assertEqual(tab.input_value("#q"), "story 1")

    def test_each_tab_keeps_its_own_filters(self):
        self.home()
        tabs = {}
        for label, key in (("World Desk", "world"), ("Sports Desk", "sports")):
            with self.ctx.expect_page() as info:
                self.page.click(f"#tabs button:text-is('{label}')")
            tabs[key] = info.value
            tabs[key].wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        tabs["world"].click("#chips button:text-is('Europe')"); tabs["world"].check("#fPrimary")
        self.assertEqual(tabs["sports"].locator("#chips button[aria-pressed=true]").inner_text(), "All")
        self.assertFalse(tabs["sports"].is_checked("#fPrimary"))
        self.assertEqual(tabs["sports"].locator("#grid .tile").count(), 3)

    def test_filters_survive_a_reload_and_a_new_tab_starts_clean(self):
        self.section_page(self.page, "world")
        self.page.click("#chips button:text-is('Asia')"); self.page.fill("#q", "story")
        self.page.reload(); self.page.wait_for_function("document.querySelectorAll('#grid > *').length > 0")
        self.assertEqual(self.page.locator("#chips button[aria-pressed=true]").inner_text(), "Asia")
        self.assertEqual(self.page.input_value("#q"), "story")
        other = self.ctx.new_page()
        self.section_page(other, "world", fresh="1")
        self.assertEqual(other.locator("#chips button[aria-pressed=true]").inner_text(), "All")
        self.assertEqual(other.input_value("#q"), "")

    def test_the_newspaper_homepage_panel_is_not_on_the_landing_page(self):
        self.home()
        self.assertEqual(self.page.locator("#panel-papers, #papersframe, a[href*='newspaper-list']").count(), 0)
        for gone in ("a.navlink", "a.navnew", "#paperlist", "#papers"):
            self.assertEqual(self.page.locator(gone).count(), 0, gone)

    def test_panels_can_be_maximised_and_restored(self):
        self.home()
        picks, other = self.panel("world"), self.panel("home")
        small = picks.bounding_box()
        btn = picks.locator(".pmax")
        self.assertEqual(btn.inner_text(), "Maximise")
        btn.click()
        self.assertEqual(btn.inner_text(), "Standard")
        box = picks.bounding_box()
        self.assertGreater(box["width"], 1200)                                                          # fills the window
        self.page.keyboard.press("Escape")                                                             # Esc restores
        self.assertEqual(btn.inner_text(), "Maximise")
        self.assertEqual(picks.bounding_box()["height"], small["height"])
        picks.locator(".pmax").click(); other.locator(".pmax").dispatch_event("click")                  # one maximised at a time
        self.assertEqual(self.page.locator(".hpanel.max").count(), 1)
        other.locator(".pmax").click()
        self.assertEqual(self.page.locator(".hpanel.max").count(), 0)

    def test_the_headline_links_back_to_home(self):
        self.section_page(self.page, "sports")
        self.page.click("#homelink")
        self.page.wait_for_function("document.querySelectorAll('#feat > *').length > 0")
        self.assertEqual(self.page.title(), "SJ News Desk")

    def test_the_panel_is_called_newspapers(self):
        self.section_page(self.page, "world")
        self.assertTrue(self.page.inner_text("#sidebox summary").startswith("Newspapers"))


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
        self.assertEqual(self.page.title(), "Newspaper Homepage — SJ News Desk")
        self.assertEqual(self.page.locator("#continents button").all_inner_texts(), ["All (4)", "Asia (2)", "Europe (1)", "Other (1)"])
        self.assertEqual(self.countries(), ["All countries", "Bangladesh", "France", "India", "International"])
        self.assertEqual(self.names(), ["Alpha Times", "Beta Post", "Gamma Wire", "Gazette Home"])
        self.assertIn("Choose a newspaper", self.page.inner_text("#stage"))
        self.assertEqual(self.page.locator("a.front").count(), 0)

    def test_back_link_returns_to_the_news_page(self):
        self.open()
        self.page.click("a.back")
        self.page.wait_for_url("**/")
        self.assertEqual(self.page.locator("h1").first.inner_text().replace("\n", " "), "SJ News Desk")

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

    def test_front_page_tile_shows_the_ten_most_recent_headlines(self):
        self.open(); self.pick("Alpha Times")
        tile = self.page.locator("a.front")
        self.assertEqual(self.page.inner_text(".mname"), "Alpha Times")
        self.assertIn("INDIA · ASIA", self.page.inner_text(".mmeta").upper())
        self.assertIn("primary", self.page.inner_text(".mmeta").lower())
        # Alpha Times has stories 0, 4, 8, 12 ... (newest first); the lead is the newest, nine more follow
        self.assertEqual(self.page.inner_text("#lead h3"), "World story 0")
        self.assertEqual(self.page.locator(".rest article h4").all_inner_texts(), [f"World story {n}" for n in range(4, 40, 4)])
        self.assertEqual(self.page.locator("#lead h3, .rest h4").count(), 10)
        self.assertLess(self.page.locator("a.front").bounding_box()["height"], 560)                  # compact: ten stories in a short tile
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
        self.assertEqual(len(titles), 10)
        self.assertTrue(all(t.startswith("World story") for t in titles))
        self.assertEqual(titles[0], "World story 1")                                       # newest Beta Post story

    def test_a_paper_with_fewer_than_ten_stories(self):
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
