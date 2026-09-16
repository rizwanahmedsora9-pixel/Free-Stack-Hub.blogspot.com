#!/usr/bin/env python3
"""
Audit the theme and the generated preview for the Lighthouse / PageSpeed items
this repo can actually control - offline, with no browser and no network.

Lighthouse has to run against the live blog (Blogger serves it, and Blogger's
own CSS/JS is not ours), but every audit the theme or a post can fail is
checkable from the source files. That is what this does:

  Performance   no render-blocking <link rel=stylesheet>/<script src> in <head>
                fonts inlined as @font-face with font-display:swap
                preconnect to the origins the page fetches from
                every <img> has width+height (CLS), the LCP image is eager and
                fetchpriority=high, everything below the fold is lazy
                every raster image has an AVIF/WebP variant and a JPG fallback
  Accessibility every <a>/<button> has an accessible name, one <h1>, headings
                do not skip levels, visible focus, skip link, contrast >= 4.5:1
  Best practice target=_blank carries rel=noopener, the theme parses as XML
  SEO           exactly one <meta name=description>, 120-160 characters

Usage:
  python3 tools/check_perf.py                 # theme + preview + every post
  python3 tools/check_perf.py --verbose       # also list the passing checks
  python3 tools/check_perf.py theme/preview.html

Exit status: 0 = clean, 1 = something would fail an audit.
"""

import argparse
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_import import POSTS_DIR, REPO_CDN, load_post            # noqa: E402
from optimize_images import VARIANTS, identify                     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "theme" / "freestackhub-theme.xml"
PREVIEW = ROOT / "theme" / "preview.html"

DESC_MIN, DESC_MAX = 120, 160
LCP_IMAGE_WIDTH_LIMIT = 160_000     # ~160 KB: above this an LCP image is a problem

TAG_RE = re.compile(r"<[^>]+>")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
SKIN_RE = re.compile(r"<b:skin>\s*<!\[CDATA\[(.*?)\]\]>\s*</b:skin>", re.S)
STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
HEAD_RE = re.compile(r"<head[^>]*>(.*?)</head>", re.S | re.I)
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
A_RE = re.compile(r"<a\b[^>]*>(.*?)</a\s*>", re.S | re.I)
A_OPEN_RE = re.compile(r"<a\b[^>]*>", re.I)
BUTTON_RE = re.compile(r"<button\b[^>]*>(.*?)</button\s*>", re.S | re.I)
PICTURE_RE = re.compile(r"<picture\b[^>]*>(.*?)</picture\s*>", re.S | re.I)
LINK_REL_RE = re.compile(r"<link\b[^>]*\brel=['\"]?stylesheet['\"]?[^>]*>", re.I)
SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*\bsrc=", re.I)
DESC_RE = re.compile(r"<meta\b[^>]*\bname=['\"]description['\"][^>]*>", re.I)
CONTENT_RE = re.compile(r"\bcontent=['\"]([^'\"]*)['\"]", re.I)
# (?<![\w-]) not \b, so a "src" inside data-src is not mistaken for src
ATTR = lambda tag, name: (re.search(rf"(?<![\w-]){name}\s*=\s*[\"']([^\"']*)[\"']", tag, re.I) or [None, ""])[1]  # noqa: E731


# ---------------------------------------------------------------------------
# WCAG 2.x relative luminance + contrast
# ---------------------------------------------------------------------------

def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def css_vars(css: str) -> dict:
    """The custom properties declared in :root, so a palette edit is caught."""
    root = re.search(r":root\s*\{(.*?)\}", css, re.S)
    body = root.group(1) if root else css
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{3,8})", body))


def resolve(value: str, variables: dict) -> str:
    m = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    return variables.get(m.group(1), value) if m else value


CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def rule_body(css: str, selector: str):
    """The declaration block of one selector, or None if the skin dropped it.

    Comments are stripped first (they would otherwise be glued to the selector
    that follows them), and a selector given as a comma list matches a rule that
    declares any one of its parts.
    """
    css = CSS_COMMENT_RE.sub(" ", css)
    want = {" ".join(x.split()) for x in selector.split(",")}
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        have = {" ".join(x.split()) for x in m.group(1).split(",")}
        if want & have:
            return m.group(2)
    return None


