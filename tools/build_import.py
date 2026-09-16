#!/usr/bin/env python3
"""
Build one Blogger import file per post.

Layout (one folder per post):

  posts/
    2026-09-16-stop-deleting-pythonanywhere-files/
      post.html        <- the post: header comment with metadata + HTML body
      post.md          <- (optional) markdown/readable version
      images/          <- ONLY this post's images
      import.xml       <- GENERATED: import this one file into Blogger

Usage:
  python3 tools/build_import.py              # build import.xml for every post folder
  python3 tools/build_import.py <folder>     # build just one post (name or path)
  python3 tools/build_import.py --check      # validate all posts, build nothing

post.html header format:

  <!--
  TITLE:  Post title
  LABELS: Label One, Label Two
  PUBLISHED: 2026-09-16          (optional; defaults to the date in the folder name)
  SEARCH DESCRIPTION:
  One or two sentences.
  -->
  <p>body...</p>
  <img src="01-hero.jpg" alt="..."/>     <- bare file name, file lives in ./images/
"""

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "posts"

GITHUB_USER = "rizwanahmedsora9-pixel"
GITHUB_REPO = "Free-Stack-Hub.blogspot.com"
GITHUB_BRANCH = os.environ.get("IMAGE_BRANCH", "main")
BLOG_URL = "https://free-stack-hub.blogspot.com"
AUTHOR_NAME = "Free Stack Hub"

# Public base URL of the repo root. Requires the repo to be PUBLIC.
REPO_CDN = os.environ.get(
    "REPO_CDN", f"https://cdn.jsdelivr.net/gh/{GITHUB_USER}/{GITHUB_REPO}@{GITHUB_BRANCH}/"
)

HEADER_RE = re.compile(r"^\s*<!--(.*?)-->", re.S)
KEY_RE = re.compile(r"^\s*([A-Z][A-Z ]+?)(?:\s*\(.*?\))?\s*:\s*(.*)$")
KEYS = {"TITLE", "LABELS", "SEARCH DESCRIPTION", "PUBLISHED", "IMAGES", "BLOGGER POST"}
IMG_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")', re.I)
FOLDER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9-]+)$")


def parse_header(header: str) -> dict:
    meta, key = {}, None
    for line in header.splitlines():
        if not line.strip() or set(line.strip()) <= {"=", "-"}:
            key = None if not line.strip() else key
            continue
        km = KEY_RE.match(line)
        if km and km.group(1).strip() in KEYS:
            key = km.group(1).strip()
            meta[key] = km.group(2).strip()
        elif key:
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return meta


def load_post(folder: Path) -> dict:
    problems = []
    fm = FOLDER_RE.match(folder.name)
    if not fm:
        problems.append("folder name must be YYYY-MM-DD-slug (lowercase, dashes)")
    html_file = folder / "post.html"
    if not html_file.exists():
        problems.append("post.html missing")
        return {"folder": folder, "problems": problems}

    raw = html_file.read_text(encoding="utf-8")
    m = HEADER_RE.match(raw)
    if not m:
        problems.append("post.html must start with a <!-- ... --> header comment")
        return {"folder": folder, "problems": problems}
    meta, body = parse_header(m.group(1)), raw[m.end():].strip()

    for k in ("TITLE", "LABELS", "SEARCH DESCRIPTION"):
        if not meta.get(k):
            problems.append(f"header is missing {k}:")

    date_str = meta.get("PUBLISHED") or (fm.group(1) if fm else None)
    try:
        when = dt.datetime.fromisoformat(date_str)
    except Exception:
        problems.append(f"bad PUBLISHED date: {date_str!r}")
        when = dt.datetime.now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)

    slug = fm.group(2) if fm else folder.name
    img_dir = folder / "images"
    used, missing = set(), []
    rel = f"posts/{folder.name}/images/"

    def fix(mm):
        src = mm.group(2)
        if re.match(r"^(https?:)?//", src) or src.startswith("data:"):
            return mm.group(0)
        name = src.split("/")[-1]
        used.add(name)
        if not (img_dir / name).exists():
            missing.append(name)
        return mm.group(1) + REPO_CDN + rel + name + mm.group(3)

    body = IMG_SRC_RE.sub(fix, body)
    for n in missing:
        problems.append(f"image used in post but not in images/: {n}")
    unused = sorted(p.name for p in img_dir.glob("*") if p.is_file()) if img_dir.exists() else []
    unused = [n for n in unused if n not in used]
    if "alt=" not in body and used:
        problems.append("images have no alt text")

    return {
        "folder": folder,
        "slug": slug,
        "title": meta.get("TITLE", ""),
        "labels": [l.strip() for l in meta.get("LABELS", "").split(",") if l.strip()],
        "description": meta.get("SEARCH DESCRIPTION", ""),
        "published": when,
        "html": body,
        "images": sorted(used),
        "unused_images": unused,
        "problems": problems,
    }


def feed_xml(p: dict) -> str:
    ts = p["published"].isoformat(timespec="milliseconds")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    labels = "".join(
        f'    <category scheme="http://www.blogger.com/atom/ns#" term="{escape(l, {chr(34): "&quot;"})}"/>\n'
        for l in p["labels"]
    )
    fname = f"/{p['published'].year}/{p['published'].month:02d}/{p['slug']}.html"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:blogger="http://schemas.google.com/blogger/2018">
  <id>tag:blogger.com,1999:blog-freestackhub</id>
  <updated>{now}</updated>
  <title type="text">Free Stack Hub</title>
  <link rel="alternate" type="text/html" href="{BLOG_URL}/"/>
  <author><name>{escape(AUTHOR_NAME)}</name></author>
  <generator>Free-Stack-Hub build_import.py</generator>
  <entry>
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
</feed>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post", nargs="?", help="post folder name or path (default: all)")
    ap.add_argument("--check", action="store_true", help="validate only, don't write")
    a = ap.parse_args()

    if a.post:
        f = Path(a.post)
        folders = [f if f.is_dir() else POSTS_DIR / a.post]
    else:
        folders = sorted(d for d in POSTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))

    bad = 0
    for folder in folders:
        p = load_post(folder)
        print(f"posts/{folder.name}/")
        for pr in p["problems"]:
            print(f"   ERROR   {pr}")
        for n in p.get("unused_images", []):
            print(f"   warning image in images/ not used by post: {n}")
        if p["problems"]:
            bad += 1
            continue
        print(f"   title   {p['title']}")
        print(f"   labels  {', '.join(p['labels'])}")
        print(f"   images  {len(p['images'])}  ->  {REPO_CDN}posts/{folder.name}/images/")
        if not a.check:
            out = folder / "import.xml"
            out.write_text(feed_xml(p), encoding="utf-8")
            print(f"   wrote   posts/{folder.name}/import.xml")
    if bad:
        sys.exit(f"\n{bad} post(s) have errors, fix them and re-run.")
    if not a.check:
        print("\nImport: Blogger > Settings > Manage blog > Import content > pick the post's import.xml")


if __name__ == "__main__":
    main()
