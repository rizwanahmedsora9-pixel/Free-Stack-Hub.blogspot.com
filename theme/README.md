# Blogger theme

`freestackhub-theme.xml` is the theme for [freestackhub.blogspot.com](https://freestackhub.blogspot.com).
It is the **source of truth** for how the blog is laid out; the copy of the theme that lives in
Blogger is only a copy. `preview.html` is a generated static mock of it, so a design change can be
looked at in a browser before it goes anywhere near Blogger.

```
theme/
  freestackhub-theme.xml   the theme, upload this to Blogger (backup/restore)
  preview.html             GENERATED - static mock of the home page + post page
```

`python3 tools/check_perf.py` audits this theme - and `preview.html`, and every post - against the
Lighthouse Performance / Accessibility / Best Practices / SEO audits, offline and with no browser.
Run it before uploading; it exits 1 if a change would fail one. **[../PERFORMANCE.md](../PERFORMANCE.md)
has the reasoning and the measured numbers behind every item below.**

## Fix: the home page showed whole posts instead of teaser cards

The archived theme described only one thing for the Blog widget:

```xml
<b:widget id='Blog1' locked='true' title='Latest Downloads' type='Blog' version='2'>
  <b:includable id='shareButtons' var='post'/>
</b:widget>
```

Blogger keeps its own defaults for every includable a theme does not define, and its default
Blog widget renders the **whole** post on list pages: `postBodySnippet` is just
`postBody` → `<data:post.body/>`. On a `layoutsVersion='3'` theme (this one) Blogger no longer
cuts `post.body` at the jump break, and the default post footer has no jump link either, so the
home page printed every post in full, with no *Read more* anywhere. That is exactly what the live
page did - compare `sample export/takeout-*.zip` → `theme-layouts.xml`, which is the same widget
after Blogger filled the defaults in.

The fixed theme defines the Blog widget's includeables itself, so the chain is explicit:

| view | what renders |
| --- | --- |
| home / label / search / archive | one **card** per post: feature image full width on top, then labels, title, date and a **Read more** button — no body text |
| card click | `data:post.url` - that post's own permalink |
| post / page | full `data:post.body`, title, date, labels ("Filed under"), comments, then Blogger's schema block for SEO |
| under the list | the pager (`← Newer Posts` / `Older Posts →`) |

Key data tags, and why these ones:

- No snippet tag at all - the cards used to print `data:post.snippets.long`, but Blogger fills
  that with roughly the first 1000 characters of the post (it does not reliably stop at the
  jump break), so the home page read like the full post. Cards are image + labels + title +
  date + **Read more** now; the post body is only ever sent on the post's own page.
- `data:post.featuredImage` - the first image of the post. Cards therefore have a picture even
  though Blogger never generates a `media$thumbnail` for jsDelivr-hosted images (the caveat in
  `POST_RULES.md` §8 no longer applies to the home page). `thumbnailUrl` is the fallback.
- `data:post.hasJumpLink` / jump-break text - not needed any more: every card ends in the same
  *Read more* button, whether or not the post has a break. (`POST_RULES.md` §3 requires one.)

## Fix: the social icons wrapped under the wordmark instead of sitting opposite it

The header row used to be a wrapping flex box:

```css
.brand-row{min-height:100px;display:flex;align-items:center;
  justify-content:space-between;padding:18px 0;gap:20px;flex-wrap:wrap}
```

`flex-wrap` is the whole bug. The brand `<a>` sizes to its content (wordmark *plus*
tagline), so as soon as that and the four icons no longer fit side by side - any phone,
or a desktop with a long-enough `data:blog.description` - the icons dropped to a second
line. A wrapped flex line then holds one item, and `justify-content:space-between`
left-aligns a single item, so they landed *under* "Free Stack Hub", on the same edge as
the brand. That is the "icons below the title" look.

The bar is now a two-column grid, which has no wrap to fall back on:

```css
.brand-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;
  min-height:100px;padding:18px 0;column-gap:24px}
.social-row{display:flex;align-items:center;justify-content:flex-end;gap:6px}
```

- Brand in the left corner, icons pinned to the right edge on every width; under
  `560px` the row only gets tighter (smaller wordmark, 31px icon buttons), it never
  re-wraps.
- `minmax(0,1fr)` + `overflow-wrap` on `.brand-title`/`.brand-tagline` mean a long title
  squeezes the *brand* column instead of pushing the icons around.
- Icons are now 34px round buttons (19px glyph inside) with a tint on hover/focus, which
  also clears the tap-target complaint the 18px bare glyph used to raise on mobile.

## Follow-up: brand text and icons hug the top of the bar together

A later change pinned the icons to the top of the bar (`align-self:start` on `.social-row`)
while the grid still centred the brand column (`align-items:center` on `.brand-row`). The
icons hugged the top edge and the wordmark floated at the bar's vertical middle - the two
corners visibly disagreed. The grid now uses `align-items:start`, putting **both** corners
on the top edge (the leftover slack of the `min-height:100px` bar sits below both equally).
If the two ever cannot share the top edge, the rule is to centre **both** again - never one
top, one middle.

## The search bar: a combo box above the navbar

The search field moved from under the navbar to **just above it**, and it is no longer a bare
input: it is a combo box. Type one word and a list drops under the field; keep typing and the
list narrows, word by word - **every word you have typed has to appear in a title or a label**,
the last one only as far as you have got, so `git` → `git hub` → `git hub pythonanywhere`
refines instead of starting over. Word order does not matter, a word matched at the start of a
title word outranks one matched inside it, and the phrase you typed comes back highlighted in
`<mark>`.

```
header  →  search bar (combo box)  →  navbar  →  visitor strip (home only)  →  ad  →  cards
```

What is in the list, most relevant first: up to **7 posts** (title + its labels), up to **2
matching labels** ("Category · every post filed under it"), and always **one last row** that
opens Blogger's own results page for the phrase - so a query that matches nothing still has
somewhere to go, and the `listbox` always holds at least one `option`, which its role requires.
Focus the field without typing and it lists the 5 newest posts instead of nothing.

**Where the suggestions come from.** This blog's own feed,
`<homepageUrl>feeds/posts/summary?alt=json&max-results=250` - the homepage is read back out of
the form's own `action`, so there is nothing per-blog to configure. It is **same-origin**: no
CORS handshake, no new origin to preconnect, no third party sees the query. One request,
fetched on the *first focus or first keystroke* and never during page load, so it cannot
contest bandwidth with the LCP image; only title, permalink and labels are kept (the feed's
post text is discarded) and the index then lives in memory for the life of the page. That is
why every later keystroke is instant and costs **zero requests** - it is local filtering, not
a search-per-keystroke. Nothing is written to a cookie or to localStorage.

**It is a search form first.** The markup is `role='search'` + one field named `q` + one submit
button, and the script only adds the list. JavaScript off, no `fetch`, an offline visitor, a
404 or a blog with nothing published yet all leave exactly what was there before: press Enter
and Blogger's own `/search?q=` page answers. (With no index loaded the last row says "Search
the blog for …" rather than "No title matches …", because it would be lying otherwise.)

**Keyboard and screen readers** follow the combobox pattern, which is the part that is easy to
get wrong: the `input` is `role='combobox'` with `aria-expanded`, `aria-controls` and
`aria-autocomplete='list'`; the `<ul>` is the `listbox`; the rows are `role='option'` with
`aria-selected`; and **focus never leaves the field** - rows are reached through
`aria-activedescendant` and their links are `tabindex='-1'`, so Tab still moves on to the
navbar instead of walking through nine suggestions. ↑/↓ (either one opens a closed list, and
they wrap), Enter opens the row you are on, Enter with no row active submits the form, Esc
closes, and the active row is scrolled inside the panel by hand - `scrollIntoView` can scroll
the *page* on some browsers, which would move the field out from under the visitor.

`check_perf.py` guards the wiring (the six ARIA attributes, the script being inline between its
markers, the bar being above the navbar, and six more contrast pairs for the panel), and
`preview.html` carries the **same script verbatim** plus a sample index built from `posts/`, so
you can type in the mock and see the real behaviour before uploading.

## The live visitor strip (home page only)

A slim four-cell strip sits between the navbar and the first ad slot: **total visits ·
your country · your device · local time**, with a pulsing green live dot. Blogger only sends
it on the main page - the markup and its script are both wrapped in
`<b:if cond='data:view.isHomepage'>`, so posts, pages, label, search and archive views carry
none of it.

Every number is real, and all of them stay off the critical path:

| cell | source | cost |
| --- | --- | --- |
| total visits | `abacus.jasoncameron.dev/hit/freestackhub/visits` - free open counter; `/hit/` auto-creates it, no key, no account | one ~300 B JSON GET, after `load` + idle |
| your country | `ipwho.is` free geo lookup; the flag is an emoji built from the ISO code (`String.fromCodePoint`), not an image | one ~500 B JSON GET, after `load` + idle |
| your device | UA string + `pointer:coarse` | none - no request |
| local time | JS `Date` | none - one `textContent` write/second |

Core Web Vitals reasoning is in `../PERFORMANCE.md` §1.8: inline script at the end of `<body>`
(no request, no parser block), SVG icons + emoji flag (no image/font requests), reserved cell
heights (em-dash placeholders swap in place, CLS 0), and the only animations are transform /
opacity on a one-shot rise and the 2px dot - collapsed under `prefers-reduced-motion` (the
count-up is skipped, not just sped up). Nothing is stored: no cookies, no localStorage. Note
`ipwho.is` necessarily sees the visitor's IP to answer the country, like any fetched server.
If either service is down the cell just keeps its em dash - no retry, no error, no shift.

To drop the strip, delete the block between `<!-- visit-strip:start -->` and
`<!-- visit-strip:end -->` (+ its `<b:if>`), the matching `<script>` at the end of `<body>`,
and the `.visit-*` rules in the skin; re-run `python3 tools/build_theme_preview.py`.

## Performance, accessibility and SEO

What the theme does now, and the reason each piece is there.

**Nothing in `<head>` blocks paint.** The Google Fonts `<link rel='stylesheet'>` is gone - it was a
stylesheet on a third origin whose only job was to name two files on a fourth, so first paint waited
on three round trips. The `@font-face` rules are inlined at the top of `<b:skin>` instead. Both
families are variable fonts, so a single file covers `font-weight: 400 700` (Space Grotesk) and
`400 600` (Source Serif 4); the old link asked for four discrete weights that all resolved to the
same file. `unicode-range` keeps an English page down to the two `latin` files. The theme adds no
`<script src>` of its own: the cards are pure server-rendered HTML (image + labels + title + date
+ Read more, no post text), and the only first-party JavaScript anywhere is two inline scripts at
the end of `<body>` - the live visitor strip's ~1 KB (home page only, does nothing until after
`load`) and the search combo box's ~4 KB (every page, does nothing until the field is focused or
typed in). Neither is a request, neither blocks the parser, and neither runs during page load;
`check_perf.py` fails the build if a `<script src>` ever appears in the theme. See "The search
bar" and "The live visitor strip" above.

