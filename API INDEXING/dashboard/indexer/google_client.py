"""Google Indexing API + Search Console API client, and a demo client with the same shape.

Every call returns a Result(ok, status, data, error, hint, duration_ms). Nothing raises for
HTTP-level problems; the caller logs the Result and decides what to do.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .config import (
    DEMO_STATE_PATH, INSPECT_ENDPOINT, KEY_PATH, METADATA_ENDPOINT, PUBLISH_ENDPOINT,
    SCOPES, SITES_ENDPOINT, USER_AGENT,
)


@dataclass
class Result:
    ok: bool
    status: int = 0
    data: dict = field(default_factory=dict)
    error: str = ""
    hint: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------- hints

def explain_error(kind: str, status: int, message: str) -> str:
    """Turn Google's terse error into a next step the user can act on."""
    m = (message or "").lower()
    if status == 401:
        return "The key was rejected (401). Re-download the service-account JSON key, and check the server clock is correct."
    if status == 429 or "quota" in m or "rate limit" in m:
        if kind == "publish":
            return "Indexing API quota hit (200 publish requests/day per Cloud project, resets midnight Pacific). Wait for the reset or request a quota increase in Google Cloud → IAM → Quotas."
        return "URL Inspection quota hit (2,000/day and 600/min per property, rolling 24 h). Slow down or wait."
    if status == 403:
        if "has not been used in project" in m or "is disabled" in m:
            api = "Indexing API" if kind in ("publish", "metadata") else "Google Search Console API"
            return f"The {api} is not enabled for this Cloud project. Enable it at console.cloud.google.com → APIs & Services → Library, then retry."
        if kind in ("publish", "metadata"):
            return ("Google could not verify ownership. In Search Console → Settings → Users and permissions, the service-account "
                    "email must be added as an OWNER of this property (Full/Restricted user is not enough).")
        return ("The service account cannot see this property. Add its email in Search Console → Users and permissions, "
                "and make sure the site URL matches exactly how Google lists it (use the property picker).")
    if status == 400:
        if "not a part of" in m or "not in property" in m or "does not belong" in m:
            return "This URL is not inside the selected Search Console property. Pick the right property or fix the URL."
        if "invalid" in m and "url" in m:
            return "Google rejected the URL format. It must be absolute (https://…) and belong to a verified property."
        return "Google rejected the request (400). See the raw response for details."
    if status == 404 and kind == "metadata":
        return "Google has no notification on record for this URL — it has never been pushed via the Indexing API (from any project)."
    if status >= 500:
        return "Google returned a server error. This is temporary — retry in a minute."
    if status == 0:
        return "Could not reach Google. Check the internet connection / firewall of this machine."
    return ""


# ---------------------------------------------------------------- response parsing

def parse_inspection(data: dict) -> dict:
    """Flatten the URL Inspection response into the columns we store."""
    ir = (data or {}).get("inspectionResult", {}) or {}
    isr = ir.get("indexStatusResult", {}) or {}
    rr = ir.get("richResultsResult") or {}

    def clean(v):
        # Google uses *_UNSPECIFIED enums for "no data" – store NULL instead.
        if not v or str(v).endswith("_UNSPECIFIED"):
            return None
        return v

    return {
        "verdict": clean(isr.get("verdict")) or "NEUTRAL",
        "coverage": isr.get("coverageState") or "",
        "last_crawl": isr.get("lastCrawlTime") or None,
        "crawled_as": clean(isr.get("crawledAs")),
        "fetch_state": clean(isr.get("pageFetchState")),
        "robots_state": clean(isr.get("robotsTxtState")),
        "indexing_state": clean(isr.get("indexingState")),
        "google_canonical": isr.get("googleCanonical") or None,
        "user_canonical": isr.get("userCanonical") or None,
        "referring_urls": isr.get("referringUrls") or [],
        "sitemaps": isr.get("sitemap") or [],
        "rich_results": rr or None,
        "result_link": ir.get("inspectionResultLink") or None,
    }


# ---------------------------------------------------------------- live client

