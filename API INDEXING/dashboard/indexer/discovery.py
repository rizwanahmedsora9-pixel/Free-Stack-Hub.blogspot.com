"""Find every URL the blog exposes: Blogger sitemaps + the public JSON feed (posts and pages).

No login needed. The feed gives title / labels / dates / author / thumbnail; the sitemap gives
lastmod and catches anything the feed pagination missed. Demo mode builds the same structure
from the posts/ folders in this repository.
"""

import glob
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests

from .config import BASE_DIR, USER_AGENT
from . import db

SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class DiscoveryError(Exception):
    pass


def _get(url, timeout=25):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r


def blog_url_from_property(site_url: str) -> str:
    """'https://x.blogspot.com/' -> same; 'sc-domain:x.com' -> 'https://x.com/'."""
    s = (site_url or "").strip()
    if s.startswith("sc-domain:"):
        return "https://" + s[len("sc-domain:"):].rstrip("/") + "/"
    if s and not s.endswith("/"):
        s += "/"
    return s


def classify(url: str, blog_url: str) -> str:
    path = urlparse(url).path
    if url.rstrip("/") == blog_url.rstrip("/"):
        return "home"
    if path.startswith("/p/"):
        return "page"
    if re.match(r"^/\d{4}/\d{2}/[^/]+\.html$", path):
        return "post"
    if "/search" in path or "/feeds/" in path:
        return "other"
    return "other"


