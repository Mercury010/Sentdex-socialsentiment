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


def _iso_to_ms(value: str) -> int | None:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return int(stamp.timestamp() * 1000)


def parse_event(raw: str | bytes | dict[str, Any]) -> Post | None:
    """Turn one Jetstream message into a :class:`Post`, or ``None``.

    Only ``commit`` events that create a post are of interest; account and
    identity events, deletes and likes are skipped.
    """
    event = raw if isinstance(raw, dict) else json.loads(raw)
    if event.get("kind") != "commit":
        return None
    commit = event.get("commit") or {}
    if commit.get("operation") != "create":
        return None
    if commit.get("collection") != POST_COLLECTION:
        return None
    record = commit.get("record") or {}
    text = str(record.get("text") or "").strip()
    if not text:
        return None

    did = str(event.get("did") or "")
    rkey = str(commit.get("rkey") or "")
    ts_ms = _iso_to_ms(str(record.get("createdAt") or ""))
    if ts_ms is None:
        ts_ms = int(event.get("time_us", 0)) // 1000
    langs = record.get("langs") or []
    lang = str(langs[0]) if langs else ""
    return Post(
        source="bluesky",
        source_id=f"{did}/{rkey}",
        ts_ms=ts_ms,
        text=text,
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
                except (ValueError, TypeError):
                    log.debug("bluesky: unparseable message skipped")
                    continue
                if post is not None:
                    self.emit(post)
