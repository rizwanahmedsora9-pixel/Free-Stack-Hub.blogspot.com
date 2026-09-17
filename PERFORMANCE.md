# Core Web Vitals and Lighthouse

What was done to `theme/freestackhub-theme.xml`, the post build and the image
pipeline to get PageSpeed Insights to pass, why each change is there, and how to
keep it passing on the next post.

```bash
python3 tools/check_perf.py --verbose    # 88 offline checks across theme, preview and posts
python3 tools/optimize_images.py         # (re)generate the AVIF/WebP variants
python3 tools/build_import.py            # regenerate import.xml / paste.html / title.txt
python3 tools/build_theme_preview.py     # regenerate theme/preview.html
python3 tools/check_published.py         # after publishing: what Blogger actually kept
```

`check_perf.py` is the guard rail. It runs offline, needs nothing but the
standard library, and exits 1 if a change would fail one of the Lighthouse
audits listed below. Run it before uploading a theme or merging a post.

---

## What this repo can and cannot control

Blogger renders the page. Its own widget CSS and its own JavaScript come from
`<b:include name='all-head-content'/>` and are not ours to tree-shake, so the
"unused JavaScript" figure on the live report will never reach zero - that part
of the score belongs to Google's platform, not to this code.

Everything below **is** ours, and is what the report was actually failing on:

| | served by | ours? |
| --- | --- | --- |
| document HTML, CSS, `<head>` | Blogger, from `theme/freestackhub-theme.xml` | **yes** |
| post body HTML (`<picture>`, `<img>` attributes) | Blogger, from `posts/*/post.html` via `import.xml` | **yes** |
| images | jsDelivr, from `posts/*/images/` in this repo | **yes** |
| fonts | fonts.gstatic.com, URLs inlined in the skin | **yes** |
| Blogger widget CSS/JS | Blogger | no |

---

## 1. Performance

### 1.1 Render-blocking resources (FCP)

**Removed.** The head used to carry

```html
<link href='https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap' rel='stylesheet'/>
```

That is the worst kind of blocking request: a stylesheet on a third origin whose
*only* job is to tell the browser the URLs of two more files on a fourth origin.
Paint waited on `fonts.googleapis.com` DNS → TLS → request → parse, and only then
could it start `fonts.gstatic.com`. Three round trips before the first pixel.

The `@font-face` rules are now inlined at the top of `<b:skin>`, so the CSS the
browser needs arrives in the HTML it already has and the woff2 files are
discovered during the first parse. Both families are **variable fonts**, so one
file covers a whole weight range:

| family | declared | file(s) |
| --- | --- | --- |
| Space Grotesk | `font-weight: 400 700` | 1 latin + 1 latin-ext |
| Source Serif 4 | `font-weight: 400 600` | 1 latin + 1 latin-ext |

The old link asked for four discrete weights of Space Grotesk; all four already
resolved to the *same* variable file, so declaring the range costs nothing and
removes three redundant `@font-face` blocks. `unicode-range` means an English
page downloads only the two `latin` files - the other subsets are never fetched.

`font-display: swap` on every webfont keeps text painted in the fallback while
they load (no invisible text, no FOIT).

**Also removed:** the theme has no `<script src>` of its own. The home page
cards are pure server-rendered HTML (feature image + labels + title + date +
Read more; no post text) - Blogger cuts everything at the template. The only
first-party JavaScript anywhere is the visitor strip's ~1 KB inline script at
the end of `<body>` (§1.8): inline, so it is not a request, not a parser pause,
and not on any page but the home page - so there is still nothing that
`defer`/`async` would help.

### 1.2 Resource hints and Preload

```html
<link crossorigin='anonymous' href='https://fonts.gstatic.com' rel='preconnect'/>
<link crossorigin='anonymous' href='https://lh3.googleusercontent.com' rel='preconnect'/>
<link href='https://lh3.googleusercontent.com' rel='dns-prefetch'/>
<link crossorigin='anonymous' href='https://cdn.jsdelivr.net' rel='preconnect'/>
<link href='https://cdn.jsdelivr.net' rel='dns-prefetch'/>
<link as='font' crossorigin='anonymous' href='https://fonts.gstatic.com/s/spacegrotesk/v22/V8mDoQDjQSkFtoMM3T6r8E7mPbF4Cw.woff2' rel='preload' type='font/woff2'/>
```

