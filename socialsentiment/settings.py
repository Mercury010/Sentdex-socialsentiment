"""Central configuration for :mod:`socialsentiment`.

Directory paths and file names are kept in separate constants so that a
deployment can relocate the data directory or rename a file without touching
any other module.  Every value can be overridden with an environment variable
(or a ``.env`` file in the project root) whose name starts with ``SS_``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent
# A .env in the working directory wins (works for installed packages too);
# the checkout root is read as a fallback.  Existing variables are never
# overridden by either file.
load_dotenv(Path.cwd() / ".env")
load_dotenv(PROJECT_DIR / ".env")

# Data lives next to where you run the tool, not inside site-packages.
DATA_DIR = Path(os.environ.get("SS_DATA_DIR") or Path.cwd() / "data")

# ---------------------------------------------------------------------------
# File names (deliberately separate from the directories above)
# ---------------------------------------------------------------------------
DB_FILENAME = os.environ.get("SS_DB_FILENAME", "socialsentiment.db")
LOG_FILENAME = os.environ.get("SS_LOG_FILENAME", "socialsentiment.log")

# ---------------------------------------------------------------------------
# Full paths
# ---------------------------------------------------------------------------
DB_PATH = DATA_DIR / DB_FILENAME
LOG_PATH = DATA_DIR / LOG_FILENAME


def _env_list(name: str, default: str = "") -> list[str]:
    """Return a comma separated environment variable as a list of strings."""
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    """Integer variable; a missing or blank value means ``default``."""
    raw = os.environ.get(name, "").strip()
    return default if raw == "" else int(raw)


def _env_float(name: str, default: float) -> float:
    """Float variable; a missing or blank value means ``default``."""
    raw = os.environ.get(name, "").strip()
    return default if raw == "" else float(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
# Keep only posts containing one of these terms (case-insensitive).  Empty
# means keep everything the source delivers (full firehose on Bluesky).
TRACK_TERMS = _env_list("SS_TRACK_TERMS")
# Keep only posts in these languages when the source reports one.  Empty
# means keep all languages.  Posts without a language tag are always kept.
LANGS = _env_list("SS_LANGS", "en")
RETENTION_DAYS = _env_int("SS_RETENTION_DAYS", 3)
# Posts stamped further in the future than this are treated as clock skew
# and dropped at ingest; posts older than RETENTION_DAYS are dropped too.
MAX_FUTURE_SKEW_SECONDS = _env_int("SS_MAX_FUTURE_SKEW_SECONDS", 300)
WRITE_FLUSH_SECONDS = _env_float("SS_WRITE_FLUSH_SECONDS", 1.0)
TRENDING_INTERVAL_SECONDS = _env_int("SS_TRENDING_INTERVAL_SECONDS", 30)
TRENDING_SAMPLE_SIZE = _env_int("SS_TRENDING_SAMPLE_SIZE", 5000)
TRENDING_TOP_N = _env_int("SS_TRENDING_TOP_N", 12)
PURGE_INTERVAL_SECONDS = _env_int("SS_PURGE_INTERVAL_SECONDS", 3600)

# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------
# VADER compound >= +threshold is positive, <= -threshold is negative.
POSITIVE_THRESHOLD = _env_float("SS_POSITIVE_THRESHOLD", 0.1)

# ---------------------------------------------------------------------------
# Bluesky (Jetstream: public, no credentials required)
# ---------------------------------------------------------------------------
BLUESKY_JETSTREAM_URL = os.environ.get(
    "SS_BLUESKY_JETSTREAM_URL",
    "wss://jetstream2.us-east.bsky.network/subscribe",
)

# ---------------------------------------------------------------------------
# Reddit (free "script" app credentials from reddit.com/prefs/apps)
# ---------------------------------------------------------------------------
REDDIT_CLIENT_ID = os.environ.get("SS_REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("SS_REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get(
    "SS_REDDIT_USER_AGENT", "socialsentiment/2.0 (by u/your_username)"
)
REDDIT_SUBREDDITS = _env_list(
    "SS_REDDIT_SUBREDDITS",
    "CryptoCurrency,Bitcoin,ethereum,stocks,wallstreetbets,investing",
)
# The subreddit list already defines the topic, so by default TRACK_TERMS
# is not applied to Reddit ("it's going to 100k" in r/Bitcoin is kept).
REDDIT_APPLY_TERMS = _env_bool("SS_REDDIT_APPLY_TERMS", False)

# ---------------------------------------------------------------------------
# RSS / news (no credentials required)
# ---------------------------------------------------------------------------
RSS_FEEDS = _env_list(
    "SS_RSS_FEEDS",
    ",".join(
        [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        ]
    ),
)
# When TRACK_TERMS is set, a Google News search feed is added per term.
RSS_GOOGLE_NEWS_TEMPLATE = os.environ.get(
    "SS_RSS_GOOGLE_NEWS_TEMPLATE",
    "https://news.google.com/rss/search?q={term}&hl=en-US&gl=US&ceid=US:en",
)
RSS_POLL_SECONDS = _env_int("SS_RSS_POLL_SECONDS", 300)
RSS_FETCH_TIMEOUT_SECONDS = _env_float("SS_RSS_FETCH_TIMEOUT_SECONDS", 30.0)
RSS_USER_AGENT = os.environ.get("SS_RSS_USER_AGENT", "socialsentiment/2.0")

# ---------------------------------------------------------------------------
# X / Twitter API v2 (filtered stream; requires a paid access tier)
# ---------------------------------------------------------------------------
X_BEARER_TOKEN = os.environ.get("SS_X_BEARER_TOKEN", "")
# Maximum length of one stream rule (512 on Basic, 1024 on Pro at the time
# of writing; check the current X developer docs).
X_RULE_MAX_LENGTH = _env_int("SS_X_RULE_MAX_LENGTH", 512)

# Sources started by the one-command `run` (collector + dashboard together).
RUN_SOURCES = _env_list("SS_RUN_SOURCES", "bluesky,rss")

# ---------------------------------------------------------------------------
# Synthetic source (offline demo / testing)
# ---------------------------------------------------------------------------
SYNTHETIC_RATE_PER_SECOND = _env_float("SS_SYNTHETIC_RATE_PER_SECOND", 5.0)

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
# IANA name (e.g. Europe/Athens) for chart axes and the posts table.  Empty
# means the machine's current UTC offset (correct now, but it does not
# follow daylight-saving changes inside the retention window).
TIMEZONE = os.environ.get("SS_TIMEZONE", "").strip()
DASH_HOST = os.environ.get("SS_DASH_HOST", "127.0.0.1")
DASH_PORT = _env_int("SS_DASH_PORT", 8050)
DASH_DEBUG = _env_bool("SS_DASH_DEBUG", False)
DEFAULT_TERM = os.environ.get("SS_DEFAULT_TERM", "bitcoin")
LIVE_WINDOW_POSTS = _env_int("SS_LIVE_WINDOW_POSTS", 1000)
# The live panel shows only posts from the last N minutes (older feed items
# stay in the longer-term panel), so "posts / minute" means what it says.
LIVE_WINDOW_MINUTES = _env_int("SS_LIVE_WINDOW_MINUTES", 60)
HISTORY_WINDOW_POSTS = _env_int("SS_HISTORY_WINDOW_POSTS", 10000)
RECENT_TABLE_ROWS = _env_int("SS_RECENT_TABLE_ROWS", 12)
LIVE_REFRESH_MS = _env_int("SS_LIVE_REFRESH_MS", 2000)
HISTORY_REFRESH_MS = _env_int("SS_HISTORY_REFRESH_MS", 30000)