def declaration(css: str, selector: str, prop: str):
    body = rule_body(css, selector)
    if body is None:
        return None
    m = re.search(rf"(?:^|[;\s]){re.escape(prop)}\s*:\s*([^;]+)", body)
    return m.group(1).strip() if m else None


def colour(spec: str, css: str, variables: dict):
    """Resolve one colour spec to a hex string.

    A spec is either a literal ("#fff"), a variable ("var(--ink)"), or a live
    lookup into the skin ("<selector>::<property>"). The lookup is what makes
    this a regression guard rather than a check of the table below: recolouring
    .copyright in the theme changes the number this computes.
    """
    if "::" in spec:
        selector, prop = spec.rsplit("::", 1)
        found = declaration(css, selector, prop)
        if not found:
            return None
        spec = found
    return resolve(spec, variables) if spec.strip().startswith("var(") else spec.strip()


# Text/background pairs the skin actually paints, as (label, foreground,
# background, minimum ratio). Values are read out of the live CSS.
CONTRAST_PAIRS = [
    ("body text on page",          "var(--ink)",                        "var(--bg)",                        4.5),
    ("body text on card",          "var(--ink)",                        "var(--surface)",                   4.5),
    ("meta, dates, tagline",       "var(--ink-soft)",                   "var(--surface)",                   4.5),
    ("popular list titles",        ".sidebar .popular-list a::color",   "var(--surface)",                   4.5),
    ("nav links",                  ".nav a::color",                     ".nav-wrap::background",            4.5),
    ("footer body text",           ".footer p,.footer li::color",       ".footer::background",              4.5),
    ("footer copyright",           ".copyright::color",                 ".footer::background",              4.5),
    ("Read more button",           ".read-more::color",                 ".read-more::background",           4.5),
    ("search button",              ".search button::color",             ".search button::background",       4.5),
    ("card tag chips",             ".card-tags a::color",               ".card-tags a::background",         4.5),
    ("post label chips",           ".post-labels a::color",             ".post-labels a::background",       4.5),
    ("search field placeholder",   ".search input::placeholder::color", "var(--surface)",                   4.5),
    ("code block",                 ".post-body pre::color",             ".post-body pre::background",       4.5),
]


def check_contrast(rep: "Report", css: str, where: str):
    rep.head(f"[{where}] accessibility - contrast (WCAG AA, 4.5:1)")
    variables = css_vars(css)
    for label, fg_spec, bg_spec, minimum in CONTRAST_PAIRS:
        fg, bg = colour(fg_spec, css, variables), colour(bg_spec, css, variables)
        if not fg or not bg:
            missing = fg_spec if not fg else bg_spec
            rep.warn(f"{label}: could not read {missing} from the CSS - selector renamed?")
            continue
        if not (fg.startswith("#") and bg.startswith("#")):
            rep.warn(f"{label}: {fg} on {bg} is not a plain colour, cannot be computed")
            continue
        ratio = contrast(fg, bg)
        if ratio < minimum:
            rep.fail(f"{label}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1")
        else:
            rep.ok(f"{label}: {fg} on {bg} = {ratio:.2f}:1")


class Report:
    def __init__(self, verbose=False):
        self.fails, self.warns, self.passes = [], [], []
        self.verbose = verbose
        self.section = ""

    def head(self, text):
        self.section = text
        if self.verbose:
            print(f"\n{text}")

    def ok(self, text):
        self.passes.append(f"{self.section} {text}")
        if self.verbose:
            print(f"   ok    {text}")

    def warn(self, text):
        self.warns.append(f"{self.section} {text}")
        print(f"   warn  {text}")

    def fail(self, text):
        self.fails.append(f"{self.section} {text}")
        print(f"   FAIL  {text}")


def blogger_probe(doc: str) -> str:
    """Approximate what a theme renders, far enough to audit names and attributes.

    Blogger tags are unwrapped rather than evaluated: <data:x/> becomes a
    placeholder (it always renders *something*, so it is an accessible name),
    expr:attr='...' becomes attr="...", and the <b:...> control tags disappear.
    That is enough to see whether every <a> has a name - it is deliberately not
    enough to evaluate conditionals, which is why the LCP/CLS rules are asserted
    on the theme source instead.
    """
    d = COMMENT_RE.sub(" ", doc)
    d = SKIN_RE.sub(lambda m: "<style>" + m.group(1) + "</style>", d)
    d = re.sub(r"expr:([\w-]+)='([^']*)'", lambda m: f'{m.group(1)}="{m.group(2)}"', d)
    d = re.sub(r"<data:[^>]*/?>", "X", d)
    d = re.sub(r"</?b:[^>]*>", " ", d)
    return d


