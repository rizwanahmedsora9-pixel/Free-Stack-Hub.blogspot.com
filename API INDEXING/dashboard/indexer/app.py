"""Flask application: setup, dashboard, URL table, URL detail, log, settings, JSON API."""

import json
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for)

from . import db
from .config import INSTANCE_DIR, KEY_PATH, PKG_DIR, QUOTA
from .discovery import blog_url_from_property
from .google_client import DemoClient, forget_client, get_client, validate_key_file
from .service import (hours_since, insights, inspect_url, metadata_url, parse_dt, push_url, quota_status,
                      recheck_ids, refresh_properties, scheduler, stale_ids, stats, unindexed_ids, worker)

FILTERS = {
    "all": ("All URLs", "1=1"),
    "indexed": ("Indexed", "verdict='PASS'"),
    "notindexed": ("Not indexed", "verdict IN ('NEUTRAL','FAIL')"),
    "unchecked": ("Never inspected", "verdict IS NULL"),
    "errors": ("Inspection errors", "verdict='ERROR'"),
    "crawled": ("Crawled", "last_crawl IS NOT NULL"),
    "nevercrawled": ("Never crawled", "verdict IS NOT NULL AND verdict!='ERROR' AND last_crawl IS NULL"),
    "pushed": ("Pushed", "push_status='ok'"),
    "notpushed": ("Not pushed", "push_status IS NULL"),
    "pushfailed": ("Push failed", "push_status='error'"),
    "blocked": ("Blocked (noindex/robots)", "indexing_state IN ('BLOCKED_BY_META_TAG','BLOCKED_BY_HTTP_HEADER') OR robots_state='DISALLOWED'"),
    "canonical": ("Canonical mismatch", "google_canonical IS NOT NULL AND user_canonical IS NOT NULL AND google_canonical!=user_canonical"),
    "fetch": ("Fetch problems", "fetch_state IS NOT NULL AND fetch_state!='SUCCESSFUL'"),
    "nositemap": ("Not in sitemap", "kind IN ('post','page') AND in_sitemap=0"),
    "posts": ("Posts", "kind='post'"),
    "pages": ("Pages", "kind='page'"),
    "ignored": ("Ignored", "ignored=1"),
}
SORTS = {
    "newest": "COALESCE(published_at, discovered_at) DESC",
    "oldest": "COALESCE(published_at, discovered_at) ASC",
    "title": "LOWER(COALESCE(title, url)) ASC",
    "status": "CASE verdict WHEN 'FAIL' THEN 0 WHEN 'ERROR' THEN 1 WHEN 'NEUTRAL' THEN 2 WHEN NULL THEN 3 ELSE 4 END, COALESCE(published_at, discovered_at) DESC",
    "crawl": "last_crawl IS NULL, last_crawl DESC",
    "inspected": "inspected_at IS NULL, inspected_at DESC",
    "pushed": "pushed_at IS NULL, pushed_at DESC",
}


def _secret_key() -> str:
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    try:
        with open(os.path.join(INSTANCE_DIR, "secret_key")) as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        with open(os.path.join(INSTANCE_DIR, "secret_key"), "w") as f:
            f.write(key)
        return key


