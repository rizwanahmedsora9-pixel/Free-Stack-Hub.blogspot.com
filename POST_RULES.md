# Rules for new posts

Every post is **one self-contained folder** with its own images and its own import file.
Nothing is shared between posts, so importing one post can never touch another.

```
posts/
  2026-09-16-stop-deleting-pythonanywhere-files/
    post.html      source (metadata header + HTML body)      <- written by hand/agent
    post.md        readable markdown copy (optional)
    images/        only this post's images
    import.xml     GENERATED - the file you import into Blogger
    paste.html     GENERATED - copy-paste-ready body (full image URLs) for the
                   Blogger editor's HTML view
  _template/       copy this to start a new post
```

## 1. Folder name
`YYYY-MM-DD-slug` — date first, then a short lowercase slug with dashes.
The date becomes the post's publish date (unless `PUBLISHED:` overrides it) and the slug
becomes the Blogger URL (`/2026/09/slug.html`) — **but only when you publish with `import.xml`**,
which writes `<blogger:filename>`. Paste-published posts get a URL built from whatever title was
typed into the editor, and a `_<number>` suffix if that URL was already taken.
Never rename a folder after import: `check_published.py` matches repo → live on the slug.

## 2. post.html header (required)
```html
<!--
TITLE:  Post title
LABELS: Label One, Label Two          (comma separated, these become Blogger labels)
PUBLISHED: 2026-09-16                 (optional)
SEARCH DESCRIPTION:
One or two sentences for search engines.
-->
```
Then the HTML body. Use `<h2>` for sections, `<p>`, `<ul>/<ol>`, `<code>`, and the
`<pre>` style block from the template for code.

## 3. Images
- Put them in the post's own `images/` folder, named `01-…jpg`, `02-…jpg` in order of appearance.
- In `post.html` reference them by **bare file name only**: `<img src="01-hero.jpg" alt="…">`.
- Every image needs `alt` text. Keep files under ~150 KB (JPG for photos/illustrations).
- The build rewrites the `src` to a public URL; nothing is uploaded to Blogger manually.

## 4. Build
```bash
python3 tools/build_import.py                          # all posts
python3 tools/build_import.py 2026-09-16-my-post       # one post
python3 tools/build_import.py --check                  # validate only
```
The build **fails** if: folder name is wrong, TITLE/LABELS/SEARCH DESCRIPTION missing,
or an `<img>` points to a file that isn't in `images/`. It warns about unused images.

## 5. Publish (two ways)
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

## 6. Public images (one-time)
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

## 7. Verify what actually went live (do this after every publish)
```bash
python3 tools/check_published.py            # every post vs the live Blogger feed + CDN
python3 tools/check_published.py <folder>   # one post
```
It reads the public feed (`<blog>/feeds/posts/default?alt=json`) — no login, no API key —
and fails (`exit 1`) on the four things that only ever go wrong on Blogger's side:

- the live **title** differs from `TITLE:` in `post.html` (someone retyped it, or pasted instead of imported)
- **labels** missing on the live post (empty `/search/label/...` pages)
- **permalink** not matching the folder slug (Blogger generated the URL from the title at
  publish time and may have added a `_<number>` suffix — set a custom permalink if it matters)
- **images** present in the post but not served by the CDN yet, or images in the repo that the
  published post never references

It also notes when a post has no Blogger `media$thumbnail`: images hosted off-blog never get one,
so the homepage/list view shows a **text-only snippet** instead of a card with a picture. That is
expected with this workflow; upload the first image inside Blogger too if you want a preview card.

## 8. Blogger settings this repo depends on
Checked against this blog's own takeout export (`sample export/`), and worth knowing because
each one silently drops something the build files carry:

- **Settings → Search description → Enable.** `blog_meta_description_enabled` is currently `false`,
  so the `SEARCH DESCRIPTION:` in every `post.html` goes nowhere and Google fills the snippet with
  the first sentences of the post instead.
- **Settings → Posts, comments and media → Convert line breaks = On** (`blog_convert_line_breaks`
  is `true`). Right for typed text; for pasted `paste.html` it can add blank space between blocks
  that already have `<p>` tags.
- **Time zone is `America/Los_Angeles`** while `PUBLISHED:` is read as midnight UTC, so a post
  dated `2026-09-16` shows and links as **Sep 15** unless you write the date with that offset in
  mind. The blog also has no **description** set (`blog_description` is empty), so page titles end
  as `Free Stack Hub: <post title>`.

Never rename a folder after import, and never retitle the post in Blogger: `posts/` is the source
of truth, and `check_published.py` reports the pair as a mismatch (exit 1).

## Checklist for the agent when adding a post
1. `cp -r posts/_template posts/YYYY-MM-DD-slug`
2. Write `post.html` (+ `post.md`), generate images into `images/`
3. `python3 tools/build_import.py YYYY-MM-DD-slug` → must print no ERROR
4. Commit the whole folder including `import.xml` and `paste.html`
5. Publish with **`import.xml`** (not `paste.html`, unless you retype title + labels by hand)
6. `python3 tools/check_published.py YYYY-MM-DD-slug` → must print no FAIL
