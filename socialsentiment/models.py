"""Data model shared by collectors, storage and the dashboard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Post:
    """One item of social or news text, normalised across sources.

    Attributes:
        source: Short source name (``bluesky``, ``reddit``, ``rss``, ``x``,
            ``synthetic``).
        source_id: Identifier unique within the source; used to
            de-duplicate on insert.
        ts_ms: Creation time as Unix epoch milliseconds (UTC).
        text: The body text.
        author: Author handle, DID or feed name; may be empty.
        lang: Language tag if the source provides one, else empty.
        url: Permalink if available.
        sentiment: VADER compound score in [-1, 1]; ``None`` until scored.
    """

    source: str
    source_id: str
    ts_ms: int
    text: str
    author: str = ""
    lang: str = ""
    url: str = ""
    sentiment: float | None = None
