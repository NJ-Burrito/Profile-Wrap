"""Locked constants. Nothing here is configurable upward.

Config may only choose values at or below a ceiling (or at or above a floor).
``data/caps.json`` mirrors the numeric limits for documentation; a unit test
keeps the two in sync.
"""
from __future__ import annotations

# Exit codes shared by every command.
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_PAUSED = 4

# Hard ceilings and floors (section 13, layer 2).
COMMENTS_REPLIES_PER_DAY_MAX = 10
COMMENTS_PER_POST = 1
ACTION_GAP_SECONDS_FLOOR = 60
POST_GAP_HOURS_FLOOR = 12
POST_GAP_HOURS_DEFAULT = 20
POSTS_PER_WEEK_MAX = 7
POSTS_PER_DUE_RUN = 1
CONNECT_SLOTS_MAX = 5
CONNECT_NOTE_MAX = 200
LIKES_DEFAULT = False
WINDOW_MIN_WIDTH_MINUTES = 60
WINDOW_MARGIN_HOURS = 0.5
STOP_STATUSES = (403, 429)

# Locked behaviours (no configuration, documented here so they are greppable).
LOCKED_BEHAVIOURS = (
    "allow_before_queue",
    "gate_rerun_before_post",
    "ledger_first_post",
    "never_blind_retry",
    "hard_stop_on_429_403",
    "no_password_cookie_browser_dm_read_or_invitation_send_code",
)

# Network policy (section 5, http.py).
# The host name is a policy constant; only profile_wrap/linkedin/ and http.py use it to make requests.
LINKEDIN_API_HOST = "api.linkedin.com"  # profile-wrap-compliance-allow: api-host
LINKEDIN_OAUTH_HOST = "www.linkedin.com"
LINKEDIN_TOKEN_HOSTS = (LINKEDIN_API_HOST, LINKEDIN_OAUTH_HOST)
UPLOAD_HOST_SUFFIXES = (".linkedin.com", ".licdn.com")
APIFY_HOST = "api.apify.com"
TAVILY_HOST = "api.tavily.com"
# Reading providers, in the order a user may chain them; "public" is always the last, rate-limited fallback.
READING_CHAIN_PROVIDERS = ("apify", "tavily", "public")
TAVILY_MONTH_CREDITS = 1000          # Tavily free plan, per calendar month
TAVILY_RESERVE_CREDITS = 100         # never spent by an automatic run
TAVILY_CACHE_DAYS = 3
APIFY_RESERVE_USD = 0.05             # left unspent in the free monthly credit
# Free "public" reader: GET-only, these path prefixes on www.linkedin.com, only with its own acknowledgement.
PUBLIC_READ_PREFIXES = ("/in/", "/posts/", "/feed/update/", "/pulse/")
PUBLIC_READ_GAP_SECONDS_FLOOR = 3
PUBLIC_READ_PAGES_PER_DAY_DEFAULT = 30
PUBLIC_READ_PAGES_PER_DAY_MAX = 100
# Guest PROFILE pages are rate-limited per IP by LinkedIn (about 20 in an hour got an address blocked on 2026-10-19):
# few per run, spread across the day, and a long pause after any 999.
PUBLIC_PROFILE_PER_RUN_DEFAULT = 2
PUBLIC_PROFILE_PER_DAY_DEFAULT = 12
PUBLIC_PROFILE_PER_DAY_MAX = 24
PUBLIC_PROFILE_GAP_MINUTES_DEFAULT = 20
PUBLIC_PROFILE_GAP_MINUTES_FLOOR = 20
PUBLIC_PROFILE_PAUSE_HOURS = 6
PUBLIC_READ_STOP_STATUSES = (999, 429, 403)
LINKEDIN_ENDPOINT_ALLOWLIST = (
    "/v2/userinfo",
    "/rest/posts",
    "/rest/images",
    "/rest/documents",
)
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# Enumerations other packages validate against.
POST_STATUSES = (
    "draft", "revising", "hold", "queued", "missed",
    "needs_check", "posted", "rejected", "demo",
)
READ_ONLY_STATUSES = ("demo", "posted")
POSTING_MODES = ("copy", "api_click", "api_scheduled")
GOALS = ("authority", "clients", "job_seeking", "hiring", "network")
STYLE_PRESETS = ("plain", "impact_copy", "adhd_emoji")
FONT_SOURCES = ("google_ofl", "system", "user_files")
EVIDENCE_GRADES = ("A", "B", "C", "X")
FACT_STATUSES = ("draft", "verified", "do_not_use", "superseded")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FORMATS = ("text", "slides", "gif", "image", "document", "multi_image")
MODEL_TIERS = ("lead", "standard", "economy")

# Acknowledgements (section 13, layer 3). action -> config paths it writes.
ACK_PHRASE = "I accept this risk"
ACK_ACTIONS = {
    "terms_read": ("ack.terms_read",),
    "api_scheduled": ("posting.api_scheduled_ack",),
    "comments_api": ("engagement.comments.api_ack", "ack.comments_api"),
    "apify": ("engagement.reading.apify_ack", "ack.scraping_risk"),
    "public": ("engagement.reading.public_ack", "ack.public_reading"),
    "tavily": ("engagement.reading.tavily_ack", "ack.tavily_reading"),
    "likes": (),
}
# Documents whose sha256 binds an acknowledgement, relative to the plugin root.
ACK_DOCUMENTS = ("docs/references/compliance.md", "docs/TERMS-AND-RISK.md")

# Pause flags under <workspace>/work/.
PAUSE_FILE = "PAUSE"
PAUSE_KINDS = ("posting", "comments")

MIN_PYTHON = (3, 10)
WORKER_ENV = "PROFILE_WRAP_WORKER"
TEST_ENV = "PROFILE_WRAP_TEST"
SCHEMA_VERSION = 1


def caps() -> dict:
    """Numeric limits as the dict mirrored in ``data/caps.json``."""
    return {
        "schema_version": SCHEMA_VERSION,
        "comments_replies_per_day_max": COMMENTS_REPLIES_PER_DAY_MAX,
        "comments_per_post": COMMENTS_PER_POST,
        "action_gap_seconds_floor": ACTION_GAP_SECONDS_FLOOR,
        "post_gap_hours_floor": POST_GAP_HOURS_FLOOR,
        "post_gap_hours_default": POST_GAP_HOURS_DEFAULT,
        "posts_per_week_max": POSTS_PER_WEEK_MAX,
        "posts_per_due_run": POSTS_PER_DUE_RUN,
        "connect_slots_max": CONNECT_SLOTS_MAX,
        "connect_note_max": CONNECT_NOTE_MAX,
        "likes_default": LIKES_DEFAULT,
        "stop_statuses": list(STOP_STATUSES),
    }
