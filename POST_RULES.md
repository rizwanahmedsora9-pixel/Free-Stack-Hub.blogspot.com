# Rules for new posts

Every post is **one self-contained folder** with its own images and its own import file.
Nothing is shared between posts, so importing one post can never touch another.

```
posts/
  2026-09-16-stop-deleting-pythonanywhere-files/
    post.html      source (metadata header + HTML body)      <- written by hand/agent
    post.md        readable markdown copy (optional)
    images/        only this post's images, plus the GENERATED .avif/.webp
                   variant of each one (see section 4)
    import.xml     GENERATED - the file you import into Blogger
    paste.html     GENERATED - copy-paste-ready body (full image URLs) for the
                   Blogger editor's HTML view
    title.txt      GENERATED - the exact title, so you never retype it by hand
    video/         GENERATED - storyboard.json, blog-to-video-vertical.mp4 and
                   blog-to-video-wide.mp4 (see section 11)
  _template/       copy this to start a new post
```

## 1. Folder name, and the URL the post actually has
`YYYY-MM-DD-slug` — date first, then a short lowercase slug with dashes.
The date becomes the post's publish date (unless `PUBLISHED:` overrides it) and the slug
becomes the Blogger URL (`/2026/09/slug.html`) — **but only when you publish with `import.xml`**,
which writes `<blogger:filename>`. Paste-published posts get a URL built from whatever title was
typed into the editor, and a `_<number>` suffix if that URL was already taken.
Never rename a folder after import: `check_published.py` matches repo → live on the slug, and a
post's images are served from its folder path, so renaming breaks every image already published.

**What you do NOT have to do per post:** the canonical tag. Blogger emits
`<link rel='canonical'>` itself for every page from the theme's
`<b:include data='blog' name='all-head-content'/>`, and it always points at the post's own URL
(the mobile `...html?m=1` variant included), on all five published posts. `tools/check_perf.py`
fails if that include ever goes missing, if a second canonical is hand-written, or if a `noindex`
appears, and `tools/check_published.py` re-reads the live `<head>` after every publish - so the tag
is checked, not assumed. Do not add one by hand: two canonicals conflict.

**When the live URL is not the folder slug, record it** — add a `PERMALINK:` line to the header,
next to `PUBLISHED:`:

```html
PERMALINK: install-python-in-termux-build-and-run
```

A bare slug, `/2026/09/slug.html` or a full URL are all accepted. The build then writes that URL
into `<blogger:filename>` (so a later import lands on it) and `check_published.py` compares the
live post against it instead of against the folder slug. Set it for every post that is already
live at a Blogger-generated URL, and **write every link to that post with that URL** — the
folder-slug URL is a 404, and a post full of 404 links reads to Google like a broken page.

## 2. post.html header (required)
```html
<!--
TITLE:  Post title
LABELS: Label One, Label Two          (comma separated, these become Blogger labels)
PUBLISHED: 2026-09-16                 (optional)
PERMALINK: the-live-slug              (optional, section 1 - only when Blogger's URL is not the folder slug)
SEARCH DESCRIPTION:
One or two sentences for search engines. New posts: 150-160 characters,
unique to this post, and the target keyword in it (section 14, rule 2).
TARGET KEYWORD: the exact phrase people would search   (required on new posts, section 13)
-->
```
Then the HTML body. Use `<h2>` for sections, `<p>`, `<ul>/<ol>`, `<code>`, and the
`<pre>` style block from the template for code. `TARGET KEYWORD:` stays in the header so the
next edit still knows the phrase. The build reads it (so it is not swallowed into the search
description) and does not print it on the page. `TITLE:` stays 50-60 characters with the
keyword in the first half (section 14, rule 1).

## 3. Story structure (the homepage teaser is cut from exactly this)
1. **Feature image first** - one `<img>` in the very first block, before any text.
2. **Hook next** - 2 to 4 short sentences in a single `<p>`. Create tension (a mistake, a
   surprising result, a problem the reader recognises), never hand over the answer, and never
   read like an ad. This is the *only* prose a reader sees before clicking.
3. **Jump break right after the hook** - a line containing only `<!--more-->`.
4. **Everything else after the break** - the problem in detail, the fix, the steps, code,
   further images. Length is free here.
