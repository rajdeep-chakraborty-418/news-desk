# RC News Desk – 2-hour sports & geopolitics headlines

A static front page of news tiles (Sports | Geopolitics, filter by continent, search).
A Python script pulls headlines from newspaper RSS feeds every 2 hours and the site is
rebuilt and published automatically. Each tile shows headline, source, time and links
to the original article.

## Sections and sources
- Sections: Indian News, World News, Sports News, Entertainment News, Defence News, Geo Politics News, Lifestyle.
  Each can be narrowed by continent, and by a multi-select country box on the right (nothing ticked = all countries).
  The page shows the top 50 stories per section; "Show more" adds 50 at a time up to 200, then says no more are available. Tiles show the story's main image (from the newspaper's feed).
- **Primary** sources are the newspapers you chose (`"primary": true` in `feeds.json`); everything else is
  secondary. Primary stories rank slightly higher and have a "Primary" mark. A checkbox shows primary only.
- Defence and Geo Politics are filled from dedicated feeds plus keyword matching on world and Indian stories.
- Country is detected from the headline (`geo.py`); Indian News is always India; otherwise the paper's home country is used.

## Refresh button (top right of the page)
Clicking it needs no login or token. The page posts a tiny request ("hours=24") to a public topic on ntfy.sh
(`refresh_topic.txt`); the scheduler job on GitHub (`scheduler_loop.py`) checks that topic about every 30 seconds
and starts the "Update news and deploy" workflow. The button stays disabled while the run is queued or running and
then shows "Last: Success" or "Last: Failed". At most one refresh starts per 5 minutes, and anything on the topic
that is not a proper `hours=` request is ignored. Optional: if you save a GitHub token in your browser
(localStorage key `rcnd_gh_token`, Actions = Read and write) the button starts the workflow directly instead.

## Time range
Next to the Refresh button, "Fetch stories from" sets how far back a refresh looks: last 6 hours, 12 hours,
24 hours (default), 3 days, 7 days, 30 days or 90 days. Automatic and push-triggered runs always use 24 hours.
Many newspaper feeds only list their latest items, so the longer ranges return whatever each feed still holds
(Google News based sources honour the full range).

## Images
Each tile has the same 16:9 image box. The fetcher picks the largest image in each feed (not the first thumbnail),
reads the article's own `og:image` when a feed has none, and the page letterboxes odd shapes over a blurred copy
and shows small images at natural size. If a publisher's image URL fails, the page retries once through the public
wsrv.nl image proxy, then falls back to a coloured placeholder. `check_images.py` logs an image health report
on manual and push runs.

## Automatic schedule
`scheduler.yml` runs `scheduler_loop.py` for about 3 hours at a time and then starts its next round. The loop
starts the update every `refresh_minutes.txt` minutes (118) and whenever the Refresh button asks. GitHub's own cron in
`update.yml` (hourly, with a ~100 minute gate) is only a backup.

## Files
- `feeds.json` – the newspapers (edit this to add or remove sources)
- `geo.py` – country/continent detection from headlines
- `fetch_news.py` – fetches the feeds, writes `site/news.json` (standard library only)
- `site/index.html` – the front page
- `.github/workflows/update.yml` – 2-hour job: fetch, then deploy to GitHub Pages
- `test_parser.py` – offline parser test (also writes demo data)

## Publish it free with GitHub Pages (about 5 minutes)
1. Create a free account at github.com and a new **public** repository, e.g. `world-desk`.
2. Upload everything in this folder (keep the `.github` folder), on the `main` branch.
3. In the repo go to **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. Go to the **Actions** tab, open "Update news and deploy", click **Run workflow**.
5. When it turns green, your site is live at `https://<your-username>.github.io/world-desk/`.
   After this it refreshes itself every 2 hours.

Note: GitHub may delay scheduled runs by several minutes at busy times, and pauses
scheduled workflows in repos with no activity for 60 days (re-run it manually to wake it).

## Use your own domain (e.g. worlddesk.in)
1. Buy a domain from any registrar (GoDaddy, Namecheap, Cloudflare, BigRock, etc.).
2. In the repo go to **Settings → Pages → Custom domain**, enter the domain and Save.
3. At your registrar's DNS settings add:
   - For a subdomain such as `www.yourdomain.com`: a `CNAME` record pointing to `<your-username>.github.io`.
   - For the bare domain `yourdomain.com`: four `A` records pointing to `185.199.108.153`,
     `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
     (confirm these against GitHub's current "Managing a custom domain" docs).
4. Wait for DNS to update (minutes to a few hours), then tick **Enforce HTTPS** in Pages settings.
Because the site is deployed with GitHub Actions, you do not need a `CNAME` file in the repo.

## Preview locally
```
python3 fetch_news.py
cd site && python3 -m http.server 8000     # open http://localhost:8000
```

## Adding sources
Add an entry to `feeds.json` with `source`, `continent`, `category` (`sports` or
`geopolitics`) and the RSS `url`. For a general feed, add `"keywords": [...]` to keep
only matching stories. A feed that breaks is skipped and reported in the job log;
some URLs may have changed, so check the log after the first run and fix or remove them.

## Content note
Only headlines, short snippets and links are shown, with clear attribution and a link
to the original. Please don't copy full article text.