def create_app() -> Flask:
    app = Flask(__name__, template_folder=os.path.join(PKG_DIR, "templates"), static_folder=os.path.join(PKG_DIR, "static"))
    app.secret_key = _secret_key()
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    db.init_db()

    # ------------------------------------------------------------ template helpers
    @app.template_filter("ago")
    def _ago(value):
        d = parse_dt(value)
        if not d:
            return "—"
        secs = (datetime.now(timezone.utc) - d).total_seconds()
        if secs < 0:
            secs = 0
        for unit, size in (("y", 31536000), ("mo", 2592000), ("d", 86400), ("h", 3600), ("m", 60)):
            if secs >= size:
                return f"{int(secs // size)}{unit} ago"
        return "just now"

    @app.template_filter("dt")
    def _dt(value):
        d = parse_dt(value)
        return d.strftime("%Y-%m-%d %H:%M UTC") if d else "—"

    @app.template_filter("date")
    def _date(value):
        d = parse_dt(value)
        return d.strftime("%d %b %Y") if d else "—"

    @app.template_filter("labels")
    def _labels(value):
        if not value:
            return []
        try:
            return json.loads(value) if isinstance(value, str) else list(value)
        except ValueError:
            return []

    @app.template_filter("jsonl")
    def _jsonl(value):
        if not value:
            return []
        try:
            return json.loads(value)
        except ValueError:
            return []

    @app.template_filter("pretty")
    def _pretty(value):
        try:
            return json.dumps(json.loads(value) if isinstance(value, str) else value, indent=2)
        except Exception:
            return value or ""

    @app.template_filter("host")
    def _host(value):
        try:
            p = urlparse(value)
            return (p.path or "/") + (("?" + p.query) if p.query else "")
        except Exception:
            return value

    @app.context_processor
    def _ctx():
        settings = db.get_settings()
        c = get_client(settings["mode"]) if settings["mode"] else None
        return {
            "settings": settings,
            "mode": settings["mode"],
            "connected": c is not None,
            "account_email": getattr(c, "email", None) if c else None,
            "job": db.active_job(),
            "FILTERS": FILTERS,
            "QUOTA": QUOTA,
        }

    # ------------------------------------------------------------ setup
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if request.method == "POST":
            action = request.form.get("action")
            if action == "upload":
                f = request.files.get("keyfile")
                if not f or not f.filename:
                    flash("Choose the service-account JSON key file first.", "error")
                    return redirect(url_for("setup"))
                os.makedirs(INSTANCE_DIR, exist_ok=True)
                tmp = KEY_PATH + ".tmp"
                f.save(tmp)
                ok, msg, email = validate_key_file(tmp)
                if not ok:
                    os.remove(tmp)
                    flash(msg, "error")
                    return redirect(url_for("setup"))
                os.replace(tmp, KEY_PATH)
                os.chmod(KEY_PATH, 0o600)
                forget_client()
                if db.get_setting("mode") == "demo":
                    db.reset_db()
                db.set_setting("mode", "live")
                db.log_event(f"Connected service account {email}", "success")
                r = refresh_properties()
                if r.get("ok"):
                    sites = r["sites"]
                    if len(sites) == 1:
                        _select_property(sites[0]["siteUrl"])
                        flash(f"Connected as {email}. Property {sites[0]['siteUrl']} selected.", "success")
                    elif not sites:
                        flash(f"Connected as {email}, but this account cannot see any Search Console property yet. "
                              f"Add {email} as an Owner in Search Console → Settings → Users and permissions, then click Refresh.", "warn")
                    else:
                        flash(f"Connected as {email}. Choose the property below.", "success")
                else:
                    flash(f"Key accepted ({email}) but listing properties failed: {r.get('error')} — {r.get('hint')}", "error")
                return redirect(url_for("setup"))
            if action == "demo":
                _enter_demo()
                flash("Demo mode: simulated Google responses, real dashboard.", "success")
                return redirect(url_for("dashboard"))
            if action == "select":
                site = request.form.get("site_url", "").strip()
                if not site:
                    flash("Pick a property.", "error")
                else:
                    _select_property(site)
                    flash(f"Property set to {site}", "success")
                return redirect(url_for("setup"))
            if action == "manual":
                site = request.form.get("site_url", "").strip()
                if not site:
                    flash("Enter the property URL.", "error")
                else:
                    _select_property(site)
                    flash(f"Property set to {site}. If inspections return 403, the string does not match Google's — use the list.", "success")
                return redirect(url_for("setup"))
            if action == "refresh":
                r = refresh_properties()
                flash("Property list refreshed." if r.get("ok") else f"{r.get('error')} — {r.get('hint')}", "success" if r.get("ok") else "error")
                return redirect(url_for("setup"))
            if action == "disconnect":
                worker.cancel()
                if os.path.exists(KEY_PATH):
                    os.remove(KEY_PATH)
                forget_client()
                db.reset_db()
                for p in ("demo_state.json",):
                    fp = os.path.join(INSTANCE_DIR, p)
                    if os.path.exists(fp):
                        os.remove(fp)
                flash("Disconnected. The key file and all local data were deleted.", "success")
                return redirect(url_for("setup"))
        props = db.query("SELECT * FROM properties ORDER BY site_url")
        return render_template("setup.html", properties=props, key_present=os.path.exists(KEY_PATH))

    def _select_property(site_url):
        db.set_settings({"site_url": site_url, "blog_url": blog_url_from_property(site_url)})

    def _enter_demo():
        forget_client()
        db.reset_db()
        db.set_setting("mode", "demo")
        _select_property("https://freestackhub.blogspot.com/")
        refresh_properties()
        db.log_event("Demo mode started", "info")

    if os.environ.get("INDEXER_DEMO") == "1" and not db.get_setting("mode"):
        _enter_demo()
        try:
            from .discovery import discover
            discover("demo", "https://freestackhub.blogspot.com/")
        except Exception as e:  # demo bootstrap must never block startup
            db.log_event(f"Demo bootstrap discovery failed: {e}", "warn")
    scheduler.start()

    # ------------------------------------------------------------ dashboard
    @app.route("/")
    def dashboard():
        settings = db.get_settings()
        if not settings["mode"]:
            return redirect(url_for("setup"))
        s = stats()
        q = quota_status()
        cards = insights(s, q, settings)
        recent = db.query("SELECT * FROM requests_log ORDER BY id DESC LIMIT 8")
        events = db.query("SELECT * FROM events ORDER BY id DESC LIMIT 8")
        attention = db.query(
            "SELECT * FROM urls WHERE ignored=0 AND (verdict IN ('FAIL','ERROR') OR push_status='error' OR "
            "(verdict='NEUTRAL' AND push_status IS NULL)) ORDER BY CASE verdict WHEN 'FAIL' THEN 0 WHEN 'ERROR' THEN 1 ELSE 2 END, "
            "COALESCE(published_at, discovered_at) DESC LIMIT 6")
        newest = db.query("SELECT * FROM urls WHERE ignored=0 AND kind='post' ORDER BY COALESCE(published_at, discovered_at) DESC LIMIT 5")
        last_jobs = db.query("SELECT * FROM jobs ORDER BY id DESC LIMIT 5")
        return render_template("dashboard.html", s=s, q=q, cards=cards, recent=recent, events=events,
                               attention=attention, newest=newest, last_jobs=last_jobs)

    # ------------------------------------------------------------ url table
    @app.route("/urls")
    def urls():
        if not db.get_setting("mode"):
            return redirect(url_for("setup"))
        flt = request.args.get("filter", "all")
        if flt not in FILTERS:
            flt = "all"
        sort = request.args.get("sort", "newest")
        if sort not in SORTS:
            sort = "newest"
        qtext = request.args.get("q", "").strip()
        label = request.args.get("label", "").strip()
        where = FILTERS[flt][1]
        params = []
        if flt != "ignored":
            where = f"({where}) AND ignored=0"
        if qtext:
            where += " AND (url LIKE ? OR title LIKE ? OR coverage LIKE ?)"
            params += [f"%{qtext}%"] * 3
        if label:
            where += " AND labels LIKE ?"
            params.append(f'%"{label}"%')
        rows = db.query(f"SELECT * FROM urls WHERE {where} ORDER BY {SORTS[sort]}", params)
        counts = {}
        for key, (_, cond) in FILTERS.items():
            c = f"({cond})" + ("" if key == "ignored" else " AND ignored=0")
            counts[key] = db.scalar(f"SELECT COUNT(*) FROM urls WHERE {c}")
        label_rows = db.query("SELECT labels FROM urls WHERE ignored=0 AND labels IS NOT NULL")
        label_counts = {}
        for r in label_rows:
            try:
                for l in json.loads(r["labels"] or "[]"):
                    label_counts[l] = label_counts.get(l, 0) + 1
            except ValueError:
                pass
        top_labels = sorted(label_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:14]
        return render_template("urls.html", rows=rows, flt=flt, sort=sort, q=qtext, label=label, counts=counts,
                               top_labels=top_labels, SORTS=SORTS)

    @app.route("/url/<int:url_id>")
    def url_detail(url_id):
        row = db.get_url(url_id=url_id)
        if not row:
            abort(404)
        history = db.query("SELECT * FROM inspections WHERE url_id=? ORDER BY id DESC LIMIT 30", (url_id,))
        log = db.query("SELECT * FROM requests_log WHERE url=? ORDER BY id DESC LIMIT 40", (row["url"],))
        latest = history[0] if history else None
        timeline = _timeline(row, history, log)
        return render_template("url_detail.html", u=row, history=history, log=log, latest=latest, timeline=timeline,
                               diagnosis=_diagnose(row))

    def _timeline(row, history, log):
        items = []
        if row.get("published_at"):
            items.append((row["published_at"], "published", "Published on the blog"))
        if row.get("updated_at") and row.get("updated_at") != row.get("published_at"):
            items.append((row["updated_at"], "updated", "Last edited (feed)"))
        items.append((row["discovered_at"], "discovered", f"Discovered by the console ({row.get('source')})"))
        for l in log:
            if l["kind"] == "publish":
                items.append((l["at"], "push-ok" if l["ok"] else "push-err",
                              f"{l['request_type']} {'accepted' if l['ok'] else 'rejected'}" + (f" — HTTP {l['http_status']} {l['error']}" if not l["ok"] else "")))
        for h in history:
            if h["verdict"] == "ERROR":
                items.append((h["checked_at"], "insp-err", f"Inspection failed — {h['error']}"))
            else:
                items.append((h["checked_at"], "insp", f"Inspected: {h['verdict']} — {h['coverage']}"))
        crawls = sorted({h["last_crawl"] for h in history if h.get("last_crawl")})
        for c in crawls:
            items.append((c, "crawl", "Googlebot crawled the page"))
        items.sort(key=lambda t: t[0] or "", reverse=True)
        return items

    def _diagnose(u) -> dict:
        """One-paragraph plain-English reading of the latest inspection."""
        v, cov = u.get("verdict"), (u.get("coverage") or "")
        if not v:
            return {"level": "muted", "title": "Not inspected yet", "body": "Click Inspect to ask Google about this URL."}
        if v == "ERROR":
            return {"level": "error", "title": "Inspection failed", "body": u.get("inspect_error") or "Unknown error."}
        if v == "PASS":
            body = "Google has this page in its index"
            if u.get("last_crawl"):
                body += f", last crawled {hours_since(u['last_crawl']) / 24:.0f} day(s) ago as {u.get('crawled_as') or 'unknown agent'}"
            body += ". Pushing it again is only useful after a meaningful content update."
            return {"level": "success", "title": "Indexed", "body": body}
        if u.get("indexing_state") in ("BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER"):
            return {"level": "error", "title": "Blocked by noindex",
                    "body": "The page tells Google not to index it. Pushing will not help. On Blogger check Settings → Crawlers and indexing → Custom robots header tags, and the post's own settings."}
        if u.get("robots_state") == "DISALLOWED":
            return {"level": "error", "title": "Blocked by robots.txt",
                    "body": "robots.txt forbids crawling this URL, so Google cannot even see the content. Fix the custom robots.txt in Blogger settings."}
        if u.get("google_canonical") and u.get("user_canonical") and u["google_canonical"] != u["user_canonical"]:
            return {"level": "warn", "title": "Google picked a different canonical",
                    "body": f"Google indexed {u['google_canonical']} instead of this URL. This URL will keep showing 'not indexed' even though the content is indexed under the other address. Make sure the page declares one canonical and internal links use it."}
        if u.get("fetch_state") and u["fetch_state"] != "SUCCESSFUL":
            return {"level": "error", "title": f"Fetch problem: {u['fetch_state']}",
                    "body": "Googlebot did not get a clean 200 response. Open the URL in an incognito window, fix whatever you see (redirect loop, 404, error page), then push."}
        if "Discovered" in cov:
            return {"level": "warn", "title": "Discovered, not crawled yet",
                    "body": "Google knows the URL exists (from the sitemap or a link) but has not visited it. This is the normal state for a new post; a push plus internal links from older posts is the fastest way through it."}
        if "Crawled" in cov:
            return {"level": "warn", "title": "Crawled, but Google chose not to index",
                    "body": "Googlebot fetched the page and decided not to keep it — a quality/thin-content signal more than a technical one. Improve the content, add internal links, then push and wait."}
        if "unknown" in cov.lower():
            return {"level": "warn", "title": "Unknown to Google",
                    "body": "Google has never seen this URL. Check that it is in sitemap.xml and linked from the homepage, then push."}
        if "Duplicate" in cov:
            return {"level": "warn", "title": "Treated as a duplicate", "body": cov + ". Consolidate: one URL, one canonical, and links pointing to it."}
        return {"level": "warn", "title": cov or v, "body": "Google is not indexing this URL at the moment. See the raw inspection below for details."}

    # ------------------------------------------------------------ url actions
    @app.route("/url/<int:url_id>/inspect", methods=["POST"])
    def action_inspect(url_id):
        r = inspect_url(url_id)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(r | {"row": _row_json(db.get_url(url_id=url_id))})
        flash(("Inspected: " + f"{r.get('verdict')} — {r.get('coverage')}") if r.get("ok") else f"Inspection failed: {r.get('error')} {r.get('hint') or ''}",
              "success" if r.get("ok") else "error")
        return redirect(request.referrer or url_for("url_detail", url_id=url_id))

    @app.route("/url/<int:url_id>/push", methods=["POST"])
    def action_push(url_id):
        rtype = request.form.get("type", "URL_UPDATED")
        r = push_url(url_id, rtype)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(r | {"row": _row_json(db.get_url(url_id=url_id))})
        flash("Pushed: Google accepted the notification." if r.get("ok") else f"Push failed: {r.get('error')} {r.get('hint') or ''}",
              "success" if r.get("ok") else "error")
        return redirect(request.referrer or url_for("url_detail", url_id=url_id))

    @app.route("/url/<int:url_id>/metadata", methods=["POST"])
    def action_metadata(url_id):
        r = metadata_url(url_id)
        if r.get("ok"):
            latest = r.get("latest") or {}
            flash(f"Google's record: {latest.get('type')} notified at {latest.get('notifyTime')}", "success")
        else:
            flash(f"{r.get('error')} — {r.get('hint') or ''}", "error" if r.get("status") != 404 else "warn")
        return redirect(url_for("url_detail", url_id=url_id))

    @app.route("/url/<int:url_id>/ignore", methods=["POST"])
    def action_ignore(url_id):
        val = 0 if request.form.get("undo") else 1
        with db.tx() as conn:
            conn.execute("UPDATE urls SET ignored=? WHERE id=?", (val, url_id))
        flash("URL ignored — it is excluded from bulk jobs and stats." if val else "URL restored.", "success")
        return redirect(request.referrer or url_for("url_detail", url_id=url_id))

    @app.route("/url/<int:url_id>/delete", methods=["POST"])
    def action_delete(url_id):
        db.delete_url(url_id)
        flash("URL removed from the console (it will come back on the next discovery if it is still on the blog).", "success")
        return redirect(url_for("urls"))

    @app.route("/url/<int:url_id>/scenario", methods=["POST"])
    def action_scenario(url_id):
        c = get_client(db.get_setting("mode"))
        row = db.get_url(url_id=url_id)
        if isinstance(c, DemoClient) and row:
            c.set_scenario(row["url"], request.form.get("scenario", "indexed"))
            flash("Demo scenario changed — inspect again to see it.", "success")
        return redirect(url_for("url_detail", url_id=url_id))

    @app.route("/urls/add", methods=["POST"])
    def add_url():
        raw = request.form.get("urls", "")
        added = 0
        for line in raw.splitlines():
            u = line.strip()
            if u.startswith("http"):
                _, created = db.upsert_url(u, kind="other" if "/p/" not in u and not u.endswith(".html") else ("page" if "/p/" in u else "post"),
                                           source="manual")
                added += 1 if created else 0
        flash(f"Added {added} new URL(s).", "success")
        return redirect(url_for("urls"))

    # ------------------------------------------------------------ jobs
    @app.route("/jobs/start", methods=["POST"])
    def start_job():
        kind = request.form.get("kind") or (request.json or {}).get("kind")
        try:
            if kind == "discover":
                jid = worker.start("discover")
            elif kind == "inspect_all":
                jid = worker.start("inspect_all", [r["id"] for r in db.query("SELECT id FROM urls WHERE ignored=0 ORDER BY COALESCE(published_at, discovered_at) DESC")])
            elif kind == "inspect_never":
                jid = worker.start("inspect_selected", stale_ids("never"))
            elif kind == "inspect_stale":
                jid = worker.start("inspect_stale", stale_ids("all"))
            elif kind == "recheck":
                jid = worker.start("recheck", recheck_ids())
            elif kind == "push_unindexed":
                jid = worker.start("push_unindexed", unindexed_ids())
            elif kind in ("inspect_selected", "push_selected"):
                ids = [int(x) for x in request.form.getlist("ids") if str(x).isdigit()]
                if not ids:
                    flash("Select at least one URL.", "error")
                    return redirect(request.referrer or url_for("urls"))
                params = {"request_type": request.form.get("request_type", "URL_UPDATED")} if kind == "push_selected" else None
                jid = worker.start(kind, ids, params)
            else:
                flash("Unknown job.", "error")
                return redirect(request.referrer or url_for("dashboard"))
        except RuntimeError as e:
            flash(str(e), "error")
            return redirect(request.referrer or url_for("dashboard"))
        job = db.get_job(jid)
        if job and job["total"] == 0 and kind != "discover":
            flash("Nothing to do for that job — no matching URLs.", "warn")
        else:
            flash(f"Started {kind.replace('_', ' ')} ({job['total'] if job else '?'} URL(s)). Progress shows in the top bar.", "success")
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/jobs/cancel", methods=["POST"])
    def cancel_job():
        worker.cancel()
        flash("Cancelling after the current request finishes…", "warn")
        return redirect(request.referrer or url_for("dashboard"))

    @app.route("/api/job")
    def api_job():
        j = db.active_job() or db.query_one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")
        return jsonify(j or {})

    @app.route("/api/stats")
    def api_stats():
        return jsonify({"stats": stats(), "quota": quota_status()})

    @app.route("/api/urls")
    def api_urls():
        return jsonify([_row_json(r) for r in db.query("SELECT * FROM urls WHERE ignored=0 ORDER BY id")])

    def _row_json(r):
        if not r:
            return None
        r = dict(r)
        try:
            r["labels"] = json.loads(r["labels"]) if r.get("labels") else []
        except ValueError:
            r["labels"] = []
        return r

    # ------------------------------------------------------------ log / settings / export
    @app.route("/log")
    def log():
        kind = request.args.get("kind", "")
        where, params = "1=1", []
        if kind in ("publish", "inspect", "metadata", "sites", "discover"):
            where, params = "kind=?", [kind]
        if request.args.get("errors"):
            where += " AND ok=0"
        rows = db.query(f"SELECT * FROM requests_log WHERE {where} ORDER BY id DESC LIMIT 300", params)
        jobs = db.query("SELECT * FROM jobs ORDER BY id DESC LIMIT 30")
        events = db.query("SELECT * FROM events ORDER BY id DESC LIMIT 60")
        return render_template("log.html", rows=rows, jobs=jobs, events=events, kind=kind, errors=bool(request.args.get("errors")))

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        if request.method == "POST":
            fields = {}
            for key in ("inspect_delay_ms", "publish_delay_ms", "publish_reserve", "inspect_reserve", "push_wait_hours",
                        "stale_inspection_days", "auto_recheck_hours", "auto_discover_hours"):
                v = request.form.get(key, "").strip()
                if v:
                    try:
                        fields[key] = str(max(0, int(float(v))))
                    except ValueError:
                        flash(f"{key} must be a number.", "error")
                        return redirect(url_for("settings_page"))
            if int(fields.get("inspect_delay_ms", 300)) < 100:
                fields["inspect_delay_ms"] = "100"
            db.set_settings(fields)
            flash("Settings saved.", "success")
            return redirect(url_for("settings_page"))
        return render_template("settings.html", q=quota_status(), db_path=db.DB_PATH)

    @app.route("/export.json")
    def export_json():
        data = {
            "exported_at": db.now_iso(),
            "settings": {k: v for k, v in db.get_settings().items()},
            "urls": [_row_json(r) for r in db.query("SELECT * FROM urls ORDER BY id")],
            "requests": db.query("SELECT id, at, kind, url, request_type, http_status, ok, summary, error FROM requests_log ORDER BY id"),
        }
        import io
        buf = io.BytesIO(json.dumps(data, indent=2).encode("utf-8"))
        return send_file(buf, mimetype="application/json", as_attachment=True, download_name="indexing-console-export.json")

    @app.route("/export.csv")
    def export_csv():
        import csv
        import io
        rows = db.query("SELECT * FROM urls ORDER BY id")
        buf = io.StringIO()
        cols = ["url", "kind", "title", "labels", "published_at", "verdict", "coverage", "last_crawl", "crawled_as",
                "fetch_state", "robots_state", "indexing_state", "google_canonical", "inspected_at", "pushed_at",
                "push_status", "push_count", "in_sitemap", "in_feed"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
        out = io.BytesIO(buf.getvalue().encode("utf-8"))
        return send_file(out, mimetype="text/csv", as_attachment=True, download_name="indexing-console-urls.csv")

    @app.errorhandler(404)
    def _404(e):
        return render_template("error.html", code=404, message="That page does not exist."), 404

    @app.errorhandler(413)
    def _413(e):
        flash("That file is too large to be a service-account key.", "error")
        return redirect(url_for("setup"))

    return app