INLINE_STYLE_RE = re.compile(r'style="([^"]*)"', re.I)


def check_inline_contrast(rep: "Report", html: str, where: str):
    """Post bodies carry their own inline colours, so the skin audit misses them."""
    rep.head(f"[{where}] accessibility - inline colours (WCAG AA, 4.5:1)")
    seen, bad = set(), 0
    for style in INLINE_STYLE_RE.findall(html):
        fg = re.search(r"(?<![-\w])color\s*:\s*(#[0-9A-Fa-f]{3,8})", style)
        if not fg:
            continue
        bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9A-Fa-f]{3,8})", style)
        # a caption with no background of its own sits on the card: --surface
        pair = (fg.group(1).lower(), bg.group(1).lower() if bg else "#ffffff")
        if pair in seen:
            continue
        seen.add(pair)
        ratio = contrast(*pair)
        if ratio < 4.5:
            rep.fail(f"inline {pair[0]} on {pair[1]} is {ratio:.2f}:1, needs 4.5:1")
            bad += 1
        else:
            rep.ok(f"inline {pair[0]} on {pair[1]} = {ratio:.2f}:1")
    if not seen:
        rep.ok("no inline colours to check")
    return bad


def accessible_name(tag: str, inner: str) -> str:
    """What a screen reader would announce for this element."""
    for a in ("aria-label", "alt", "title"):
        if ATTR(tag, a).strip():
            return ATTR(tag, a).strip()
    text = " ".join(TAG_RE.sub(" ", inner).split())
    if text:
        return text
    # a link wrapping only an image takes its name from that image's alt
    for img in IMG_RE.findall(inner):
        if ATTR(img, "alt").strip():
            return ATTR(img, "alt").strip()
    for svg in re.findall(r"<svg\b.*?</svg>", inner, re.S | re.I):
        if re.search(r"<title\b", svg, re.I):
            return "svg <title>"
    return ""


def is_decorative(tag: str) -> bool:
    return ATTR(tag, "aria-hidden").lower() == "true"


# ---------------------------------------------------------------------------
# checks that run on the generated preview (real HTML, real attribute values)
# ---------------------------------------------------------------------------

def content_scopes(doc: str) -> list:
    """One (label, html) per page being mocked.

    theme/preview.html deliberately holds TWO pages in one file - the home page
    card list and the post page - so "the first image is the LCP element" has to
    be evaluated per page, not once for the whole document.
    """
    parts = doc.split('<section class="preview-block">')[1:]
    if parts:
        return [(f"page {n}", c) for n, c in enumerate(parts, 1)]
    main = re.search(r"<main\b.*?</main>", doc, re.S | re.I)
    return [("page", main.group(0) if main else doc)]


