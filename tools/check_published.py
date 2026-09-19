#!/usr/bin/env python3
"""
Check how the posts in posts/ actually show up on the live blog.

The build step only produces files; Blogger is where things quietly go missing. This
reads the public Blogger feed (no login, no API key) plus the jsDelivr index that serves
the images, and compares both against the post.html header of every post folder.

It catches the failures that are invisible from the repo:
  * a post that was pasted in by hand, so the live TITLE differs from the repo one
  * LABELS that never made it to Blogger (empty /search/label/... pages, no "Filed under")
  * a permalink that does not match the folder slug (Blogger rewrites the URL when the
    title is edited or a same-titled post existed, leaving ..._0745083948.html) - or
    does not match the "PERMALINK:" recorded in post.html, which means the post moved
  * an internal link inside a post that 404s: the href looks fine in post.html, but a
    paste-published post lives at Blogger's title-derived slug, so every link written
    from the folder slug leads to Blogger's not-found page
  * a post that no other published post links to, which is the state Search Console
    reports as "Referring page: None detected"
  * images referenced in the post that the CDN does not serve yet (jsDelivr caches a
    branch snapshot for about a week, so a freshly merged post shows broken images)
  * posts with no Blogger-generated thumbnail, which is why list/homepage cards are text-only

Usage:
  python3 tools/check_published.py                  # all posts
  python3 tools/check_published.py <folder>         # one post
  python3 tools/check_published.py --no-cdn         # skip the image-CDN check
  python3 tools/check_published.py --json-file f    # check against a saved feed JSON

Exit status: 0 = everything matches, 1 = mismatch found, 2 = could not read the blog.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_import import (  # noqa: E402
    BLOG_URL,
    GITHUB_REPO,
    GITHUB_USER,
    IMAGE_REF,
    POSTS_DIR,
    load_post,
)

FEED = f"{BLOG_URL}/feeds/posts/default?alt=json&max-results=150"
CDN_INDEX = f"https://data.jsdelivr.com/v1/package/gh/{GITHUB_USER}/{GITHUB_REPO}@{IMAGE_REF}"
UA = {"User-Agent": "free-stack-hub-check/1.0"}

OK, NOTE, WARN, ERR = "ok", "note", "warn", "ERR "
ICON = {OK: "  ok  ", NOTE: " note ", WARN: " warn ", ERR: " FAIL "}
KIND_SCHEMES = ("http://schemas.google.com/g/2005#kind",)


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def norm_title(s: str) -> str:
    """Titles must compare equal ignoring quotes, case and spacing."""
    s = unicodedata.normalize("NFKD", s or "")
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"[^0-9a-z']+", " ", s.lower())
    return " ".join(s.split())


def live_entries(feed: dict) -> list:
    out = []
    for e in feed.get("feed", {}).get("entry", []) or []:
        title = e.get("title", {}).get("$t", "")
        link = next(
            (l.get("href", "") for l in e.get("link", []) if l.get("rel") == "alternate"), ""
        )
        labels = [
            c.get("term", "")
            for c in e.get("category", []) or []
            if c.get("scheme") not in KIND_SCHEMES and "blogger.com/2008/kind" not in (c.get("term") or "")
        ]
        out.append(
            {
                "title": title,
                "labels": [l for l in labels if l],
                "link": link,
                "html": e.get("content", {}).get("$t", "") or "",
                "published": e.get("published", {}).get("$t", ""),
                "thumbnail": bool(e.get("media$thumbnail")),
            }
        )
    return out


def jsdelivr_index() -> set:
    """File names jsDelivr currently serves for the ref the image URLs use."""
    data = get_json(CDN_INDEX)
    found = set()

    def walk(nodes):
        for n in nodes or []:
            if n.get("type") == "directory":
                walk(n.get("files"))
            elif n.get("name"):
                found.add(n["name"])

    walk(data.get("files"))
    return found


_BLOG_HOST = re.escape(BLOG_URL.split("//", 1)[-1])


def link_path(href: str) -> str:
    """The on-blog path of an internal link, or "" if it points elsewhere.

    Handles what the posts actually contain: absolute blog URLs (the build
    writes them) and root-relative ones. Off-blog links, anchors and mailto
    return "", because a broken external link is not this blog's indexing
    problem.
    """
    h = (href or "").strip()
    if not h or h.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return ""
    if re.match(r"^(https?:)?//", h, re.I):
        m = re.match(rf"^(?:https?:)?//(?:www\.)?{_BLOG_HOST}(/.*)?$", h, re.I)
        if not m:
            return ""
        h = m.group(1) or "/"
    elif not h.startswith("/"):
        return ""
    return h.split("#")[0].split("?")[0]


def internal_links(html: str) -> list:
    """(href, path) for every link in a post that points back at this blog."""
    out, seen = [], set()
    for href in re.findall(r'<a\b[^>]*?\shref="([^"]*)"', html, re.I):
        path = link_path(href)
        if not path or path == "/" or path in seen:
            continue
        seen.add(path)
        out.append((href, path))
    return out


def http_status(url: str, cache: dict) -> int | None:
    """HTTP status of one URL, once per run. None = could not reach it."""
    if url in cache:
        return cache[url]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            cache[url] = r.status
    except urllib.error.HTTPError as exc:
        cache[url] = exc.code
    except Exception:  # noqa: BLE001 - unreachable is a finding, not a crash
        cache[url] = None
    return cache[url]


def match_local(post: dict, entries: list) -> tuple:
    """Find which live entry this folder became. Title first, then shared images."""
    for e in entries:
        if norm_title(e["title"]) == norm_title(post["title"]):
            return e, "title"
    folder = post["folder"].name
    scored = [
        (sum(1 for i in post["images"] if i in e["html"] or f"/{folder}/" in e["html"]), e)
        for e in entries
    ]
    hits = [(s, e) for s, e in scored if s]
    if hits:
        hits.sort(key=lambda x: -x[0])
        return hits[0][1], "images"
    return None, ""


def report(post: dict, entries: list, cdn_files: set, check_links: bool = True, cache: dict | None = None) -> int:
    """Print how one post shows on the blog; return 0 (clean) or 1 (problem)."""
    rc, name = 0, post["folder"].name
    cache = {} if cache is None else cache

    def line(level, msg):
        nonlocal rc
        print(f"   {ICON[level]} {msg}")
        if level == ERR:
            rc = 1
        return rc

    line(NOTE, f'source title  "{post["title"]}"')

    live, how = match_local(post, entries)
    if not live:
        line(ERR, f"not published - no post on the blog has this title or any of its {len(post['images'])} images")
        line(NOTE, "publish it: Blogger > Settings > Manage blog > Import content > import.xml")
        return rc

    line(NOTE, f"live on blog  {live['link']}")

    # 1. title
    if norm_title(live["title"]) != norm_title(post["title"]):
        line(
            ERR,
            f'live title is "{live["title"]}" but posts/{name}/post.html says "{post["title"]}" '
            "- paste.html publishing retypes the title by hand; import.xml carries it",
        )
    else:
        line(OK, "title matches post.html")

    # 2. labels
    want, got = [l.lower() for l in post["labels"]], [l.lower() for l in live["labels"]]
    if not got:
        line(
            ERR,
            f"no labels on the live post (expected: {', '.join(post['labels'])}) "
            "- so /search/label/... pages are empty and nothing links them together",
        )
    elif missing := [l for l in want if l not in got]:
        line(ERR, "live post is missing label(s): " + ", ".join(missing))
    else:
        line(OK, f"labels present ({len(got)})")

    # 3. permalink
    #    The URL the post has to live at. `PERMALINK:` in post.html wins when it
    #    is set (a paste- or API-published post gets Blogger's title-derived
    #    slug, not the folder's); otherwise the folder slug is the expectation.
    slug = post["permalink"]
    recorded = slug != post["slug"]
    path = re.sub(r"^https?://[^/]+", "", live["link"])
    if f"/{slug}.html" in path:
        if recorded:
            line(OK, f"permalink is the recorded PERMALINK: {path}")
        else:
            line(OK, f"permalink matches the folder slug: {path}")
    else:
        suffix = re.search(r"_(\d+)\.html$", path)
        why = (
            "a post with the same title probably existed (deleted or trashed), so Blogger "
            "appended a numeric suffix"
            if suffix
            else "the title was edited in Blogger after publishing"
        )
        if recorded:
            line(
                WARN,
                f'permalink is "{path}" but post.html records PERMALINK: {slug} - the post '
                "moved, so every internal link pointing at the recorded URL now 404s",
            )
        else:
            line(WARN, f'permalink is "{path}", not the folder slug "{slug}" - {why}')
        line(
            NOTE,
            f'accept it: add "PERMALINK: {Path(path).stem}" to posts/{name}/post.html (then fix the '
            "links that use the folder slug) - or set Post settings > Permalink > Custom permalink "
            f'to "{slug}" in the Blogger editor',
        )

    # 4. images
    shown = [i for i in post["images"] if i in live["html"]]
    if shown and len(shown) == len(post["images"]):
        line(OK, f"all {len(shown)} image tag(s) present in the published HTML")
    elif shown:
        line(ERR, f"only {len(shown)}/{len(post['images'])} image(s) present in the published HTML")
    else:
        line(ERR, "the published post has no images at all (only the body was pasted?)")
    if cdn_files is not None:
        absent = [i for i in post["images"] if i not in cdn_files]
        if absent:
            line(
                ERR,
                f"{len(absent)} image(s) not served by the CDN at @{IMAGE_REF} yet: "
                + ", ".join(absent)
                + " - they show as broken on the blog until jsDelivr refreshes "
                "(merge to main, or rebuild with IMAGE_REF=<commit-sha>)",
            )
        else:
            line(OK, f"all {len(shown)} image(s) are live on the CDN at @{IMAGE_REF}")

    # 5. extras Blogger only offers for its own hosted images
    if not live["thumbnail"]:
        line(
            NOTE,
            "no Blogger thumbnail (media$thumbnail) - external CDN images get no preview card, "
            "so the homepage shows text only; upload the hero image into Blogger if you want a card",
        )

    # 6. did the Core Web Vitals markup survive Blogger's importer?
    #    tools/check_perf.py audits what this repo publishes; this audits what
    #    Blogger actually kept, because its importer rewrites post HTML.
    live_html = live["html"]
    if "<picture" in post.get("html", "").lower():
        if "<picture" in live_html.lower():
            line(OK, "the <picture> elements survived Blogger's importer")
        else:
            line(
                WARN,
                "Blogger stripped the <picture> wrappers - the images still show (the <img> "
                "fallback is the JPG), but the post is served without AVIF/WebP, so LCP and "
                "the page weight go back up",
            )
        modern = [i for i in post["images"] if i.endswith((".avif", ".webp"))]
        served = [i for i in modern if i in live_html]
        if modern and served:
            line(OK, f"{len(served)}/{len(modern)} AVIF/WebP variant(s) are in the published HTML")
        elif modern:
            line(WARN, f"none of the {len(modern)} AVIF/WebP variants reached the published HTML")

    imgs = re.findall(r"<img\b[^>]*>", live_html, re.I)
    if imgs:
        bare = [t for t in imgs if not ("width=" in t.lower() and "height=" in t.lower())]
        if bare:
            line(
                WARN,
                f"Blogger dropped width/height from {len(bare)}/{len(imgs)} published <img> - "
                "the page shifts as they land (CLS); re-add them in the editor's HTML view",
            )
        else:
            line(OK, f"all {len(imgs)} published <img> keep their width/height (CLS stays 0)")
        if "fetchpriority" not in imgs[0].lower():
            line(
                WARN,
                "the published hero image lost fetchpriority=high - it is still the LCP element, "
                "just a lower-priority request than it should be",
            )
        else:
            line(OK, "the published hero image is still fetchpriority=high")
        if "loading" in imgs[0].lower() and 'loading="lazy"' in imgs[0].lower():
            line(ERR, "the published hero image is loading=lazy - that is the LCP element, it must be eager")

    # 7. the links this post makes back to the rest of the blog
    #    A dead internal link is invisible from the repo - the href looks right
    #    in post.html - and the post it was meant to point at ends up with no
    #    inbound link at all, which is the "Referring page: None detected" row
    #    in Search Console's URL Inspection.
    links = internal_links(live["html"])
    broken, unverified = [], []
    for _href, path in links:
        code = http_status(BLOG_URL + path, cache) if check_links else None
        if code is None:
            unverified.append(path)
        elif code >= 400:
            broken.append((path, code))
    if not links:
        line(NOTE, "this post links to no other page on the blog (POST_RULES section 12 asks for one)")
    elif broken:
        for path, code in broken:
            line(ERR, f"internal link 404s: {path} (HTTP {code}) - Google follows it and lands on nothing")
        line(NOTE, "point the href at the target's real URL (its PERMALINK:) in post.html, then re-publish the body")
    elif not check_links:
        line(NOTE, f"{len(links)} internal link(s) not checked (--no-links)")
    elif unverified:
        line(WARN, f"could not reach {len(unverified)} internal link(s): " + ", ".join(unverified[:3]))
    else:
        line(OK, f"all {len(links)} internal link(s) resolve")

    # 8. does anything else on the blog link here?
    mine = link_path(live["link"])
    others = [e for e in entries if e is not live]
    inbound = [e for e in others if mine and mine in e["html"]]
    stale = [e for e in others if post["slug"] != post["permalink"] and f"/{post['slug']}.html" in e["html"]]
    if inbound:
        line(OK, f"{len(inbound)} other published post(s) link here")
    elif stale:
        line(
            ERR,
            f"{len(stale)} post(s) link to /{post['slug']}.html, which is not where this post lives "
            f"({mine}) - those links 404",
        )
    else:
        line(
            WARN,
            "no other published post links here - a page nothing links to is the easiest one for "
            "Google to leave out of the index",
        )
        line(NOTE, "add a contextual link from a related post (POST_RULES section 12), then re-publish that body")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("post", nargs="?", help="post folder name or path (default: all)")
    ap.add_argument("--no-cdn", action="store_true", help="skip the jsDelivr image check")
    ap.add_argument("--no-links", action="store_true", help="skip the internal-link (404) check")
    ap.add_argument("--json-file", type=Path, help="read the feed from a saved JSON file instead of the network")
    a = ap.parse_args()

    try:
        feed = json.loads(a.json_file.read_text(encoding="utf-8")) if a.json_file else get_json(FEED)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        sys.exit(f"could not read the blog feed ({FEED}): {exc}\nUse --json-file to check against a saved copy.")

    entries = live_entries(feed)
    n = feed.get("feed", {}).get("openSearch$totalResults", {}).get("$t", len(entries))
    print(f"{BLOG_URL}  ->  {n} published post(s)")

    cdn_files = None
    if not a.no_cdn:
        try:
            cdn_files = jsdelivr_index()
            print(f"CDN @{IMAGE_REF}  ->  serving {len(cdn_files)} file(s) from the repo\n")
        except Exception as exc:  # noqa: BLE001 - the CDN check is best-effort
            print(f"warning: could not read the CDN index ({exc}); skipping image availability\n")

    if a.post:
        f = Path(a.post)
        folders = [f if f.is_dir() else POSTS_DIR / a.post]
    else:
        folders = sorted(d for d in POSTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))

    rc, link_cache = 0, {}
    for folder in folders:
        p = load_post(folder)
        if p["problems"]:
            print(f"posts/{folder.name}/")
            for pr in p["problems"]:
                print(f"   {ICON[ERR]} {pr}")
            rc = 1
            continue
        print(f"posts/{folder.name}/")
        rc |= report(p, entries, cdn_files, check_links=not a.no_links, cache=link_cache)
        print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