class LiveClient:
    mode = "live"

    def __init__(self, key_path=KEY_PATH):
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        self.creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
        self.session = AuthorizedSession(self.creds)
        self.session.headers["User-Agent"] = USER_AGENT
        self.email = self.creds.service_account_email
        self.project_id = getattr(self.creds, "project_id", None)

    # -- generic request with retries on transient failures
    def _request(self, kind, method, url, **kw) -> Result:
        started = time.monotonic()
        last_exc = None
        for attempt in range(3):
            try:
                resp = self.session.request(method, url, timeout=30, **kw)
            except Exception as e:  # network / auth refresh failure
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
                continue
            duration = int((time.monotonic() - started) * 1000)
            try:
                data = resp.json() if resp.content else {}
            except ValueError:
                data = {"_raw_text": resp.text[:2000]}
            if resp.status_code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            if 200 <= resp.status_code < 300:
                return Result(True, resp.status_code, data, duration_ms=duration)
            err = data.get("error", {}) if isinstance(data, dict) else {}
            message = err.get("message") if isinstance(err, dict) else None
            message = message or data.get("_raw_text") or resp.reason or f"HTTP {resp.status_code}"
            return Result(False, resp.status_code, data, error=str(message)[:1000],
                          hint=explain_error(kind, resp.status_code, str(message)), duration_ms=duration)
        duration = int((time.monotonic() - started) * 1000)
        msg = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "request failed"
        return Result(False, 0, {}, error=msg[:500], hint=explain_error(kind, 0, msg), duration_ms=duration)

    def list_sites(self) -> Result:
        return self._request("sites", "GET", SITES_ENDPOINT)

    def inspect(self, url, site_url) -> Result:
        return self._request("inspect", "POST", INSPECT_ENDPOINT,
                             json={"inspectionUrl": url, "siteUrl": site_url, "languageCode": "en-US"})

    def publish(self, url, request_type="URL_UPDATED") -> Result:
        return self._request("publish", "POST", PUBLISH_ENDPOINT, json={"url": url, "type": request_type})

    def metadata(self, url) -> Result:
        return self._request("metadata", "GET", f"{METADATA_ENDPOINT}?url={quote(url, safe='')}")


# ---------------------------------------------------------------- demo client

_DEMO_SCENARIOS = [
    "indexed", "indexed", "indexed", "indexed", "indexed_desktop", "indexed_no_sitemap",
    "discovered", "crawled_not_indexed", "unknown", "duplicate_canonical", "redirect", "noindex",
]


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