def check_html(rep: Report, path: Path, raw: str):
    doc = COMMENT_RE.sub(" ", raw)          # comments are not markup
    head = (HEAD_RE.search(doc) or [None, doc])[1] if HEAD_RE.search(doc) else doc

    rep.head(f"[{path.name}] performance - render-blocking resources")
    blocking = [l for l in LINK_REL_RE.findall(head) if not re.search(r"\bmedia=.print", l, re.I)]
    for link in blocking:
        rep.fail(f"render-blocking stylesheet in <head>: {link[:90]}")
    if not blocking:
        rep.ok("no render-blocking <link rel=stylesheet> in <head>")
    scripts = SCRIPT_SRC_RE.findall(head)
    for s in scripts:
        rep.fail(f"parser-blocking <script src> in <head>: {s[:90]}")
    if not scripts:
        rep.ok("no <script src> in <head>")

    fonts = re.findall(r"@font-face\s*\{(.*?)\}", doc, re.S)
    rep.head(f"[{path.name}] performance - fonts")
    if fonts:
        # faces whose only src is local() resolve instantly and never block paint
        remote = [f for f in fonts if re.search(r"url\(", f)]
        no_swap = [f for f in remote if not re.search(r"font-display\s*:\s*swap", f, re.I)]
        local_faces = len(fonts) - len(remote)
        if no_swap:
            rep.fail(f"{len(no_swap)} @font-face without font-display:swap (invisible text while loading)")
        else:
            rep.ok(f"{len(remote)} webfont @font-face, all font-display:swap"
                   + (f" (+{local_faces} metric-adjusted local fallback)" if local_faces else ""))
        if re.search(r"<link\b[^>]*fonts\.googleapis\.com[^>]*rel=['\"]?stylesheet", doc, re.I):
            rep.fail("still linking the Google Fonts stylesheet - that is the blocking request")
        else:
            rep.ok("no Google Fonts stylesheet request")
    else:
        rep.warn("no @font-face found - is the skin inlined?")

    rep.head(f"[{path.name}] performance - preconnect")
    for origin in ("fonts.gstatic.com", "cdn.jsdelivr.net"):
        if re.search(rf"<link\b[^>]*href=['\"]https://{re.escape(origin)}['\"][^>]*rel=['\"]?preconnect", doc, re.I) \
           or re.search(rf"<link\b[^>]*rel=['\"]?preconnect['\"]?[^>]*href=['\"]https://{re.escape(origin)}", doc, re.I):
            rep.ok(f"preconnect to {origin}")
        else:
            rep.fail(f"no preconnect to {origin} - the LCP image and the fonts pay DNS+TLS on the critical path")

    rep.head(f"[{path.name}] performance - CLS / image dimensions")
    imgs = IMG_RE.findall(doc)
    no_dims, no_alt = [], []
    for tag in imgs:
        if not (ATTR(tag, "width") and ATTR(tag, "height")):
            no_dims.append(ATTR(tag, "src").split("/")[-1] or tag[:60])
        if not ATTR(tag, "alt"):
            no_alt.append(ATTR(tag, "src").split("/")[-1] or tag[:60])
    if no_dims:
        rep.fail(f"{len(no_dims)} <img> without width+height (layout shifts when they land): {', '.join(no_dims[:4])}")
    else:
        rep.ok(f"all {len(imgs)} <img> have explicit width+height")
    if no_alt:
        rep.fail(f"{len(no_alt)} <img> without alt text: {', '.join(no_alt[:4])}")
    else:
        rep.ok(f"all {len(imgs)} <img> have alt text")

    rep.head(f"[{path.name}] performance - LCP and lazy loading")
    for label, scope in content_scopes(doc):
        scoped = IMG_RE.findall(scope)
        if not scoped:
            continue
        lcp = scoped[0]
        name = ATTR(lcp, "src").split("/")[-1] or "first image"
        if ATTR(lcp, "loading").lower() == "lazy":
            rep.fail(f"{label}: the LCP image ({name}) is loading=lazy - it is not discovered until after layout")
        elif ATTR(lcp, "loading").lower() != "eager":
            rep.warn(f"{label}: LCP image has loading={ATTR(lcp, 'loading') or '(unset)'}; set eager to be explicit")
        else:
            rep.ok(f"{label}: LCP image is loading=eager")
        if ATTR(lcp, "fetchpriority").lower() == "high":
            rep.ok(f"{label}: LCP image is fetchpriority=high")
        else:
            rep.fail(f"{label}: the LCP image ({name}) has no fetchpriority=high")
        eager_below = [t for t in scoped[1:] if ATTR(t, "loading").lower() != "lazy"]
        if eager_below:
            rep.fail(f"{label}: {len(eager_below)} below-the-fold image(s) are not loading=lazy")
        elif len(scoped) > 1:
            rep.ok(f"{label}: {len(scoped) - 1} below-the-fold image(s) are loading=lazy")

    rep.head(f"[{path.name}] performance - modern formats")
    pics = PICTURE_RE.findall(doc)
    if pics:
        order_bad = [p for p in pics
                     if [m.lower() for m in re.findall(r"type=['\"]image/(\w+)['\"]", p, re.I)]
                     != sorted(re.findall(r"type=['\"]image/(\w+)['\"]", p, re.I),
                               key=lambda e: {"avif": 0, "webp": 1}.get(e.lower(), 9))]
        if order_bad:
            rep.fail(f"{len(order_bad)} <picture> list WebP before AVIF - the browser takes the first "
                     f"source it supports, so the smallest format must come first")
        else:
            rep.ok(f"{len(pics)} <picture> with AVIF ahead of WebP")
        no_fallback = [p for p in pics if not IMG_RE.search(p)]
        if no_fallback:
            rep.fail(f"{len(no_fallback)} <picture> without an <img> fallback - no image at all on old browsers")
        else:
            rep.ok("every <picture> keeps a JPG <img> fallback")
    else:
        rep.warn("no <picture> in the document - post images are served as single-format <img>")

    rep.head(f"[{path.name}] accessibility - link and button names")
    unnamed = []
    for m in A_RE.finditer(doc):
        tag, inner = m.group(0)[:m.group(0).index(">") + 1], m.group(1)
        if is_decorative(tag):
            continue
        if not accessible_name(tag, inner):
            unnamed.append(tag[:80])
    for m in BUTTON_RE.finditer(doc):
        tag, inner = m.group(0)[:m.group(0).index(">") + 1], m.group(1)
        if not accessible_name(tag, inner):
            unnamed.append(tag[:80])
    if unnamed:
        rep.fail(f"{len(unnamed)} link(s)/button(s) with no accessible name: {unnamed[:3]}")
    else:
        rep.ok("every link and button has an accessible name")
    # "Read more" repeated N times is a name, but a useless one
    bare = [m for m in A_RE.finditer(doc)
            if " ".join(TAG_RE.sub(" ", m.group(1)).split()).lower() in ("read more", "read more →")
            and not ATTR(m.group(0)[:m.group(0).index(">") + 1], "aria-label")]
    if bare:
        rep.fail(f'{len(bare)} "Read more" link(s) without an aria-label naming the post')
    else:
        rep.ok('"Read more" links carry the post title in aria-label')

    rep.head(f"[{path.name}] accessibility - document structure")
    h1 = re.findall(r"<h1\b", doc, re.I)
    if len(h1) > 1:
        rep.fail(f"{len(h1)} <h1> elements - a page has exactly one")
    else:
        rep.ok(f"{len(h1)} <h1>")
    levels = [int(m) for m in re.findall(r"<h([1-6])\b", doc, re.I)]
    jumps = [f"h{a}->h{b}" for a, b in zip(levels, levels[1:]) if b - a > 1]
    if jumps:
        rep.fail(f"heading levels skip: {', '.join(jumps[:4])}")
    else:
        rep.ok("no heading level is skipped")
    html_tag = (re.search(r"<html\b[^>]*>", doc, re.I) or [""])[0]
    if ATTR(html_tag, "lang") or "expr:lang" in html_tag:
        rep.ok("<html> declares a language")
    else:
        rep.fail("<html> has no lang attribute")
    if re.search(r"\bskip-link\b", doc) and re.search(r"id=['\"]main-content['\"]", doc):
        rep.ok("skip link present and its #main-content target exists")
    else:
        rep.fail("no skip link / #main-content target - keyboard users must tab through the whole header")
    if re.search(r":focus-visible", doc):
        rep.ok("visible :focus-visible ring")
    else:
        rep.fail("no :focus-visible styling - focus is invisible for keyboard users")
    if re.search(r"prefers-reduced-motion", doc):
        rep.ok("prefers-reduced-motion honoured")
    else:
        rep.warn("no prefers-reduced-motion block")

    rep.head(f"[{path.name}] best practices")
    for m in re.finditer(r"<a\b[^>]*target=['\"]_blank['\"][^>]*>", doc, re.I):
        if not re.search(r"rel=['\"][^'\"]*noopener", m.group(0), re.I):
            rep.fail(f"target=_blank without rel=noopener: {m.group(0)[:80]}")
            break
    else:
        rep.ok("every target=_blank link carries rel=noopener")
    vp = (re.search(r"<meta\b[^>]*name=['\"]viewport['\"][^>]*>", doc, re.I) or [""])[0]
    if vp and re.search(r"user-scalable\s*=\s*no|maximum-scale\s*=\s*1", vp, re.I):
        rep.fail("viewport disables zoom")
    elif vp:
        rep.ok("viewport allows zooming")
    else:
        rep.fail("no viewport meta tag")

    rep.head(f"[{path.name}] SEO")
    metas = DESC_RE.findall(doc)
    if len(metas) != 1:
        rep.fail(f"{len(metas)} <meta name=description> tags - Google needs exactly one")
    else:
        text = CONTENT_RE.search(metas[0]).group(1)
        n = len(text)
        if DESC_MIN <= n <= DESC_MAX:
            rep.ok(f"meta description present, {n} characters (target {DESC_MIN}-{DESC_MAX})")
        else:
            rep.fail(f"meta description is {n} characters, outside {DESC_MIN}-{DESC_MAX}")
    if re.search(r"<title\b[^>]*>\s*</title>", doc, re.I) or not re.search(r"<title\b", doc, re.I):
        rep.fail("missing or empty <title>")
    else:
        rep.ok("<title> present")

    check_contrast(rep, "".join(STYLE_RE.findall(doc)) or doc, path.name)


