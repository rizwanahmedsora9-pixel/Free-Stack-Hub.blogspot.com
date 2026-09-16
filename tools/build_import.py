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
      paste.html       <- GENERATED: same body with full image URLs; safe to
                          copy-paste into the Blogger post editor (HTML view)

Usage:
  python3 tools/build_import.py              # build import.xml + paste.html for every post
  python3 tools/build_import.py <folder>     # build just one post (name or path)
  python3 tools/build_import.py --check      # validate all posts, build nothing

Environment:
  IMAGE_REF=<commit-sha>   pin image URLs to a commit instead of a branch. Use this if
                           the blog shows broken images right after publishing: jsDelivr
                           caches a branch snapshot (@main) for about a week, so files
                           pushed minutes ago may not be served yet.
  IMAGE_BRANCH=<branch>    branch to point image URLs at (default: main)

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimize_images import VARIANTS, identify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "posts"

GITHUB_USER = "rizwanahmedsora9-pixel"
GITHUB_REPO = "Free-Stack-Hub.blogspot.com"
# Blogger's numeric blog id, from Settings > Others. It appears in every <id> and
# in the label <category scheme="..."> that Blogger's own export/import format uses.
# Taken from Blogger's real takeout export, so imported labels actually stick.
BLOG_ID = os.environ.get("BLOG_ID", "7497660712599875944")
BLOG_URL = "https://freestackhub.blogspot.com"
AUTHOR_NAME = "Free Stack Hub"

# Image hosting ref. jsDelivr caches a *branch* snapshot (@main) for about a week, so
# images pushed minutes ago can still 404 on the live blog. Pin a commit SHA instead
# when that bites: IMAGE_REF=<full-sha> python3 tools/build_import.py
GITHUB_BRANCH = os.environ.get("IMAGE_BRANCH", "main")
IMAGE_REF = os.environ.get("IMAGE_REF") or GITHUB_BRANCH

# Public base URL of the repo root. Requires the repo to be PUBLIC.
REPO_CDN = os.environ.get(
    "REPO_CDN", f"https://cdn.jsdelivr.net/gh/{GITHUB_USER}/{GITHUB_REPO}@{IMAGE_REF}/"
)

HEADER_RE = re.compile(r"^\s*<!--(.*?)^[ \t]*[-=]*[ \t]*-->[ \t]*$", re.S | re.M)
KEY_RE = re.compile(r"^\s*([A-Z][A-Z ]+?)(?:\s*\(.*?\))?\s*:\s*(.*)$")
KEYS = {"TITLE", "LABELS", "SEARCH DESCRIPTION", "PUBLISHED", "IMAGES", "BLOGGER POST"}
IMG_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")', re.I)
# <img src> and <source srcset> both carry file names the build has to make public
TAG_SRC_RE = re.compile(r'(<img\b[^>]*?(?<![\w-])src=|<source\b[^>]*?(?<![\w-])srcset=)"([^"]+)"', re.I)
# an existing <picture> block (re-build) or a bare <img> (first build). The
# <picture> alternative comes first so the <img> inside it is not matched twice.
PICTURE_OR_IMG_RE = re.compile(r"([ \t]*)(<picture\b[^>]*>.*?</picture\s*>|<img\b[^>]*>)",
                               re.I | re.S)
# <source> order matters: the browser takes the FIRST type it can decode, so the
# smallest format has to come first.
SOURCE_ORDER = ("avif", "webp")
MIME = {"avif": "image/avif", "webp": "image/webp"}
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
# (?<![\w-]) rather than \b: a word boundary also sits between "-" and "s", so
# \bsrc would happily match the "src" inside data-src / data-srcset.
ATTR_RE = lambda name: re.compile(rf'(?<![\w-]){name}\s*=\s*"([^"]*)"', re.I)  # noqa: E731
JUMP_RE = re.compile(r"^[ \t]*<!--[ \t]*more[ \t]*-->[ \t]*$", re.M | re.I)
TAG_RE = re.compile(r"<[^>]+>")
FOLDER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9-]+)$")
# the feed-level <updated> (2-space indent); the entry-level one is 4-space indented
FEED_UPDATED_RE = re.compile(r"^  <updated>.*</updated>$", re.M)


