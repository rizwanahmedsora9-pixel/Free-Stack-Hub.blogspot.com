# Why the Python-in-Termux post is not in Google yet, and what fixes it

This is the write-up of a Search Console **URL Inspection** report for
`https://freestackhub.blogspot.com/2026/09/install-python-in-termux-build-and-run.html`
that came back as **"URL is not on Google" → Page is not indexed: Crawled - currently not indexed**,
together with what the audit of `posts/` found and what was changed.

---

## 1. What that report is actually saying

| Field in the report | What it means |
|---|---|
| **Page is not indexed: Crawled - currently not indexed** | Google fetched the page successfully and then *decided* not to add it to the index yet. This is not a block. |
| **Crawl allowed? Yes · Page fetch: Successful · Indexing allowed? Yes** | `robots.txt` is fine, the page returned content, there is no `noindex`. Nothing to "unblock". |
| **User-declared canonical** = the post URL, **Google-selected canonical** = the same | You are not fighting a canonical problem either. |
| **Discovery → Sitemaps: Temporary processing error** | A Search Console status for the submitted sitemap, not a verdict on the page. Blogger's own `sitemap.xml` lists all five posts correctly, so this is transient - resubmit and it clears. |
| **Discovery → Referring page: None detected** | Google found the URL from the sitemap or the manual submission, **not from a link on the site**. This was the single most useful line in the report. |
| **Last crawl: Sep 19, 2026, 10:37 PM · Googlebot smartphone** | Crawled ~12 hours after publishing. The verdict is fresh, which is good news: there is still time to change it cheaply. |

"Crawled - currently not indexed" on a new blog is a quality-and-discovery judgement, not a
technical block. The way out of it is the same as the way out of every early indexing problem:
make the page part of the site's link graph, give it the metadata the site already has for every
other post, and ask for a re-crawl **after** those are in place - not before.

---

## 2. What the audit found

The five published posts were not published through `import.xml`. Blogger therefore built every
URL from the post's **title**, so **not one live URL matches its folder slug** in `posts/`:

| `posts/` folder | live URL (the only one that exists) |
|---|---|
| `2026-09-19-install-python-in-termux-demo-app` | `/2026/09/install-python-in-termux-build-and-run.html` |
| `2026-09-17-termux-commands-git-nano` | `/2026/09/termux-commands-worth-memorising-basics.html` |
| `2026-09-16-google-search-console-step-by-step` | `/2026/09/google-search-console-from-zero-add.html` |
| `2026-09-16-pagespeed-insights-scores-explained` | `/2026/09/check-your-websites-vital-scores-with.html` |
| `2026-09-16-stop-deleting-pythonanywhere-files` | `/2026/09/stop-deleting-your-pythonanywhere-files.html` |

That is not cosmetic. Everything in the repo was written against the folder slugs, so:

1. **The inspected post's four internal links were all 404.** It linked to the Termux, PythonAnywhere,
   PageSpeed and Search Console posts using their folder slugs. Checked live:
   `…/2026/09/termux-commands-git-nano.html` → **404**. A new post whose outbound links all land on
   Blogger's "page not found" page is exactly the kind of page Google leaves out.
2. **Nothing linked back to it.** The four sister posts contain no internal links at all, so the
   newest post had *zero* inbound internal links - hence **Referring page: None detected**.
3. **The live post has no labels.** The other four posts have labels; this one was published without
   them, so it is missing from every `/search/label/...` hub (Termux, Android, Python, …) - the
   blog's own topic navigation, and the main way its pages link to each other.
4. **`POST_RULES.md` §12 was itself pointing at three 404s** in its "must link to" examples, so every
   new post written by following the rules inherited the broken links.

Note what was *not* the problem, because it is worth knowing: the post's HTML, images,
`<picture>`/AVIF markup and width/height attributes all survived publishing intact, the sitemap
lists the right URLs, and the page renders fully on desktop and at `?m=1`.

---

## 3. Fixed in this repo

| Fix | Where |
|---|---|
| `PERMALINK:` header key - records the URL a post actually lives at when Blogger's slug is not the folder slug. Accepted by `build_import.py` (writes it into `<blogger:filename>`, so a future import lands on the same URL), `check_published.py` and `build_theme_preview.py`. | `tools/build_import.py`, `tools/check_published.py`, `tools/build_theme_preview.py` |
| All five posts now record their live URL, so the repo stops claiming URLs that 404 | `posts/*/post.html` |
| The four dead links in the inspected post now point at the real URLs (post.html + post.md) | `posts/2026-09-19-install-python-in-termux-demo-app/` |
| Inbound links added from the two posts that continue this one (Termux commands → install Python; PythonAnywhere → run the script from your phone) | `posts/2026-09-17-termux-commands-git-nano/`, `posts/2026-09-16-stop-deleting-pythonanywhere-files/` |
| New check: every internal link a post makes is fetched, and one that 404s **fails** the post (`--no-links` skips it) | `tools/check_published.py` |
| New check: a post that no other published post links to is **warned** about - the "Referring page: None detected" state | `tools/check_published.py` |
| §1 documents `PERMALINK:`, §8 documents the two new checks, §12's example links now use live URLs and require linking *both* ways | `POST_RULES.md` |
| `theme/preview.html` regenerated so the mock's sample links match the live URLs | `theme/` |

