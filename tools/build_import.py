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
  PERMALINK: the-slug-it-lives-at   (optional; see below)
  SEARCH DESCRIPTION:
  One or two sentences. New posts: 150-160 characters, keyword included.
  TARGET KEYWORD: the exact search phrase   (optional; required on new posts)
  -->
  <p>body...</p>
  <img src="01-hero.jpg" alt="..."/>     <- bare file name, file lives in ./images/

PERMALINK is the slug the post is published under. Leave it out and the folder
name's slug is used, which is what <blogger:filename> writes - so importing the
post's import.xml puts it at that URL. Set it when Blogger generated a different
permalink (a post that was pasted or pushed through the API instead of imported:
Blogger builds the slug from the title). Without it the repo keeps claiming a
URL the post does not live at, and every internal link written from the folder
slug 404s. Accepts a bare slug, /2026/09/slug.html or a full URL.
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
KEYS = {"TITLE", "LABELS", "SEARCH DESCRIPTION", "PUBLISHED", "PERMALINK", "IMAGES", "BLOGGER POST", "TARGET KEYWORD"}
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

# --- section 14: the SEO rules every post must pass ---------------------------
# Posts with TARGET KEYWORD: set (every new post) fail the build on any of
# these. The five Sep 16-19 posts predate section 14, so the judgement rules
# (title/description length, link counts, word count) print as warnings there:
# visible, but they do not fail the build.
TITLE_MIN, TITLE_MAX = 50, 60
DESC_MIN, DESC_MAX = 150, 160
MIN_INTERNAL_LINKS = 2
MIN_OUTBOUND_LINKS = 1
MIN_PROSE_WORDS = 1200
MIN_ALT_CHARS = 15
GENERIC_ANCHORS = {
    "click here", "clickhere", "here", "this post", "this article",
    "read more", "readmore", "link", "this link", "more here",
}
TEST_TITLE_RE = re.compile(r"\b(tests?|drafts?)\b", re.I)
PLACEHOLDER_TITLE_RE = re.compile(r"your post title here|untitled|lorem", re.I)
GENERIC_ALT_RE = re.compile(r"^(image|img|picture|photo|screenshot|figure)\s*\d*$", re.I)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.S | re.I)
LINK_RE = re.compile(r"<a\b([^>]*)>(.*?)</a\s*>", re.S | re.I)
HREF_RE = re.compile(r"\shref=\"([^\"]*)\"", re.I)
CAPTION_RE = re.compile(r"font-size:\s*13px", re.I)
BLOG_HOST = BLOG_URL.split("//", 1)[-1].lower()


def stamp(feed: str) -> str:
    """The feed's own timestamp, so two builds can be compared ignoring it."""
    m = FEED_UPDATED_RE.search(feed)
    return m.group(0) if m else ""


def permalink_slug(value: str, fallback: str) -> str:
    """The slug a post actually lives at on the blog.

    `PERMALINK:` may be written as a bare slug, as a path (/2026/09/slug.html)
    or as a full URL; only the last path segment matters, because that is the
    part Blogger's <blogger:filename> carries. Anything unparsable, or a missing
    key, falls back to the folder name's slug - the pre-existing behaviour.
    """
    seg = (value or "").strip().split("#")[0].split("?")[0].rstrip("/")
    seg = seg.rsplit("/", 1)[-1]
    if seg.lower().endswith(".html"):
        seg = seg[:-5]
    return seg or fallback


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


HERO_MAX_BYTES = 80_000        # 80 KB max for hero JPG
HERO_MAX_WIDTH = 1200          # 1200px max width for hero image
HERO_AVIF_MAX_BYTES = 30_000   # 30 KB max for hero AVIF variant


