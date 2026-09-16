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

## Performance, accessibility and SEO

What the theme does now, and the reason each piece is there.

**Nothing in `<head>` blocks paint.** The Google Fonts `<link rel='stylesheet'>` is gone - it was a
stylesheet on a third origin whose only job was to name two files on a fourth, so first paint waited
on three round trips. The `@font-face` rules are inlined at the top of `<b:skin>` instead. Both
families are variable fonts, so a single file covers `font-weight: 400 700` (Space Grotesk) and
`400 600` (Source Serif 4); the old link asked for four discrete weights that all resolved to the
same file. `unicode-range` keeps an English page down to the two `latin` files. The theme adds no
`<script src>` of its own - there is no first-party JavaScript to defer, because the cards are
pure server-rendered HTML (image + labels + title + date + Read more, no post text).

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
13 pairs `check_perf.py` computes from this file now clear 4.5:1. `@media(prefers-reduced-motion)`
collapses the card and button transitions.

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
  leak onto the home page. The "Most Downloaded" sidebar widget has a custom includable that
  renders thumbnail + title only - Blogger's default PopularPosts markup dumps a long snippet
  under every entry, which is the "dozens of lines" the sidebar used to show.
- CSS lives in the `<b:skin>` block: the inlined `@font-face` rules and their metric-adjusted
  fallbacks come first, then the layout, then the additions labelled "List cards (home / label /
  search / archive)". Blogger's own share buttons are hidden in both the widget (`shareButtons`)
  and the CSS.
- If you change a colour, re-run `python3 tools/check_perf.py`: it reads the palette out of this
  file and recomputes all 13 contrast pairs, so a recolour that drops under 4.5:1 fails the build
  rather than the audit.
- Blogger's own widget CSS and JavaScript arrive through `<b:include name='all-head-content'/>` and
  are not removable from a theme. If PageSpeed still reports unused JavaScript after uploading,
  check the URL in the report's network table - `blogspot.com`/`blogger.com` means it is theirs.