**Both origins the page fetches from are preconnected:** `fonts.gstatic.com` for the woff2 files
(with `crossorigin`, which fonts require or the connection cannot be reused) and `cdn.jsdelivr.net`,
which serves the hero image - the LCP element.

**The LCP image is not lazy.** The card list loops with `<b:loop index='i'>` and wraps each card in
`<b:with value='data:i == 0' var='isFirst'>`, so `cardImage` can render the first card's image
`loading='eager' fetchpriority='high'` and every later one `loading='lazy'`. Before this, *every*
card image was `loading='lazy'`, including the one at the top of the page - a lazy LCP image is not
requested until after layout, so the browser finds its own largest element last.

**Nothing shifts.** Card `<img>`s declare `width='640' height='360'` and `.card-media` an
`aspect-ratio:16/9`, so the media column has a height before the image lands. Post images get their
`width`/`height` from the build, read off the real file. And because `font-display:swap` re-lays out
every line when the webfont arrives, two metric-adjusted faces - `'Space Grotesk Fallback'` and
`'Source Serif 4 Fallback'`, `size-adjust`/`ascent-override`/`descent-override`, `src:local()` -
sit behind the real ones in `--font-head`/`--font-body` and absorb the swap. They are estimates;
re-derive them if the swap still visibly moves text. `.sidebar .widget img` is pinned to a square
because Blogger's own PopularPosts/Label markup is not ours to add attributes to.

