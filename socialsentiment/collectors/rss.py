"""RSS / Atom news collector (polling, no credentials needed)."""

from __future__ import annotations

import calendar
import logging
import threading
import urllib.request
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote_plus

from socialsentiment import settings
from socialsentiment.collectors.base import Collector, Sink
from socialsentiment.models import Post
from socialsentiment.storage import now_ms
from socialsentiment.text import strip_html

log = logging.getLogger(__name__)

ACCEPT_HEADER = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
    "text/xml;q=0.9, */*;q=0.8"
)


def _entry_ts_ms(entry: Any, fallback_ms: int) -> int:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key) if hasattr(entry, "get") else None
        if parsed:
            return int(calendar.timegm(parsed) * 1000)
    return fallback_ms


def parse_entry(
    feed_name: str, entry: Any, fallback_ms: int | None = None
) -> Post | None:
    """Map one feedparser entry to a :class:`Post`."""
    link = str(entry.get("link") or "")
    entry_id = str(entry.get("id") or link)
    if not entry_id:
        return None
    title = strip_html(str(entry.get("title") or ""))
    summary = strip_html(str(entry.get("summary") or ""))
    text = title if not summary or summary == title else f"{title}. {summary}"
    text = text.strip()
    if not text:
        return None
    return Post(
        source="rss",
        source_id=f"{feed_name}|{entry_id}",
        ts_ms=_entry_ts_ms(entry, fallback_ms or now_ms()),
        text=text,
        author=feed_name,
        url=link,
    )


def google_news_feeds(terms: Sequence[str]) -> list[str]:
    """One Google News search feed per tracked term."""
    template = settings.RSS_GOOGLE_NEWS_TEMPLATE
    return [template.format(term=quote_plus(term)) for term in terms]


class RssCollector(Collector):
    name = "rss"

    def __init__(
        self,
        sink: Sink,
        *,
        feeds: Sequence[str] = tuple(settings.RSS_FEEDS),
        poll_seconds: int = settings.RSS_POLL_SECONDS,
        user_agent: str = settings.RSS_USER_AGENT,
        fetch_timeout: float = settings.RSS_FETCH_TIMEOUT_SECONDS,
        add_google_news: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(sink, **kwargs)
        self.feeds = list(feeds)
        if add_google_news and self.terms:
            self.feeds.extend(google_news_feeds(self.terms))
        if not self.feeds:
            raise ValueError("rss: no feeds configured")
        self.poll_seconds = poll_seconds
        self.user_agent = user_agent
        self.fetch_timeout = fetch_timeout

    def _fetch(self, url: str) -> Any:
        """Download and parse one feed with a bounded socket timeout.

        ``feedparser.parse(url)`` has no timeout, so a host that accepts the
        connection and never answers would block the poll loop forever.
        """
        import feedparser

        if url.startswith(("http://", "https://")):
            request = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent, "Accept": ACCEPT_HEADER},
            )
            with urllib.request.urlopen(
                request, timeout=self.fetch_timeout
            ) as response:
                data = response.read()
                headers = dict(response.headers.items())
            return feedparser.parse(data, response_headers=headers)
        return feedparser.parse(url, agent=self.user_agent)

    def poll(self) -> int:
        """Fetch every feed once; return the number of emitted posts.

        A feed that fails (network error, timeout, unparseable body) is
        logged and skipped so the others keep their cadence.
        """
        emitted = 0
        for url in self.feeds:
            try:
                parsed = self._fetch(url)
            except Exception as exc:
                log.warning(
                    "rss: %s fetch failed (%s: %s)",
                    url,
                    type(exc).__name__,
                    exc,
                )
                continue
            if parsed.get("bozo") and not parsed.entries:
                log.warning(
                    "rss: %s could not be parsed (%s)",
                    url,
                    parsed.get("bozo_exception"),
                )
                continue
            feed_name = str(parsed.feed.get("title") or url)
            for entry in parsed.entries:
                post = parse_entry(feed_name, entry)
                if post is not None and self.emit(post):
                    emitted += 1
        return emitted

    def run_once(self, stop_event: threading.Event) -> None:
        log.info("rss: polling %d feed(s)", len(self.feeds))
        while not stop_event.is_set():
            emitted = self.poll()
            log.debug("rss: poll done, %d accepted", emitted)
            if stop_event.wait(self.poll_seconds):
                break
