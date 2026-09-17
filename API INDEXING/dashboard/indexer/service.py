"""Business logic: quota accounting, single-URL actions, bulk jobs, smart insights."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db
from .config import QUOTA
from .discovery import blog_url_from_property, discover
from .google_client import get_client, parse_inspection

PACIFIC = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------- helpers

def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def hours_since(s) -> float:
    d = parse_dt(s)
    if not d:
        return 1e9
    return (datetime.now(timezone.utc) - d).total_seconds() / 3600


def setting_int(key, default=0) -> int:
    try:
        return int(float(db.get_setting(key, default) or default))
    except (TypeError, ValueError):
        return default


def current_mode() -> str:
    return db.get_setting("mode", "")


def client():
    return get_client(current_mode())


# ---------------------------------------------------------------- quota

def quota_status() -> dict:
    """Publish quota: per Cloud project, resets at midnight Pacific. Inspect: rolling 24 h."""
    now_utc = datetime.now(timezone.utc)
    pac_midnight = now_utc.astimezone(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    pac_midnight_utc = pac_midnight.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    day_ago = (now_utc - timedelta(hours=24)).replace(microsecond=0).isoformat()
    minute_ago = (now_utc - timedelta(minutes=1)).replace(microsecond=0).isoformat()

    pub_used = db.count_requests_since("publish", pac_midnight_utc) + db.count_requests_since("metadata", pac_midnight_utc)
    insp_used = db.count_requests_since("inspect", day_ago)
    insp_min = db.count_requests_since("inspect", minute_ago)
    next_reset = (pac_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return {
        "publish_used": pub_used,
        "publish_limit": QUOTA["publish_per_day"],
        "publish_left": max(0, QUOTA["publish_per_day"] - pub_used),
        "publish_pct": min(100, round(pub_used * 100 / QUOTA["publish_per_day"])),
        "publish_resets_at": next_reset.isoformat(),
        "publish_resets_in_h": round((next_reset - now_utc).total_seconds() / 3600, 1),
        "inspect_used": insp_used,
        "inspect_limit": QUOTA["inspect_per_day"],
        "inspect_left": max(0, QUOTA["inspect_per_day"] - insp_used),
        "inspect_pct": min(100, round(insp_used * 100 / QUOTA["inspect_per_day"])),
        "inspect_minute": insp_min,
        "inspect_minute_limit": QUOTA["inspect_per_minute"],
    }


def _can_publish(reserve=0) -> bool:
    return quota_status()["publish_left"] > reserve


def _can_inspect(reserve=0) -> bool:
    q = quota_status()
    return q["inspect_left"] > reserve and q["inspect_minute"] < QUOTA["inspect_per_minute"] - 5


# ---------------------------------------------------------------- single actions

def inspect_url(url_id: int, job_id=None) -> dict:
    row = db.get_url(url_id=url_id)
    if not row:
        return {"ok": False, "error": "URL not found"}
    c = client()
    if c is None:
        return {"ok": False, "error": "Not connected"}
    site_url = db.get_setting("site_url")
    if not site_url:
        return {"ok": False, "error": "No Search Console property selected"}

    res = c.inspect(row["url"], site_url)
    ts = db.now_iso()
    if res.ok:
        p = parse_inspection(res.data)
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO inspections(url_id, checked_at, http_status, verdict, coverage, last_crawl, crawled_as, fetch_state, "
                "robots_state, indexing_state, google_canonical, user_canonical, referring_urls, sitemaps, rich_results, result_link, raw) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (url_id, ts, res.status, p["verdict"], p["coverage"], p["last_crawl"], p["crawled_as"], p["fetch_state"],
                 p["robots_state"], p["indexing_state"], p["google_canonical"], p["user_canonical"],
                 json.dumps(p["referring_urls"]), json.dumps(p["sitemaps"]),
                 json.dumps(p["rich_results"]) if p["rich_results"] else None, p["result_link"], json.dumps(res.data)),
            )
            conn.execute(
                "UPDATE urls SET verdict=?, coverage=?, last_crawl=?, crawled_as=?, fetch_state=?, robots_state=?, "
                "indexing_state=?, google_canonical=?, user_canonical=?, inspected_at=?, inspect_error=NULL WHERE id=?",
                (p["verdict"], p["coverage"], p["last_crawl"], p["crawled_as"], p["fetch_state"], p["robots_state"],
                 p["indexing_state"], p["google_canonical"], p["user_canonical"], ts, url_id),
            )
        db.log_request("inspect", url=row["url"], http_status=res.status, ok=True,
                       summary=f"{p['verdict']} — {p['coverage']}", duration_ms=res.duration_ms, job_id=job_id)
        return {"ok": True, **p, "checked_at": ts}

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO inspections(url_id, checked_at, http_status, verdict, error, raw) VALUES (?,?,?,?,?,?)",
            (url_id, ts, res.status, "ERROR", res.error, json.dumps(res.data)),
        )
        conn.execute("UPDATE urls SET verdict='ERROR', inspected_at=?, inspect_error=? WHERE id=?",
                     (ts, f"{res.status}: {res.error}", url_id))
    db.log_request("inspect", url=row["url"], http_status=res.status, ok=False, error=res.error,
                   summary=res.hint, duration_ms=res.duration_ms, job_id=job_id, raw=res.data)
    return {"ok": False, "status": res.status, "error": res.error, "hint": res.hint}


def push_url(url_id: int, request_type="URL_UPDATED", job_id=None) -> dict:
    row = db.get_url(url_id=url_id)
    if not row:
        return {"ok": False, "error": "URL not found"}
    c = client()
    if c is None:
        return {"ok": False, "error": "Not connected"}
    if request_type not in ("URL_UPDATED", "URL_DELETED"):
        return {"ok": False, "error": "Bad request type"}

    res = c.publish(row["url"], request_type)
    ts = db.now_iso()
    if res.ok:
        notify = ((res.data.get("urlNotificationMetadata") or {}).get("latestUpdate") or {}).get("notifyTime") or ts
        with db.tx() as conn:
            conn.execute(
                "UPDATE urls SET pushed_at=?, push_status='ok', push_error=NULL, push_type=?, push_count=push_count+1, notify_time=? WHERE id=?",
                (ts, request_type, notify, url_id),
            )
        db.log_request("publish", url=row["url"], request_type=request_type, http_status=res.status, ok=True,
                       summary=f"Google accepted the notification (notifyTime {notify})", duration_ms=res.duration_ms,
                       job_id=job_id, raw=res.data)
        return {"ok": True, "pushed_at": ts, "notify_time": notify}

    with db.tx() as conn:
        conn.execute("UPDATE urls SET pushed_at=?, push_status='error', push_error=?, push_type=?, push_count=push_count+1 WHERE id=?",
                     (ts, f"{res.status}: {res.error}", request_type, url_id))
    db.log_request("publish", url=row["url"], request_type=request_type, http_status=res.status, ok=False,
                   error=res.error, summary=res.hint, duration_ms=res.duration_ms, job_id=job_id, raw=res.data)
    return {"ok": False, "status": res.status, "error": res.error, "hint": res.hint}


def metadata_url(url_id: int) -> dict:
    """Ask Google what it has on record for this URL (counts against the publish quota!)."""
    row = db.get_url(url_id=url_id)
    c = client()
    if not row or c is None:
        return {"ok": False, "error": "Not connected"}
    res = c.metadata(row["url"])
    if res.ok:
        latest = res.data.get("latestUpdate") or {}
        notify = latest.get("notifyTime")
        if notify:
            with db.tx() as conn:
                conn.execute("UPDATE urls SET notify_time=? WHERE id=?", (notify, url_id))
        db.log_request("metadata", url=row["url"], http_status=res.status, ok=True,
                       summary=f"Google's latest notification: {latest.get('type')} at {notify}", duration_ms=res.duration_ms, raw=res.data)
        return {"ok": True, "latest": latest, "latest_remove": res.data.get("latestRemove")}
    db.log_request("metadata", url=row["url"], http_status=res.status, ok=False, error=res.error, summary=res.hint,
                   duration_ms=res.duration_ms, raw=res.data)
    return {"ok": False, "status": res.status, "error": res.error, "hint": res.hint}


def refresh_properties() -> dict:
    c = client()
    if c is None:
        return {"ok": False, "error": "Not connected"}
    res = c.list_sites()
    if not res.ok:
        db.log_request("sites", http_status=res.status, ok=False, error=res.error, summary=res.hint, duration_ms=res.duration_ms)
        return {"ok": False, "status": res.status, "error": res.error, "hint": res.hint}
    sites = res.data.get("siteEntry", []) or []
    with db.tx() as conn:
        conn.execute("DELETE FROM properties")
        for s in sites:
            conn.execute("INSERT INTO properties(site_url, permission_level, fetched_at) VALUES (?,?,?)",
                         (s.get("siteUrl"), s.get("permissionLevel"), db.now_iso()))
    db.log_request("sites", http_status=res.status, ok=True, summary=f"{len(sites)} propert{'y' if len(sites) == 1 else 'ies'} visible",
                   duration_ms=res.duration_ms)
    return {"ok": True, "sites": sites}


# ---------------------------------------------------------------- selection helpers

def unindexed_ids(include_errors=False, respect_wait=True) -> list:
    """URLs worth pushing: not PASS, not ignored, and not pushed within the wait window."""
    wait_h = setting_int("push_wait_hours", 48)
    rows = db.query("SELECT id, verdict, pushed_at, push_status, indexing_state, robots_state, coverage FROM urls WHERE ignored=0")
    out = []
    for r in rows:
        v = r["verdict"]
        if v == "PASS":
            continue
        if v == "ERROR" and not include_errors:
            continue
        # A push cannot fix noindex / robots blocks – don't burn quota on them.
        if r["indexing_state"] in ("BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER") or r["robots_state"] == "DISALLOWED":
            continue
        if respect_wait and r["push_status"] == "ok" and hours_since(r["pushed_at"]) < wait_h:
            continue
        out.append(r["id"])
    return out


def stale_ids(kind="all") -> list:
    """URLs whose inspection is missing or older than the stale threshold."""
    stale_days = setting_int("stale_inspection_days", 7)
    rows = db.query("SELECT id, inspected_at, verdict FROM urls WHERE ignored=0")
    out = []
    for r in rows:
        if kind == "never" and r["inspected_at"]:
            continue
        if not r["inspected_at"] or hours_since(r["inspected_at"]) > stale_days * 24:
            out.append(r["id"])
    return out


def recheck_ids() -> list:
    """Pushed URLs that were not re-inspected since the push (after the wait window)."""
    wait_h = setting_int("push_wait_hours", 48)
    rows = db.query("SELECT id, pushed_at, inspected_at, verdict FROM urls WHERE ignored=0 AND push_status='ok'")
    out = []
    for r in rows:
        if r["verdict"] == "PASS":
            continue
        pushed, inspected = parse_dt(r["pushed_at"]), parse_dt(r["inspected_at"])
        if pushed and hours_since(r["pushed_at"]) >= wait_h and (not inspected or inspected < pushed):
            out.append(r["id"])
    return out


# ---------------------------------------------------------------- job worker

class Worker:
    """One background thread; jobs run strictly one at a time so quota pacing is honest."""

    def __init__(self):
        self.thread = None
        self.cancel_flag = threading.Event()
        self.lock = threading.Lock()

    def start(self, kind, ids=None, params=None) -> int:
        with self.lock:
            if db.active_job():
                raise RuntimeError("Another job is already running. Wait for it or cancel it first.")
            job_id = db.create_job(kind, total=len(ids or []), params={"ids": ids or [], **(params or {})})
            self.cancel_flag.clear()
            self.thread = threading.Thread(target=self._run, args=(job_id, kind, ids or [], params or {}), daemon=True)
            self.thread.start()
            return job_id

    def cancel(self):
        self.cancel_flag.set()

    def _run(self, job_id, kind, ids, params):
        db.update_job(job_id, status="running", started_at=db.now_iso())
        ok = err = skipped = done = 0
        message = ""
        try:
            if kind == "discover":
                summary = discover(current_mode(), db.get_setting("blog_url") or db.get_setting("site_url"), job_id)
                message = db.get_setting("last_discovery_summary")
                ok, done = 1, 1
                db.update_job(job_id, total=1)
                if summary.get("errors"):
                    err = len(summary["errors"])
                    message += " · " + "; ".join(summary["errors"])[:500]
                db.log_event(f"Discovery finished: {message}", "success" if not err else "warn")
            elif kind in ("inspect_all", "inspect_selected", "inspect_stale", "recheck"):
                delay = setting_int("inspect_delay_ms", 300) / 1000
                reserve = setting_int("inspect_reserve", 50)
                for uid in ids:
                    if self.cancel_flag.is_set():
                        message = "Cancelled by user"
                        break
                    if not _can_inspect(reserve):
                        message = f"Stopped: URL Inspection quota reserve reached ({reserve} left)."
                        db.log_event(message, "warn")
                        break
                    r = inspect_url(uid, job_id)
                    done += 1
                    ok += 1 if r.get("ok") else 0
                    err += 0 if r.get("ok") else 1
                    db.update_job(job_id, done=done, ok_count=ok, err_count=err)
                    if not r.get("ok") and r.get("status") in (401, 403, 429):
                        message = f"Stopped after a {r.get('status')} error: {r.get('hint') or r.get('error')}"
                        db.log_event(message, "error")
                        break
                    time.sleep(delay)
            elif kind in ("push_unindexed", "push_selected"):
                delay = setting_int("publish_delay_ms", 500) / 1000
                reserve = setting_int("publish_reserve", 10)
                rtype = params.get("request_type", "URL_UPDATED")
                for uid in ids:
                    if self.cancel_flag.is_set():
                        message = "Cancelled by user"
                        break
                    if not _can_publish(reserve):
                        message = f"Stopped: Indexing API quota reserve reached ({reserve} left for manual use)."
                        db.log_event(message, "warn")
                        break
                    r = push_url(uid, rtype, job_id)
                    done += 1
                    ok += 1 if r.get("ok") else 0
                    err += 0 if r.get("ok") else 1
                    db.update_job(job_id, done=done, ok_count=ok, err_count=err)
                    if not r.get("ok") and r.get("status") in (401, 403, 429):
                        message = f"Stopped after a {r.get('status')} error: {r.get('hint') or r.get('error')}"
                        db.log_event(message, "error")
                        break
                    time.sleep(delay)
            else:
                raise ValueError(f"Unknown job kind {kind}")
            status = "cancelled" if self.cancel_flag.is_set() else "done"
            if not message:
                message = f"{ok} ok, {err} failed" + (f", {skipped} skipped" if skipped else "")
                db.log_event(f"{kind.replace('_', ' ').title()} finished: {message}", "success" if not err else "warn")
            db.update_job(job_id, status=status, finished_at=db.now_iso(), done=done, ok_count=ok, err_count=err,
                          skipped=skipped, message=message)
        except Exception as e:  # never leave a job stuck in "running"
            db.update_job(job_id, status="failed", finished_at=db.now_iso(), done=done, ok_count=ok, err_count=err,
                          message=f"{type(e).__name__}: {e}")
            db.log_event(f"Job {kind} failed: {e}", "error")


worker = Worker()


class Scheduler:
    """Optional in-process automation: re-check pushed URLs, re-discover the blog."""

    def __init__(self):
        self.thread = None
        self.stop_flag = threading.Event()
        self.last_recheck = None
        self.last_discover = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop_flag.wait(60):
            try:
                self._tick()
            except Exception as e:
                db.log_event(f"Scheduler error: {e}", "error")

    def _tick(self):
        if not current_mode() or db.active_job():
            return
        now = time.monotonic()
        rh = setting_int("auto_recheck_hours", 0)
        if rh > 0 and (self.last_recheck is None or now - self.last_recheck > rh * 3600):
            self.last_recheck = now
            ids = recheck_ids()
            if ids:
                db.log_event(f"Auto re-check: inspecting {len(ids)} pushed URL(s)", "info")
                worker.start("recheck", ids)
                return
        dh = setting_int("auto_discover_hours", 0)
        if dh > 0 and (self.last_discover is None or now - self.last_discover > dh * 3600):
            self.last_discover = now
            db.log_event("Auto discovery: syncing sitemap and feed", "info")
            worker.start("discover")


scheduler = Scheduler()


# ---------------------------------------------------------------- stats & insights

def stats() -> dict:
    rows = db.query("SELECT kind, verdict, coverage, last_crawl, crawled_as, inspected_at, pushed_at, push_status, "
                    "in_sitemap, in_feed, published_at, ignored, indexing_state, robots_state, google_canonical, user_canonical, "
                    "fetch_state FROM urls")
    live = [r for r in rows if not r["ignored"]]
    total = len(live)
    indexed = [r for r in live if r["verdict"] == "PASS"]
    not_indexed = [r for r in live if r["verdict"] in ("NEUTRAL", "FAIL")]
    errors = [r for r in live if r["verdict"] == "ERROR"]
    unchecked = [r for r in live if not r["verdict"]]
    crawled = [r for r in live if r["last_crawl"]]
    never_crawled = [r for r in live if r["verdict"] and r["verdict"] != "ERROR" and not r["last_crawl"]]
    pushed = [r for r in live if r["push_status"] == "ok"]
    push_failed = [r for r in live if r["push_status"] == "error"]
    stale_days = setting_int("stale_inspection_days", 7)
    stale = [r for r in live if r["inspected_at"] and hours_since(r["inspected_at"]) > stale_days * 24]
    blocked = [r for r in live if r["indexing_state"] in ("BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER") or r["robots_state"] == "DISALLOWED"]
    canonical_mismatch = [r for r in live if r["google_canonical"] and r["user_canonical"] and r["google_canonical"] != r["user_canonical"]]
    fetch_problems = [r for r in live if r["fetch_state"] and r["fetch_state"] not in ("SUCCESSFUL",)]
    not_in_sitemap = [r for r in live if r["kind"] in ("post", "page") and not r["in_sitemap"]]
    mobile = sum(1 for r in live if r["crawled_as"] == "MOBILE")
    desktop = sum(1 for r in live if r["crawled_as"] == "DESKTOP")
    recent_crawl = [r for r in crawled if hours_since(r["last_crawl"]) <= 7 * 24]

    coverage_counts = {}
    for r in live:
        if r["coverage"]:
            coverage_counts[r["coverage"]] = coverage_counts.get(r["coverage"], 0) + 1
    coverage_top = sorted(coverage_counts.items(), key=lambda kv: -kv[1])

    kinds = {}
    for r in live:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1

    checked = len(indexed) + len(not_indexed)
    return {
        "total": total, "indexed": len(indexed), "not_indexed": len(not_indexed), "errors": len(errors),
        "unchecked": len(unchecked), "crawled": len(crawled), "never_crawled": len(never_crawled),
        "pushed": len(pushed), "push_failed": len(push_failed), "stale": len(stale), "blocked": len(blocked),
        "canonical_mismatch": len(canonical_mismatch), "fetch_problems": len(fetch_problems),
        "not_in_sitemap": len(not_in_sitemap), "mobile": mobile, "desktop": desktop,
        "recent_crawl": len(recent_crawl), "index_rate": round(len(indexed) * 100 / checked) if checked else None,
        "coverage_top": coverage_top[:8], "kinds": kinds, "ignored": len(rows) - total,
        "pushable": len(unindexed_ids()), "recheck_due": len(recheck_ids()), "stale_days": stale_days,
    }


def insights(s: dict, q: dict, settings: dict) -> list:
    """The 'smart cards': prioritised, actionable observations about the site."""
    out = []
    mode = settings.get("mode")
    if not settings.get("site_url"):
        out.append({"level": "warn", "icon": "◎", "title": "No property selected",
                    "body": "Pick the Search Console property so inspections know which site they belong to.",
                    "action": {"label": "Choose property", "href": "/setup"}})
    if s["total"] == 0:
        out.append({"level": "info", "icon": "⌕", "title": "No URLs yet",
                    "body": "Run discovery to pull every post and page from the blog's sitemap and feed.",
                    "action": {"label": "Discover URLs", "job": "discover"}})
        return out
    if s["unchecked"]:
        out.append({"level": "info", "icon": "?", "title": f"{s['unchecked']} URL{'s' if s['unchecked'] != 1 else ''} never inspected",
                    "body": f"Google has not been asked about {'them' if s['unchecked'] != 1 else 'it'} yet. One inspection each tells you indexed / crawled / canonical in a single call.",
                    "action": {"label": "Inspect unchecked", "job": "inspect_never"}})
    if s["pushable"]:
        out.append({"level": "warn", "icon": "↑", "title": f"{s['pushable']} not-indexed URL{'s' if s['pushable'] != 1 else ''} ready to push",
                    "body": f"Not indexed, not blocked, and not pushed in the last {settings.get('push_wait_hours', '48')} h. "
                            f"Pushing uses {s['pushable']} of your {q['publish_left']} remaining Indexing API calls today.",
                    "action": {"label": "Push all unindexed", "job": "push_unindexed"}})
    if s["recheck_due"]:
        out.append({"level": "info", "icon": "↻", "title": f"{s['recheck_due']} pushed URL{'s' if s['recheck_due'] != 1 else ''} due for a re-check",
                    "body": "Pushed more than the wait window ago and not inspected since. Re-inspecting shows whether Google actually crawled and indexed them.",
                    "action": {"label": "Re-check pushed", "job": "recheck"}})
    if s["blocked"]:
        out.append({"level": "error", "icon": "⛔", "title": f"{s['blocked']} URL{'s' if s['blocked'] != 1 else ''} blocked by noindex / robots.txt",
                    "body": "Pushing cannot fix these. Remove the noindex tag or robots rule (Blogger: Settings → Crawlers and indexing, or the post's custom robots tags) and re-inspect.",
                    "action": {"label": "Show blocked", "href": "/urls?filter=blocked"}})
    if s["canonical_mismatch"]:
        out.append({"level": "warn", "icon": "⇄", "title": f"{s['canonical_mismatch']} canonical mismatch{'es' if s['canonical_mismatch'] != 1 else ''}",
                    "body": "Google chose a different canonical than the page declares (often the ?m=1 mobile URL on Blogger). The indexed copy is the other URL, so this one will never show as indexed.",
                    "action": {"label": "Show mismatches", "href": "/urls?filter=canonical"}})
    if s["fetch_problems"]:
        out.append({"level": "error", "icon": "!", "title": f"{s['fetch_problems']} URL{'s' if s['fetch_problems'] != 1 else ''} with fetch problems",
                    "body": "Googlebot could not fetch the page cleanly (redirect, 404, 5xx, soft-404). Fix the page, then push again.",
                    "action": {"label": "Show fetch issues", "href": "/urls?filter=fetch"}})
    if s["not_in_sitemap"]:
        out.append({"level": "warn", "icon": "▤", "title": f"{s['not_in_sitemap']} post{'s' if s['not_in_sitemap'] != 1 else ''}/page{'s' if s['not_in_sitemap'] != 1 else ''} missing from the sitemap",
                    "body": "Found in the feed but not in sitemap.xml. Drafts, scheduled posts and pages with noindex are left out by Blogger — check whether these are really published.",
                    "action": {"label": "Show them", "href": "/urls?filter=nositemap"}})
    if s["stale"]:
        out.append({"level": "info", "icon": "◷", "title": f"{s['stale']} inspection{'s' if s['stale'] != 1 else ''} older than {s['stale_days']} days",
                    "body": "Index status changes silently. A periodic sweep keeps the dashboard truthful — it costs one inspection per URL out of 2,000/day.",
                    "action": {"label": "Refresh stale", "job": "inspect_stale"}})
    if s["push_failed"]:
        out.append({"level": "error", "icon": "✕", "title": f"{s['push_failed']} push{'es' if s['push_failed'] != 1 else ''} failed",
                    "body": "The last Indexing API request for these URLs was rejected. Open the URL for the exact Google error and the fix.",
                    "action": {"label": "Show failed", "href": "/urls?filter=pushfailed"}})
    if q["publish_pct"] >= 80:
        out.append({"level": "warn", "icon": "▮", "title": f"Indexing API quota {q['publish_pct']}% used",
                    "body": f"{q['publish_left']} of {q['publish_limit']} publish calls left today. Resets in {q['publish_resets_in_h']} h (midnight Pacific). Bulk jobs stop automatically at your reserve of {settings.get('publish_reserve', '10')}.",
                    "action": None})
    if s["index_rate"] is not None and s["total"] >= 5:
        if s["index_rate"] >= 90:
            out.append({"level": "success", "icon": "✓", "title": f"{s['index_rate']}% of inspected URLs are indexed",
                        "body": "Healthy. Keep discovery + a weekly stale sweep running and new posts will show up here automatically.", "action": None})
        elif s["index_rate"] < 50:
            out.append({"level": "warn", "icon": "▽", "title": f"Only {s['index_rate']}% of inspected URLs are indexed",
                        "body": "Below half. Before pushing more, check content quality and internal links — 'Crawled - currently not indexed' is Google saying it saw the page and chose not to keep it.", "action": None})
    if s["desktop"] and s["mobile"] and s["desktop"] > s["mobile"]:
        out.append({"level": "info", "icon": "▭", "title": "Mostly crawled as DESKTOP",
                    "body": "Google indexes mobile-first. More desktop than mobile crawls usually means the mobile version (?m=1 on Blogger) has problems or is blocked.", "action": None})
    if mode == "demo":
        out.append({"level": "info", "icon": "⚑", "title": "Demo mode",
                    "body": "Everything you see is simulated: pushed URLs get 'crawled' after ~1 minute and 'indexed' after ~3 minutes so you can watch the flow. Upload a real key in Setup to go live.",
                    "action": {"label": "Go live", "href": "/setup"}})
    return out[:8]