**Every link has a name.** The four social icons are SVG-only, so each has an `aria-label`. The card
image is a second link to the same post as its title, so it stays `aria-hidden='true'
tabindex='-1'`. The important one is *Read more*: repeated per card it announces as an identical
list, so each carries `expr:aria-label='"Read more: " + data:post.title'` while the visible text
stays "Read more →".

**Keyboard and contrast.** A skip link is the first thing in `<body>`, targeting
`<main id='main-content' tabindex='-1'>`. The search field used to be `outline:0` - the one input on
the page with no focus indicator - and now has a ring, with a global `:focus-visible` rule (light
ring on the dark nav and footer). Every `target='_blank'` link carries `rel='noopener noreferrer'`.
The footer copyright moved `#8991A0` → `#A8B0BE`, the placeholder is darkened to `#4A5160`, and all
19 pairs `check_perf.py` computes from this file now clear 4.5:1 - 13 for the page plus the six the
search drop-down added (rows, the active row, the `<mark>` highlight, the meta line, label rows, the
see-every-result row). `@media(prefers-reduced-motion)` collapses the card and button transitions;
the suggestion panel has no animation at all to collapse.

**SEO.** `<b:if cond='not data:blog.metaDescription'>` emits a 146-character description when
Blogger does not - and this blog does not, because `blog_description` is empty *and*
`blog_meta_description_enabled` is false (see `../POST_RULES.md` §9). The guard is what makes it
safe: enable Settings → Search description and Blogger's own tag takes over, with no duplicate.
Also added: `og:`/`twitter:card` for the Shorts/Reels shares, a `Blog` JSON-LD block, `theme-color`,
and a fallback tagline in the header so the home page has descriptive text above the fold instead of
the blank line an empty `data:blog.description` leaves.