def strip_html(s: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(html.unescape(s).split())


# ---------------------------------------------------------------- sitemap

def read_sitemap(url: str, seen=None, depth=0) -> list:
    """Return [(loc, lastmod)] following sitemap indexes (Blogger paginates posts per 150)."""
    seen = seen if seen is not None else set()
    if url in seen or depth > 3:
        return []
    seen.add(url)
    try:
        r = _get(url)
    except requests.RequestException as e:
        raise DiscoveryError(f"Could not fetch {url}: {e}") from e
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise DiscoveryError(f"{url} is not valid XML: {e}") from e
    tag = root.tag.split("}")[-1]
    out = []
    if tag == "sitemapindex":
        for sm in root.findall("sm:sitemap", SM_NS):
            loc = sm.findtext("sm:loc", default="", namespaces=SM_NS).strip()
            if loc:
                out.extend(read_sitemap(loc, seen, depth + 1))
    else:
        for u in root.findall("sm:url", SM_NS):
            loc = u.findtext("sm:loc", default="", namespaces=SM_NS).strip()
            lastmod = u.findtext("sm:lastmod", default="", namespaces=SM_NS).strip() or None
            if loc:
                out.append((loc, lastmod))
    return out


# ---------------------------------------------------------------- feed

def _feed_entries(feed_url: str) -> list:
    """Walk the paginated Blogger JSON feed."""
    entries, start, page_size = [], 1, 150
    while True:
        sep = "&" if "?" in feed_url else "?"
        url = f"{feed_url}{sep}alt=json&max-results={page_size}&start-index={start}"
        try:
            data = _get(url).json()
        except (requests.RequestException, ValueError) as e:
            raise DiscoveryError(f"Could not read feed {url}: {e}") from e
        batch = data.get("feed", {}).get("entry", []) or []
        entries.extend(batch)
        total = int(data.get("feed", {}).get("openSearch$totalResults", {}).get("$t", 0) or 0)
        start += page_size
        if not batch or start > total or len(entries) >= 3000:
            break
    return entries


def parse_entry(e: dict) -> dict:
    link = next((l.get("href") for l in e.get("link", []) if l.get("rel") == "alternate"), None)
    # Blogger labels use scheme http://www.blogger.com/atom/ns#; the "kind" category uses schemas.google.com.
    labels = [c.get("term") for c in e.get("category", []) or []
              if c.get("term") and "schemas.google.com" not in (c.get("scheme") or "")
              and "blogger.com/2008/kind" not in c.get("term")]
    content = e.get("content", {}).get("$t") or e.get("summary", {}).get("$t") or ""
    text = strip_html(content)
    thumb = (e.get("media$thumbnail") or {}).get("url")
    if thumb:
        # Blogger hands out 72px thumbnails; ask for a 320px one (both URL styles).
        thumb = re.sub(r"/s72-c(-[a-z]+)?/", "/s320/", thumb)
        thumb = re.sub(r"=s72-c(-[a-z]+)?$", "=s320", thumb)
    return {
        "url": link,
        "title": e.get("title", {}).get("$t", "").strip() or None,
        "labels": labels,
        "published_at": e.get("published", {}).get("$t"),
        "updated_at": e.get("updated", {}).get("$t"),
        "author": ((e.get("author") or [{}])[0].get("name") or {}).get("$t"),
        "thumbnail": thumb,
        "summary": text[:280] or None,
        "word_count": len(text.split()) if text else None,
    }


# ---------------------------------------------------------------- live discovery

def discover_live(blog_url: str, job_id=None) -> dict:
    blog_url = blog_url_from_property(blog_url)
    if not blog_url.startswith("http"):
        raise DiscoveryError("Set the blog / property URL first.")
    started = time.monotonic()
    summary = {"sitemap": 0, "feed_posts": 0, "feed_pages": 0, "new": 0, "updated": 0, "errors": []}

    sitemap_rows = []
    for sm in ("sitemap.xml", "sitemap-pages.xml"):
        try:
            sitemap_rows.extend(read_sitemap(urljoin(blog_url, sm)))
        except DiscoveryError as e:
            summary["errors"].append(str(e))
    summary["sitemap"] = len(sitemap_rows)

    seen = set()
    for loc, lastmod in sitemap_rows:
        seen.add(loc)
        _, created = db.upsert_url(loc, kind=classify(loc, blog_url), in_sitemap=1, sitemap_lastmod=lastmod,
                                   source="sitemap")
        summary["new" if created else "updated"] += 1

    for kind, path in (("post", "feeds/posts/default"), ("page", "feeds/pages/default")):
        try:
            entries = _feed_entries(urljoin(blog_url, path))
        except DiscoveryError as e:
            summary["errors"].append(str(e))
            continue
        for e in entries:
            p = parse_entry(e)
            if not p["url"]:
                continue
            summary["feed_posts" if kind == "post" else "feed_pages"] += 1
            seen.add(p["url"])
            url = p.pop("url")
            _, created = db.upsert_url(url, kind=kind, in_feed=1, source="feed", **p)
            summary["new" if created else "updated"] += 1

    # homepage is a URL too
    _, created = db.upsert_url(blog_url, kind="home", title="Homepage", in_sitemap=0, source="feed")
    summary["new" if created else "updated"] += 1

    duration = int((time.monotonic() - started) * 1000)
    msg = (f"Sitemap {summary['sitemap']} · feed {summary['feed_posts']} posts + {summary['feed_pages']} pages · "
           f"{summary['new']} new, {summary['updated']} updated")
    db.log_request("discover", url=blog_url, ok=not summary["errors"], summary=msg,
                   error="; ".join(summary["errors"]) or None, duration_ms=duration, job_id=job_id)
    db.set_settings({"last_discovery_at": db.now_iso(), "last_discovery_summary": msg})
    return summary


# ---------------------------------------------------------------- demo discovery

def _repo_posts() -> list:
    """Real posts from this repository's posts/ folders, for a believable demo."""
    repo_root = os.path.dirname(os.path.dirname(BASE_DIR))
    out = []
    for folder in sorted(glob.glob(os.path.join(repo_root, "posts", "20*"))):
        slug = os.path.basename(folder)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})-(.+)", slug)
        if not m:
            continue
        yyyy, mm, dd, rest = m.groups()
        title_path = os.path.join(folder, "title.txt")
        title = open(title_path).read().strip() if os.path.exists(title_path) else rest.replace("-", " ").title()
        labels, desc, body_words = [], None, None
        ph = os.path.join(folder, "post.html")
        if os.path.exists(ph):
            src = open(ph, encoding="utf-8", errors="ignore").read()
            lm = re.search(r"LABELS:\s*(.+)", src)
            if lm:
                labels = [l.strip() for l in lm.group(1).split(",") if l.strip()]
            dm = re.search(r"SEARCH DESCRIPTION.*?\n(.+)", src)
            if dm:
                desc = dm.group(1).strip()[:280]
            body_words = len(strip_html(src).split())
        imgs = glob.glob(os.path.join(folder, "images", "*.png")) + glob.glob(os.path.join(folder, "images", "*.jpg"))
        thumb = None
        if imgs:
            name = os.path.basename(sorted(imgs)[0])
            thumb = f"https://cdn.jsdelivr.net/gh/rizwanahmedsora9-pixel/Free-Stack-Hub.blogspot.com@main/posts/{slug}/images/{name}"
        out.append({
            "url": f"https://freestackhub.blogspot.com/{yyyy}/{mm}/{rest}.html",
            "title": title, "labels": labels,
            "published_at": f"{yyyy}-{mm}-{dd}T09:{30 + len(out) * 7 % 29:02d}:00+05:00",
            "updated_at": f"{yyyy}-{mm}-{dd}T12:{10 + len(out) * 5 % 49:02d}:00+05:00",
            "author": "Free Stack Hub", "thumbnail": thumb, "summary": desc, "word_count": body_words,
        })
    return out


