# Free-Stack-Hub.blogspot.com

Source for the posts on [freestackhub.blogspot.com](https://freestackhub.blogspot.com).

Each post is one self-contained folder under `posts/`:

```
posts/2026-09-16-stop-deleting-pythonanywhere-files/
  post.html    the post: header comment (title/labels/date/description) + HTML body
  post.md      readable markdown copy
  images/      this post's images, plus GENERATED .avif/.webp variants of each
  title.txt    GENERATED - exact title, so you never retype it in Blogger
  import.xml   GENERATED - the file you import into Blogger
  paste.html   GENERATED - body with full image URLs, for the editor's HTML view
  video/       GENERATED - storyboard.json + narrated vertical and wide MP4s
```

To publish a post, either:

- **Import (recommended):** Blogger → Settings → Manage blog → Import content → pick that post's
  `import.xml`. This is the only route that carries the title, the labels and the search
  description as well as the body.
- **or copy-paste:** open the post's `paste.html`, copy all of it into the Blogger post editor
  (HTML view). That is the body only — you have to retype the title (it's in `title.txt`) and set
  the labels and the search description by hand, or the post goes out without them.

Every post follows one shape, so the homepage teaser is always feature image → 2-4 sentence hook
→ jump break → the rest. The build enforces it, and the Blogger theme in `theme/` renders exactly
that: each home-page card is the feature image, the hook, and a **Read more** button that opens
that post's own URL. After publishing, check what actually landed:

```bash
python3 tools/check_published.py      # live title / labels / permalink / images / links vs posts/
python3 tools/check_published.py --no-links   # same, without fetching every internal link
python3 tools/check_perf.py           # Core Web Vitals / a11y / SEO, offline, no browser
python3 tools/make_video.py 2026-09-16-stop-deleting-pythonanywhere-files   # social videos
```

Never paste `post.html` itself into Blogger — its `<img>` tags use bare file names, so the
images would show as broken. Only the generated files have full URLs.

- **Rules for writing / adding posts (structure, images, publishing, videos):** [POST_RULES.md](POST_RULES.md)
- **Blogger theme:** `theme/freestackhub-theme.xml` (the file to upload to Blogger) plus
  `theme/preview.html`, a static mock of the home page and a post page - see [theme/README.md](theme/README.md)
- **Build tool:** `python3 tools/build_import.py` (regenerates `import.xml`, `paste.html`, `title.txt`)
- **Image tool:** `python3 tools/optimize_images.py` (writes the `.avif`/`.webp` variants, reports pixel sizes)
- **Performance audit:** `python3 tools/check_perf.py` - see [PERFORMANCE.md](PERFORMANCE.md)
- **Theme preview:** `python3 tools/build_theme_preview.py` (regenerates `theme/preview.html`)
- **Video tool:** `python3 tools/make_video.py` (needs `pillow` + ffmpeg; see POST_RULES §11)
- **Published-vs-source check:** `python3 tools/check_published.py` - also fetches every internal
  link a post makes (a 404 fails the post), checks the live page's `rel=canonical` and robots meta,
  and warns when nothing on the blog links to it
- **Indexing playbook:** [INDEXING.md](INDEXING.md) - what "Crawled - currently not indexed",
  "Redirect error" and "Indexing allowed? N/A" each mean, the audit behind the `PERMALINK:` key, and
  the Blogger/Search Console steps that fix a post
- **Cache headers for a static host:** `perf/netlify.toml`
- **Template:** `posts/_template/`
- **Performance / accessibility / SEO:** [PERFORMANCE.md](PERFORMANCE.md) - what was changed in the
  theme and the build to pass PageSpeed, and how to keep the next post passing

Images are served from this repo via jsDelivr, so the repository must be **public**
(Settings → General → Change visibility), and the post must be merged to `main`. A brand-new
file can take a while to appear on that CDN, because a branch snapshot is cached; if the
published post shows broken images, rebuild with `IMAGE_REF=<commit-sha>`.
