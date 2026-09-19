#!/usr/bin/env python3
"""
Write theme/preview.html - a static mock of what the Blogger theme in
theme/freestackhub-theme.xml renders.

Blogger is the only place the real theme runs, so this file exists to answer
"what will my blog look like?" *before* uploading anything: it reuses the exact
skin (CSS) from the theme file, the exact card markup the Blog1 widget emits, the
theme's own <header>, search combo box and visitor strip (parsed out of their
marked blocks, so a change there cannot be missed here), the suggestion script
verbatim, and the real title / labels / hook / body of a post from posts/.

Usage:
  python3 tools/build_theme_preview.py                     # newest post folder
  python3 tools/build_theme_preview.py <folder>            # one post
  python3 tools/build_theme_preview.py --open              # also serve instructions

Generated - do not hand-edit; edit theme/freestackhub-theme.xml or the post and
run this again.
"""

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_import import (  # noqa: E402
    FOLDER_RE, GITHUB_REPO, GITHUB_USER, HEADER_RE as POST_HEADER_RE, IMAGE_REF,
    POSTS_DIR, load_post, parse_header, permalink_slug,
)

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "theme" / "freestackhub-theme.xml"
OUT = ROOT / "theme" / "preview.html"

# Kept in step with theme/freestackhub-theme.xml by tools/check_perf.py, which
# fails if the two ever disagree.
SITE_DESCRIPTION = (
    "Free PDFs, self-made apps and clean config files, plus step-by-step guides "
    "for Python, Git and free-tier hosting. No cracked software, no clutter."
)
CARD_IMG_W, CARD_IMG_H = 640, 360        # the 16:9 box the skin renders cards into

TAG_RE = re.compile(r"<[^>]+>")
MORE_RE = re.compile(r"<!--\s*more\s*-->", re.I)
HEADER_RE = re.compile(r"<header class='header'.*?</header>", re.S)
VISIT_RE = re.compile(r"<!-- visit-strip:start -->(.*?)<!-- visit-strip:end -->", re.S)
SEARCH_RE = re.compile(r"<!-- search-bar:start -->(.*?)<!-- search-bar:end -->", re.S)
SEARCH_JS_RE = re.compile(r"<!-- search-suggest:start -->(.*?)<!-- search-suggest:end -->", re.S)
BLOG_TITLE = "Free Stack Hub"


def header_html(theme_xml: str) -> str:
    """The theme's own <header> block, with Blogger's tags resolved by hand.

    The preview used to carry a second, hand-written header, and that is exactly
    how the mock (two text glyphs) and the theme (four SVG icons, a .brand
    wrapper, the corner-pinned social row) drifted apart. Parsing the block out
    of theme/freestackhub-theme.xml means a header change shows up in the preview
    on the next run, with nothing to remember to copy.
    """
    m = HEADER_RE.search(theme_xml)
    if not m:
        sys.exit("ERR  could not find <header class='header'> in theme/freestackhub-theme.xml")
    head = m.group(0)
    # <b:if cond='data:blog.description'>...<b:else/>FALLBACK</b:if> -> the
    # fallback, because on this blog the description setting is off (see
    # POST_RULES.md section 9), which is what Blogger renders today.
    head = re.sub(r"<b:if\b[^>]*>.*?<b:else/>(.*?)</b:if>", r"\1", head, flags=re.S)
    head = head.replace("expr:href='data:blog.homepageUrl'", "href='#'")
    head = head.replace("<data:blog.title/>", BLOG_TITLE)
    head = re.sub(r"<data:[^>]*/>", "", head)
    return head


def visit_strip_html(theme_xml: str) -> str:
    """The theme's live visitor strip, with sample values stood in for the
    ones the real page fills in by fetch.

    Same reason as header_html: parsing the marked block out of the theme
    means a strip change shows up in the mock on the next run. On Blogger the
    b:if keeps this strip on the home page only; here it sits in section 1 -
    the post-page section below correctly does not show it.
    """
    m = VISIT_RE.search(theme_xml)
    if not m:
        sys.exit("ERR  could not find the visit-strip markers in theme/freestackhub-theme.xml")
    strip = m.group(1)
    # stand-ins for what the after-load fetches write in: a plausible count,
    # a flag (&#127477;&#127472; = the PK regional-indicator pair), country,
    # device + the is-mobile class the script would have added
    strip = strip.replace("id='visitTotal'>&#8212;", "id='visitTotal'>12,482")
    strip = strip.replace("id='visitFlag'></span>", "id='visitFlag'>&#127479;&#127472; </span>")
    strip = strip.replace("id='visitCountry'>&#8212;", "id='visitCountry'>Pakistan")
    strip = strip.replace("class='visit-cell vc-device'", "class='visit-cell vc-device is-mobile'")
    strip = strip.replace("id='visitDevice'>&#8212;", "id='visitDevice'>Mobile")
    strip = strip.replace("id='visitTime'>&#8212;", "id='visitTime'>9:41 PM")
    return strip