_DEMO_EXTRA = [
    ("2026/08/flask-on-pythonanywhere-in-10-minutes.html", "Deploy a Flask App on PythonAnywhere in 10 Minutes", ["Flask", "PythonAnywhere", "Deployment"], 15),
    ("2026/08/github-pages-custom-domain-https.html", "GitHub Pages with a Custom Domain and Free HTTPS", ["GitHub", "DNS", "Web Development"], 17),
    ("2026/08/sqlite-vs-postgres-for-side-projects.html", "SQLite vs Postgres for Side Projects: Pick the Boring One", ["SQLite", "PostgreSQL", "Databases"], 20),
    ("2026/08/blogger-custom-theme-from-scratch.html", "Build a Blogger Theme from Scratch (No Widgets You Don't Need)", ["Blogger", "Themes", "CSS"], 23),
    ("2026/08/termux-python-server-on-android.html", "Run a Python Web Server on Android with Termux", ["Termux", "Android", "Python"], 26),
    ("2026/07/free-tier-hosting-compared-2026.html", "Free-Tier Hosting Compared (2026): Render, Fly, PythonAnywhere, Vercel", ["Hosting", "Free Tier", "Comparison"], 33),
    ("2026/07/jsdelivr-cdn-for-blog-images.html", "Use jsDelivr as a Free CDN for Your Blog Images", ["jsDelivr", "CDN", "Images", "Blogger"], 38),
    ("2026/07/git-for-absolute-beginners.html", "Git for Absolute Beginners: The 12 Commands You Actually Use", ["Git", "GitHub", "Command Line"], 41),
    ("2026/07/core-web-vitals-on-blogger.html", "Fixing Core Web Vitals on a Blogger Blog (Real Numbers)", ["Core Web Vitals", "PageSpeed Insights", "Blogger"], 45),
    ("2026/06/nano-editor-cheatsheet.html", "The Nano Editor Cheat-Sheet You Can Actually Remember", ["Nano", "Command Line", "Linux"], 52),
    ("2026/06/pythonanywhere-scheduled-tasks-guide.html", "PythonAnywhere Scheduled Tasks: Cron Without the Cron", ["PythonAnywhere", "Automation", "Python"], 58),
    ("2026/06/google-indexing-api-for-blogger.html", "Google Indexing API for Blogger: Setup, Quotas and the Honest Truth", ["Indexing", "Google Search Console", "SEO"], 63),
]