def stamp(feed: str) -> str:
    """The feed's own timestamp, so two builds can be compared ignoring it."""
    m = FEED_UPDATED_RE.search(feed)
    return m.group(0) if m else ""


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


def public_url(name: str, rel: str) -> str:
    """The jsDelivr URL one file inside a post's images/ folder is served from."""
    return f"{REPO_CDN}{rel}{name}"


def is_remote(src: str) -> bool:
    return bool(re.match(r"^(https?:)?//", src)) or src.startswith("data:")


def attr(tag: str, name: str) -> str:
    m = ATTR_RE(name).search(tag)
    return m.group(1) if m else ""


def upgrade_picture(block: str, img_dir: Path, rel: str, hero: str, indent: str,
                    problems: list) -> "tuple[str, set]":
    """Rewrite one <picture>/<img> block into the shape Core Web Vitals want.

    * bare file names  -> full jsDelivr URLs (on <img src> and <source srcset>)
    * the file's real pixel size -> width= and height=, so the browser reserves
      the exact box before a single byte arrives (this is what keeps CLS at 0)
    * .webp/.avif siblings, when tools/optimize_images.py has made them ->
      <source> elements ahead of the .jpg, so every browser gets the smallest
      format it can decode
    * the hero image -> loading=eager + fetchpriority=high (it is the LCP
      element); every later image -> loading=lazy + decoding=async

    Idempotent: a block that is already in this shape comes back byte-identical,
    so re-running the build is safe and git diff only shows real changes.
    Returns (new block, set of file names it references).
    """
    imgs = IMG_TAG_RE.findall(block)
    if not imgs:
        return block, set()
    tag = imgs[0]
    src = attr(tag, "src").split("/")[-1]
    if not src or src.startswith("data:"):
        return block, set()

    referenced = {n for n in re.findall(r'(?<![\w-])src(?:set)?="([^"]+)"', block, re.I)}
    referenced = {n.split("/")[-1] for n in referenced if not is_remote(n)}

    # A remote src we did not generate: only fix up the URLs, change no shape.
    if is_remote(src) or not (img_dir / src).exists():
        fixed = TAG_SRC_RE.sub(lambda m: m.group(0) if is_remote(m.group(2))
                               else f'{m.group(1)}"{public_url(m.group(2).split("/")[-1], rel)}"',
                               block)
        return fixed, referenced

    size = identify(img_dir / src)
    if not size:
        problems.append(f"cannot read the pixel size of {src}, so no width/height could be set")
        return block, referenced
    w, h = size

    is_hero = src == hero
    sources = []
    for ext in SOURCE_ORDER:
        variant = (img_dir / src).with_suffix("." + ext)
        if variant.exists():
            sources.append(f'{indent}  <source srcset="{public_url(variant.name, rel)}" '
                           f'type="{MIME[ext]}"/>')

    style = attr(tag, "style") or "max-width:100%; height:auto;"
    if "height:auto" not in style.replace(" ", ""):
        style = style.rstrip("; ").lstrip("; ") + "; max-width:100%; height:auto;"
    extras = "".join(
        f' {name}="{attr(tag, name)}"'
        for name in ("class", "id", "title") if attr(tag, name)
    )
    priority = ' fetchpriority="high"' if is_hero else ""
    img = (
        f'{indent}  <img alt="{attr(tag, "alt")}" decoding="async"{priority} height="{h}" '
        f'loading="{"eager" if is_hero else "lazy"}" src="{public_url(src, rel)}" '
        f'style="{style}" width="{w}"{extras}/>'
    )
    return (f"{indent}<picture>\n" + "\n".join(sources + [img])
            + f"\n{indent}</picture>", referenced)