def check_theme(rep: Report):
    rep.head("[theme] Blogger can only be given well-formed XML")
    try:
        ET.parse(THEME)
        rep.ok("freestackhub-theme.xml parses as XML")
    except ET.ParseError as e:
        rep.fail(f"freestackhub-theme.xml is not well-formed: {e}")
        return None
    doc = THEME.read_text(encoding="utf-8")
    skin = (SKIN_RE.search(doc) or [None, ""])[1]
    if not skin:
        rep.fail("no <b:skin> block found")
        return None

    rep.head("[theme] performance - the card list")
    if re.search(r"expr:loading='data:isFirst \? &quot;eager&quot; : &quot;lazy&quot;'", doc):
        rep.ok("card image: first card eager, the rest lazy")
    elif re.search(r"loading='lazy'", doc) and re.search(r"card-media", doc):
        rep.fail("every card image is loading=lazy - the first one is the LCP element")
    if re.search(r"expr:fetchpriority='data:isFirst \? &quot;high&quot;", doc):
        rep.ok("card image: fetchpriority=high on the first card")
    else:
        rep.fail("the LCP card image has no fetchpriority=high")
    if re.search(r"<b:loop index='i' values='data:posts'", doc) and "var='isFirst'" in doc:
        rep.ok("the loop exposes isFirst so the theme knows which card is above the fold")
    else:
        rep.fail("no b:loop index / b:with isFirst - the theme cannot tell the first card from the rest")
    card_img = re.search(r"<b:includable id='cardImage'.*?</b:includable>", doc, re.S)
    if card_img:
        for need in ("width=", "height="):
            if need not in card_img.group(0):
                rep.fail(f"card <img> has no {need.rstrip('=')} - the browser cannot reserve the box (CLS)")
        if "width=" in card_img.group(0) and "height=" in card_img.group(0):
            rep.ok("card <img> declares width+height")
    if re.search(r"\.card-media\s*\{[^}]*aspect-ratio", skin):
        rep.ok(".card-media reserves an aspect-ratio")
    else:
        rep.fail(".card-media has no aspect-ratio - the card collapses until the image lands")
    check_contrast(rep, skin, "theme")

    probe = blogger_probe(doc)
    head = (HEAD_RE.search(probe) or [None, ""])[1]

    rep.head("[theme] performance - render-blocking resources")
    blocking = [l for l in LINK_REL_RE.findall(head) if not re.search(r"\bmedia=.print", l, re.I)]
    for link in blocking:
        rep.fail(f"render-blocking stylesheet in the theme head: {link[:90]}")
    if not blocking:
        rep.ok("no render-blocking <link rel=stylesheet> in the theme head")
    if SCRIPT_SRC_RE.findall(head):
        rep.fail("the theme adds a parser-blocking <script src> to <head>")
    else:
        rep.ok("the theme adds no <script src> of its own")
    for origin in ("fonts.gstatic.com", "cdn.jsdelivr.net"):
        links = re.findall(r"<link\b[^>]*>", head, re.I)
        if any(ATTR(l, "rel").lower() == "preconnect" and origin in ATTR(l, "href") for l in links):
            rep.ok(f"preconnect to {origin}")
        else:
            rep.fail(f"no preconnect to {origin} in the theme head")

    rep.head("[theme] performance - fonts and motion")
    webfonts = re.findall(r"font-family:'([^']+)'", skin)
    missing_fallback = []
    for family in dict.fromkeys(webfonts):
        if f"{family} Fallback" not in skin:
            continue
        face = re.search(rf"@font-face\{{[^}}]*font-family:'{re.escape(family)} Fallback'.*?\}}", skin, re.S)
        if not face or "size-adjust" not in face.group(0):
            missing_fallback.append(family)
        if f"'{family} Fallback'" not in skin.split(":root", 1)[-1]:
            missing_fallback.append(f"{family} (declared but not in the font stack)")
    real = [f for f in dict.fromkeys(webfonts) if not f.endswith("Fallback")]
    if missing_fallback:
        rep.fail(f"no metric-adjusted fallback for {', '.join(dict.fromkeys(missing_fallback))} - "
                 f"the font swap will move every line of text (CLS)")
    elif real:
        rep.ok(f"metric-adjusted fallback face wired into the stack for {', '.join(real)}")
    if re.search(r"prefers-reduced-motion", skin):
        rep.ok("prefers-reduced-motion honoured")
    else:
        rep.fail("no prefers-reduced-motion block")
    if re.search(r":focus-visible", skin):
        rep.ok("visible :focus-visible ring")
    else:
        rep.fail("no :focus-visible styling")

    rep.head("[theme] accessibility - link and button names")
    unnamed = []
    for m in A_RE.finditer(probe):
        tag = m.group(0)[:m.group(0).index(">") + 1]
        if is_decorative(tag):
            continue
        if not accessible_name(tag, m.group(1)):
            unnamed.append(" ".join(tag.split())[:90])
    for m in BUTTON_RE.finditer(probe):
        tag = m.group(0)[:m.group(0).index(">") + 1]
        if not accessible_name(tag, m.group(1)):
            unnamed.append(" ".join(tag.split())[:90])
    if unnamed:
        rep.fail(f"{len(unnamed)} theme link(s)/button(s) with no accessible name: {unnamed[:3]}")
    else:
        rep.ok("every link and button in the theme has an accessible name")
    if re.search(r"class='read-more'[^>]*aria-label=", doc):
        rep.ok('"Read more" carries the post title in its aria-label')
    else:
        rep.fail('"Read more" has no aria-label - a screen reader announces the same link per card')
    if re.search(r"skip-link", doc) and re.search(r"id='main-content'", doc):
        rep.ok("skip link and its #main-content target")
    else:
        rep.fail("no skip link / #main-content target in the theme")
    for m in re.finditer(r"<a\b[^>]*target='_blank'[^>]*>", doc, re.I):
        if not re.search(r"rel='[^']*noopener", m.group(0), re.I):
            rep.fail(f"target=_blank without rel=noopener: {' '.join(m.group(0).split())[:80]}")
            break
    else:
        rep.ok("every target=_blank link carries rel=noopener")

    rep.head("[theme] SEO")
    if re.search(r"<b:if cond='not data:blog\.metaDescription'>", doc):
        rep.ok("meta description has a fallback and steps aside when Blogger provides one")
    else:
        rep.fail("no guarded meta description - Blogger emits none while search descriptions are off")
    m = re.search(r"<meta content='([^']*)' name='description'/>", doc)
    if m:
        n = len(m.group(1))
        if DESC_MIN <= n <= DESC_MAX:
            rep.ok(f"fallback description is {n} characters")
        else:
            rep.fail(f"fallback description is {n} characters, outside {DESC_MIN}-{DESC_MAX}")
    return doc


