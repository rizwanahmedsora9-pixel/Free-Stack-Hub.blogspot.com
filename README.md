# Free-Stack-Hub.blogspot.com

Source for the posts on [freestackhub.blogspot.com](https://freestackhub.blogspot.com).

Each post lives in its own folder under `posts/` with its own `images/` and two generated
files. To publish a post, either:

- **Import (recommended):** Blogger → Settings → Manage blog → Import content → pick that post's
  `import.xml`. This is the only route that carries the title, the labels and the search
  description as well as the body.
- **or copy-paste:** open the post's `paste.html`, copy all of it into the Blogger post editor
  (HTML view). That is the body only — you have to retype the title and set the labels and the
  search description by hand, or the post goes out without them.

After publishing, check what actually landed on the blog:

```bash
python3 tools/check_published.py      # live title / labels / permalink / images vs posts/
```

Never paste `post.html` itself into Blogger — its `<img>` tags use bare file names, so the
images would show as broken. Only the generated files have full URLs.

- **Rules for writing / adding posts:** [POST_RULES.md](POST_RULES.md)
- **Build tool:** `python3 tools/build_import.py` (regenerates every `import.xml`)
- **Published-vs-source check:** `python3 tools/check_published.py`
- **Template:** `posts/_template/`

Images are served from this repo via jsDelivr, so the repository must be **public**
(Settings → General → Change visibility), and the post must be merged to `main`. A brand-new
file can take a while to appear on that CDN, because a branch snapshot is cached; if the
published post shows broken images, rebuild with `IMAGE_REF=<commit-sha>`.
