# Why the posts are not in Google yet, and what fixes each one

This is the write-up of two Search Console **URL Inspection** reports from
freestackhub.blogspot.com:

| Report | Post | Verdict | Page fetch | Indexing allowed |
|---|---|---|---|---|
| **A** | `install-python-in-termux-build-and-run.html` | Crawled - currently not indexed | Successful | Yes |
| **B** | `google-search-console-from-zero-add.html` | Redirect error | **Failed: Redirect error** | **N/A** |

They are two *different* failures - A is a quality/discovery judgement, B is a technical
fetch failure - and below each one is explained, then the audit that found the underlying
problem they share, and the steps that are left.

---

## 1. Report A: "Crawled - currently not indexed"

| Field in the report | What it means |
|---|---|
| **Page is not indexed: Crawled - currently not indexed** | Google fetched the page successfully and then *decided* not to add it to the index yet. This is not a block. |
| **Crawl allowed? Yes · Page fetch: Successful · Indexing allowed? Yes** | `robots.txt` is fine, the page returned content, there is no `noindex`. Nothing to "unblock". |
| **User-declared canonical** = the post URL, **Google-selected canonical** = the same | Not a canonical problem either. |
| **Discovery → Sitemaps: Temporary processing error** | A Search Console status for the submitted sitemap, not a verdict on the page. Blogger's own `sitemap.xml` lists all five posts correctly, so this is transient - resubmit and it clears. |
| **Discovery → Referring page: None detected** | Google found the URL from the sitemap or the manual submission, **not from a link on the site**. This was the single most useful line in the report. |
| **Last crawl: Sep 19, 2026, 10:37 PM · Googlebot smartphone** | Crawled ~12 hours after publishing, so the verdict is fresh and cheap to change. |

"Crawled - currently not indexed" on a new blog is a quality-and-discovery judgement. The way out
is to make the page part of the site's link graph, give it the metadata every other post has, and
ask for a re-crawl **after** those are in place - not before.

---

## 2. Report B: "Redirect error", and why it says "Indexing allowed? N/A"

### 2.1 What happened

The crawl at Sep 19, 22:10 **failed**, so no verdict could be formed:

```
Page fetch     Failed: Redirect error
Indexing allowed?   N/A
User-declared canonical   N/A
```