def check_post(rep: Report, folder: Path):
    rep.head(f"[{folder.name}] post source")
    p = load_post(folder)
    for problem in p["problems"]:
        rep.fail(problem)
    if not p["problems"]:
        rep.ok("build_import.py reports no structural problems")
    body = p.get("html", "")
    if not body:
        return

    imgs = IMG_RE.findall(body)
    if imgs:
        hero = imgs[0]
        name = ATTR(hero, "src").split("/")[-1]
        if ATTR(hero, "fetchpriority").lower() == "high" and ATTR(hero, "loading") == "eager":
            rep.ok(f"hero image {name} is the eager, high-priority LCP element")
        else:
            rep.fail(f"hero image {name} is not eager + fetchpriority=high")
        rest = [t for t in imgs[1:] if ATTR(t, "loading") != "lazy"]
        if rest:
            rep.fail(f"{len(rest)} below-the-fold image(s) are not loading=lazy")
        elif len(imgs) > 1:
            rep.ok(f"{len(imgs) - 1} later images are loading=lazy")
        for tag in imgs:
            w, h = ATTR(tag, "width"), ATTR(tag, "height")
            if not (w and h):
                rep.fail(f"{ATTR(tag, 'src').split('/')[-1]} has no width/height in the built HTML")
        rep.ok("every built <img> carries width/height")

    check_inline_contrast(rep, body, folder.name)

    img_dir = folder / "images"
    rep.head(f"[{folder.name}] image payload")
    for tag in imgs:
        src = ATTR(tag, "src")
        if not src.startswith(REPO_CDN):
            continue
        rel = src[len(REPO_CDN):]
        local = ROOT / rel
        if not local.exists():
            rep.fail(f"{local.name} is referenced by the post but not in the repo")
            continue
        size = identify(local)
        w, h = ATTR(tag, "width"), ATTR(tag, "height")
        if size and (str(size[0]) != w or str(size[1]) != h):
            rep.fail(f"{local.name} declares {w}x{h} but the file is {size[0]}x{size[1]} - "
                     f"the reserved box is wrong, so the page still shifts")
        else:
            rep.ok(f"{local.name} declares its real size {w}x{h}")
        stem, missing = local.with_suffix(""), []
        for ext, _q in VARIANTS:
            if not stem.with_suffix("." + ext).exists():
                missing.append(ext)
        if missing:
            rep.fail(f"{local.name} has no {'/'.join(missing)} variant - run tools/optimize_images.py")
        else:
            avif = stem.with_suffix(".avif")
            saved = 100 - 100 * avif.stat().st_size / local.stat().st_size
            rep.ok(f"{local.name} has AVIF (-{saved:.0f}%) and WebP variants")
        if tag is imgs[0] and local.stat().st_size > LCP_IMAGE_WIDTH_LIMIT:
            rep.warn(f"the LCP image is {local.stat().st_size / 1024:.0f} KB - worth compressing further")


