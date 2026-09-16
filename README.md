# Free-Stack-Hub.blogspot.com

Source for the posts on [free-stack-hub.blogspot.com](https://free-stack-hub.blogspot.com).

Each post lives in its own folder under `posts/` with its own `images/` and a generated
`import.xml`. To publish a post: Blogger → Settings → Manage blog → Import content → pick
that post's `import.xml`. Title, body, labels, search description, date and images are all
included.

- **Rules for writing / adding posts:** [POST_RULES.md](POST_RULES.md)
- **Build tool:** `python3 tools/build_import.py` (regenerates every `import.xml`)
- **Template:** `posts/_template/`

Images are served from this repo via jsDelivr, so the repository must be **public**
(Settings → General → Change visibility).