- **`lh3.googleusercontent.com`**: Blogger's image proxy serves all card thumbnails (`data:post.featuredImage`).
  Preconnecting to this origin saves ~300-450 ms of DNS/TLS handshake latency on mobile for the homepage LCP image.
- **`fonts.gstatic.com`**: Font origin. `crossorigin` is required because fonts are always fetched in CORS mode.
- **`cdn.jsdelivr.net`**: Serves post body images.
- **Font Preload**: Preloads the primary latin variable font (`Space Grotesk`) directly in `<head>` so text painting
  (FCP) begins as soon as the font file downloads, without waiting for DOM construction and stylesheet parsing.

### 1.3 LCP: the hero image

Two different LCP elements, both optimized:

**Home page** - the first card's image:
1. It is eager loaded with high priority:
   ```xml
   expr:fetchpriority='data:isFirst ? "high" : "auto"'
   expr:loading='data:isFirst ? "eager" : "lazy"'
   ```
2. It uses Blogger's built-in image resizing operator:
   ```xml
   expr:src='resizeImage(data:post.featuredImage, 640, "16:9")'
   ```
   Instead of downloading the uncompressed raw 1200px+ original, Google's proxy crops and scales the image to 640px,
   cutting transfer size by over 60%.
3. In the sidebar, `PopularPosts` uses `resizeImage(data:post.featuredImage, 72, "1:1")` to serve ~1.5 KB thumbnails
   instead of full 50-100 KB images.

**Post page** - the feature image:
1. `build_import.py` marks the first `<img>` in the body `loading="eager" fetchpriority="high"` and every later one
   `loading="lazy" decoding="async"`.
2. **Strict Hero Image Size Budget**:
   - Max width: **1200px** (never upload 1400px+ images).
   - Max JPG size: **≤ 70 KB** (warning at 60 KB; build/check_perf fails if > 80 KB).
   - Max AVIF size: **≤ 30 KB** (build/check_perf fails if > 30 KB).
   This ensures that under throttled mobile Slow 4G (1.6 Mbps), the image transfer completes in under 150 ms.

### 1.4 CLS: reserving space

Three separate causes, three fixes.

1. **Post images.** Every `<img>` now carries `width` and `height` read from the
   actual file by `tools/optimize_images.py`'s `identify()` - a dependency-free
   parser for JPEG/PNG/WebP/AVIF/GIF, with ImageMagick as a fallback. The author
   never types a number: write `<img src="01-hero.jpg" alt="…">` and the build
   looks the pixels up. If `post.html` claims a size the file disagrees with, the
   file wins, so a wrong number cannot ship. With `max-width:100%;height:auto` in
   the skin, modern browsers derive `aspect-ratio` from the attributes and
   reserve the exact box before any bytes arrive.
2. **Card images.** `.card-media` and its `<img>` now declare `aspect-ratio:16/9`,
   plus `width='640' height='360'` on the element, so the card's media column has
   a height before the image lands instead of collapsing to `min-height`.
3. **The font swap.** `font-display:swap` re-lays out every line when the webfont
   replaces the fallback. Two metric-adjusted faces absorb it:

   ```css
   @font-face{font-family:'Space Grotesk Fallback';src:local('Arial'),local('Helvetica');
     size-adjust:104%;ascent-override:90%;descent-override:22%;line-gap-override:0%}
   @font-face{font-family:'Source Serif 4 Fallback';src:local('Georgia'),local('Times New Roman');
     size-adjust:101%;ascent-override:94%;descent-override:26%;line-gap-override:0%}
   ```

   wired into the stacks as `'Space Grotesk','Space Grotesk Fallback',system-ui,…`.
   The percentages are tuned estimates, not measured metrics - if the swap still
   shifts noticeably, re-derive them with the fallback-metrics calculator and
   update both faces.