def check_drift(rep: Report, theme_doc: str):
    rep.head("[drift] the mock and the theme must not disagree")
    if not PREVIEW.exists() or not theme_doc:
        rep.warn("nothing to compare")
        return
    preview = PREVIEW.read_text(encoding="utf-8")
    theme_desc = (re.search(r"<meta content='([^']*)' name='description'/>", theme_doc) or [None, ""])[1]
    prev_desc = (re.search(r'<meta content="([^"]*)" name="description"/>', preview) or [None, ""])[1]
    if theme_desc and prev_desc and theme_desc != prev_desc:
        rep.fail("the meta description in preview.html differs from the theme's")
    elif theme_desc:
        rep.ok("meta description matches between theme and preview")
    theme_skin = (SKIN_RE.search(theme_doc) or [None, ""])[1]
    if theme_skin and theme_skin.strip() in preview:
        rep.ok("preview.html embeds the theme's current skin CSS")
    elif theme_skin:
        rep.fail("preview.html is stale - run python3 tools/build_theme_preview.py")


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline Lighthouse/PSI audit of the theme, preview and posts")
    ap.add_argument("path", nargs="?", help="extra HTML file to audit")
    ap.add_argument("--verbose", action="store_true", help="list the passing checks too")
    a = ap.parse_args()

    rep = Report(a.verbose)
    theme_doc = check_theme(rep) if THEME.exists() else None
    if PREVIEW.exists():
        check_html(rep, PREVIEW, PREVIEW.read_text(encoding="utf-8"))
    if a.path:
        extra = Path(a.path)
        if not extra.is_absolute():
            extra = ROOT / extra
        if not extra.exists():
            print(f"ERR   no such file: {extra}")
            return 1
        text = extra.read_text(encoding="utf-8")
        if extra.suffix == ".xml":
            text = (SKIN_RE.search(text).group(1) if SKIN_RE.search(text) else "") + text
        check_html(rep, extra, text)
    for folder in sorted(d for d in POSTS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")):
        check_post(rep, folder)
    check_drift(rep, theme_doc)

    print()
    if rep.warns:
        print(f"{len(rep.warns)} warning(s)")
    if rep.fails:
        print(f"{len(rep.fails)} check(s) FAILED:")
        for f in rep.fails:
            print(f"  - {f}")
        return 1
    print(f"clean - {len(rep.passes)} check(s) passed, nothing that would fail a Lighthouse audit")
    print("\nThis audits what the repo controls. Blogger's own CSS/JS is not ours to")
    print("remove; re-run PageSpeed on the live blog after uploading the theme.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
