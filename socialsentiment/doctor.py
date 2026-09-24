"""Connectivity self-test for every configured source (``check`` command).

Each check opens a real connection with a short timeout and reports what
came back, so a fresh machine can tell in half a minute which sources work
and why the others do not, without starting the collector.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from socialsentiment import settings
from socialsentiment.collectors import available_sources
from socialsentiment.collectors.bluesky import POST_COLLECTION, parse_event
from socialsentiment.collectors.rss import RssCollector, google_news_feeds

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    source: str
    ok: bool
    detail: str
    hint: str = ""


def _fail(source: str, exc: BaseException, hint: str) -> CheckResult:
    return CheckResult(source, False, f"{type(exc).__name__}: {exc}", hint)


def check_bluesky(
    url: str = settings.BLUESKY_JETSTREAM_URL,
    seconds: float = 5.0,
    connect_timeout: float = 15.0,
) -> CheckResult:
    """Connect to Jetstream and count posts for ``seconds``."""
    from websockets.sync.client import connect

    endpoint = f"{url}?{urlencode({'wantedCollections': POST_COLLECTION})}"
    hint = (
        "check SS_BLUESKY_JETSTREAM_URL and that outbound websockets "
        "(wss, port 443) are allowed by your firewall or proxy"
    )
    posts = 0
    sample = ""
    try:
        with connect(
            endpoint, open_timeout=connect_timeout, max_size=2**20
        ) as socket:
            deadline = time.monotonic() + seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = socket.recv(timeout=remaining)
                except TimeoutError:
                    break
                try:
                    post = parse_event(raw)
                except Exception:
                    continue
                if post is not None:
                    posts += 1
                    sample = sample or post.text[:60].replace("\n", " ")
    except Exception as exc:
        return _fail("bluesky", exc, hint)
    if not posts:
        return CheckResult(
            "bluesky", False, f"connected, no posts in {seconds:.0f} s", hint
        )
    return CheckResult(
        "bluesky", True, f"{posts / seconds:.0f} posts/s, e.g. {sample!r}"
    )


def check_rss(
    feeds: Sequence[str] | None = None,
    terms: Sequence[str] = (),
) -> list[CheckResult]:
    """Fetch every feed once and report entry counts."""
    urls = list(feeds if feeds is not None else settings.RSS_FEEDS)
    if terms:
        urls.extend(google_news_feeds(terms))
    collector = RssCollector(lambda post: None, feeds=urls or ["x"],
                             add_google_news=False)
    results: list[CheckResult] = []
    for url in urls:
        name = f"rss {urlsplit(url).netloc}"
        try:
            parsed = collector._fetch(url)
        except Exception as exc:
            results.append(_fail(name, exc, f"feed URL: {url}"))
            continue
        entries = len(parsed.entries)
        if parsed.get("bozo") and not entries:
            results.append(
                CheckResult(
                    name, False,
                    f"not a feed ({parsed.get('bozo_exception')})",
                    f"feed URL: {url}",
                )
            )
            continue
        title = str(parsed.feed.get("title") or "untitled")
        results.append(CheckResult(name, True, f"{entries} entries, {title!r}"))
    return results


def check_reddit(
    subreddits: Sequence[str] = tuple(settings.REDDIT_SUBREDDITS),
    client_id: str = settings.REDDIT_CLIENT_ID,
    client_secret: str = settings.REDDIT_CLIENT_SECRET,
    user_agent: str = settings.REDDIT_USER_AGENT,
) -> CheckResult:
    """Authenticate read-only and fetch the newest submission."""
    hint = (
        "create a 'script' app at https://www.reddit.com/prefs/apps and set "
        "SS_REDDIT_CLIENT_ID / SS_REDDIT_CLIENT_SECRET in .env"
    )
    if not client_id or not client_secret:
        return CheckResult("reddit", False, "credentials not set", hint)
    try:
        import praw

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            check_for_async=False,
        )
        reddit.read_only = True
        newest = next(iter(reddit.subreddit("+".join(subreddits)).new(limit=1)))
        title = str(getattr(newest, "title", ""))[:60]
    except Exception as exc:
        return _fail("reddit", exc, hint)
    return CheckResult("reddit", True, f"r/{'+'.join(subreddits)}: {title!r}")


def check_x(bearer_token: str = settings.X_BEARER_TOKEN) -> CheckResult:
    """Verify the bearer token against the stream-rules endpoint."""
    hint = (
        "set SS_X_BEARER_TOKEN; the filtered stream needs an access tier "
        "that includes streaming (check the current X developer pricing)"
    )
    if not bearer_token:
        return CheckResult("x", False, "SS_X_BEARER_TOKEN not set", hint)
    try:
        import tweepy

        response = tweepy.StreamingClient(bearer_token).get_rules()
        rules = response.data or []
    except Exception as exc:
        return _fail("x", exc, hint)
    return CheckResult("x", True, f"token accepted, {len(rules)} rule(s) set")


def run_checks(
    sources: Sequence[str] | None = None,
    *,
    seconds: float = 5.0,
    terms: Sequence[str] = (),
) -> list[CheckResult]:
    """Run the checks for ``sources`` (default: all real sources)."""
    wanted = list(sources) if sources else [
        s for s in available_sources() if s != "synthetic"
    ]
    results: list[CheckResult] = []
    for source in wanted:
        if source == "bluesky":
            results.append(check_bluesky(seconds=seconds))
        elif source == "rss":
            results.extend(check_rss(terms=terms))
        elif source == "reddit":
            results.append(check_reddit())
        elif source == "x":
            results.append(check_x())
        elif source == "synthetic":
            results.append(CheckResult("synthetic", True, "always available"))
        else:
            results.append(
                CheckResult(source, False, "unknown source",
                            f"choose from {available_sources()}")
            )
    return results


def format_report(results: Sequence[CheckResult]) -> str:
    """Plain-text table for the terminal."""
    width = max((len(r.source) for r in results), default=6)
    lines = []
    for result in results:
        status = "OK  " if result.ok else "FAIL"
        lines.append(f"{status}  {result.source:<{width}}  {result.detail}")
        if not result.ok and result.hint:
            lines.append(f"      {'':<{width}}  hint: {result.hint}")
    passed = sum(1 for r in results if r.ok)
    lines.append(f"{passed}/{len(results)} checks passed")
    return "\n".join(lines)
