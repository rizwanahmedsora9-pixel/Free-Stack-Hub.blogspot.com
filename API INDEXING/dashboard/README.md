# Indexing Console

A Flask dashboard for **freestackhub.blogspot.com** that does everything the notebooks and the
old `blogger-indexer.zip` app did — and the things they couldn't:

| Feature | How |
|---|---|
| Upload the service-account JSON key, connect | Setup page; key stored in `instance/` (git-ignored, mode 600) |
| See every property the account can access | `GET webmasters/v3/sites` → pick from a list (no more typing the siteUrl wrong) |
| Find **every URL on the blog** | `sitemap.xml` + `sitemap-pages.xml` + the public JSON feed (title, labels, dates, author, thumbnail, word count) |
| Indexed / not indexed, crawled or not, **which bot** | URL Inspection API: verdict, coverage state, `lastCrawlTime`, `crawledAs` (MOBILE/DESKTOP), fetch state, robots, noindex, canonicals, sitemaps, referring URLs, rich results |
| Push the unindexed | Indexing API `URL_UPDATED` / `URL_DELETED`, one URL or in bulk, skipping URLs a push can't fix (noindex / robots) |
| **Which request was sent, when, and what Google said** | Every call is logged: time, kind, URL, type, HTTP status, Google's message, duration, raw JSON. Plus `urlNotifications/metadata` to read Google's own `notifyTime` |
| Smart info cards | Prioritised, actionable insights: pushable URLs, blocked URLs, canonical mismatches, fetch problems, stale checks, quota warnings, index rate |
| Quota safety | Counts publish (200/day, per Cloud project, resets midnight Pacific) and inspection (2,000/day rolling, 600/min) usage; bulk jobs pace themselves and stop at a reserve |
| Background jobs | Inspect all / stale / never-checked, push all unindexed, re-check pushed — one at a time with a live progress bar; cancellable |
| History | Every inspection is kept (not overwritten), so you get a per-URL timeline: published → discovered → pushed → crawled → indexed |
| Demo mode | Simulated Google, real UI. Pushed URLs get "crawled" after ~1 min and "indexed" after ~3 min |
| Export | JSON and CSV of all URLs + request log |
| Optional automation | Auto re-check pushed URLs and auto-discover new posts on an interval (while the app runs) |

## Run

```bash
cd "API INDEXING/dashboard"
pip install -r requirements.txt          # add --break-system-packages on PythonAnywhere / Debian
python3 run.py --demo                    # try it with simulated data
python3 run.py                           # real mode: open http://127.0.0.1:5000 and upload the key
```

Options: `--host 0.0.0.0 --port 8080 --debug`. Env: `PORT`, `HOST`, `SECRET_KEY`, `INDEXER_INSTANCE_DIR`, `INDEXER_DB`.

## One-time Google setup

1. **Google Cloud** → project → *APIs & Services → Library* → enable **Web Search Indexing API** and **Google Search Console API**.
2. *IAM & Admin → Service Accounts → Create* → *Keys → Add key → JSON* → download.
3. **Search Console** → property → *Settings → Users and permissions → Add user* → the `client_email` from the JSON → permission **Owner** (the Indexing API rejects anything less; inspection works with Full too).
4. Setup page → upload the JSON. The property is picked automatically when the account can see exactly one.

## Daily use

1. **Discover URLs** — pulls sitemap + feed. New posts appear automatically on the next run.
2. **Inspect all** (or the *Inspect unchecked* card) — one inspection per URL.
3. Read the cards. **Push unindexed** sends only URLs that are not indexed, not blocked, and not pushed in the last 48 h.
4. After the wait window, the *Re-check pushed* card tells you whether Google actually crawled/indexed them.

## Honest notes

- The Indexing API is officially for `JobPosting` / `BroadcastEvent` pages. It accepts blog URLs (HTTP 200) and often triggers a crawl in practice, but Google does not promise anything for ordinary pages. "Pushed" ≠ "indexed" — the re-inspection is the proof, which is why this console keeps both.
- Quota is counted from this console's own log. Other tools using the same Cloud project / property share it.
- The scheduler only runs while the app is running. On PythonAnywhere's free tier, use a *Scheduled Task* instead, e.g. hourly:
  `cd /home/you/.../dashboard && python3 -c "from indexer.app import create_app; from indexer.service import worker; import time; app=create_app(); worker.start('discover'); time.sleep(30)"`

## Deploy on PythonAnywhere

Clone the repo, point the Web app's *Source code* at `API INDEXING/dashboard`, and set the WSGI file to:

```python
import sys; sys.path.insert(0, "/home/YOU/Free-Stack-Hub.blogspot.com/API INDEXING/dashboard")
from wsgi import app as application
```

Upload the key through the Setup page (it lands in `instance/`, which stays on the server). Reload.

## Layout

```
dashboard/
  run.py, wsgi.py, requirements.txt
  indexer/
    config.py         endpoints, quotas, default settings
    db.py             SQLite schema (urls, inspections, requests_log, jobs, events, properties, settings)
    google_client.py  LiveClient (google-auth + retries + error→hint), DemoClient (same interface)
    discovery.py      sitemap + Blogger feed → urls table; demo data from ../../posts/
    service.py        quota, inspect/push/metadata, bulk Worker, Scheduler, stats, insight cards
    app.py            Flask routes, filters, JSON API
    templates/, static/
  instance/           PRIVATE: service_account.json, indexer.db, secret_key (git-ignored)
```
