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


def _quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


def build_rule(terms: Sequence[str], langs: Sequence[str] = ()) -> str:
    """Compose one v2 stream rule: ``(btc OR eth) -is:retweet lang:en``.

    Multi-word terms are quoted so they match as phrases.
    """
    if not terms:
        raise ValueError("x: SS_TRACK_TERMS must be set for the X stream")
    rule = "(" + " OR ".join(_quote(t) for t in terms) + ") -is:retweet"
    langs = list(langs)
    if len(langs) == 1:
        rule += f" lang:{langs[0]}"
    return rule


def build_rules(
    terms: Sequence[str],
    langs: Sequence[str] = (),
    max_length: int = settings.X_RULE_MAX_LENGTH,
) -> list[str]:
    """Split ``terms`` into as many rules as needed to respect ``max_length``.

    The API rejects over-long rules inside a 2xx response, which would
    otherwise result in a silently empty stream.
    """
    if not terms:
        raise ValueError("x: SS_TRACK_TERMS must be set for the X stream")
    rules: list[str] = []
    chunk: list[str] = []
    for term in terms:
        candidate = build_rule([*chunk, term], langs)
        if chunk and len(candidate) > max_length:
            rules.append(build_rule(chunk, langs))
            chunk = [term]
        else:
            chunk.append(term)
    rules.append(build_rule(chunk, langs))
    for rule in rules:
        if len(rule) > max_length:
            raise ValueError(
                f"x: a single term makes a rule longer than {max_length} "
                f"characters: {rule!r}"
            )
    return rules


def check_rules_response(response: Any) -> None:
    """Raise if the rules endpoint reported errors inside a 2xx body."""
    errors = getattr(response, "errors", None) or []
    meta = getattr(response, "meta", None) or {}
    created = (meta.get("summary") or {}).get("created")
    if errors:
        raise RuntimeError(f"x: stream rules rejected: {errors}")
    if created == 0:
        raise RuntimeError(f"x: no stream rule was created: {meta}")


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
        max_retries: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(sink, **kwargs)
        if not bearer_token:
            raise ValueError("x: SS_X_BEARER_TOKEN must be set")
        self.bearer_token = bearer_token
        self.max_retries = max_retries
        self.rules = build_rules(self.terms, sorted(self.langs))

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

        # daemon=True: interpreter exit never waits on tweepy's thread while
        # it sleeps through an HTTP-error back-off.  wait_on_rate_limit is
        # off so a 429 raises and goes through our own stop-aware back-off.
        # Finite max_retries lets a rejected token surface instead of
        # looping forever inside tweepy.
        client = _Client(
            self.bearer_token,
            wait_on_rate_limit=False,
            daemon=True,
            max_retries=self.max_retries,
        )
        existing = client.get_rules().data or []
        if existing:
            client.delete_rules([rule.id for rule in existing])
        response = client.add_rules(
            [tweepy.StreamRule(rule) for rule in self.rules]
        )
        check_rules_response(response)
        log.info("x: streaming with %d rule(s): %s", len(self.rules), self.rules)
        thread = client.filter(tweet_fields=TWEET_FIELDS, threaded=True)
        while not stop_event.is_set() and thread.is_alive():
            stop_event.wait(1.0)
        client.disconnect()
        thread.join(timeout=10.0)
        if not stop_event.is_set():
            raise RuntimeError("x: stream ended; reconnecting")