Blogger's own sidebar widgets (PopularPosts, Label) emit markup this theme does
not control, so `.sidebar .widget img{aspect-ratio:1/1;height:auto;object-fit:cover}`
pins their thumbnails to a square box that cannot push the column down.

### 1.5 Image payload: AVIF and WebP

`tools/optimize_images.py` writes two siblings next to every JPEG and the build
wraps each image in a `<picture>`:

```html
<picture>
  <source srcset="…/01-hero.avif" type="image/avif"/>
  <source srcset="…/01-hero.webp" type="image/webp"/>
  <img alt="…" decoding="async" fetchpriority="high" height="480" loading="eager"
       src="…/01-hero.jpg" style="max-width:100%; height:auto;" width="1200"/>
</picture>
```

Measured on the published post:

| format | total for 4 images | vs JPEG |
| --- | --- | --- |
| JPEG (before) | 138.1 KiB | — |
| WebP | 72.3 KiB | **−48 %** |
| AVIF | 50.7 KiB | **−63 %** |

The hero alone goes 45.7 KiB → 22.6 KiB.

Two details that matter:

- **AVIF must be listed first.** The browser takes the first `<source>` whose
  `type` it supports, so WebP-before-AVIF silently throws away the extra 15 %.
  `check_perf.py` fails the build if the order is ever reversed.
- **The JPEG stays as the `<img>`.** It is the fallback for the ~3 % of browsers
  with no AVIF, and it is what Blogger's `data:post.featuredImage` extraction
  sees - which is also why the home-page card thumbnails are JPEG. This is a
  deliberate trade: an `<img>` that always works beats a card image 20 KiB
  smaller.

### 1.6 Caching

Images are served by jsDelivr, which already sends
`cache-control: public, max-age=604800` for a branch ref and
`max-age=31536000, immutable` for a commit-SHA ref. The theme's CSS is inlined
into the HTML by Blogger, so there is no stylesheet request to cache.

`perf/netlify.toml` holds the long-lived `max-age=31536000, immutable` rules for
the images, WebP/AVIF and theme, and `max-age=0, must-revalidate` for HTML, ready
for the day this output is served from a static host. The nginx equivalent:

```nginx
location ~* \.(avif|webp|jpe?g|png|woff2)$ {
    add_header Cache-Control "public, max-age=31536000, immutable";
}
location ~* \.html$ {
    add_header Cache-Control "public, max-age=0, must-revalidate";
}
```

The practical lever on Blogger is the URL, not the header: build with
`IMAGE_REF=$(git rev-parse origin/main)` to address images by immutable commit
SHA instead of a branch that jsDelivr caches for a week (POST_RULES.md §7).

### 1.7 Unused code

There is no bundle to split: no framework, no route-level chunks, and the only
first-party JavaScript is the visitor strip's inline ~1 KB (§1.8). The
reduction that was available was in CSS and fonts, and both were taken - the
four discrete Space Grotesk weights collapsed into one variable range, the
unused subsets stay unfetched thanks to `unicode-range`, and the Google Fonts
stylesheet request is gone entirely.

### 1.8 The live visitor strip (home page only)

The strip under the search bar - total visits · your country · your device ·
local time - was added with the explicit requirement of not moving any of the
metrics above. Budget, line by line:

- **Markup is home-page-only.** Both the strip and its script sit inside
  `<b:if cond='data:view.isHomepage'>`; every other view ships neither. Item
  pages keep exactly the weight they had.
- **FCP / LCP: untouched.** The script is inline at the end of `<body>`, so it
  is neither a request nor a parser pause. The two network fetches (`abacus.jasoncameron.dev`
  and `ipwho.is`) are deferred to true browser idle via `requestIdleCallback` (with a 3.5s timeout /
  2.5s fallback) so they never contest bandwidth with the LCP image or critical path assets during
  initial page load.
