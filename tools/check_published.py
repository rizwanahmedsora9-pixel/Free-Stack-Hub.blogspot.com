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
    title is edited or a same-titled post existed, leaving ..._0745083948.html)
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


def report(post: dict, entries: list, cdn_files: set) -> int:
    """Print how one post shows on the blog; return 0 (clean) or 1 (problem)."""
    rc, name = 0, post["folder"].name

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
    slug = post["slug"]
    path = re.sub(r"^https?://[^/]+", "", live["link"])
    if f"/{slug}.html" in path:
        line(OK, f"permalink matches the folder slug: {path}")
    else:
        suffix = re.search(r"_(\d+)\.html$", path)
        why = (
            "a post with the same title probably existed (deleted or trashed), so Blogger "
            "appended a numeric suffix"
            if suffix
            else "the title was edited in Blogger after publishing"
        )
        line(WARN, f'permalink is "{path}", not the folder slug "{slug}" - {why}')
        line(NOTE, "fix in the Blogger editor: Post settings > Permalink > Custom permalink")

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
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("post", nargs="?", help="post folder name or path (default: all)")
    ap.add_argument("--no-cdn", action="store_true", help="skip the jsDelivr image check")
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

    rc = 0
    for folder in folders:
        p = load_post(folder)
        if p["problems"]:
            print(f"posts/{folder.name}/")
            for pr in p["problems"]:
                print(f"   {ICON[ERR]} {pr}")
            rc = 1
            continue
        print(f"posts/{folder.name}/")
        rc |= report(p, entries, cdn_files)
        print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