class DemoClient:
    """Fakes Google with believable, time-evolving data. No network."""

    mode = "demo"
    email = "indexer-demo@free-stack-hub-demo.iam.gserviceaccount.com"
    project_id = "free-stack-hub-demo"

    def __init__(self):
        self.state = {"pushed": {}, "scenarios": {}}
        if os.path.exists(DEMO_STATE_PATH):
            try:
                with open(DEMO_STATE_PATH) as f:
                    self.state.update(json.load(f))
            except Exception:
                pass

    def _save(self):
        os.makedirs(os.path.dirname(DEMO_STATE_PATH), exist_ok=True)
        with open(DEMO_STATE_PATH, "w") as f:
            json.dump(self.state, f)

    def set_scenario(self, url, scenario):
        self.state["scenarios"][url] = scenario
        self._save()

    def scenario_for(self, url):
        s = self.state["scenarios"].get(url)
        if s:
            return s
        return _DEMO_SCENARIOS[_h(url) % len(_DEMO_SCENARIOS)]

    @staticmethod
    def _sleep():
        time.sleep(0.12)

    def list_sites(self) -> Result:
        self._sleep()
        return Result(True, 200, {"siteEntry": [
            {"siteUrl": "https://freestackhub.blogspot.com/", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:example-second-blog.com", "permissionLevel": "siteFullUser"},
        ]}, duration_ms=120)

    def publish(self, url, request_type="URL_UPDATED") -> Result:
        self._sleep()
        if self.scenario_for(url) == "forbidden":
            return Result(False, 403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
                                                  "message": "Permission denied. Failed to verify the URL ownership."}},
                          error="Permission denied. Failed to verify the URL ownership.",
                          hint=explain_error("publish", 403, "Permission denied"), duration_ms=140)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.state["pushed"][url] = {"at": now.isoformat(), "type": request_type}
        self._save()
        return Result(True, 200, {"urlNotificationMetadata": {
            "url": url, "latestUpdate": {"url": url, "type": request_type, "notifyTime": now.isoformat()}}},
            duration_ms=140)

    def metadata(self, url) -> Result:
        self._sleep()
        p = self.state["pushed"].get(url)
        if not p:
            return Result(False, 404, {"error": {"code": 404, "message": "Requested entity was not found."}},
                          error="Requested entity was not found.", hint=explain_error("metadata", 404, ""), duration_ms=90)
        return Result(True, 200, {"url": url, "latestUpdate": {"url": url, "type": p["type"], "notifyTime": p["at"]}},
                      duration_ms=90)

    def inspect(self, url, site_url) -> Result:
        self._sleep()
        if site_url and not site_url.startswith("sc-domain:") and not url.startswith(site_url.rstrip("/")):
            return Result(False, 400, {"error": {"code": 400, "message": f"URL '{url}' is not a part of property '{site_url}'."}},
                          error=f"URL is not a part of property '{site_url}'.",
                          hint=explain_error("inspect", 400, "not a part of"), duration_ms=100)

        now = datetime.now(timezone.utc).replace(microsecond=0)
        seed = _h(url)
        scenario = self.scenario_for(url)
        days_ago = 2 + seed % 9
        home = site_url if site_url.startswith("http") else "https://freestackhub.blogspot.com/"
        base = {
            "verdict": "PASS", "coverageState": "Submitted and indexed", "robotsTxtState": "ALLOWED",
            "indexingState": "INDEXING_ALLOWED", "pageFetchState": "SUCCESSFUL", "crawledAs": "MOBILE",
            "lastCrawlTime": (now - timedelta(days=days_ago, hours=seed % 23)).isoformat(),
            "googleCanonical": url, "userCanonical": url,
            "sitemap": [home + "sitemap.xml"],
            "referringUrls": [home, home + "search/label/SEO"],
        }
        rich = {"verdict": "PASS", "detectedItems": [{"richResultType": "Article", "items": [{"name": "Article", "issues": []}]}]}

        if scenario == "indexed_desktop":
            base["crawledAs"] = "DESKTOP"
        elif scenario == "indexed_no_sitemap":
            base["coverageState"] = "Indexed, not submitted in sitemap"
            base["sitemap"] = []
        elif scenario == "discovered":
            base.update(verdict="NEUTRAL", coverageState="Discovered - currently not indexed",
                        pageFetchState="PAGE_FETCH_STATE_UNSPECIFIED", crawledAs="CRAWLING_USER_AGENT_UNSPECIFIED",
                        googleCanonical=None, referringUrls=[home])
            base.pop("lastCrawlTime")
            rich = None
        elif scenario == "crawled_not_indexed":
            base.update(verdict="NEUTRAL", coverageState="Crawled - currently not indexed", googleCanonical=None)
            rich = None
        elif scenario == "unknown":
            base.update(verdict="NEUTRAL", coverageState="URL is unknown to Google",
                        robotsTxtState="ROBOTS_TXT_STATE_UNSPECIFIED", indexingState="INDEXING_STATE_UNSPECIFIED",
                        pageFetchState="PAGE_FETCH_STATE_UNSPECIFIED", crawledAs="CRAWLING_USER_AGENT_UNSPECIFIED",
                        googleCanonical=None, userCanonical=None, sitemap=[], referringUrls=[])
            base.pop("lastCrawlTime")
            rich = None
        elif scenario == "duplicate_canonical":
            base.update(verdict="NEUTRAL", coverageState="Duplicate, Google chose different canonical than user",
                        googleCanonical=url + "?m=1")
            rich = None
        elif scenario == "redirect":
            base.update(verdict="NEUTRAL", coverageState="Page with redirect", pageFetchState="REDIRECT_ERROR",
                        googleCanonical=None)
            rich = None
        elif scenario == "noindex":
            base.update(verdict="FAIL", coverageState="Submitted URL marked 'noindex'", indexingState="BLOCKED_BY_META_TAG",
                        googleCanonical=None)
            rich = None
        elif scenario == "robots":
            base.update(verdict="FAIL", coverageState="Submitted URL blocked by robots.txt", robotsTxtState="DISALLOWED",
                        pageFetchState="BLOCKED_ROBOTS_TXT", googleCanonical=None)
            base.pop("lastCrawlTime")
            rich = None
        elif scenario == "server_error":
            base.update(verdict="FAIL", coverageState="Server error (5xx)", pageFetchState="SERVER_ERROR", googleCanonical=None)
            rich = None

        # Time evolution: a pushed URL gets crawled ~1 min later and indexed ~3 min later (demo speed),
        # unless something structural (noindex / robots / redirect) prevents it.
        p = self.state["pushed"].get(url)
        if p and scenario in ("discovered", "crawled_not_indexed", "unknown"):
            pushed_at = datetime.fromisoformat(p["at"])
            elapsed = (now - pushed_at).total_seconds()
            if elapsed >= 60:
                base.update(coverageState="Crawled - currently not indexed", verdict="NEUTRAL", robotsTxtState="ALLOWED",
                            indexingState="INDEXING_ALLOWED", pageFetchState="SUCCESSFUL", crawledAs="MOBILE",
                            lastCrawlTime=(pushed_at + timedelta(seconds=45)).isoformat(), userCanonical=url,
                            sitemap=[home + "sitemap.xml"], referringUrls=[home])
            if elapsed >= 180:
                base.update(verdict="PASS", coverageState="Submitted and indexed", googleCanonical=url)
                rich = {"verdict": "PASS", "detectedItems": [{"richResultType": "Article", "items": [{"name": "Article", "issues": []}]}]}

        result = {"inspectionResult": {
            "inspectionResultLink": f"https://search.google.com/search-console/inspect?resource_id={quote(site_url, safe='')}&id={quote(url, safe='')}",
            "indexStatusResult": base,
            "mobileUsabilityResult": {"verdict": "VERDICT_UNSPECIFIED"},
        }}
        if rich:
            result["inspectionResult"]["richResultsResult"] = rich
        return Result(True, 200, result, duration_ms=100 + seed % 200)


