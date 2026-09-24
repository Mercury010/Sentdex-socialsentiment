"""X (Twitter) API v2 filtered-stream collector via Tweepy 4.

The v1.1 ``statuses/filter`` endpoint used by the original project no longer
exists.  The v2 filtered stream needs a bearer token from an access tier
that includes streaming (check the current X developer pricing before
relying on this source).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from socialsentiment import settings
from socialsentiment.collectors.base import Collector, Sink
from socialsentiment.models import Post

log = logging.getLogger(__name__)

TWEET_FIELDS = ["created_at", "lang", "author_id"]


def build_rule(terms: Sequence[str], langs: Sequence[str] = ()) -> str:
    """Compose a v2 stream rule such as ``(btc OR eth) lang:en -is:retweet``.

    Multi-word terms are quoted so they match as phrases.
    """
    if not terms:
        raise ValueError("x: SS_TRACK_TERMS must be set for the X stream")
    quoted = [f'"{t}"' if " " in t else t for t in terms]
    rule = "(" + " OR ".join(quoted) + ") -is:retweet"
    langs = list(langs)
    if len(langs) == 1:
        rule += f" lang:{langs[0]}"
    return rule


def parse_tweet(data: dict[str, Any]) -> Post | None:
    """Map a v2 tweet payload (``tweet.data``) to a :class:`Post`."""
    text = str(data.get("text") or "").strip()
    tweet_id = str(data.get("id") or "")
    if not text or not tweet_id:
        return None
    created = data.get("created_at")
    if isinstance(created, datetime):
        ts_ms = int(created.timestamp() * 1000)
    elif isinstance(created, str):
        stamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
        ts_ms = int(stamp.timestamp() * 1000)
    else:
        ts_ms = int(datetime.now().timestamp() * 1000)
    author = str(data.get("author_id") or "")
    return Post(
        source="x",
        source_id=tweet_id,
        ts_ms=ts_ms,
        text=text,
        author=author,
        lang=str(data.get("lang") or ""),
        url=f"https://x.com/i/web/status/{tweet_id}",
    )


class XStreamCollector(Collector):
    name = "x"

    def __init__(
        self,
        sink: Sink,
        *,
        bearer_token: str = settings.X_BEARER_TOKEN,
        **kwargs: Any,
    ) -> None:
        super().__init__(sink, **kwargs)
        if not bearer_token:
            raise ValueError("x: SS_X_BEARER_TOKEN must be set")
        self.bearer_token = bearer_token
        self.rule = build_rule(self.terms, sorted(self.langs))

    def run_once(self, stop_event: threading.Event) -> None:
        import tweepy

        collector = self

        class _Client(tweepy.StreamingClient):
            def on_tweet(self, tweet: Any) -> None:
                post = parse_tweet(tweet.data)
                if post is not None:
                    collector.emit(post)

            def on_errors(self, errors: Any) -> None:
                log.warning("x: stream errors %s", errors)

            def on_connection_error(self) -> None:
                log.warning("x: connection error, disconnecting")
                self.disconnect()

        client = _Client(self.bearer_token, wait_on_rate_limit=True)
        existing = client.get_rules().data or []
        if existing:
            client.delete_rules([rule.id for rule in existing])
        client.add_rules(tweepy.StreamRule(self.rule))
        log.info("x: streaming with rule %s", self.rule)
        thread = client.filter(tweet_fields=TWEET_FIELDS, threaded=True)
        while not stop_event.is_set() and thread.is_alive():
            stop_event.wait(1.0)
        client.disconnect()
        thread.join(timeout=10.0)
