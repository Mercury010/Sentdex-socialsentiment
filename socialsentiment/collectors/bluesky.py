"""Bluesky collector using the public Jetstream firehose.

Jetstream is a JSON websocket that relays every public Bluesky post without
authentication, which makes it the closest free replacement for the old
Twitter v1.1 sample/filter stream.  Text filtering happens client-side.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from socialsentiment import settings
from socialsentiment.collectors.base import Collector, Sink
from socialsentiment.models import Post

log = logging.getLogger(__name__)

POST_COLLECTION = "app.bsky.feed.post"
# ``createdAt`` is written by the client and can be wrong by years.  Trust
# it only when it is close to the server-side arrival time (``time_us``).
MAX_CREATED_PAST_MS = 7 * 86_400_000
MAX_CREATED_FUTURE_MS = 5 * 60_000


def _iso_to_ms(value: str) -> int | None:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(stamp.timestamp() * 1000)
    except (ValueError, OverflowError, OSError, AttributeError, TypeError):
        return None


def choose_timestamp(created_ms: int | None, arrival_ms: int) -> int:
    """Prefer the client's ``createdAt`` only when it is plausible."""
    if created_ms is None:
        return arrival_ms
    if not arrival_ms:
        return created_ms
    if created_ms > arrival_ms + MAX_CREATED_FUTURE_MS:
        return arrival_ms
    if created_ms < arrival_ms - MAX_CREATED_PAST_MS:
        return arrival_ms
    return created_ms


def parse_event(raw: str | bytes | dict[str, Any]) -> Post | None:
    """Turn one Jetstream message into a :class:`Post`, or ``None``.

    Only ``commit`` events that create a post are of interest; account and
    identity events, deletes and likes are skipped.  Malformed records
    (Jetstream relays them as written) yield ``None`` rather than raising.
    """
    event = raw if isinstance(raw, dict) else json.loads(raw)
    if not isinstance(event, dict) or event.get("kind") != "commit":
        return None
    commit = event.get("commit")
    if not isinstance(commit, dict):
        return None
    if commit.get("operation") != "create":
        return None
    if commit.get("collection") != POST_COLLECTION:
        return None
    record = commit.get("record")
    if not isinstance(record, dict):
        return None
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    did = str(event.get("did") or "")
    rkey = str(commit.get("rkey") or "")
    try:
        arrival_ms = int(event.get("time_us") or 0) // 1000
    except (TypeError, ValueError):
        arrival_ms = 0
    created_ms = _iso_to_ms(str(record.get("createdAt") or ""))
    langs = record.get("langs")
    lang = ""
    if isinstance(langs, list) and langs and isinstance(langs[0], str):
        lang = langs[0]
    return Post(
        source="bluesky",
        source_id=f"{did}/{rkey}",
        ts_ms=choose_timestamp(created_ms, arrival_ms),
        text=text.strip(),
        author=did,
        lang=lang,
        url=f"https://bsky.app/profile/{did}/post/{rkey}",
    )


class BlueskyCollector(Collector):
    name = "bluesky"

    def __init__(
        self,
        sink: Sink,
        *,
        url: str = settings.BLUESKY_JETSTREAM_URL,
        recv_timeout: float = 5.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(sink, **kwargs)
        self.url = url
        self.recv_timeout = recv_timeout

    def run_once(self, stop_event: threading.Event) -> None:
        from websockets.sync.client import connect

        query = urlencode({"wantedCollections": POST_COLLECTION})
        endpoint = f"{self.url}?{query}"
        log.info("bluesky: connecting to %s", endpoint)
        with connect(endpoint, max_size=2**20) as socket:
            while not stop_event.is_set():
                try:
                    raw = socket.recv(timeout=self.recv_timeout)
                except TimeoutError:
                    continue
                try:
                    post = parse_event(raw)
                except Exception:
                    # One malformed message must not drop the firehose.
                    log.debug("bluesky: unparseable message skipped")
                    continue
                if post is not None:
                    self.emit(post)
