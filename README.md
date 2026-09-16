# Free-Stack-Hub.blogspot.com

Source for the posts on [free-stack-hub.blogspot.com](https://free-stack-hub.blogspot.com).

```
post/      one  <slug>-blogger.html  per post (HTML body + metadata header)
images/    all post images (referenced by bare file name inside the posts)
tools/     build_import.py  -> builds the Blogger import file
import/    blogger-import.xml (the file you import) + imported.json (what's already imported)
```

## Publishing workflow

1. A new post is added as `post/<slug>-blogger.html` and its images go into `images/`.
2. Build the import file:
   ```bash
   python3 tools/build_import.py
   ```
   It only includes posts that have **not** been imported before, so you never get duplicates.
   Image `src`s are rewritten to public URLs automatically (title, labels, search
   description and publish date all come from the post's header comment).
3. In Blogger: **Settings → Manage blog → Import content** → pick `import/blogger-import.xml`.
   (Untick "Automatically publish" if you want to review posts first.)
4. Mark them as done so the next build skips them:
   ```bash
   python3 tools/build_import.py --done
   ```

Other commands: `--list` shows imported / pending status, `--all` rebuilds every post.

## Images

The import file points images at
`https://cdn.jsdelivr.net/gh/rizwanahmedsora9-pixel/Free-Stack-Hub.blogspot.com@main/images/…`
which works once this repository is **public** (Settings → General → Danger zone → Change visibility).
To use GitHub Pages instead, enable Pages (branch `main`, folder `/`) and set
`IMAGE_BASE=https://rizwanahmedsora9-pixel.github.io/Free-Stack-Hub.blogspot.com/images/`
when running the build.

## Post header format

```html
<!--
TITLE:  Post title
LABELS: Label One, Label Two
PUBLISHED: 2026-09-16
SEARCH DESCRIPTION:
One or two sentences for search engines.
-->
<p>Post body…</p>
<img src="01-hero.jpg" alt="…" />
```