def perf_checks(body: str) -> list:
    """Fail the build on the Core Web Vitals mistakes a post could still make.

    These are the audits upgrade_picture() exists to pass; the checks stay here
    so a hand-edited or externally hosted <img> cannot sneak past them.
    """
    problems = []
    for i, tag in enumerate(IMG_TAG_RE.findall(body), 1):
        name = attr(tag, "src").split("/")[-1] or f"image #{i}"
        for need in ("width", "height", "alt"):
            if not attr(tag, need):
                why = ("the browser cannot reserve its box, so the page shifts when it "
                       "lands (CLS)" if need != "alt" else "screen readers get nothing")
                problems.append(f"{name} has no {need}= attribute - {why}")
        loading = attr(tag, "loading").lower()
        if i == 1:
            if loading == "lazy":
                problems.append("the first image is the LCP element - it must not be loading=lazy")
            if attr(tag, "fetchpriority").lower() != "high":
                problems.append("the first image is the LCP element - it needs fetchpriority=high")
        elif loading != "lazy":
            problems.append(f"{name} is below the fold - give it loading=lazy")
    return problems


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
    rel = f"posts/{folder.name}/images/"

    # --- responsive, dimension-correct images (Core Web Vitals) -------------
    # Every bare <img> that points at a file in images/ becomes a <picture>
    # with AVIF + WebP sources and the file's real width/height on the <img>,
    # so the browser can reserve the exact box before a single byte arrives
    # (CLS 0) and pick the smallest format it can decode (LCP / byte weight).
    blocks = list(PICTURE_OR_IMG_RE.finditer(body))
    first_tag = IMG_TAG_RE.search(blocks[0].group(2)) if blocks else None
    hero = attr(first_tag.group(0), "src").split("/")[-1] if first_tag else ""
    assets, local = set(), set()          # assets = referenced AND on disk

    def upgrade(m):
        block, refs = upgrade_picture(m.group(2), img_dir, rel, hero, m.group(1), problems)
        for n in refs:
            local.add(n)
            if (img_dir / n).exists():
                assets.add(n)
                assets.update(v for v in (f"{Path(n).stem}.{e}" for e, _ in VARIANTS)
                              if (img_dir / v).exists())
        return block

    body = PICTURE_OR_IMG_RE.sub(upgrade, body)
    for n in sorted(local):
        if not (img_dir / n).exists():
            problems.append(f"image used in post but not in images/: {n}")
    used = set(assets)
    unused = sorted(p.name for p in img_dir.glob("*") if p.is_file()) if img_dir.exists() else []
    unused = [n for n in unused if n not in used and not n.startswith(".")]
    problems.extend(perf_checks(body))

    # --- jump break (the "Read More" split Blogger renders on the homepage) ---
    teaser, jump_after = body, ""
    marks = list(JUMP_RE.finditer(body))
    if not marks:
        problems.append(
            "no jump break: put a line containing only <!--more--> right after the 2-4 "
            "sentence hook (feature image first)"
        )
    elif len(marks) > 1:
        problems.append(f"{len(marks)} jump break markers found - a post may have exactly one")
    else:
        cut = marks[0]
        teaser, rest = body[: cut.start()], body[cut.end():]
        jump_after = " ".join(TAG_RE.sub(" ", teaser).split())[-90:]
        if not " ".join(TAG_RE.sub(" ", teaser).split()):
            problems.append("nothing before the jump break - the homepage teaser would be empty")
        if not " ".join(TAG_RE.sub(" ", rest).split()):
            problems.append("nothing after the jump break - the marker must not sit at the end")
        imgs = len(IMG_SRC_RE.findall(teaser))
        if imgs != 1:
            problems.append(f"the teaser should hold exactly 1 feature image, found {imgs}")
        hook_txt = " ".join(" ".join(TAG_RE.sub(" ", x).split()) for x in re.findall(r"<p\b[^>]*>(.*?)</p>", teaser, re.S | re.I))
        hook_sents = [x for x in re.split(r"(?<=[.!?])\s+", hook_txt) if x]
        if not 2 <= len(hook_sents) <= 4:
            problems.append(
                f"hook is {len(hook_sents)} sentence(s) before the break; the rule is 2-4 short ones"
            )
        body = teaser.strip() + "\n\n" + rest.strip()

    return {
        "folder": folder,
        "teaser": teaser,
        "jump_after": jump_after,
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
    """Blogger-format Atom feed for ONE post.

    Element order and namespaces follow what Blogger itself writes in a
    Takeout export (see sample export/feed.atom), because the importer is
    pickiest about that shape: labels only survive when the <category> uses
    scheme="tag:blogger.com,1999:blog-<blog id>", and the post's permalink
    comes from <blogger:filename>.
    """
    ts = p["published"].isoformat(timespec="milliseconds")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    q = lambda s: escape(s, {chr(34): "&quot;"})  # noqa: E731
    labels = "".join(
        f'    <category scheme="tag:blogger.com,1999:blog-{BLOG_ID}" term="{q(l)}"/>\n'
        for l in p["labels"]
    )
    fname = f"/{p['published'].year}/{p['published'].month:02d}/{p['slug']}.html"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:blogger="http://schemas.google.com/blogger/2018">
  <id>tag:blogger.com,1999:blog-{BLOG_ID}</id>
  <updated>{now}</updated>
  <title type="text">Free Stack Hub</title>
  <link rel="alternate" type="text/html" href="{BLOG_URL}/"/>
  <author><name>{escape(AUTHOR_NAME)}</name></author>
  <generator>Free-Stack-Hub build_import.py</generator>
  <entry>
    <id>tag:blogger.com,1999:blog-{BLOG_ID}.post-{p['slug']}</id>
    <blogger:type>POST</blogger:type>
    <blogger:status>LIVE</blogger:status>
    <author>
      <name>{escape(AUTHOR_NAME)}</name>
      <blogger:type>BLOGGER</blogger:type>
    </author>
    <title type="text">{escape(p['title'])}</title>
    <content type="html">{escape(p['html'])}</content>
    <blogger:metaDescription>{escape(p['description'])}</blogger:metaDescription>
    <blogger:created>{ts}</blogger:created>
    <published>{ts}</published>
    <updated>{ts}</updated>
    <blogger:location/>
{labels}    <blogger:filename>{fname}</blogger:filename>
    <link/>
    <enclosure/>
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
            (folder / "title.txt").write_text(p["title"] + "\n", encoding="utf-8")
            print(f"   wrote   posts/{folder.name}/title.txt")
            if p.get("jump_after"):
                print(f'   break   paste into the editor, then Insert > Jump break right after:  "...{p["jump_after"]}"')
            out = folder / "import.xml"
            feed = feed_xml(p)
            # <updated> is wall-clock, so a rebuild that changed nothing would
            # still dirty the file. Keep the old stamp unless the post moved.
            old = out.read_text(encoding="utf-8") if out.exists() else ""
            if old and FEED_UPDATED_RE.sub("", old) == FEED_UPDATED_RE.sub("", feed):
                feed = FEED_UPDATED_RE.sub(lambda _: stamp(old), feed, count=1)
                print(f"   kept    posts/{folder.name}/import.xml (unchanged, timestamp not bumped)")
            else:
                print(f"   wrote   posts/{folder.name}/import.xml")
            out.write_text(feed, encoding="utf-8")
            paste = folder / "paste.html"
            paste.write_text(p["html"], encoding="utf-8")
            print(f"   wrote   posts/{folder.name}/paste.html")
    if bad:
        sys.exit(f"\n{bad} post(s) have errors, fix them and re-run.")
    if not a.check:
        print("\nPublish option A (recommended): Blogger > Settings > Manage blog > Import content")
        print("  -> pick the post's import.xml. This is the only route that carries the")
        print("     title, the labels and the search description.")
        print("Publish option B: open the post's paste.html, copy ALL of it into the Blogger editor's HTML view")
        print("  -> body only. You MUST retype the title, set every label by hand and paste the")
        print("     search description, or the post goes out with none of them.")
        print("After publishing: python3 tools/check_published.py   (compares the live blog with posts/)")
        print("WARNING: never paste post.html itself into Blogger - its <img> tags use bare file")
        print("names, so the images would show as broken. Always use import.xml or paste.html.")


if __name__ == "__main__":
    main()