# ---------------------------------------------------------------- factory

_cache = {"client": None, "mode": None, "key_mtime": None, "problem": None}


def get_client(mode: str):
    """Return the client for the configured mode, or None when not connected.

    Never raises: a missing or unreadable key file simply means "not connected", so the
    app falls back to the Setup page instead of crashing. `key_problem()` explains why.
    """
    if mode == "demo":
        if _cache["mode"] != "demo" or _cache["client"] is None:
            _cache.update(client=DemoClient(), mode="demo", key_mtime=None)
        return _cache["client"]
    if mode == "live":
        if not os.path.exists(KEY_PATH):
            _cache["problem"] = "No key file found. Upload the service-account JSON again."
            return None
        mtime = os.path.getmtime(KEY_PATH)
        if _cache["mode"] != "live" or _cache["client"] is None or _cache["key_mtime"] != mtime:
            try:
                _cache.update(client=LiveClient(KEY_PATH), mode="live", key_mtime=mtime, problem=None)
            except Exception as e:  # corrupt / hand-edited / wrong file
                _cache.update(client=None, mode="live", key_mtime=mtime,
                              problem=f"The stored key file could not be loaded ({type(e).__name__}: {str(e)[:120]}). Upload it again.")
                return None
        return _cache["client"]
    return None


def key_problem():
    """Why the live client is unavailable (None when everything is fine)."""
    return _cache.get("problem")


def key_info() -> dict:
    """Non-secret facts about the stored key, for the Setup page."""
    if not os.path.exists(KEY_PATH):
        return {}
    info = {"added_at": datetime.fromtimestamp(os.path.getmtime(KEY_PATH), tz=timezone.utc).replace(microsecond=0).isoformat(),
            "size": os.path.getsize(KEY_PATH)}
    try:
        with open(KEY_PATH) as f:
            data = json.load(f)
        info.update(email=data.get("client_email"), project_id=data.get("project_id"),
                    key_id=(data.get("private_key_id") or "")[:8])
    except Exception:
        info["corrupt"] = True
    return info


def forget_client():
    _cache.update(client=None, mode=None, key_mtime=None, problem=None)


def validate_key_file(path) -> tuple:
    """Return (ok, message, email). Reads the JSON without hitting the network."""
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return False, f"Not valid JSON: {e}", None
    if data.get("type") != "service_account":
        return False, "This JSON is not a service-account key (\"type\" must be \"service_account\"). OAuth client IDs and API keys do not work here.", None
    for k in ("client_email", "private_key", "token_uri"):
        if not data.get(k):
            return False, f"Key file is missing \"{k}\".", None
    try:
        from google.oauth2 import service_account
        service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    except Exception as e:
        return False, f"google-auth could not load the key: {e}", None
    return True, "ok", data["client_email"]