- **Zero image/font cost.** Icons are inline SVG in `currentColor`; the country
  flag is an emoji composed from the ISO code with `String.fromCodePoint`
  (each regional indicator letter = codepoint + 127397), so there is no flag
  sprite, no icon font, no extra origin at all.
- **TBT / INP: ~0.** The script body is a few `getElementById`s and a UA test.
  The count-up is one 700 ms `requestAnimationFrame` loop, after which the page
  holds no frame work at all; the clock writes one `textContent` per second.
- **CLS: 0.** The skin reserves the strip (`min-height` + fixed cell padding)
  with em-dash placeholders; real values swap in place. The two `@keyframes`
  animate only `transform` and `opacity` (no width/height/top reflow), and the
  global `prefers-reduced-motion` block collapses them - the JS additionally
  skips the count-up outright instead of animating it anyway.
- **Failure is invisible.** If either service is down the cell keeps its em
  dash. No retry loop, no error state, no layout change.
- **Privacy.** No cookies, no localStorage, nothing written about the visitor.
  The Abacus hit increments one page-view counter; ipwho.is sees the visitor's
  IP to answer the country, as any fetched server does. The strip is also why
  the Privacy Policy page should not claim "no third-party requests".

---

## 2. Accessibility

**Link names.** Every `<a>` and `<button>` in the theme has an accessible name;
`check_perf.py` verifies it by unwrapping the Blogger tags and reading each
element's text, `aria-label`, `title`, or nested `<img alt>`.

- The four social icons are SVG-only, so each carries `aria-label` (`Facebook`,
  `Instagram`, `YouTube`, `WhatsApp`) - and now `rel='noopener noreferrer'`,
  because `target='_blank'` without it is a reverse-tabnabbing hole that the
  Best Practices audit reports. They are 34px round buttons (`width`/`height`
  on the anchor, not just the glyph), which is the tap-target item, and the row
  sits in the right-hand corner of the header bar: `.brand-row` is a
  `minmax(0,1fr) auto` grid, because a wrapping flex row dropped the icons onto a
  second line and left-aligned them under the wordmark (see `theme/README.md`).
- The card image is a second link to the same post as its title, so it stays
  `aria-hidden='true' tabindex='-1'`: a screen reader gets one link, not two.
- **"Read more" was the real failure.** Repeated once per card, it announces as
  an identical list of "Read more, Read more, Read more". Each now carries

  ```xml
  expr:aria-label='"Read more: " + data:post.title'
  ```

  while the visible text stays "Read more →" - the accessible name is
  descriptive, the design is unchanged.

**Keyboard.** A skip link is the first element in `<body>`, targeting
`<main id='main-content' tabindex='-1'>`; it is off-screen until focused. The
search field had `outline:0`, which removed the focus indicator from the one
input on the page - it now has a visible ring, and a global `:focus-visible`
rule covers every interactive element (light ring on the dark nav and footer).

**Contrast (WCAG AA, 4.5:1).** All 13 text/background pairs the skin paints now
pass, computed live from the stylesheet rather than from a table, so recolouring
a variable fails the check:

| pair | ratio |
| --- | --- |
| body text on card | 16.51:1 |
| nav links on `--ink` | 14.33:1 |
| code block | 14.94:1 |
| meta, dates, tagline | 6.13:1 |
| Read more / search button label | 6.02:1 |
| card tag chips | 5.33:1 |
| footer copyright | 7.56:1 (was `#8991A0`) |
| search placeholder | 7.96:1 |

The post bodies carry their own inline colours, which the skin audit cannot see.
The image captions used `color:#777` on white = **4.48:1** - just under the
threshold, and the kind of thing that only shows up in a real audit. They are now
`#5B6270`, the theme's own `--ink-soft`, at 6.13:1. `check_perf.py` extracts
every inline `color:`/`background:` pair from the built post HTML and checks it,
so the next post cannot reintroduce one.

**Motion.** `@media(prefers-reduced-motion:reduce)` collapses the card and
Read-more transitions.