5. **One break per post** - never a second one, never at the very end.
6. **End with a recap or a call to action** - the closing `<ol>` also becomes the video's
   recap card, so make it the real summary.

The build (section 5) **fails the post** if the marker is missing, doubled, last, or if the
teaser is not one image plus a 2-4 sentence hook, so a post cannot ship with a ragged teaser.
The marker lives only in `post.html`: `import.xml` and `paste.html` are written without it,
and the build prints the sentence the break belongs after. In Blogger put the cursor there and
use **Insert -> Jump break**. The home-page cards themselves show **no body text at all**:
the theme (`theme/freestackhub-theme.xml`) builds each card as feature image + labels + title +
date + **Read more**, and the title and the button both open that post's own URL. (The cards
used to print `data:post.snippets.long`, which shows up as a wall of the post itself - roughly
its first 1000 characters - so the snippet was removed from the card entirely.) The jump break
still matters for feeds and for any view Blogger trims at the break, so keep writing it.

## 4. Images
- Put them in the post's own `images/` folder, named `01-…jpg`, `02-…jpg` in order of appearance.
- In `post.html` reference them by **bare file name only**: `<img src="01-hero.jpg" alt="…">`.
  Write **no** `width`, `height`, `<picture>`, `loading` or `fetchpriority` - the build adds all
  of them from the file itself, and overwrites anything you typed (section 5).
- Every image needs `alt` text.
- **Strict Hero Image (01-hero) LCP Budget (enforced by build & audit)**:
  The first image (`01-hero.jpg`) is the post page's **LCP element** and feeds Blogger's homepage card.
  To ensure mobile and desktop LCP stays consistently low (under 2.5s on mobile Slow 4G):
  1. **Maximum width: 1200px** (e.g., 1200x675 for 16:9, or 1200x480). Never save 1400px+ images.
  2. **Hero JPG size limit: ≤ 70 KB** (warns above 60 KB; hard fail by `build_import.py` and `check_perf.py` at > 80 KB).
  3. **Hero AVIF variant size: ≤ 30 KB** (hard fail at > 30 KB).
  4. Subsequent body images: keep under ~100 KB JPG.
- Generate the modern-format variants, and commit them next to the JPGs:

  ```bash
  python3 tools/optimize_images.py <folder>     # writes NN-name.avif and NN-name.webp
  python3 tools/optimize_images.py --check      # report missing/stale variants, write nothing
  ```

  The build then wraps every image in a `<picture>` that offers AVIF (≈63 % smaller than the JPG
  on this blog's images), then WebP (≈48 %), then the JPG as the `<img>` fallback. **AVIF must be
  the first `<source>`** - the browser takes the first type it can decode - and the JPG fallback
  must stay, both for old browsers and because Blogger reads `data:post.featuredImage` from the
  `<img>`, which is what feeds the home-page cards.
- Captions and any other inline colour sit on the white card, so they must clear WCAG AA: the
  template's `color:#5B6270` is the theme's own `--ink-soft` at 6.13:1. Do not use `#777` - that
  is 4.48:1 and fails the contrast audit. `tools/check_perf.py` extracts every inline
  `color:`/`background:` pair from the built HTML and checks it.
- The build rewrites the `src` to a public URL; nothing is uploaded to Blogger manually.

## 5. Build
```bash
python3 tools/build_import.py                          # all posts
python3 tools/build_import.py 2026-09-16-my-post       # one post
python3 tools/build_import.py --check                  # validate only
```
The build **fails** if: folder name is wrong, TITLE/LABELS/SEARCH DESCRIPTION missing, an
`<img>` points to a file that isn't in `images/`, or the section 3 structure is off (missing or
doubled jump break, empty teaser, not exactly one feature image, hook outside 2-4 sentences).
It writes `title.txt` alongside `import.xml`/`paste.html` and warns about unused images.

The build also **produces and enforces** the Core Web Vitals markup, so a post cannot ship without
it. For every `<img>` it emits a `<picture>` with the AVIF/WebP sources ahead of the JPG, sets
`width`/`height` from the file's real pixels (this is what keeps CLS at 0 - the browser reserves
the exact box before the bytes arrive), and marks the **first** image
`loading="eager" fetchpriority="high"` because it is the LCP element, with `loading="lazy"
decoding="async"` on every later one. It fails if an image has no `alt`, no dimensions could be
read, the first image is lazy, or a later image is not lazy. `import.xml` is only re-stamped when
the post actually changed, so re-running the build never dirties the file.