A **Redirect error** means Google followed a redirect and could not finish - a loop, a chain that
never settles, or a redirect Google gave up on (crawl budget). Blogger produces exactly that
pattern on its own: a Blogger post exists as a clean URL *and* as its mobile variant with `?m=1`
appended, and Blogger redirects between them. **Googlebot smartphone is now the primary crawler**
(mobile-first indexing), so it is the bot that meets that redirect first, and when it drops the
crawl instead of following it through, Search Console reports what you see. Google's own
[community guide for Blogger redirect errors](https://support.google.com/webmasters/community-guide/254759331)
describes this and says that when it is the `?m=1` dance, it is normally expected behaviour rather
than a misconfiguration - while warning that a **custom theme must still carry the canonical tag**,
because that tag is what tells Google the two URLs are one page.

### 2.2 Why "Indexing allowed" is N/A, and why there is no switch to make it "Allowed"

This is the part worth being blunt about: **"Indexing allowed" is a read-out, not a setting.**

Google reports it after reading the page's own signals - the `<meta name='robots'>` tag, an
`X-Robots-Tag` header, and `robots.txt`. In report B the page was **never read** (`Page fetch:
Failed`), so Google had nothing to evaluate and printed **N/A**. It is a *symptom of the failed
fetch*, not a second problem: fix the fetch and the field fills itself in.

There is no button anywhere - in Search Console or in Blogger - that "allows indexing instantly".
The only things that can flip it to **No** are things you would have to have done:
`Settings → Privacy → Visible to search engines = No`, or a `noindex` in a post's
**Custom robots tags**. Both are already correct on this blog (verified below), and the four other
posts report **Indexing allowed? Yes** - the same theme, the same settings, the same server. That
rules out the site's own signals and leaves the failed crawl as the whole story.

### 2.3 What was verified on the live page instead of guessed

**Nothing in this repo produces the canonical, and nothing in this repo was changed to produce
it.** Blogger emits `<link rel='canonical'>` itself, from the one line the theme keeps:

```xml
<b:include data='blog' name='all-head-content'/>
```

Fetched live on 2026-09-19, every published post declares **its own clean URL** - no `?m=1`, and no
robots `noindex` on any of them:

| Post (live URL) | live `rel=canonical` |
|---|---|
| `/2026/09/install-python-in-termux-build-and-run.html` | itself |
| `/2026/09/google-search-console-from-zero-add.html` | itself |
| `/2026/09/termux-commands-worth-memorising-basics.html` | itself |
| `/2026/09/check-your-websites-vital-scores-with.html` | itself |
| `/2026/09/stop-deleting-your-pythonanywhere-files.html` | itself |

That includes report B's post, whose inspection says **`User-declared canonical: N/A`**. N/A there
is not "this post has no canonical" - it is the *same failed fetch* as `Page fetch: Failed` and
`Indexing allowed? N/A`. Google read nothing, so it could report nothing. On the newest post the
crawl succeeded and the same field was filled in. Same theme, same tag, different crawl outcome:
**the difference between the two reports is the crawl, not the page.**

Also worth knowing, because it is the mechanism behind report B: a request that looks like a mobile
client to Blogger is served a **302 from the clean URL to `...html?m=1`** - reproduced while
checking these pages. A desktop fetch sees no redirect at all, which is why the page "works fine"
when you open it yourself. The canonical tag is what tells Google the two URLs are one page, and
because Blogger emits it correctly here, the redirect itself is not a defect - the failed crawl is.

And from the blog's own Takeout export (`sample export/`):

| Setting | Value | Meaning |
|---|---|---|
| `blog_searchable` | `true` | "Visible to search engines" is on - the blog-level indexing switch is already correct |
| `blog_custom_robots_txt_enabled` | `false` | no custom `robots.txt` is blocking anything (and none should be added - see 5.4) |
| `show_mobile_view` | `false` | one responsive template serves both desktop and mobile, which is what a `b:responsive='true'` theme wants |

So nothing in the site's configuration is refusing Google. Report B is a crawl that did not
complete, on a blog whose mobile/desktop pair is linked correctly by its canonical.

### 2.4 What actually fixes it (and what "instantly" can and cannot mean)

Nothing makes indexing instant, but the fetch failure is cheap to clear, and this is the order
that works:

1. **URL Inspection → Test Live URL** on the post. This is the decisive diagnostic: it makes
   Google fetch the page right now and reports what it got. If it comes back **"URL is available to
   Google"**, the redirect error was a crawl-time failure that is already gone, and the page-index
   status is simply stale.
2. **Request Indexing** on that same screen. It queues one URL for re-crawl - roughly 10-20 a day
   per property - and the status then walks from "not on Google" to crawled to indexed.
3. **If the clean URL keeps failing, inspect and request the `?m=1` version instead.** It serves the
   same post, it is the URL Googlebot smartphone actually gets, and it is the variant Blogger's
   community guidance says to point at when the clean URL keeps tripping the redirect check. Google
   resolves it back to the canonical URL, and no duplicate is created because the canonical tag
   (verified above) points at the clean one. Treat it as an acceleration tactic for a new post, not
   a permanent routine.
4. **Resubmit `sitemap.xml`** once, to clear the "Temporary processing error", and leave it alone
   after that.

Steps 1-3 are the whole of "make it allowed" - there is no shorter path, and any guide promising
one is selling you a button that does not exist.

### 2.5 Things that make it worse, not better

All three are listed as actions **not** to take in Google's Blogger guidance, and each one converts
a cosmetic report into a real problem:

- **`Disallow: /*?m=1` in robots.txt.** It stops the mobile URL from being crawled, breaking the
  mobile/desktop relationship - and this blog's `robots.txt` is deliberately not customised.
- **`noindex` on the `?m=1` URL.** Duplicate handling belongs to the canonical tag, not to noindex.
- **JavaScript that strips `?m=1`.** It forces a desktop render on phones and creates the very
  redirect loop Search Console is complaining about.

---

## 3. What the audit found behind both reports

The five published posts were not published through `import.xml`. Blogger therefore built every URL
from the post's **title**, so **not one live URL matches its folder slug** in `posts/`:

| `posts/` folder | live URL (the only one that exists) |
|---|---|
| `2026-09-19-install-python-in-termux-demo-app` | `/2026/09/install-python-in-termux-build-and-run.html` |
| `2026-09-17-termux-commands-git-nano` | `/2026/09/termux-commands-worth-memorising-basics.html` |
| `2026-09-16-google-search-console-step-by-step` | `/2026/09/google-search-console-from-zero-add.html` |
| `2026-09-16-pagespeed-insights-scores-explained` | `/2026/09/check-your-websites-vital-scores-with.html` |
| `2026-09-16-stop-deleting-pythonanywhere-files` | `/2026/09/stop-deleting-your-pythonanywhere-files.html` |

That is not cosmetic. Everything in the repo was written against the folder slugs, so:

1. **Report A's post had four internal links, and all four 404.** It linked to the Termux,
   PythonAnywhere, PageSpeed and Search Console posts using their folder slugs. Opened live, three
   answer Blogger's 404 page (`termux-commands-git-nano.html`,
   `stop-deleting-pythonanywhere-files.html`, `pagespeed-insights-scores-explained.html`), and the
   fourth is absent from the feed and the sitemap too.