def perf_checks(body: str, img_dir: Path = None, hero: str = "") -> list:
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
            if img_dir and hero:
                hero_path = img_dir / hero
                if hero_path.exists():
                    sz = hero_path.stat().st_size
                    if sz > HERO_MAX_BYTES:
                        problems.append(
                            f"hero image {hero} is {sz / 1024:.1f} KB (exceeds {HERO_MAX_BYTES / 1024:.0f} KB limit). "
                            f"Compress it to keep mobile LCP fast."
                        )
                    dims = identify(hero_path)
                    if dims and dims[0] > HERO_MAX_WIDTH:
                        problems.append(
                            f"hero image {hero} width is {dims[0]}px (exceeds {HERO_MAX_WIDTH}px limit). "
                            f"Resize it to max 1200px width."
                        )
                    avif_variant = hero_path.with_suffix(".avif")
                    if avif_variant.exists() and avif_variant.stat().st_size > HERO_AVIF_MAX_BYTES:
                        problems.append(
                            f"hero AVIF variant {avif_variant.name} is {avif_variant.stat().st_size / 1024:.1f} KB "
                            f"(exceeds {HERO_AVIF_MAX_BYTES / 1024:.0f} KB limit)."
                        )
        elif loading != "lazy":
            problems.append(f"{name} is below the fold - give it loading=lazy")
    return problems


def _text_of(html: str) -> str:
    """Visible text of an HTML fragment, whitespace collapsed."""
    return " ".join(TAG_RE.sub(" ", html).split())


def prose_words(body: str) -> int:
    """Words of original prose: headings, paragraphs, lists, quotes.

    Code blocks (<pre>), caption lines and comments do not count (section 14
    rule 7: code, alt text and captions are not prose).
    """
    no_code = re.sub(r"<pre\b.*?</pre\s*>", " ", body, flags=re.S | re.I)
    no_cap = re.sub(r"<div\b[^>]*font-size:\s*13px[^>]*>.*?</div\s*>", " ",
                    no_code, flags=re.S | re.I)
    return len(_text_of(HTML_COMMENT_RE.sub(" ", no_cap)).split())


def links_in(body: str) -> list:
    """(href, anchor text, position) for every <a> in the body.

    Comments are stripped first, so a commented-out example link (like the
    ones in posts/_template/) never counts toward the rules 3-4 minimums.
    """
    clean = HTML_COMMENT_RE.sub(" ", body)
    out = []
    for m in LINK_RE.finditer(clean):
        hm = HREF_RE.search(m.group(1) or "")
        if not hm:
            continue
        out.append((hm.group(1).strip(), _text_of(m.group(2)), m.start()))
    return out


def href_kind(href: str) -> str:
    """'internal' (points at this blog), 'outbound', or '' (anchor/mailto)."""
    h = (href or "").strip()
    if not h or h.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return ""
    if re.match(r"^(https?:)?//", h, re.I):
        host = re.sub(r"^(https?:)?//", "", h, flags=re.I).split("/")[0].lower()
        if host.startswith("www."):
            host = host[4:]
        return "internal" if host == BLOG_HOST else "outbound"
    return "internal" if h.startswith("/") else ""