def discover_demo(blog_url="https://freestackhub.blogspot.com/", job_id=None) -> dict:
    from .google_client import get_client
    client = get_client("demo")
    now = datetime.now(timezone.utc)
    summary = {"sitemap": 0, "feed_posts": 0, "feed_pages": 0, "new": 0, "updated": 0, "errors": []}

    posts = _repo_posts()
    for path, title, labels, days in _DEMO_EXTRA:
        pub = now - timedelta(days=days, hours=days % 7)
        posts.append({
            "url": blog_url + path, "title": title, "labels": labels,
            "published_at": pub.replace(microsecond=0).isoformat(),
            "updated_at": (pub + timedelta(hours=5)).replace(microsecond=0).isoformat(),
            "author": "Free Stack Hub", "thumbnail": None,
            "summary": f"{title}. A practical, step-by-step guide with screenshots, commands and the mistakes to avoid.",
            "word_count": 900 + (days * 37) % 1400,
        })
    # Realistic story: the newest posts (this repo's) are fresh and not indexed yet; older posts are
    # mostly indexed with a couple of genuine problems mixed in.
    fresh = [p for p in posts if "2026/09/" in p["url"]]
    for i, p in enumerate(fresh):
        client.set_scenario(p["url"], ["discovered", "unknown", "crawled_not_indexed", "discovered"][i % 4])
    older_plan = ["indexed", "indexed", "indexed_desktop", "indexed", "crawled_not_indexed", "indexed",
                  "indexed_no_sitemap", "indexed", "redirect", "indexed", "indexed", "duplicate_canonical"]
    for (path, _, _, _), scenario in zip(_DEMO_EXTRA, older_plan):
        client.set_scenario(blog_url + path, scenario)

    for p in posts:
        url = p.pop("url")
        _, created = db.upsert_url(url, kind="post", in_sitemap=1, in_feed=1, source="demo",
                                   sitemap_lastmod=p.get("updated_at"), **p)
        summary["new" if created else "updated"] += 1
        summary["sitemap"] += 1
        summary["feed_posts"] += 1

    pages = [
        ("p/about.html", "About Free Stack Hub"), ("p/contact.html", "Contact"),
        ("p/privacy-policy.html", "Privacy Policy"), ("p/disclaimer.html", "Disclaimer"),
    ]
    for path, title in pages:
        _, created = db.upsert_url(blog_url + path, kind="page", title=title, labels=[], in_sitemap=1, in_feed=1,
                                   source="demo", author="Free Stack Hub",
                                   published_at=(now - timedelta(days=70)).replace(microsecond=0).isoformat())
        summary["new" if created else "updated"] += 1
        summary["sitemap"] += 1
        summary["feed_pages"] += 1
    client.set_scenario(blog_url + "p/disclaimer.html", "noindex")
    client.set_scenario(blog_url + "p/contact.html", "duplicate_canonical")

    _, created = db.upsert_url(blog_url, kind="home", title="Homepage", source="demo", in_sitemap=0, in_feed=0)
    summary["new" if created else "updated"] += 1

    msg = (f"Sitemap {summary['sitemap']} · feed {summary['feed_posts']} posts + {summary['feed_pages']} pages · "
           f"{summary['new']} new, {summary['updated']} updated (demo data)")
    db.log_request("discover", url=blog_url, ok=True, summary=msg, duration_ms=180, job_id=job_id)
    db.set_settings({"last_discovery_at": db.now_iso(), "last_discovery_summary": msg})
    return summary


def discover(mode: str, blog_url: str, job_id=None) -> dict:
    if mode == "demo":
        return discover_demo(blog_url_from_property(blog_url) or "https://freestackhub.blogspot.com/", job_id)
    return discover_live(blog_url, job_id)