2. **Nothing linked back to it.** The sister posts contained no internal links at all, so the newest
   post had *zero* inbound internal links - Search Console's **Referring page: None detected**.
3. **The live post has no labels**, so it is missing from every `/search/label/...` hub (Termux,
   Android, Python, …) - the blog's own topic navigation, and the main way its pages link to each
   other.
4. **`POST_RULES.md` §12 was itself pointing at three 404s**, so every new post written by following
   the rules inherited the broken links.

Note what was *not* the problem: HTML, images, `<picture>`/AVIF markup and `width`/`height`
attributes all survived publishing intact, the sitemap lists the right URLs, the canonical is
correct (2.3), and the pages render on desktop and mobile alike.

---

## 4. Fixed in this repo

| Fix | Where |
|---|---|
| `PERMALINK:` header key - records the URL a post actually lives at when Blogger's slug is not the folder slug. Accepted by `build_import.py` (written into `<blogger:filename>`, so a future import lands on the same URL), `check_published.py` and `build_theme_preview.py`. | `tools/build_import.py`, `tools/check_published.py`, `tools/build_theme_preview.py` |
| All five posts record their live URL, so the repo stops claiming URLs that 404 | `posts/*/post.html` |
| The four dead links now point at the real URLs (post.html + post.md) | `posts/2026-09-19-install-python-in-termux-demo-app/` |
| Inbound links added from the two posts that continue this one (Termux commands → install Python; PythonAnywhere → run the script from your phone) | `posts/2026-09-17-termux-commands-git-nano/`, `posts/2026-09-16-stop-deleting-pythonanywhere-files/` |
| New check: every internal link a post makes is fetched, and one that 404s **fails** the post | `tools/check_published.py` |
| New check: a post that no other published post links to is **warned** about - the "Referring page: None detected" state | `tools/check_published.py` |
| New check: the live page's `<head>` is fetched and its **`rel=canonical`** must be the post's own clean URL, with no `noindex` in its robots meta - i.e. section 2.3, automated for every post | `tools/check_published.py` |
| New guard: the theme must keep `<b:include name='all-head-content'/>` (that one line is what emits the canonical) and must not add a second, hand-written canonical or a noindex | `tools/check_perf.py` |
| §1 documents `PERMALINK:`, §8 documents the new checks, §9 records the mobile/`?m=1` and all-head-content rules, §12's example links use live URLs and require linking *both* ways | `POST_RULES.md` |
| `theme/preview.html` regenerated so the mock's sample links match the live URLs | `theme/` |

Everything is rebuilt: `import.xml`, `paste.html` and `title.txt` for all five posts, and
`python3 tools/check_perf.py` reports `clean` (192 checks).

---

## 5. What only you can do, in this order

The repo cannot reach Blogger. These are the steps on the blog itself.

### 5.1 Clear the two per-post switches (30 seconds, no re-paste)

1. Blogger → the post → right sidebar → **Custom robots tags**: leave it on the default / empty
   value. Anything with `noindex` here is the one thing that can put a post back to
   "Indexing allowed? No".
2. **Settings → Privacy → Visible to search engines = Yes.** (Already `true` in the export - check
   it once and forget it.)

### 5.2 Re-paste three bodies (the fixed links live in the body)

For each post: Blogger → **Edit** → **HTML view** → select all → paste the content of that post's
`paste.html` → **Update**.

| Post to re-paste | What changes |
|---|---|
| `posts/2026-09-19-install-python-in-termux-demo-app/paste.html` | the 4 dead links now point at the 4 live URLs |
| `posts/2026-09-17-termux-commands-git-nano/paste.html` | adds the inbound link to the Python post |
| `posts/2026-09-16-stop-deleting-pythonanywhere-files/paste.html` | adds the inbound link to the Python post |

If you would rather change only the last paragraph of those two sister posts, replace it with the
matching paragraph from their `paste.html` - that is the only line that changed.

