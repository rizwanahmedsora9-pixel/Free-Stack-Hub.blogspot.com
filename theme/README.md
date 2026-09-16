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
| home / label / search / archive | one **card** per post: feature image, labels, title, date, the text before the jump break, and a **Read more** button |
| card click | `data:post.url` - that post's own permalink |
| post / page | full `data:post.body`, title, date, labels ("Filed under"), comments, then Blogger's schema block for SEO |
| under the list | the pager (`← Newer Posts` / `Older Posts →`) |

Key data tags, and why these ones:

- `data:post.snippets.long` - the post **up to the jump break** as plain text (Blog widget v2 has
  `snippets`, not v1's `snippet`). This is the "catchy lines", cut by Blogger itself, so no
  JavaScript, no `max-height` hacks, and the rest of the post is not even sent to the browser.
- `data:post.featuredImage` - the first image of the post. Cards therefore have a picture even
  though Blogger never generates a `media$thumbnail` for jsDelivr-hosted images (the caveat in
  `POST_RULES.md` §8 no longer applies to the home page). `thumbnailUrl` is the fallback.
- `data:post.hasJumpLink` / jump-break text - not needed any more: every card ends in the same
  *Read more* button, whether or not the post has a break. (`POST_RULES.md` §3 requires one.)

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
- The card excerpt is the post's own text **before the jump break**, captions included. So a
  caption under the feature image ("The old way and the new way, side by side.") shows up as the
  first words of the card. Give the feature image no visible caption if you would rather the card
  open straight on the hook.
- CSS lives in the `<b:skin>` block: list cards at the top of the additions, labelled
  "List cards (home / label / search / archive)". Blogger's own share buttons are hidden in both
  the widget (`shareButtons`) and the CSS.