## 6. Publish (two ways)
**Import (recommended):** Blogger → **Settings → Manage blog → Import content** → choose that
post's `import.xml`. One file = one post. This is the **only** route that carries the title,
the labels and the search description — the XML uses Blogger's own export format
(`<category scheme="tag:blogger.com,1999:blog-<blog id>">`, `<blogger:filename>`,
`<blogger:metaDescription>`), so they survive the trip.

**Copy-paste (body only):** open the post's `paste.html`, copy **all** of it, and paste into
the Blogger post editor with the HTML view active (pencil icon → HTML view). Then set the
title, labels and search description by hand — `paste.html` is the post body, so Blogger has
no way to know any of that. Skipping the labels is the usual miss: the post then has no
"Filed under" line and every `/search/label/...` page stays empty forever.

**Never paste `post.html` itself.** Its `<img>` tags use bare file names (`01-hero.jpg`), so
Blogger would look for the images on the blog's own domain and show them broken. Only the
generated `import.xml` / `paste.html` contain the full public image URLs.

To update a post already on Blogger, edit it in the Blogger editor (re-importing the same
file creates a second copy).

## 7. Public images (one-time)
Image URLs are `https://cdn.jsdelivr.net/gh/rizwanahmedsora9-pixel/Free-Stack-Hub.blogspot.com@main/posts/<folder>/images/<file>`.
This needs the repo to be **public** and the post merged to `main`.
To test from a branch before merging: `IMAGE_BRANCH=<branch-name> python3 tools/build_import.py`.

**jsDelivr caches a branch snapshot for about a week.** A brand-new folder merged to `main`
may therefore serve its images as 404 for a while, and the published post shows broken image
icons even though the files are on GitHub. When that happens, pin the build to the merge
commit instead — commit SHAs are immutable and never stale:

```bash
IMAGE_REF=$(git rev-parse origin/main) python3 tools/build_import.py <folder>
```

## 8. Verify what actually went live (do this after every publish)
```bash
python3 tools/check_published.py            # every post vs the live Blogger feed + CDN
python3 tools/check_published.py <folder>   # one post
```
It reads the public feed (`<blog>/feeds/posts/default?alt=json`) — no login, no API key —
and fails (`exit 1`) on the things that only ever go wrong on Blogger's side:

- the live **title** differs from `TITLE:` in `post.html` (someone retyped it, or pasted instead of imported)
- **labels** missing on the live post (empty `/search/label/...` pages, and nothing filing the post
  under its topic)
- **permalink** not matching the folder slug, or not matching the `PERMALINK:` recorded in `post.html`
  (Blogger generated the URL from the title at publish time and may have added a `_<number>` suffix)
- **images** present in the post but not served by the CDN yet, or images in the repo that the
  published post never references
- **internal links that 404** — every link the post makes back to the blog is fetched, and one that
  lands on Blogger's not-found page fails the post (`--no-links` skips the fetching)
- a post **no other published post links to**: a warning, not a failure, but it is the state Search
  Console describes as *Referring page: None detected*

The internal-link check exists because of a real miss: the posts went live at Blogger-generated
URLs while the links inside them were written from the folder slugs, so four links in one post —
and all four example links in section 12 — pointed at 404s. Nothing in the repo could see it.

It also notes when a post has no Blogger `media$thumbnail`: images hosted off-blog never get one.
That only affects Blogger's own widgets (Popular Posts, Featured Post, the `/feeds` thumbnail) -
the theme's home-page cards use `data:post.featuredImage`, i.e. the post's first image, so they
show a picture either way. Upload the first image inside Blogger too if you also want a thumbnail
in those widgets.

## 9. Blogger settings this repo depends on
Checked against this blog's own takeout export (`sample export/`), and worth knowing because
each one silently drops something the build files carry:

- **Settings → Search preferences → Meta tags → Description → Enable.**
  `blog_meta_description_enabled` is currently `false`, so the `SEARCH DESCRIPTION:` in every
  `post.html` goes nowhere. The theme now emits a 146-character fallback description of its own on
  every page while that is off, guarded by `<b:if cond='not data:blog.metaDescription'>`, so no page
  ships without one - but the fallback is generic. Enable the setting and paste a blog-level
  description to make `import.xml`'s `<blogger:metaDescription>` win, which gives every post its own
  snippet; the theme's fallback steps aside automatically and there is never a duplicate.
- **Settings → Posts, comments and media → Lightbox = No.** `blog_use_lightbox` is currently `true`,
  which makes Blogger inject its lightbox CSS/JS and wrap every post image in a generated `<a>`.
  That is extra render-blocking payload, and the wrapper link has no accessible name - both are
  things `check_perf.py` would fail if they were ours. Turn it off; the post images are already
  full width.
- **Settings → Posts, comments and media → Convert line breaks = On** (`blog_convert_line_breaks`
  is `true`). Right for typed text; for pasted `paste.html` it can add blank space between blocks
  that already have `<p>` tags.
- **Theme → Mobile:** Blogger serves one responsive template to both desktop and mobile
  (`show_mobile_view` is `false` in the blog's own export), which is what a `b:responsive='true'`
  theme wants - keep it. The mobile variant of a URL is still reachable as `...html?m=1`, and because
  Googlebot smartphone is now the primary crawler it is the bot that meets Blogger's redirect between
  the two. Two rules follow:
  - **Never remove `<b:include data='blog' name='all-head-content'/>` from the theme.** That one line
    is what emits `<link rel='canonical'>`, which is the tag that declares the `?m=1` URL and the
    clean URL to be the same page. `tools/check_perf.py` fails the theme if it is missing, if a
    second canonical is hand-written, or if a `noindex` appears.
  - **Never "fix" the `?m=1` reports** by disallowing `?m=1` in robots.txt, noindexing it, or
    stripping it with JavaScript - all three break the mobile/desktop relationship. See
    [INDEXING.md](INDEXING.md) section 2.
- **Time zone is `America/Los_Angeles`** while `PUBLISHED:` is read as midnight UTC, so a post
  dated `2026-09-16` shows and links as **Sep 15** unless you write the date with that offset in
  mind. The blog also has no **description** set (`blog_description` is empty), so page titles end
  as `Free Stack Hub: <post title>`.

Never rename a folder after import, and never retitle the post in Blogger: `posts/` is the source
of truth, and `check_published.py` reports the pair as a mismatch (exit 1).

## 10. Performance, accessibility and SEO (check before every merge)
```bash
python3 tools/check_perf.py             # 128+ checks; exit 1 if one would fail a Lighthouse audit
python3 tools/check_perf.py --verbose   # list the passing checks too
```
It runs offline with nothing but the standard library, and audits `theme/freestackhub-theme.xml`,
`theme/preview.html` and every post against Core Web Vitals and PageSpeed categories:
- **Low FCP**: No render-blocking stylesheets in head, fonts inlined with `font-display:swap`,
  primary font `Space Grotesk` preloaded in `<head>`, and preconnects to Google Fonts,
  Blogger image CDN (`lh3.googleusercontent.com`), and jsDelivr.
- **Low LCP**: Hero image strictly capped (≤ 1200px width, ≤ 70 KB JPG, ≤ 30 KB AVIF), marked
  `loading="eager"` + `fetchpriority="high"`, homepage cards scaled via `resizeImage(..., 640, "16:9")`,
  sidebar thumbnails scaled via `resizeImage(..., 72, "1:1")`, and third-party analytics deferred to idle.
- **Zero CLS**: Explicit `width`/`height` on every image derived from the file's real pixels,
  metric-adjusted font fallbacks to absorb font-swap reflow, and fixed 16:9 aspect-ratio containers.
- **Accessibility, SEO & Best Practices**: Accessible names on every link and button, contrast ≥ 4.5:1
  (including inline colours in post bodies), exactly one `<h1>`, no skipped headings, skip link,
  and 120-160 character meta description.

What it cannot check is Blogger's own widget CSS/JS, which is not ours to remove. **[PERFORMANCE.md](PERFORMANCE.md)
has the full reasoning, the measured numbers, and what to do if the live report still fails.**

After publishing, `tools/check_published.py` reports whether Blogger's importer *kept* the
`<picture>` wrappers, the AVIF/WebP sources, the `width`/`height` attributes and
`fetchpriority=high` - it rewrites post HTML, and only the live feed shows the result. If it
stripped them the post still renders (the `<img>` fallback is the JPG); you just lose the
compression, and the tool says so.

## 11. Video for a post (optional, one command per post)
```bash
python3 tools/make_video.py 2026-09-16-my-post --dry-run   # write video/storyboard.json only
python3 tools/make_video.py 2026-09-16-my-post              # narrated 1080x1920 + 1920x1080 MP4s
```
Needs `pillow` and an ffmpeg binary; `python3 -m pip install --break-system-packages
imageio-ffmpeg pillow` gets both (that package ships a static ffmpeg with libx264 + aac).

* The storyboard is: hook card (feature image + title + the section 3 hook), one card per
  `<h2>` after the break, then a recap/CTA card. `--max-cards` merges extra sections instead of
  dropping them.
* `video/storyboard.json` is the edit surface: change a card's `title`, `image`, `voiceover` or
  `subtitle` there and re-run with `--reuse-storyboard`. Keep `voiceover` short - it is also
  what appears as the burned-in caption, so spoken copy and subtitles never disagree.
* Narration goes in `video/narration/` as `01.mp3`, `02.mp3`, ... one clip per card, in card
  order. Each card is timed to its own clip, so audio and captions cannot drift; a card without
  a clip falls back to word-count timing and is padded with matching silence.
* Output is `blog-to-video-vertical.mp4` (Shorts/Reels/TikTok - keep it under ~60s by capping
  `--max-cards`) and `blog-to-video-wide.mp4` (YouTube/X). Both are committed; `narration_full.m4a`,
  `list_*.txt` and `frames_*/` are generated intermediates and are git-ignored.

**Blogger cannot host video.** Upload the two files to YouTube and link them from the post, or
embed the wide one with a `<iframe>`; never expect the MP4 in the post folder to stream itself.

## 12. Interlinking rule (mandatory across all posts)
Every post published on Free Stack Hub must actively participate in an interconnected internal linking structure:

- **Mandatory interlinking:** Every post **must** include natural, contextual links to other published posts on the blog. The minimum is two links per post, placed where the topic comes up - never dumped after the recap (section 14 rule 3).
- **Related posts are mandatory links ("specially related must"):** Whenever a post touches on a related topic, tool, or stack layer, it is strictly required to link to the existing sister posts. For example:
  - Any mobile/terminal post must link to [Termux Commands Worth Memorising: Basics, Git Cloning and Nano on Android](https://freestackhub.blogspot.com/2026/09/termux-commands-worth-memorising-basics.html).
  - Any Python or deployment post must link to [Stop Deleting Your PythonAnywhere Files on Every Update. Use Git Instead](https://freestackhub.blogspot.com/2026/09/stop-deleting-your-pythonanywhere-files.html).
  - Any performance or web speed post must link to [Check Your Website's Vital Scores with PageSpeed Insights](https://freestackhub.blogspot.com/2026/09/check-your-websites-vital-scores-with.html).
  - Any SEO or site discovery post must link to [Google Search Console from Zero](https://freestackhub.blogspot.com/2026/09/google-search-console-from-zero-add.html).
- **Use the target's real URL.** Those links are the posts' live permalinks, not their folder names.
  Every post's `PERMALINK:` in `post.html` is the URL that exists on the blog; a link built from the
  folder slug is a 404, and `check_published.py` now fails the post for it.
- **Link both ways.** Linking out to four related posts while nothing links back leaves the newest
  post with no inbound internal link at all — Search Console reports that as
  *Referring page: None detected*, and a page nothing links to is the easiest one to leave out of
  the index. When a new post goes up, go back and add a contextual link to it from the sister post
  it continues (one sentence is enough).
- **Descriptive anchor text:** Always use descriptive, human-readable anchor text that clearly identifies the target topic (e.g., `<a href="https://freestackhub.blogspot.com/2026/09/termux-commands-worth-memorising-basics.html">our step-by-step Termux terminal commands and nano guide</a>`). Never use generic text like "click here", "read more", or unformatted raw URLs.
- **Future posts commitment:** In every future post, interlinking to existing posts (especially related ones) is a required quality gate before merging.

## 13. Writing rule: original, searchable, and not a rehash

This is the writing brief for every **new** post, on top of sections 3, 4 and 12. The five
posts already live are not rewritten to match it. The topic and the exact search phrase come
from the request. If either is missing, ask before writing. Record the phrase as
`TARGET KEYWORD:` in the header.

Audience: beginners who want clear, honest, no-fluff guidance on free and open-source ways to
build and host things (Python, Git, Termux, free hosting, dev tools). Write at least **1200
words** of original prose (paragraphs, lists, headings, quotes) (section 14 rule 7). Do not pad with repetition,
generic disclaimers, or the same point said twice. Code blocks, alt text and captions do not
count toward the 1200. Every paragraph has to earn its place.

1. **Open on a real mistake.** The section 3 hook is that opening: 2-4 sentences, one specific
   pain point or error a beginner actually hits, then `<!--more-->`. Not "In this guide, you
   will learn…", and not "In today's digital world…".
2. **Three things the official docs do not say.** At least three of: a gotcha you only learn by
   doing it, a real error message and the fix that actually works, a comparison of two approaches
   with an opinion on which is better and why, or a timing or size you measured. "It depends" is
   not one of the three.
3. **Shape.** Clear `<h2>` / `<h3>` (section 14 rule 5: no `<h1>` in the body, no `<h3>` without
   a parent `<h2>`), paragraphs of 2-4 sentences, and at least one `<ul>` or `<ol>` where a list
   is the honest shape (the closing recap counts, a list in the body is better when the steps
   are the point).
4. **Voice.** Direct, human, slightly conversational. Not robotic, not keyword-stuffed, no filler.
5. **Close on a next action.** After the section 3 recap `<ol>`, one short closing paragraph:
   what to do next, or the follow-up mistake to avoid. Not "Hope this helped!"
6. **Keyword, once each, never forced.** The target keyword appears in `TITLE:` (in the first
   half), in exactly one `<h2>`, and in the opening paragraph (the hook). Nowhere else unless
   the sentence needs it. `TITLE:` stays **50-60 characters** (section 14 rule 1).
   `SEARCH DESCRIPTION:` is **150-160 characters**, unique to this post, and includes the keyword
   once, naturally (section 14 rule 2). It still only reaches Google after the section 9
   setting is on; write it anyway.
7. **Exactly 7 images, each one a screenshot the reader needs.** After a command, an error, or
   the final output — not decoration, not a stock hero with nothing to look at. Count the feature
   image: `01-….jpg` through `07-….jpg`, in the order they appear. Section 4's hero budget still
   applies to `01`. Every image gets a descriptive alt and a one-line caption (section 14 rule 6).
8. **Two or three internal links, already real, plus one outbound.** A related post on this blog gets a normal
   sentence and a descriptive `<a>`. Section 12 decides the URL: the target's live permalink,
   never `href="#"`, never a folder slug, never "click here". If the sister post does not exist
   yet, leave the sentence out and name the missing topic in `post.md`. Add one outbound link
   to an official source for the post's main tool - docs, GitHub repo, or wiki (section 14
   rule 4). A guessed URL is how the live posts shipped four 404s. When this post continues an
   older one, add the return link in that older post too.

**What the brief's output format means in this repo.** Do not hand Blogger a loose HTML blob,
and do not leave image placeholders in the file that gets built.

| The brief says | Write this instead |
|---|---|
| SEO title on its own line, 50-60 characters, keyword first | `TITLE:` in the header (section 14 rule 1) |
| Meta description, 150-160 characters | `SEARCH DESCRIPTION:` in the header (section 14 rule 2) |
| `<img src="REPLACE_ME_1.png">` … `REPLACE_ME_7.png` | bare `<img src="01-short-name.jpg" alt="…">` through `07-…`. The build rejects a src that is not a file in `images/` |
| `<figcaption>` | the template's caption line: `<div style="font-size:13px; color:#5B6270; margin-top:6px;"><i>One line: what the reader is looking at.</i></div>`. `#777` fails the contrast check |
| alt text | specific enough that someone could take the screenshot from the alt alone (section 14 rule 6) |
| paste into Blogger's HTML view | `post.html` is the source. `paste.html` is generated. Never paste `post.html` |
| tags limited to `h2 h3 p ul li strong em blockquote img figcaption a` | those, plus the house tags the build and the template already use: `<ol>`, `<code>`, `<pre style="background:#0d1117; color:#c9d1d9; padding:14px 16px; border-radius:8px; overflow-x:auto; font-size:14px;">`, the caption `<div>`, and one `<!--more-->`. No `<html>`, `<head>`, `<body>`, `<picture>`, or a hand-written canonical |

Generate the seven images into `images/` before the build (section 4). A post that still says
`REPLACE_ME` is not finished.

## 14. SEO rules - every post, no exceptions (the 10 rules)

Sections 12 and 13 say what to write. This section says what every post must *pass* before it
goes live - the same ten rules, checked the same way, on every post. The build enforces the
automatable half: a post with `TARGET KEYWORD:` set (every new post) **fails** on any of them.
The five Sep 16-19 posts predate this section, so the judgement rules (1, 2, 3, 4, 7) print as
**warnings** on them - visible in `build_import.py` and `check_perf.py`, but they do not fail
the build. Clear a warning the next time that post is edited: change the repo, mirror the same
edit on the live post (title, search description, or body - a title edit on an already-published
post keeps its URL), and re-run `check_published.py`. The never-rules (5, 6, 8) are errors for
every post: no live post trips them. Rules 9 and 10 are process, not markup - the checklist
enforces them, not code.

| # | Rule | Checked by |
|---|---|---|
| 1 | Title 50-60 characters, keyword in the first half | `build_import.py` (error on new posts, warning on the five legacy ones) |
| 2 | Unique 150-160 character search description with the keyword | `build_import.py` (length, keyword); `check_perf.py` (uniqueness across posts) |
| 3 | At least 2 internal links, descriptive anchors, placed in context | `build_import.py` (count, anchors, placement); `check_published.py` (live count, 404s) |
| 4 | At least 1 outbound link to an official source | `build_import.py`; `check_published.py` (live presence) |
| 5 | H2 sections, H3 only under H2, no H1 in the body | `build_import.py` (error on every post) |
| 6 | Descriptive alt plus a one-line caption per screenshot | `build_import.py` (error on every post) |
| 7 | 1,200+ words of prose, no padding | `build_import.py` (error on new, warning on legacy) |
| 8 | No test/placeholder/duplicate titles | `build_import.py` (test/draft/REPLACE_ME/lorem); `check_perf.py` (duplicate + near-duplicate titles) |
| 9 | Uniqueness search before publishing | manual - checklist step 1 |
| 10 | One topic lane at a time | manual - checklist step 1; `check_perf.py` warns when the newest post shares no label with the previous three |

1. **Title length: 50-60 characters max. Put the main keyword in the first half.** `TITLE:` is
   50-60 characters and the `TARGET KEYWORD:` starts in its first half. Never write a title you
   have to trim in your head - if it needs "and," "with," or a colon-subtitle to explain
   everything, cut it down before publishing. The keyword also appears in exactly one `<h2>` and
   in the hook (section 13.6); the build checks all three placements.
2. **Meta description required - never leave blank.** Every post has its own unique
   `SEARCH DESCRIPTION:` (150-160 characters), carrying the keyword once, naturally, and
   describing what THIS post specifically covers - not a generic blog blurb. On the import route
   `import.xml`'s `<blogger:metaDescription>` carries it (once the section 9 setting is on); on
   the paste route, paste it into the editor's Search Description field by hand. Never let a post
   fall back to the sitewide default.
3. **Internal links: minimum 2 per post.** At least two links to two other existing posts, with
   descriptive anchor text - never "click here," "this post," or a raw URL. Place them where the
   topic comes up in the body; at least one must sit before the final `<h2>`, never dumped after
   the recap. Use each target's live permalink (sections 1, 12), and add the return link from the
   sister post this one continues.
4. **Outbound links: minimum 1 per post, where relevant.** Every tutorial names a tool, a
   language, or a platform - so every tutorial links out to at least one official/primary source
   for it: official docs, the GitHub repo, the official wiki. This is a trust signal; do not skip
   it just because it sends traffic away.
5. **Headings: H2 for main sections, H3 for sub-points within a section.** Never skip a level -
   no `<h3>` without a parent `<h2>`, no `h2`->`h4` jumps. The post title is the page's H1
   (handled by the theme); never add a second H1 inside the body.
6. **Images: descriptive alt, one-line caption, every screenshot.** Each alt describes what is
   actually in the screenshot (at least 15 characters - never "image1" or the filename) so
   specifically that someone could take the screenshot from the alt alone. Each screenshot gets
   the template's one-line caption underneath saying what the reader is seeing.
7. **Word count floor: 1,200 words minimum for a tutorial/guide post.** Prose only - code
   blocks, alt text, and captions do not count. Never pad to hit this: if the topic is naturally
   shorter, it is the wrong topic for a full post; make it a short update or roll it into a
   bigger post instead.
8. **No test/placeholder posts published, ever.** Draft and delete test content before it ever
   hits "Publish." A title containing "test" or "draft," a body containing `REPLACE_ME` or lorem
   ipsum, and a title identical or near-identical (at least 90% similar) to another post's title
   does not go live - full stop. (Titles at least 80% similar warn.)
9. **Uniqueness check before publishing.** Search the exact target keyword first. If the top 3
   results already cover this angle thoroughly, the post must add something they do not - a real
   error/fix, a comparison, a personal benchmark, an opinion - before it is allowed to publish.
   That is section 13's "three things the official docs do not say," aimed at the live results,
   not the docs. Re-explaining existing docs in your own words is not enough on its own.
10. **One topic lane at a time.** Do not scatter across unrelated tool categories in the same
    week. Cluster related posts (e.g. all Termux, then all Git) so the blog builds topical
    authority before jumping elsewhere. In this repo the lane shows in the labels: the newest
    post should share at least one label with the previous three.

## Checklist for the agent when adding a post
1. Lane first, then uniqueness (section 14 rules 9-10): confirm the post continues the current topic lane (it should share a label with recent posts), and search the exact target keyword. If the top 3 already cover the angle, the draft must add an error/fix, a comparison, a benchmark, or an opinion - re-explaining docs is not enough. Record the phrase as `TARGET KEYWORD:`.
2. `cp -r posts/_template posts/YYYY-MM-DD-slug`
3. Write `post.html` (+ `post.md`) to sections 13-14: 1200+ words of prose, a real opening mistake, three details the docs skip, `TITLE:` at 50-60 characters with the keyword in the first half, `SEARCH DESCRIPTION:` at 150-160 characters unique to this post with the keyword once, no `<h1>` in the body, no `<h3>` without a parent `<h2>`, no test/draft title. Generate exactly 7 images into `images/` (`01`-`07`), each with a descriptive alt and a one-line caption, bare `<img src alt>`, no sizes, no `REPLACE_ME`
4. Write to section 3: feature image, then a 2-4 sentence hook containing the keyword, then the break marker, then a recap `<ol>` and a closing that says what to do next
5. Apply sections 12 and 14 together: 2-3 contextual internal links to related posts (each target's live URL, never `href="#"`, a folder slug, or "click here"), at least one outbound link to an official source, links placed where the topic comes up - and a return link from the sister post this one continues
6. `python3 tools/optimize_images.py YYYY-MM-DD-slug` → the `.avif`/`.webp` variants
7. `python3 tools/build_import.py YYYY-MM-DD-slug` → must print no ERROR
8. `python3 tools/check_perf.py` → must print `clean`
9. Commit the whole folder including the image variants, `import.xml`, `paste.html` and `title.txt`
10. Publish with **`import.xml`** (not `paste.html`, unless you retype title + labels + search description by hand)
11. `python3 tools/check_published.py YYYY-MM-DD-slug` → must print no FAIL. It follows every internal link the post makes and fails the ones that 404, checks the live link counts against section 14, and warns when no other post links here. If Blogger gave the post a different URL than the folder slug, check what it actually got and put it in the header as `PERMALINK:` (see section 1), then fix the links that used the slug.
12. `python3 tools/make_video.py YYYY-MM-DD-slug` for the two social videos