def seo_checks(meta: dict, body: str, teaser: str) -> "tuple[list, list]":
    """Section 14 SEO rules. Returns (errors, warnings).

    Errors fail the build. New posts (TARGET KEYWORD: set) get errors for
    every automatable rule; the five Sep 16-19 posts predate section 14, so
    the judgement rules (title/description length, link counts, word count)
    are warnings there. The never-rules - no test/placeholder titles, no
    <h1> in the body, no skipped heading levels, no placeholder alt text, a
    caption under every screenshot - are errors for every post: no live post
    trips them, and no new one may introduce them.
    """
    errors, warnings = [], []
    title = meta.get("TITLE", "")
    desc = meta.get("SEARCH DESCRIPTION", "")
    kw = meta.get("TARGET KEYWORD", "").strip()
    is_new = bool(kw)
    clean = HTML_COMMENT_RE.sub(" ", body)

    def legacy(msg: str):
        (errors if is_new else warnings).append(msg)

    # rule 1: title length, keyword in the first half
    if title:
        n = len(title)
        if not TITLE_MIN <= n <= TITLE_MAX:
            legacy(f"TITLE: is {n} characters, the rule is {TITLE_MIN}-{TITLE_MAX} "
                   f"(section 14 rule 1) - cut the subtitle before publishing, "
                   f"do not trim it in your head")
        if TEST_TITLE_RE.search(title) or PLACEHOLDER_TITLE_RE.search(title):
            errors.append(f"TITLE: {title!r} looks like a test/placeholder title - "
                          f"it must never be published (section 14 rule 8)")
        if kw:
            pos = title.lower().find(kw.lower())
            if pos < 0:
                errors.append(f"TITLE: does not contain the target keyword {kw!r} "
                              f"(section 14 rule 1)")
            elif pos > n // 2:
                errors.append(f"TITLE: the target keyword starts at character {pos + 1} "
                              f"of {n} - put it in the first half (section 14 rule 1)")

    # rule 2: search description length, keyword, this-post specificity
    if desc:
        n = len(desc)
        if not DESC_MIN <= n <= DESC_MAX:
            legacy(f"SEARCH DESCRIPTION: is {n} characters, the rule is "
                   f"{DESC_MIN}-{DESC_MAX} (section 14 rule 2)")
        if kw and kw.lower() not in desc.lower():
            errors.append("SEARCH DESCRIPTION: does not contain the target keyword "
                          f"{kw!r} (section 14 rule 2)")
        elif kw and desc.lower().count(kw.lower()) > 1:
            warnings.append("SEARCH DESCRIPTION: repeats the target keyword - "
                            "once, naturally (section 14 rule 2)")

    # rule 1 (keyword placement): the keyword in exactly one <h2> and in the hook
    if kw:
        h2s = [m for m in HEADING_RE.finditer(clean) if m.group(1) == "2"]
        hits = [m for m in h2s if kw.lower() in _text_of(m.group(2)).lower()]
        if not hits:
            errors.append(f"no <h2> contains the target keyword {kw!r} - exactly one "
                          f"must (section 14 rule 1)")
        elif len(hits) > 1:
            errors.append(f"{len(hits)} <h2> headings contain the target keyword - "
                          f"exactly one may (section 14 rule 1)")
        hook = _text_of(" ".join(re.findall(r"<p\b[^>]*>(.*?)</p>", teaser, re.S | re.I)))
        if kw.lower() not in hook.lower():
            errors.append("the hook (the teaser before the jump break) does not contain "
                          "the target keyword (section 14 rule 1)")

    # rule 5: headings - <h2> sections, <h3> only under an <h2>, no <h1> in the body
    levels = [(int(m.group(1)), _text_of(m.group(2))[:60]) for m in HEADING_RE.finditer(clean)]
    if levels and not any(lv == 2 for lv, _ in levels):
        errors.append("no <h2> in the body - main sections use <h2> (section 14 rule 5)")
    if any(lv == 1 for lv, _ in levels):
        errors.append("the body contains an <h1> - the post title is the page's only "
                      "<h1> (section 14 rule 5)")
    seen_h2, prev = False, None
    for lv, txt in levels:
        if lv == 2:
            seen_h2 = True
        if lv == 3 and not seen_h2:
            errors.append(f"<h3> {txt!r} appears before any <h2> - never skip a level "
                          f"(section 14 rule 5)")
            break
        if prev is not None and lv - prev > 1:
            errors.append(f"heading levels skip: h{prev}->h{lv} ({txt!r}) "
                          f"(section 14 rule 5)")
            break
        prev = lv

    # rules 3-4: internal and outbound links
    links = links_in(body)
    internal = [(h, a, p) for h, a, p in links if href_kind(h) == "internal"]
    outbound = [(h, a, p) for h, a, p in links if href_kind(h) == "outbound"]
    uniq_internal = {h.split("#")[0].split("?")[0].rstrip("/") for h, _, _ in internal}
    uniq_internal.discard("")
    if len(uniq_internal) < MIN_INTERNAL_LINKS:
        legacy(f"only {len(uniq_internal)} internal link(s) to other posts, the rule is "
               f"at least {MIN_INTERNAL_LINKS} with descriptive anchors "
               f"(section 14 rule 3)")
    for h, a, _ in internal:
        norm = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", a.lower())).strip()
        if not a.strip():
            errors.append(f"internal link to {h} has no anchor text - describe the "
                          f"target post (section 14 rule 3)")
        elif norm in GENERIC_ANCHORS or a.strip().lower().startswith(("http://", "https://", "www.")):
            errors.append(f"internal link uses generic anchor text {a.strip()!r} - "
                          f"describe the target post (section 14 rule 3)")
    h2_pos = [m.start() for m in re.finditer(r"<h2\b", clean, re.I)]
    if internal and h2_pos and all(p > h2_pos[-1] for _, _, p in internal):
        legacy("every internal link sits after the last <h2> - link where the topic "
               "comes up in the body, not in a dump at the end (section 14 rule 3)")
    if not outbound:
        legacy(f"no outbound link to an official/primary source (docs, GitHub repo, "
               f"wiki) - at least {MIN_OUTBOUND_LINKS} is required where the post names "
               f"a tool, language or platform (section 14 rule 4)")

    # rule 6: descriptive alt text, one caption line per screenshot
    for tag in IMG_TAG_RE.findall(clean):
        src = attr(tag, "src").split("/")[-1]
        alt = attr(tag, "alt").strip()
        if not alt:
            continue  # perf_checks already fails a missing alt
        if (len(alt) < MIN_ALT_CHARS or GENERIC_ALT_RE.match(alt) or alt == src
                or alt.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"))
                or "REPLACE_ME" in alt):
            errors.append(f"{src or 'an image'} has a placeholder alt ({alt!r}) - "
                          f"describe what the screenshot actually shows "
                          f"(section 14 rule 6)")
    imgs = list(IMG_TAG_RE.finditer(clean))
    if imgs:
        caps = len(CAPTION_RE.findall(clean))
        if caps < len(imgs):
            errors.append(f"{len(imgs)} images but only {caps} caption lines - every "
                          f"screenshot needs its one-line caption (section 14 rule 6)")
        else:
            for i, m in enumerate(imgs):
                nxt = imgs[i + 1].start() if i + 1 < len(imgs) else len(clean)
                if not CAPTION_RE.search(clean[m.end():nxt][:2000]):
                    src = attr(m.group(0), "src").split("/")[-1]
                    errors.append(f"{src or f'image #{i + 1}'} has no caption line after "
                                  f"it - say what the reader is seeing (section 14 rule 6)")

    # rule 7: word count floor (prose only)
    n_words = prose_words(clean)
    if n_words < MIN_PROSE_WORDS:
        legacy(f"{n_words} words of prose, the floor for a tutorial/guide is "
               f"{MIN_PROSE_WORDS} (code, alt text and captions do not count) - if the "
               f"topic is naturally shorter it is the wrong topic for a full post "
               f"(section 14 rule 7)")

    # rule 8: no placeholders in the body, ever
    if "REPLACE_ME" in clean:
        errors.append("the body still contains REPLACE_ME - the post is not finished "
                      "(section 14 rule 8)")
    if re.search(r"lorem ipsum", clean, re.I):
        errors.append("the body contains lorem ipsum placeholder text "
                      "(section 14 rule 8)")

    return errors, warnings


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
    permalink = permalink_slug(meta.get("PERMALINK", ""), slug)
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
    problems.extend(perf_checks(body, img_dir, hero))

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

    # --- section 14: the SEO rules every post must pass ----------------------
    seo_errors, seo_warnings = seo_checks(meta, body, teaser)
    problems.extend(seo_errors)

    return {
        "folder": folder,
        "teaser": teaser,
        "jump_after": jump_after,
        "slug": slug,
        "permalink": permalink,
        "title": meta.get("TITLE", ""),
        "labels": [l.strip() for l in meta.get("LABELS", "").split(",") if l.strip()],
        "description": meta.get("SEARCH DESCRIPTION", ""),
        "target_keyword": meta.get("TARGET KEYWORD", "").strip(),
        "published": when,
        "html": body,
        "images": sorted(used),
        "unused_images": unused,
        "problems": problems,
        "warnings": seo_warnings,
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
    fname = f"/{p['published'].year}/{p['published'].month:02d}/{p['permalink']}.html"
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
        for w in p.get("warnings", []):
            print(f"   warning {w}")
        for n in p.get("unused_images", []):
            print(f"   warning image in images/ not used by post: {n}")
        if p["problems"]:
            bad += 1
            continue
        print(f"   title   {p['title']}")
        print(f"   labels  {', '.join(p['labels'])}")
        if p["permalink"] != p["slug"]:
            print(
                f"   permalink {p['permalink']}  (from PERMALINK:; folder slug is "
                f"{p['slug']} - links must use the permalink, it is the URL that exists)"
            )
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