def search_html(theme_xml: str) -> str:
    """The theme's search combo box, with its one Blogger expression resolved.

    Parsed out of the marked block in theme/freestackhub-theme.xml for the same
    reason as the header and the visitor strip: the mock used to carry a second,
    hand-written search form, and a hand-written copy is how the two drift. The
    field sits ABOVE the navbar here exactly as it does in the theme.
    """
    m = SEARCH_RE.search(theme_xml)
    if not m:
        sys.exit("ERR  could not find the search-bar markers in theme/freestackhub-theme.xml")
    box = m.group(1)
    # the one Blogger tag in the block: <homepageUrl>search -> the mock's own
    # action. The suggestion script reads the homepage back out of this
    # attribute, so the value has to keep its trailing "search".
    box = box.replace("expr:action='data:blog.homepageUrl + &quot;search&quot;'", 'action="/search"')
    return box


def search_sample() -> list:
    """The suggestion index the mock feeds the script, built from posts/.

    On Blogger the script fetches the blog's own summary feed; a static file on
    disk has no feed to ask, so the preview injects the same three fields per
    post (title, permalink, labels) out of the post headers instead. Real
    titles, so typing a real word in the mock returns a real row.

    Only the header comment is read - no image work, no validation - because
    this is an index of what exists, not a build of it.
    """
    sample = []
    for folder in sorted(POSTS_DIR.iterdir(), reverse=True):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        fm = FOLDER_RE.match(folder.name)
        src = folder / "post.html"
        if not fm or not src.exists():
            continue
        m = POST_HEADER_RE.match(src.read_text(encoding="utf-8"))
        if not m:
            continue
        meta = parse_header(m.group(1))
        title = meta.get("TITLE", "").strip()
        if not title:
            continue
        try:
            when = dt.datetime.fromisoformat(meta.get("PUBLISHED") or fm.group(1))
        except ValueError:
            continue
        sample.append({
            "t": title,
            "u": f"/{when.strftime('%Y/%m')}/{permalink_slug(meta.get('PERMALINK', ''), fm.group(2))}.html",
            "l": [l.strip() for l in meta.get("LABELS", "").split(",") if l.strip()],
            "d": when.strftime("%Y-%m-%d"),
        })
    return sample


def search_script(theme_xml: str) -> str:
    """The theme's suggestion script verbatim, plus the mock's sample index.

    Copied rather than retyped so the preview exercises the real code: whatever
    the script does on the blog - the word-by-word narrowing, the arrow keys,
    the aria-activedescendant wiring - is what you can try in the mock. The
    `//<![CDATA[` markers around it are JavaScript comments in plain HTML, so
    the block runs unchanged outside Blogger.
    """
    m = SEARCH_JS_RE.search(theme_xml)
    if not m:
        sys.exit("ERR  could not find the search-suggest markers in theme/freestackhub-theme.xml")
    sample = json.dumps(search_sample(), ensure_ascii=False)
    return (
        "  <script>\n"
        "  /* preview.html only: the index the suggestion script below uses instead\n"
        "     of fetching the blog's own feed (a static mock has no feed to ask).\n"
        "     Generated from the headers in posts/ - real titles, real labels. */\n"
        f"  window.FSH_SEARCH_SAMPLE = {sample};\n"
        "  </script>\n\n"
        + m.group(1).strip("\n")
        + "\n"
    )


def skin_css(theme_xml: str) -> str:
    m = re.search(r"<b:skin>\s*<!\[CDATA\[(.*?)\]\]>\s*</b:skin>", theme_xml, re.S)
    if not m:
        sys.exit("ERR  could not find <b:skin> CSS in theme/freestackhub-theme.xml")
    return m.group(1)


