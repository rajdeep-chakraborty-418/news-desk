# RC News Desk

A static front page of news tiles built from newspaper RSS feeds. A Python script fetches the headlines, a scheduler
refreshes them, and the site is rebuilt and published to GitHub Pages. Each tile shows image, headline, source, time
and a link to the original article.

## Repository layout
```
external_config/        everything you configure (no code)
  sections.json           the sections (tabs): names, colours, keyword rules
  newspaper_sections/      one file per newspaper: its own sections mapped onto your sections (many-to-one, e.g. Sports, AFL, NFL -> sports)
  settings.json           refresh interval, time-range and story-count choices, relay topic
src/                    all code
  fetch_news.py           fetches feeds, sorts stories into sections, writes site/news.json
  config.py, settings.py  load and validate the files in external_config/
  build_site.py           builds site/ (page + sections.json + papers.json + settings.json)
  scheduler_loop.py       the refresh scheduler and the Refresh-button relay listener
  check_images.py         image health report (diagnostic)
  web/index.html          the front page
  web/newspaper-list/     the Newspaper Homepage page (published at .../newspaper-list/)
test/                   tests (they use their own sample data and mocks, never external_config/)
.github/workflows/      update.yml (fetch + deploy), scheduler.yml (timer + refresh requests)
site/                   generated, not committed
```

## Configuring
- **Newspapers** (`newspaper_sections/<newspaper>.json`, one file each; the only list of newspapers): `newspaper`, `tier` (`primary`/`secondary`), `homepage`, optional `country`/`continent`, `feeds` (each `section`, `url`, optional `label`/`state`) and the section map below.
- **Sections** (`sections.json`): the order here is the tab order. Each has `key`, `label` and `color` (light and dark).
  There are no keyword or place rules: a story's section comes from its feed plus the newspaper's section map, and its
  country and continent are always its newspaper's (`country` / `continent` in its file; "Other" if it has none).
- **Settings** (`settings.json`): `refresh.manual_cooldown_minutes` (after a refresh finishes, no other refresh is
  accepted for this long; 360 = 6 hours), `refresh.min_gap_seconds`, `refresh.request_topic`, `time_ranges` (the
  "Fetch stories from" choices and default) and `article_counts` (the "Stories per section" choices and default).
  **There is no automatic refresh**: the news only updates when someone clicks Refresh. The page checks the cooldown
  first (using `refresh.json`, written by every refresh, and the server's clock) and shows a "please wait" popup; the
  scheduler job and the workflow check it again, so it cannot be bypassed. A failed refresh does not start a cooldown.
  A code push only redeploys the site with the headlines it already has.

A mistake in these files stops the build with a message naming the file, the entry and what to fix.
Set `NEWSDESK_CONFIG_DIR` to read the configuration from another folder.

## Running locally
```
python3 src/build_site.py          # page + config-derived files into site/
python3 src/fetch_news.py          # fetch and write site/news.json (WINDOW_HOURS / ARTICLE_COUNT env vars optional)
python3 -m http.server -d site     # preview
python3 -m unittest discover -s test     # or: python3 -m pytest test
```
Tests need PyYAML for the workflow checks; the browser tests need Playwright and Chrome and skip themselves without.

## The page
- Tabs (sections), continent chips, one Newspapers tree (tick a country for all its newspapers, or expand it to pick newspapers), search, and Primary / Secondary source-type checkboxes
  that apply on top of the other filters. Reset clears every selection.
- **Newspaper Homepage** (link beside the headline; the arrow opens it in a new tab) is a separate page at
  `newspaper-list/`: filter by continent, then country, search by country or newspaper, pick one newspaper, and a
  front-page style tile shows its 4 most recent headlines from the latest refresh. Clicking the tile opens the
  newspaper's own homepage in a new tab. The chosen paper is kept in the address (`#paper=Name`) so it can be shared.
- Each section shows 50 stories, "Show more" adds 50 up to the story count kept by the last refresh, then
  "No more articles available."
- Refresh (top right) needs no login: it posts the chosen time range and story count to a public ntfy.sh topic
  (`refresh.request_topic`); the scheduler job checks the topic about every 30 seconds and starts the update workflow.
  The button stays disabled until the run finishes, then shows Last: Success or Failed. At most one refresh starts per
  `refresh.min_gap_seconds`; anything that is not a valid request is ignored.
- Many feeds only list their latest items, so long time ranges return what each feed still holds
  (Google News based sources honour the full range).

## Images
Each tile has the same 16:9 box. The fetcher picks the largest image in each feed and reads the article's `og:image`
when a feed has none; the page letterboxes odd shapes and falls back to a placeholder.

## Publish for free with GitHub Pages
Public repository, Settings -> Pages -> Source: GitHub Actions, then run "Update news and deploy" once.
The listener job (`scheduler.yml`) restarts itself every ~3 hours; GitHub may delay its backup schedule and pauses scheduled workflows in repositories with no activity for 60 days.

## Newspaper section maps

`external_config/newspaper_sections/<newspaper>.json` maps a newspaper's own sections onto your sections:

```json
{"newspaper": "Hindustan Times",
 "section_map": {"sports": ["Sports", "Cricket", "US Sports"], "india": ["India News", "Delhi"]},
 "other": ["Videos", "Opinion"]}
```

A story is looked up by its feed tags and by the folders in its web address (`/sports/cricket/...`). Every match adds that story to the mapped section, on top of the section of the feed it came from. There are no keyword rules: a story is in its feed's section plus whatever the map gives. A newspaper is on the site only if it has a file here. Pilot: Hindustan Times, Times of India, India Today, Deccan Herald. `legacy_newspapers.json` is the old, unused list.

## Home page and section tabs

- **Home** (`/`) shows the refresh controls (Refresh, Last/Next Refresh, "Fetch stories from", "Stories per section"), the section buttons, and one random story *with a picture* for every section (a card reading "No stories yet" when a section has none). Picks change on every page load, after a refresh, and with the Shuffle button.
- **Section pages** (`/?section=<key>`) hold the filters, the Newspapers panel and the stories, and show nothing about refreshing. The headline reads "RC News Desk – {Section}" and links back to Home.
- Clicking a section opens it in its own browser tab (named `rcnd-<key>`); if that tab is already open it is just brought forward. A new tab starts with default filters; each tab keeps its filters in its URL and its own sessionStorage, so reloads restore them and tabs never affect each other.

## Repeated headlines

On every refresh, `src/dedupe.py` removes repeated headlines inside each section, across all newspapers: headlines at least 90% similar (character based, after lower-casing and dropping punctuation and a trailing " - Newspaper") count as the same story and only one is kept. A primary source beats a secondary one; then the copy with an image, the longer summary and the longer headline wins. A story dropped in one section but kept in another stays only in the one where it was kept. This runs before the per-section story cap, so the cap fills with distinct stories.

The de-duplication is a self-contained step: `fetch_news.py` calls only `dedupe.apply(items) -> (items, removed)`, which never changes its input, never adds or reorders stories and touches only each story's `sections`. The method inside `src/dedupe.py` (threshold, similarity, speed-ups) can be changed or replaced without touching the fetcher, the page or `news.json`'s format, and `test/test_dedupe.py` checks that contract. If the step ever raises an error, the refresh carries on without it.
