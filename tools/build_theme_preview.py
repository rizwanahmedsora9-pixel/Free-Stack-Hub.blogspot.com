#!/usr/bin/env python3
"""
Write theme/preview.html - a static mock of what the Blogger theme in
theme/freestackhub-theme.xml renders.

Blogger is the only place the real theme runs, so this file exists to answer
"what will my blog look like?" *before* uploading anything: it reuses the exact
skin (CSS) from the theme file, the exact card markup the Blog1 widget emits,
and the real title / labels / hook / body of a post from posts/.

Usage:
  python3 tools/build_theme_preview.py                     # newest post folder
  python3 tools/build_theme_preview.py <folder>            # one post
  python3 tools/build_theme_preview.py --open              # also serve instructions

Generated - do not hand-edit; edit theme/freestackhub-theme.xml or the post and
run this again.
"""

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_import import GITHUB_REPO, GITHUB_USER, IMAGE_REF, POSTS_DIR, load_post  # noqa: E402

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
        + widget("Most Downloaded", f'<ul class="popular-list">{popular_item}</ul>')
    )


def build(post: dict) -> str:
    theme_xml = THEME.read_text(encoding="utf-8")
    css = skin_css(theme_xml)
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
    post_url = f"/{post['published'].strftime('%Y/%m')}/{post['slug']}.html"

    demo_title = "Your next post shows up as the second card in this list"
    demo_label = labels[:1] or ["PythonAnywhere"]

    # the "Most Downloaded" sidebar widget: thumbnail + title only, the way
    # the theme's custom PopularPosts includable renders it
    popular_item = ""
    if image:
        popular_item = (
            f'<li><a href="#"><img aria-hidden="true" alt="{html.escape(title)}" '
            f'decoding="async" height="56" loading="lazy" src="{image}" width="56"/>'
            f"<span>{html.escape(title)}</span></a></li>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1" name="viewport"/>
  <title>Theme preview &middot; Free Stack Hub</title>
  <meta content="{SITE_DESCRIPTION}" name="description"/>
  <meta content="#1F6F5C" name="theme-color"/>
  <link crossorigin="anonymous" href="https://fonts.gstatic.com" rel="preconnect"/>
  <link crossorigin="anonymous" href="https://cdn.jsdelivr.net" rel="preconnect"/>
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
    <code>{html.escape(post_url)}</code>).
  </div>

  <header class="header">
    <div class="container brand-row">
      <a href="#">
        <div class="brand-title">Free Stack Hub</div>
        <div class="brand-tagline">Free PDFs, self-made apps and legit config files</div>
      </a>
      <div class="social-row">
        <a aria-label="YouTube" href="#">&#9654;</a>
        <a aria-label="WhatsApp" href="#">&#9993;</a>
      </div>
    </div>
  </header>

  <nav class="nav-wrap">
    <div class="container nav">
      <a href="#">Home</a><a href="#">PDFs</a><a href="#">Apps</a>
      <a href="#">Configs &amp; Patches</a><a href="#">About Us</a>
    </div>
  </nav>

  <div class="search-wrap">
    <div class="container">
      <form class="search">
        <input aria-label="Search" placeholder="Search PDFs, apps, configs&hellip;" type="search"/>
        <button aria-label="Search this blog" type="submit">Search</button>
      </form>
    </div>
  </div>

  <div class="container">
    <div class="ad-slot"><div class="ad-inner"><div class="ad-label">Advertisement</div></div></div>
  </div>

  <main class="container" id="main-content" tabindex="-1">

    <section class="preview-block">
      <div class="preview-tag">1 &mdash; Home page: teaser cards</div>
      <p class="preview-hint">Feature image + labels + title + date + <b>Read more</b> &mdash;
        no body text on the home page any more (the cards used to print the post&rsquo;s own
        snippet, which read like the full post). The title and the button both open that
        post&rsquo;s own URL.</p>
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

</body>
</html>
"""


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