Everything is rebuilt: `import.xml`, `paste.html` and `title.txt` for all five posts, and
`python3 tools/check_perf.py` still reports `clean` (189 checks).

---

## 4. What only you can do (in this order)

The repo cannot reach Blogger. These are the steps on the blog itself.

### 4.1 Re-paste three bodies (the fixed links live in the body)

For each post: Blogger → **Edit** → **HTML view** → select all → paste the content of that post's
`paste.html` → **Update**.

| Post to re-paste | What changes |
|---|---|
| `posts/2026-09-19-install-python-in-termux-demo-app/paste.html` | the 4 dead links now point at the 4 live URLs |
| `posts/2026-09-17-termux-commands-git-nano/paste.html` | adds the inbound link to the Python post |
| `posts/2026-09-16-stop-deleting-pythonanywhere-files/paste.html` | adds the inbound link to the Python post |

If you would rather change only the last paragraph of those two sister posts, replace it with the
matching paragraph from their `paste.html` - that is the only line that changed.

While the editor is open, put the cursor right after the hook sentence and use
**Insert → Jump break** where `build_import.py` printed the break belongs (it names the sentence).

### 4.2 Add the labels to the inspected post (no re-paste needed)

Open the post → **Labels** in the right sidebar → paste exactly:

```
Termux, Android, Python, Command Line, Nano, Mobile Development, Free Stack
```

This is the one item that is a hard FAIL in `check_published.py`, and it is what puts the post into
the Termux / Android / Python label hubs that the sidebar's Categories list links to.

### 4.3 Restore the search description

**Settings → Search preferences → Meta tags → Description → Enable**, and paste a blog-level
description. Then in the post's **Search description** field paste the post's own:

> Install Python in Termux on Android, write a complete interactive CLI demo app using nano, and run your scripts with zero compilation headaches.

While in Settings, also set **Posts, comments and media → Lightbox = No** (it injects extra CSS/JS
and wraps every image in a link with no accessible name). Both are described in `POST_RULES.md` §9.

### 4.4 Then ask Google again

1. Search Console → **Sitemaps** → resubmit `sitemap.xml` (clears the "Temporary processing error").
2. Search Console → **URL Inspection** → inspect the **canonical** URL
   `https://freestackhub.blogspot.com/2026/09/install-python-in-termux-build-and-run.html`
   (not the `?m=1` mobile variant) → **Request Indexing**.
3. Request indexing for the two sister posts you re-pasted as well - their bodies changed.
4. Wait a few days, then inspect again. Expect "URL is on Google" or at worst a crawl date that
   moved.

Do the fixes **before** the re-crawl requests. A re-crawl of the broken state just re-confirms it.

### 4.5 Optional, but worth it

- Upload the hero image of the newest post inside Blogger once. Images hosted off-blog get no
  `media$thumbnail`, which is why Blogger's own Popular Posts / Featured Post widgets show a
  picture for other posts and none for this one. The theme's home-page cards are unaffected.
- `API INDEXING/dashboard` can push unindexed URLs and read their inspection state. Treat it as a
  monitor: Google documents the Indexing API for `JobPosting`/`BroadcastEvent` only, so a `200`
  there is not a promise about a blog post. The real levers are the internal links and Search
  Console's own Request Indexing.

---

## 5. Verifying, and keeping it fixed

```bash
python3 tools/check_published.py            # live titles, labels, permalinks, images, internal links, orphans
python3 tools/check_published.py --no-links # same, without fetching every internal link
python3 tools/check_perf.py                 # offline; must print "clean"
```

`check_published.py` exits 1 on any FAIL, so the state that caused this post's problem cannot pass
unnoticed again: a link built from a folder slug is fetched and reported as a 404, and a post that
nothing links to is reported as an orphan.

Two habits that prevent a repeat:

- **Publish with `import.xml`.** It is the only route that carries the title, the labels and the
  search description, and it pins `<blogger:filename>` to the slug the repo expects. If you paste
  the body instead, Blogger invents the URL from the title - then set `PERMALINK:` in `post.html`
  to whatever it invented (section 1 of `POST_RULES.md`) before you write any other post's link to it.
- **Never write an internal link from the folder name.** Open the live post, copy its URL, and use
  that. `check_published.py` will catch the mistake, but only after it is published.
