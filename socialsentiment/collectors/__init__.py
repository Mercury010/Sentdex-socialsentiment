"""Source collectors: each turns a live source into :class:`Post` objects.

Collector classes are imported lazily so that optional dependencies (``praw``
for Reddit, ``tweepy`` for X) are only required when that source is used.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from socialsentiment.collectors.base import Collector

REGISTRY: dict[str, tuple[str, str]] = {
    "bluesky": ("socialsentiment.collectors.bluesky", "BlueskyCollector"),
    "reddit": ("socialsentiment.collectors.reddit", "RedditCollector"),
    "rss": ("socialsentiment.collectors.rss", "RssCollector"),
    "x": ("socialsentiment.collectors.x_stream", "XStreamCollector"),
    "synthetic": (
        "socialsentiment.collectors.synthetic",
        "SyntheticCollector",
    ),
}


def available_sources() -> list[str]:
    return sorted(REGISTRY)


def create_collector(name: str, sink: Any, **kwargs: Any) -> Collector:
    """Instantiate the collector registered under ``name``."""
    try:
        module_name, class_name = REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown source {name!r}; choose from {available_sources()}"
        ) from exc
    module = import_module(module_name)
    collector_class = getattr(module, class_name)
    return collector_class(sink, **kwargs)


__all__ = ["Collector", "REGISTRY", "available_sources", "create_collector"]