def newest_post() -> Path:
    folders = sorted(p for p in POSTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))
    if not folders:
        sys.exit("ERR  no post folders under posts/")
    return folders[-1]


def first_image(post: dict) -> str:
    m = re.search(r"<img[^>]+src=\"([^\"]+)\"", post["html"], re.I)
    if not m:
        return ""
    src = m.group(1)
    if src.startswith("http"):
        return src
    # bare file name -> the same public URL the build writes into the post
    rel = f"posts/{post['folder'].name}/images/{src.split('/')[-1]}"
    return f"https://cdn.jsdelivr.net/gh/{GITHUB_USER}/{GITHUB_REPO}@{IMAGE_REF}/{rel}"


def card(post: dict, title: str, url: str, image: str, labels: list,
         date: str, demo: bool = False, first: bool = False) -> str:
    tags = "".join(f'<a href="{url}" rel="tag">{html.escape(l)}</a>' for l in labels)
    badge = '<span class="preview-demo">demo card</span>' if demo else ""
    # first card = the LCP element: eager, high priority. Every other card is
    # below the fold and lazy, so it never competes with it for bandwidth.
    priority = ' fetchpriority="high"' if first else ""
    loading = "eager" if first else "lazy"
    media = (
        f'<a aria-hidden="true" class="card-media" href="{url}" tabindex="-1">'
        f'<img alt="{html.escape(title)}" decoding="async"{priority} height="{CARD_IMG_H}" '
        f'loading="{loading}" src="{image}" width="{CARD_IMG_W}"/></a>'
        if image else ""
    )
    # No excerpt: the card is image + labels + title + date + Read more. The
    # theme stopped printing data:post.snippets.long because that showed up as
    # a wall of the post itself on the home page.
    return f"""        <article class="post-card">
          {media}
          <div class="card-body">
            <div class="card-tags">{badge}{tags}</div>
            <h2 class="card-title"><a href="{url}">{html.escape(title)}</a></h2>
            <div class="card-meta"><time class="published">{date}</time></div>
            <div class="card-more">
              <a class="read-more" href="{url}" aria-label="Read more: {html.escape(title, quote=True)}">Read more <span aria-hidden="true">&#8594;</span></a>
            </div>
          </div>
        </article>"""


def widget(title: str, inner: str) -> str:
    return (
        '<div class="widget">'
        f"<h2>{title}</h2>"
        f'<div class="widget-content">{inner}</div>'
        "</div>"
    )


def sidebar(popular_item: str) -> str:
    return (
        widget("About", "Free PDFs, self-made apps and legit config files &mdash; "
                        "organized, ad-supported, no cracked or pirated content.")
        + '<div class="ad-slot"><div class="ad-inner"><div class="ad-label">Advertisement</div></div></div>'
        + widget("Categories", "<ul><li><a href='#'>PDFs</a></li><li><a href='#'>Apps</a></li>"
                               "<li><a href='#'>Configs &amp; Patches</a></li></ul>")
        # PopularPosts ranks by page views, so the widget says "Most Viewed
        # Stories" - it was "Most Downloaded", a counter this blog does not keep.
        + widget("Most Viewed Stories", f'<ul class="popular-list">{popular_item}</ul>')
    )