**Structure.** One `<h1>` per page (the post title; card titles are `<h2>`,
sidebar widget headings `<h2>`, footer `<h3>`), no skipped heading levels, and
`<html expr:lang='data:blog.locale'>` was already correct.

---

## 3. SEO

**Meta description.** The blog had none on any page. Two settings in
`sample export/settings.csv` explain why: `blog_description` is empty *and*
`blog_meta_description_enabled` is false, so Blogger's `all-head-content` never
emits one and `SEARCH DESCRIPTION:` in every `post.html` went nowhere.

The theme now guarantees one, and steps aside the moment a real one exists:

```xml
<b:if cond='not data:blog.metaDescription'>
  <meta content='Free PDFs, self-made apps and clean config files, plus step-by-step
  guides for Python, Git and free-tier hosting. No cracked software, no clutter.'
        name='description'/>
</b:if>
```

146 characters, inside the 120-160 window. The guard is what makes it safe: turn
on **Settings → Search preferences → Meta tags → Description** and
`data:blog.metaDescription` becomes non-empty, `all-head-content` emits the
per-post description, and this branch stops firing - so there is never a
duplicate.

**To get per-post descriptions** (worth doing - the fallback is generic):
Settings → Search preferences → Meta tags → Description → **Edit** → paste the
146-character text → Save. From then on `import.xml`'s
`<blogger:metaDescription>` is honoured and each post describes itself.

**Also added:** `og:title` / `og:description` / `og:type` / `og:url` /
`og:site_name` and `twitter:card`, because the posts get cut into Shorts and
Reels (POST_RULES §11) and the share preview has to carry the hook on its own;
a `Blog` JSON-LD block; `theme-color`; and a visible tagline in the header when
`data:blog.description` is empty, so the home page has real descriptive text
above the fold instead of a blank line.

---

## 4. Best Practices

- `rel='noopener noreferrer'` on every `target='_blank'` link.
- The theme is validated as well-formed XML before upload - Blogger rejects the
  file outright otherwise, and `check_perf.py` parses it with `ElementTree`.
- No first-party JavaScript at all, so no console errors, no vulnerable
  libraries, and nothing for the "unused JavaScript" audit to find.
- The `<img>` inside every `<picture>` is a plain JPEG, so no browser is left
  with a broken image.

---

## 5. Doing this for the next post

The whole pipeline is in the build, so a new post gets it for free:

```bash
cp -r posts/_template posts/2026-10-01-my-post
# write post.html; reference images by bare file name: <img src="01-hero.jpg" alt="…">
#   no width, no height, no <picture> - the build adds all three
python3 tools/optimize_images.py 2026-10-01-my-post   # AVIF + WebP variants
python3 tools/build_import.py 2026-10-01-my-post      # fails if the hero is lazy, an
                                                      # <img> has no alt, or a caption
                                                      # colour fails contrast
python3 tools/check_perf.py                           # 88 checks across theme + posts
# publish with import.xml, then:
python3 tools/check_published.py 2026-10-01-my-post   # what Blogger actually kept
```

`check_published.py` is the last step for a reason: Blogger's importer rewrites
post HTML, and only the live feed shows whether `<picture>`, the AVIF/WebP
sources, `width`/`height` and `fetchpriority` survived the trip. It reports each
one separately, and if Blogger did strip the `<picture>` wrappers the post still
renders - the `<img>` fallback is the JPEG - you just lose the compression, and
the tool says so instead of leaving you to notice a slow page.

## 6. Re-measuring

After uploading `theme/freestackhub-theme.xml` and re-importing the post, run
PageSpeed Insights on both the home page and the post permalink. Compare against
this file's claims: FCP should drop with the font stylesheet gone, LCP with the
eager hero, CLS should read 0, and the contrast and link-name audits should clear.

Anything still failing that is not listed here is Blogger's own payload, not this
repo's - check the "Network requests" table in the report and see whether the URL
is on `blogspot.com` / `blogger.com` before editing the theme again.
