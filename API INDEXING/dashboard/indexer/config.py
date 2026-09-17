"""Paths, endpoints, quotas and default settings for the indexing console."""

import os

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(PKG_DIR)

# Everything private lives in instance/ (git-ignored): the key, the database, the secret.
INSTANCE_DIR = os.environ.get("INDEXER_INSTANCE_DIR") or os.path.join(BASE_DIR, "instance")
KEY_PATH = os.path.join(INSTANCE_DIR, "service_account.json")
DB_PATH = os.environ.get("INDEXER_DB") or os.path.join(INSTANCE_DIR, "indexer.db")
SECRET_PATH = os.path.join(INSTANCE_DIR, "secret_key")
DEMO_STATE_PATH = os.path.join(INSTANCE_DIR, "demo_state.json")

SCOPES = [
    "https://www.googleapis.com/auth/indexing",
    "https://www.googleapis.com/auth/webmasters.readonly",
]
SITES_ENDPOINT = "https://www.googleapis.com/webmasters/v3/sites"
INSPECT_ENDPOINT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
PUBLISH_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
METADATA_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications/metadata"

# Google's published limits. Publish quota is per Cloud project and resets at
# midnight Pacific; URL Inspection is per Search Console property, rolling 24 h.
QUOTA = {
    "publish_per_day": 200,
    "inspect_per_day": 2000,
    "inspect_per_minute": 600,
    "metadata_per_minute": 180,
}

DEFAULT_SETTINGS = {
    "mode": "",                    # "" (not connected) | "live" | "demo"
    "site_url": "",                # Search Console property exactly as Google lists it
    "blog_url": "",                # where sitemap.xml / feeds live (derived from site_url)
    "inspect_delay_ms": "300",     # pause between inspections (600/min hard limit)
    "publish_delay_ms": "500",
    "publish_reserve": "10",       # publish calls a bulk job must leave for manual use
    "inspect_reserve": "50",
    "push_wait_hours": "48",       # how long after a push before we re-check it
    "stale_inspection_days": "7",  # inspections older than this count as stale
    "auto_recheck_hours": "24",    # 0 = off. Re-inspect pushed URLs after this many hours
    "auto_discover_hours": "0",    # 0 = off. Re-sync sitemap/feed on this interval
    "last_discovery_at": "",
    "last_discovery_summary": "",
}

USER_AGENT = "free-stack-hub-indexing-console/1.0 (+https://freestackhub.blogspot.com)"