def build(post: dict) -> str:
    theme_xml = THEME.read_text(encoding="utf-8")
    css = skin_css(theme_xml)
    header = header_html(theme_xml)
    visit_strip = visit_strip_html(theme_xml)
    search_bar = search_html(theme_xml)
    suggest_js = search_script(theme_xml)
    title = post["title"]
    slug_url = "#"
    labels = post["labels"]
    date = post["published"].strftime("%B %d, %Y")
    image = first_image(post)
    body = MORE_RE.sub("", post["html"]).strip()

    # bare image names in the body -> the public URLs the build writes
    def fix_img(m):
        src = m.group(2)
        if src.startswith("http"):
            return m.group(0)
        rel = f"posts/{post['folder'].name}/images/{src.split('/')[-1]}"
        url = f"https://cdn.jsdelivr.net/gh/{GITHUB_USER}/{GITHUB_REPO}@{IMAGE_REF}/{rel}"
        return m.group(1) + url + m.group(3)

    body = re.sub(r'(<img[^>]*\ssrc=")([^"]+)(")', fix_img, body, flags=re.I)

    labels_html = "".join(f'<a href="{slug_url}" rel="tag">{html.escape(l)}</a>' for l in labels)
    post_url = f"/{post['published'].strftime('%Y/%m')}/{post['permalink']}.html"

    demo_title = "Your next post shows up as the second card in this list"
    demo_label = labels[:1] or ["PythonAnywhere"]

    # the "Most Viewed Stories" sidebar widget: thumbnail + title only, the way
    # the theme's custom PopularPosts includable renders it
    popular_item = ""
    if image:
        popular_item = (
            f'<li><a href="#"><img aria-hidden="true" alt="{html.escape(title)}" '
            f'decoding="async" height="56" loading="lazy" src="{image}" width="56"/>'
            f"<span>{html.escape(title)}</span></a></li>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1" name="viewport"/>
  <title>Theme preview &middot; Free Stack Hub</title>
  <meta content="{SITE_DESCRIPTION}" name="description"/>
  <meta content="#1F6F5C" name="theme-color"/>
  <link crossorigin="anonymous" href="https://fonts.gstatic.com" rel="preconnect"/>
  <link crossorigin="anonymous" href="https://lh3.googleusercontent.com" rel="preconnect"/>
  <link href="https://lh3.googleusercontent.com" rel="dns-prefetch"/>
  <link crossorigin="anonymous" href="https://cdn.jsdelivr.net" rel="preconnect"/>
  <link href="https://cdn.jsdelivr.net" rel="dns-prefetch"/>
  <link as="font" crossorigin="anonymous" href="https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPbF4Cw.woff2" rel="preload" type="font/woff2"/>
  <!-- No <link rel=stylesheet> to Google Fonts here: the @font-face rules are
       inlined in the skin CSS just below, exactly like in the Blogger theme. -->
  <style>
{css}
  /* ---- preview-only chrome (not part of the Blogger theme) ---- */
  .preview-note{{background:#FFF8E1;border-bottom:1px solid #EFDFA6;color:#6B5300;
    font:13.5px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:11px 16px;text-align:center}}
  .preview-note b{{color:#4E3C00}}
  .preview-block{{border-top:2px dashed #D7DCE4;padding-top:4px;margin-top:8px}}
  .preview-tag{{display:inline-block;margin:20px 0 0;font:600 11px/1 system-ui,sans-serif;
    letter-spacing:.09em;text-transform:uppercase;color:#0F4A3C;background:#E4F1ED;
    padding:6px 10px;border-radius:4px}}
  .preview-hint{{font:13.5px/1.5 system-ui,sans-serif;color:#6B7280;margin:8px 0 0}}
  .preview-demo{{display:inline-block;font:600 10px/1 system-ui,sans-serif;letter-spacing:.08em;
    text-transform:uppercase;color:#8A6D00;background:#FFF3C4;padding:4px 8px;border-radius:4px}}
  </style>
</head>
<body>

  <a class="skip-link" href="#main-content">Skip to content</a>

  <div class="preview-note">
    <b>Design preview</b> &mdash; this is a static mock of what
    <code>theme/freestackhub-theme.xml</code> renders, not the live blog.
    The card below is built from the real post <b>{html.escape(title)}</b>, and
    &ldquo;Read more&rdquo; opens that post&rsquo;s own URL (on Blogger:
    <code>{html.escape(post_url)}</code>).<br/>
    <b>Try the search box above the navbar</b> &mdash; it is a combo box: type a
    word and a list drops down, keep typing and it narrows word by word. Here it
    reads a sample index built from <code>posts/</code>; on the blog the same
    script reads the blog&rsquo;s own feed. Arrow keys walk the list, Enter opens
    the row, Escape closes it.
  </div>

  {header}

  <!--SEARCH_BAR-->

  <nav class="nav-wrap">
    <div class="container nav">
      <a href="#">Home</a><a href="#">PDFs</a><a href="#">Apps</a>
      <a href="#">Configs &amp; Patches</a><a href="#">About Us</a>
    </div>
  </nav>

{visit_strip}

  <div class="container">
    <div class="ad-slot"><div class="ad-inner"><div class="ad-label">Advertisement</div></div></div>
  </div>

  <main class="container" id="main-content" tabindex="-1">

    <section class="preview-block">
      <div class="preview-tag">1 &mdash; Home page: live visitor strip + teaser cards</div>
      <p class="preview-hint"><b>The slim strip under the navbar</b> is the live visitor
        snapshot &mdash; total visits &middot; your country &middot; your device &middot; local time.
        Its numbers here are stand-ins; on the blog they fill in after page load (two tiny
        requests), and Blogger sends this strip <b>on the home page only</b>. Cards below:
        feature image + labels + title + date + <b>Read more</b>, no body text; the title and
        the button both open that post&rsquo;s own URL. In the sidebar, <b>Most Viewed
        Stories</b> is Blogger&rsquo;s PopularPosts widget &mdash; it ranks by page views,
        which is why it no longer says &ldquo;Most Downloaded&rdquo;.</p>
      <div class="main-layout">
        <section class="content-area">
          <div class="post-list hfeed">
{card(post, title, slug_url, image, labels, date, first=True)}
{card(post, demo_title, slug_url, "", demo_label, date, demo=True)}
          </div>
          <div class="blog-pager container" id="blog-pager">
            <a class="blog-pager-older-link" href="#">Older Posts</a>
          </div>
        </section>
        <aside class="sidebar">{sidebar(popular_item)}</aside>
      </div>
    </section>

    <section class="preview-block">
      <div class="preview-tag">2 &mdash; The post page that Read more opens</div>
      <p class="preview-hint">Same skin, full body, labels and the comment section below
        (comments are Blogger&rsquo;s own markup).</p>
      <div class="main-layout">
        <section class="content-area">
          <article class="post-outer hentry">
            <header class="post-header">
              <h1 class="post-title entry-title">{html.escape(title)}</h1>
              <div class="post-meta"><time class="published">{date}</time>
                <span class="post-author"> &middot; AHMED</span></div>
            </header>
            <div class="post-body entry-content" id="post-body-1">
{body}
            </div>
            <div class="post-footer">
              <div class="post-labels">Filed under: {labels_html}</div>
              <a class="comment-link" href="#">Leave a comment</a>
            </div>
          </article>
        </section>
        <aside class="sidebar">{sidebar(popular_item)}</aside>
      </div>
    </section>

  </main>

  <footer class="footer">
    <div class="container">
      <div class="footer-grid">
        <div><h3>Free Stack Hub</h3><p>Free PDFs, self-made apps and legit config
          files/patches &mdash; built for readers, not clutter.</p></div>
        <div><h3>Pages</h3><ul><li><a href="#">About Us</a></li><li><a href="#">Privacy Policy</a></li>
          <li><a href="#">Contact Us</a></li><li><a href="#">DMCA</a></li></ul></div>
        <div><h3>Categories</h3><ul><li><a href="#">PDFs</a></li><li><a href="#">Apps</a></li>
          <li><a href="#">Configs &amp; Patches</a></li></ul></div>
      </div>
      <div class="copyright">&copy; Free Stack Hub &middot; All rights reserved.</div>
    </div>
  </footer>

<!--SEARCH_SCRIPT-->
</body>
</html>
"""

    # The two blocks lifted out of theme/freestackhub-theme.xml go in last, as
    # verbatim copies: the suggestion script is full of the braces an f-string
    # would otherwise try to read as placeholders.
    return (page
            .replace("<!--SEARCH_BAR-->", search_bar.strip("\n"))
            .replace("<!--SEARCH_SCRIPT-->", suggest_js.rstrip("\n")))


def main() -> None:
    ap = argparse.ArgumentParser(description="Write theme/preview.html")
    ap.add_argument("folder", nargs="?", help="posts/ folder (default: newest)")
    args = ap.parse_args()

    folder = (POSTS_DIR / args.folder) if args.folder else newest_post()
    if not folder.is_dir():
        sys.exit(f"ERR  no such post folder: {folder}")
    post = load_post(folder)
    for p in post["problems"]:
        print(f" warn  {p}")
    OUT.write_text(build(post), encoding="utf-8")
    print(f" ok   {OUT.relative_to(ROOT)}  (from {folder.name})")
    print("      open it with:  python3 -m http.server 8000  ->  /theme/preview.html")


if __name__ == "__main__":
    main()
