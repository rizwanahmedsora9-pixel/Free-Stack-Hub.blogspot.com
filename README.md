# Free-Stack-Hub.blogspot.com

Source for the posts on [free-stack-hub.blogspot.com](https://free-stack-hub.blogspot.com).

Each post lives in its own folder under `posts/` with its own `images/` and two generated
files. To publish a post, either:

- **Import:** Blogger → Settings → Manage blog → Import content → pick that post's `import.xml`,
- **or copy-paste:** open the post's `paste.html`, copy all of it into the Blogger post editor
  (HTML view). Title, labels, search description and images are all included.

Never paste `post.html` itself into Blogger — its `<img>` tags use bare file names, so the
images would show as broken. Only the generated files have full URLs.

- **Rules for writing / adding posts:** [POST_RULES.md](POST_RULES.md)
- **Build tool:** `python3 tools/build_import.py` (regenerates every `import.xml`)
- **Template:** `posts/_template/`

Images are served from this repo via jsDelivr, so the repository must be **public**
(Settings → General → Change visibility).