`preview.html` mirrors all of it - same inlined skin, same head, same card attributes - so what
`check_perf.py` passes is what Blogger will render. It is generated by
`tools/build_theme_preview.py`; if the two disagree the tool says so.

## Upload it to Blogger

1. **Keep a rollback copy:** Blogger → **Theme** → ⋮ → **Backup** (or *Download*).
   That file re-uploads as-is if you want the old theme back.
2. Blogger → **Theme** → ⋮ → **Backup / Restore** → **Upload** → `theme/freestackhub-theme.xml`
   → *Upload* (confirm the overwrite).
   Or: **Theme → Edit HTML**, select everything (Ctrl+A) and paste the whole file in, then **Save**.
3. Open the blog: home page, one label page, and one post page (`/2026/09/…html`). Widgets in the
   sidebar are untouched by the upload - Blogger rebuilds them from the file's `<b:section>`s.
4. Type a word in the search bar above the navbar and check the list drops, narrows as you keep
   typing, and that ↑/↓ + Enter open a post. The first keystroke is what fires the one feed
   request, so a blog that has just been made private or a feed that is off will simply leave the
   field as a plain search form.
5. The sidebar widget now reads **Most Viewed Stories**. Its heading is hardcoded in the theme
   (not `<data:title/>`) precisely because Blogger keeps a widget's *stored* title when a theme is
   uploaded over an existing layout - so the page cannot come back still saying "Most Downloaded".
   The `title` attribute is renamed too, which is what the Layout panel shows; if the two ever
   disagree, the page wins.

Nothing here depends on a Blogger-hosted image, so publishing keeps working exactly as before:
write the post, build `import.xml`, import it, and the home page picks up the new card.

## Look at the design before uploading

```bash
python3 tools/build_theme_preview.py                   # newest post folder
python3 tools/build_theme_preview.py <post-folder>     # a specific post
python3 -m http.server 8000                            # -> /theme/preview.html
```

The preview reuses the real skin from `freestackhub-theme.xml`, the real card markup, and the
real post's title / labels / hook / body, so what it shows is what Blogger will render. It is a
mock, not a second copy of the blog: edit the theme or the post, re-run, refresh.

## Notes

- `theme/freestackhub-theme.xml` is hand-maintained. When it changes, Blogger writes the whole
  expanded widget back if you re-download it - keep editing this file, not that one.
- Cards show **no post text**: only the feature image (full width, 16:9, `object-fit: cover`),
  labels, title, date and the Read more button. Captions under the feature image therefore never
  leak onto the home page. The **Most Viewed Stories** sidebar widget (Blogger's `PopularPosts`,
  which ranks by page views - it was titled "Most Downloaded", a counter this blog does not keep)
  has a custom includable that renders thumbnail + title only - Blogger's default PopularPosts
  markup dumps a long snippet under every entry, which is the "dozens of lines" the sidebar used
  to show. Its heading is hardcoded in the includable, so the rename survives an upload.
- CSS lives in the `<b:skin>` block: the inlined `@font-face` rules and their metric-adjusted
  fallbacks come first, then the layout, then the additions labelled "List cards (home / label /
  search / archive)". Blogger's own share buttons are hidden in both the widget (`shareButtons`)
  and the CSS.
- If you change a colour, re-run `python3 tools/check_perf.py`: it reads the palette out of this
  file and recomputes all 19 contrast pairs, so a recolour that drops under 4.5:1 fails the build
  rather than the audit.
- Blogger's own widget CSS and JavaScript arrive through `<b:include name='all-head-content'/>` and
  are not removable from a theme. If PageSpeed still reports unused JavaScript after uploading,
  check the URL in the report's network table - `blogspot.com`/`blogger.com` means it is theirs.