**Nothing in this repo can reach Blogger.** Editing `post.html`/`paste.html` changes the *source*
only; the live post keeps whatever body was last pasted into the editor. That is why a fixed link can
sit in the repo for days while the live post still 404s. `check_published.py` is the tool that tells
the two apart - run against the live blog, it reports each broken link **by its anchor text**, so you
can search for that exact sentence in the editor:

```
FAIL  internal link 404s: /2026/09/termux-commands-git-nano.html (HTTP 404)
      on "our step-by-step guide to essential Termux commands, Git cloning, and ..."
```

After a re-paste the same run prints `ok   all 4 internal link(s) resolve`.

While the editor is open, put the cursor right after the hook sentence and use
**Insert → Jump break** where `build_import.py` printed the break belongs (it names the sentence).

### 5.3 Add the labels to report A's post (no re-paste needed)

Open the post → **Labels** in the right sidebar → paste exactly:

```
Termux, Android, Python, Command Line, Nano, Mobile Development, Free Stack
```

This is the one item that is a hard FAIL in `check_published.py`, and it is what puts the post into
the Termux / Android / Python label hubs that the sidebar's Categories list links to.

### 5.4 Restore the search description

**Settings → Search preferences → Meta tags → Description → Enable**, and paste a blog-level
description. Then in the post's **Search description** field paste the post's own:

> Install Python in Termux on Android, write a complete interactive CLI demo app using nano, and run your scripts with zero compilation headaches.

While in Settings, also set **Posts, comments and media → Lightbox = No** (it injects extra CSS/JS
and wraps every image in a link with no accessible name). Both are described in `POST_RULES.md` §9.

### 5.5 Then ask Google again, per post

1. Search Console → **Sitemaps** → resubmit `sitemap.xml` (clears the "Temporary processing error").
2. Search Console → **URL Inspection** → **Test Live URL** on each affected post.
   - **Report B's post** (redirect error): if the live test passes, **Request Indexing**. If it
     fails again with the redirect error, inspect and request the **`?m=1`** version instead (2.4).
   - **Report A's post**: inspect the canonical URL
     `https://freestackhub.blogspot.com/2026/09/install-python-in-termux-build-and-run.html`
     (not the `?m=1` variant) → **Request Indexing**.
3. Request indexing for the two sister posts you re-pasted as well - their bodies changed.
4. Do the fixes **before** the re-crawl requests. A re-crawl of the broken state just re-confirms it.
5. Wait a few days, then inspect again. Expect "URL is on Google", or at worst a crawl date that
   moved.

### 5.6 Optional, but worth it

- `API INDEXING/dashboard` can push unindexed URLs and read their inspection state. Treat it as a
  monitor: Google documents the Indexing API for `JobPosting`/`BroadcastEvent` only, so a `200` there
  is not a promise about a blog post. The real levers are the internal links and Search Console's own
  Request Indexing.
- Nothing to do about thumbnails: the theme's Popular Posts widget and the home-page cards both use
  the post's own first image (`data:post.featuredImage`), which Blogger proxies, so the newest post
  already shows a picture in the sidebar.

---

## 6. Verifying, and keeping it fixed

```bash
python3 tools/check_published.py            # live titles, labels, permalinks, images, links, canonical, robots
python3 tools/check_published.py --no-links # feed + CDN only; no live page fetches
python3 tools/check_perf.py                 # offline; must print "clean"
```

`check_published.py` exits 1 on any FAIL, so none of the states that caused these two reports can
pass unnoticed again: a link built from a folder slug is fetched and reported as a 404, a post that
nothing links to is reported as an orphan, and a live page whose `rel=canonical` is missing or points
somewhere else - or that ships a `noindex` - fails the post outright.

Three habits that prevent a repeat:

- **Publish with `import.xml`.** It is the only route that carries the title, the labels and the
  search description, and it pins `<blogger:filename>` to the slug the repo expects. If you paste the
  body instead, Blogger invents the URL from the title - then set `PERMALINK:` in `post.html` to
  whatever it invented (section 1 of `POST_RULES.md`) before you write any other post's link to it.
- **Never write an internal link from the folder name.** Open the live post, copy its URL, and use
  that. `check_published.py` will catch the mistake, but only after it is published.
- **Never remove `<b:include data='blog' name='all-head-content'/>` from the theme.** It is the one
  line that emits `rel=canonical`; `check_perf.py` fails the theme if it goes missing, because that
  is the tag that keeps the mobile `?m=1` URL and the desktop URL the same page in Google's eyes.
