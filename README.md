# RC News Desk

A static front page of news tiles built from newspaper RSS feeds. A Python script fetches the headlines, a scheduler
refreshes them, and the site is rebuilt and published to GitHub Pages. Each tile shows image, headline, source, time
and a link to the original article.

## Repository layout
```
external_config/        everything you configure (no code)
  newspapers.json         newspapers, as "primary" and "secondary" nodes
  sections.json           the sections (tabs): names, colours, keyword rules
  settings.json           refresh interval, time-range and story-count choices, relay topic
src/                    all code
  fetch_news.py           fetches feeds, sorts stories into sections, writes site/news.json
  config.py, settings.py  load and validate the files in external_config/
  build_site.py           builds site/ (page + sections.json + papers.json + settings.json)
  scheduler_loop.py       the refresh scheduler and the Refresh-button relay listener
  geo.py                  country detection from headlines
  check_images.py         image health report (diagnostic)
  web/index.html          the front page
test/                   tests (they use their own sample data and mocks, never external_config/)
.github/workflows/      update.yml (fetch + deploy), scheduler.yml (timer + refresh requests)
site/                   generated, not committed
```

## Configuring
- **Newspapers** (`newspapers.json`): `{"primary": [...], "secondary": [...]}`. Each newspaper has `name`, `homepage`,
  optional `country` and `continent`, optional `"listed": false` (hide from the homepage dropdown) and `feeds`.
  Each feed has `section` (where its stories always appear), `url`, and optionally `label`, `state`,
  `general` (also match its stories against keyword sections), `country`, `continent`.
- **Sections** (`sections.json`): the order here is the tab order. Each has `key`, `label` and `color` (light and dark).
  Optional keyword rules: `keywords` are matched as whole words in headline and snippet of stories from feeds in
  `also_from_sections`, and from `general` feeds when `include_general_newspapers` is true
  (`extra_keywords_for_general_newspapers` adds words for those). `place` pins the story's country
  (`{"country", "continent"}`) or takes it from the newspaper (`"newspaper"`).
- **Settings** (`settings.json`): `refresh.interval_minutes` (how often the scheduled refresh runs),
  `refresh.min_gap_seconds`, `refresh.request_topic`, `time_ranges` (the "Fetch stories from" choices and default) and
  `article_counts` (the "Stories per section" choices and default). Scheduled refreshes use the defaults.
  The cron line in `update.yml` is the one thing GitHub makes you write in the workflow itself.

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
- Tabs (sections), continent chips, a multi-select country box, search, and Primary / Secondary source-type checkboxes
  that apply on top of the other filters. The Newspaper Homepage box (search + dropdown grouped by country) shows a link
  to the chosen paper's homepage. Reset clears every selection.
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
GitHub may delay scheduled runs and pauses them in repositories with no activity for 60 days.
