#!/usr/bin/env python3
"""
Build a Blogger import file (Atom XML) from the posts in post/.

Usage
-----
  python3 tools/build_import.py            # new (not-yet-imported) posts -> import/blogger-import.xml
  python3 tools/build_import.py --all      # every post, regardless of imported.json
  python3 tools/build_import.py --done     # mark everything in the current import file as imported
  python3 tools/build_import.py --list     # show post status (imported / pending)

How a post is defined
---------------------
Every file  post/<slug>-blogger.html  is one post. Its header comment carries the
metadata (this is the format already used in the repo):

  TITLE:  My post title
  LABELS: Label One, Label Two
  SEARCH DESCRIPTION (anything...):
  One or more lines of description, ended by a blank line or the next KEY:.
  PUBLISHED: 2026-09-16            (optional, ISO date; defaults to file mtime)

Images in the post body are written with just the file name
(<img src="01-something.jpg">) and live in images/. This script rewrites them to
public CDN URLs so Blogger shows them straight after import.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
POST_DIR = ROOT / "post"
IMG_DIR = ROOT / "images"
OUT_DIR = ROOT / "import"
OUT_FILE = OUT_DIR / "blogger-import.xml"
STATE_FILE = OUT_DIR / "imported.json"

# ---- configuration -----------------------------------------------------------
GITHUB_USER = "rizwanahmedsora9-pixel"
GITHUB_REPO = "Free-Stack-Hub.blogspot.com"
GITHUB_BRANCH = "main"
BLOG_URL = "https://free-stack-hub.blogspot.com"
AUTHOR_NAME = "Free Stack Hub"

# Public URL prefix for images/. Options:
#   jsDelivr CDN (works as soon as the repo is public, cached worldwide):
IMAGE_BASE = f"https://cdn.jsdelivr.net/gh/{GITHUB_USER}/{GITHUB_REPO}@{GITHUB_BRANCH}/images/"
#   GitHub Pages (needs Pages enabled on main / root in repo settings):
#IMAGE_BASE = f"https://{GITHUB_USER.lower()}.github.io/{GITHUB_REPO}/images/"
#   Raw GitHub:
#IMAGE_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/images/"
IMAGE_BASE = os.environ.get("IMAGE_BASE", IMAGE_BASE)
# ------------------------------------------------------------------------------

HEADER_RE = re.compile(r"^\s*<!--(.*?)-->", re.S)
KEY_RE = re.compile(r"^\s*([A-Z][A-Z ]+?)(?:\s*\(.*?\))?\s*:\s*(.*)$")
IMG_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")', re.I)


def parse_post(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    m = HEADER_RE.match(raw)
    if not m:
        sys.exit(f"{path.name}: missing header comment with TITLE/LABELS")
    header, body = m.group(1), raw[m.end():].strip()

    meta, key = {}, None
    for line in header.splitlines():
        if set(line.strip()) <= {"=", "-"}:
            continue
        km = KEY_RE.match(line)
        if km and km.group(1).strip() in ("TITLE", "LABELS", "SEARCH DESCRIPTION", "PUBLISHED", "IMAGES", "BLOGGER POST"):
            key = km.group(1).strip()
            meta[key] = km.group(2).strip()
        elif key and line.strip():
            meta[key] = (meta[key] + " " + line.strip()).strip()
        elif not line.strip():
            key = None

    if "TITLE" not in meta:
        sys.exit(f"{path.name}: header has no TITLE:")

    slug = path.name[: -len("-blogger.html")] if path.name.endswith("-blogger.html") else path.stem
    published = meta.get("PUBLISHED")
    if published:
        when = dt.datetime.fromisoformat(published)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
    else:
        when = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)

    # rewrite bare image file names -> public URLs, and check they exist
    missing = []

    def fix(mm):
        src = mm.group(2)
        if re.match(r"^(https?:)?//", src) or src.startswith("data:"):
            return mm.group(0)
        name = src.split("/")[-1]
        if not (IMG_DIR / name).exists():
            missing.append(name)
        return mm.group(1) + IMAGE_BASE + name + mm.group(3)

    body = IMG_SRC_RE.sub(fix, body)
    if missing:
        print(f"  WARNING {path.name}: images not found in images/: {', '.join(missing)}")

    labels = [l.strip() for l in meta.get("LABELS", "").split(",") if l.strip()]
    return {
        "slug": slug,
        "title": meta["TITLE"],
        "labels": labels,
        "description": meta.get("SEARCH DESCRIPTION", ""),
        "published": when,
        "html": body,
        "file": path.name,
    }


def entry_xml(p: dict) -> str:
    ts = p["published"].isoformat(timespec="milliseconds")
    labels = "".join(
        f'    <category scheme="http://www.blogger.com/atom/ns#" term="{escape(l, {chr(34): "&quot;"})}"/>\n'
        for l in p["labels"]
    )
    fname = f"/{p['published'].year}/{p['published'].month:02d}/{p['slug']}.html"
    return f"""  <entry>
    <id>tag:blogger.com,1999:blog-freestackhub.post-{p['slug']}</id>
    <published>{ts}</published>
    <updated>{ts}</updated>
    <category scheme="http://schemas.google.com/g/2005#kind" term="http://schemas.google.com/blogger/2008/kind#post"/>
{labels}    <title type="text">{escape(p['title'])}</title>
    <content type="html">{escape(p['html'])}</content>
    <author>
      <name>{escape(AUTHOR_NAME)}</name>
    </author>
    <blogger:type>POST</blogger:type>
    <blogger:status>LIVE</blogger:status>
    <blogger:created>{ts}</blogger:created>
    <blogger:filename>{fname}</blogger:filename>
    <blogger:metaDescription>{escape(p['description'])}</blogger:metaDescription>
  </entry>
