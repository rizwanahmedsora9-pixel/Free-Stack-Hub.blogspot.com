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
The date becomes the post's publish date (unless `PUBLISHED:` overrides it) and the
slug becomes the Blogger URL (`/2026/09/slug.html`). Never rename a folder after import.

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
post's `import.xml`. One file = one post.

**Copy-paste:** open the post's `paste.html`, copy **all** of it, and paste into the Blogger
post editor with the HTML view active (pencil icon → HTML view). Then set the title, labels
and search description by hand if you want them.

**Never paste `post.html` itself.** Its `<img>` tags use bare file names (`01-hero.jpg`), so
Blogger would look for the images on the blog's own domain and show them broken. Only the
generated `import.xml` / `paste.html` contain the full public image URLs.

To update a post already on Blogger, edit it in the Blogger editor (re-importing the same
file creates a second copy).

## 6. Public images (one-time)
Image URLs are `https://cdn.jsdelivr.net/gh/rizwanahmedsora9-pixel/Free-Stack-Hub.blogspot.com@main/posts/<folder>/images/<file>`.
This needs the repo to be **public** and the post merged to `main`.
To test from a branch before merging: `IMAGE_BRANCH=<branch-name> python3 tools/build_import.py`.

## Checklist for the agent when adding a post
1. `cp -r posts/_template posts/YYYY-MM-DD-slug`
2. Write `post.html` (+ `post.md`), generate images into `images/`
3. `python3 tools/build_import.py YYYY-MM-DD-slug` → must print no ERROR
4. Commit the whole folder including `import.xml` and `paste.html`
