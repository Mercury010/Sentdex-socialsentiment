"""Base class shared by all collectors."""

from __future__ import annotations

import abc
import logging
import threading
import time
from collections.abc import Callable, Sequence

from socialsentiment.models import Post
from socialsentiment.text import compile_terms

log = logging.getLogger(__name__)

Sink = Callable[[Post], None]


class Collector(abc.ABC):
    """Consume a source and hand accepted posts to ``sink``.

    Subclasses implement :meth:`run_once`, which should block until the
    connection drops or ``stop_event`` is set.  :meth:`run` wraps it in a
    reconnect loop with exponential back-off.

    ``max_age_ms`` / ``max_future_ms`` (both optional) drop posts whose
    timestamp is implausibly old or in the future, so a stale feed item or
    a client with a broken clock cannot distort the live window.
    """

    name: str = "base"

    def __init__(
        self,
        sink: Sink,
        *,
        terms: Sequence[str] = (),
        langs: Sequence[str] = (),
        max_age_ms: int | None = None,
        max_future_ms: int | None = None,
        max_backoff: float = 60.0,
    ) -> None:
        self._sink = sink
        self.terms = [term.lower() for term in terms if term]
        self._term_pattern = compile_terms(self.terms)
        self.langs = {lang.lower() for lang in langs if lang}
        self.max_age_ms = max_age_ms
        self.max_future_ms = max_future_ms
        self.max_backoff = max_backoff
        self.emitted = 0
        self.dropped = 0

    def accept(self, post: Post) -> bool:
        """Apply the language, term and timestamp filters."""
        if self.langs and post.lang:
            primary = post.lang.split("-")[0].lower()
            if primary not in self.langs:
                return False
        if self._term_pattern and not self._term_pattern.search(post.text):
            return False
        if self.max_age_ms is not None or self.max_future_ms is not None:
            now_ms = int(time.time() * 1000)
            if self.max_age_ms is not None and (
                post.ts_ms < now_ms - self.max_age_ms
            ):
                return False
            if self.max_future_ms is not None and (
                post.ts_ms > now_ms + self.max_future_ms
            ):
                return False
        return True

    def emit(self, post: Post) -> bool:
        if self.accept(post):
            self._sink(post)
            self.emitted += 1
            return True
        self.dropped += 1
        return False

    @abc.abstractmethod
    def run_once(self, stop_event: threading.Event) -> None:
        """Connect and consume until ``stop_event`` is set or a failure."""

    def run(self, stop_event: threading.Event) -> None:
        """Reconnect loop; returns when ``stop_event`` is set."""
        backoff = 1.0
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                self.run_once(stop_event)
            except Exception:
                log.exception("%s: collector error", self.name)
            if stop_event.is_set():
                break
            if time.monotonic() - started > 60:
                backoff = 1.0
            log.info("%s: reconnecting in %.0f s", self.name, backoff)
            if stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, self.max_backoff)
        log.info(
            "%s: stopped (emitted=%d, dropped=%d)",
            self.name,
            self.emitted,
            self.dropped,
        )