"""


def feed_xml(posts: list) -> str:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:blogger="http://schemas.google.com/blogger/2018">\n'
        "  <id>tag:blogger.com,1999:blog-freestackhub</id>\n"
        f"  <updated>{now}</updated>\n"
        "  <title type=\"text\">Free Stack Hub</title>\n"
        f'  <link rel="alternate" type="text/html" href="{BLOG_URL}/"/>\n'
        f"  <author><name>{escape(AUTHOR_NAME)}</name></author>\n"
        "  <generator>Free-Stack-Hub build_import.py</generator>\n"
        + "".join(entry_xml(p) for p in posts)
        + "</feed>\n"
    )


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"imported": {}, "pending": []}


def save_state(state: dict):
    OUT_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="include already-imported posts too")
    ap.add_argument("--done", action="store_true", help="mark posts in the last build as imported")
    ap.add_argument("--list", action="store_true", help="show status of every post")
    a = ap.parse_args()

    state = load_state()
    files = sorted(POST_DIR.glob("*-blogger.html"))
    posts = [parse_post(f) for f in files]

    if a.list:
        for p in posts:
            st = "imported " + state["imported"][p["slug"]][:10] if p["slug"] in state["imported"] else "PENDING"
            print(f"  [{st:>19}] {p['slug']}  ({len(p['labels'])} labels, {p['html'].count('<img')} images)")
        return

    if a.done:
        today = dt.date.today().isoformat()
        for slug in state["pending"]:
            state["imported"][slug] = today
        n = len(state["pending"])
        state["pending"] = []
        save_state(state)
        print(f"Marked {n} post(s) as imported.")
        return

    selected = posts if a.all else [p for p in posts if p["slug"] not in state["imported"]]
    if not selected:
        print("Nothing new to import. (use --all to rebuild everything)")
        return

    OUT_DIR.mkdir(exist_ok=True)
    OUT_FILE.write_text(feed_xml(selected), encoding="utf-8")
    state["pending"] = [p["slug"] for p in selected]
    save_state(state)

    print(f"Wrote {OUT_FILE.relative_to(ROOT)} with {len(selected)} post(s):")
    for p in selected:
        print(f"  - {p['title']}  [{', '.join(p['labels'])}]  {p['html'].count('<img')} images")
    print(f"\nImages are served from: {IMAGE_BASE}")
    print("Next: Blogger > Settings > Manage blog > Import content > choose this file.")
    print("After a successful import run:  python3 tools/build_import.py --done")


if __name__ == "__main__":
    main()
