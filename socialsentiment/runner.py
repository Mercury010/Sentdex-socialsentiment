"""Run collectors, the batch writer and periodic maintenance in one process."""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from socialsentiment import settings, storage
from socialsentiment.collectors import Collector, create_collector
from socialsentiment.trending import trending_terms

log = logging.getLogger(__name__)

TRENDING_KEY = "trending"


def refresh_trending(conn: Any, sample_size: int, top_n: int) -> int:
    """Recompute trending terms from the newest posts and cache them."""
    posts = storage.fetch_posts(conn, "", limit=sample_size)
    stats = trending_terms(posts, top_n=top_n)
    storage.set_meta(conn, TRENDING_KEY, stats)
    return len(stats)


def purge_expired(conn: Any, retention_days: int) -> int:
    cutoff_ms = storage.now_ms() - retention_days * 86_400_000
    return storage.purge_older_than(conn, cutoff_ms)


def _maintenance_loop(db_path: Path, stop_event: threading.Event) -> None:
    conn = storage.connect(db_path)
    storage.init_schema(conn)
    next_trending = 0.0
    next_purge = time.monotonic() + 60.0
    try:
        while not stop_event.wait(1.0):
            now = time.monotonic()
            if now >= next_trending:
                try:
                    found = refresh_trending(
                        conn,
                        settings.TRENDING_SAMPLE_SIZE,
                        settings.TRENDING_TOP_N,
                    )
                    log.debug("trending refreshed (%d terms)", found)
                except Exception:
                    log.exception("trending refresh failed")
                next_trending = now + settings.TRENDING_INTERVAL_SECONDS
            if now >= next_purge:
                try:
                    deleted = purge_expired(conn, settings.RETENTION_DAYS)
                    if deleted:
                        log.info("purged %d expired posts", deleted)
                except Exception:
                    log.exception("purge failed")
                next_purge = now + settings.PURGE_INTERVAL_SECONDS
    finally:
        conn.close()


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handler(signum: int, _frame: Any) -> None:
        log.info("signal %s received, shutting down", signum)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except ValueError:
            # Not in the main thread (e.g. embedded in a notebook).
            return


def run(
    sources: Sequence[str],
    *,
    db_path: Path | str = settings.DB_PATH,
    terms: Sequence[str] = tuple(settings.TRACK_TERMS),
    langs: Sequence[str] = tuple(settings.LANGS),
    collector_options: dict[str, dict[str, Any]] | None = None,
    stop_event: threading.Event | None = None,
    status_interval: float = 30.0,
) -> None:
    """Block until interrupted, feeding posts from ``sources`` into the DB."""
    if not sources:
        raise ValueError("at least one source is required")
    db_path = Path(db_path)
    stop_event = stop_event or threading.Event()
    options = collector_options or {}

    writer = storage.BatchWriter(db_path, settings.WRITE_FLUSH_SECONDS)
    writer.start()

    collectors: list[Collector] = [
        create_collector(
            name, writer.submit, terms=terms, langs=langs, **options.get(name, {})
        )
        for name in sources
    ]
    threads = [
        threading.Thread(
            target=collector.run,
            args=(stop_event,),
            name=f"collector-{collector.name}",
            daemon=True,
        )
        for collector in collectors
    ]
    maintenance = threading.Thread(
        target=_maintenance_loop,
        args=(db_path, stop_event),
        name="maintenance",
        daemon=True,
    )

    _install_signal_handlers(stop_event)
    log.info(
        "collecting %s into %s (terms=%s, langs=%s)",
        ", ".join(sources),
        db_path,
        list(terms) or "all",
        list(langs) or "all",
    )
    for thread in [*threads, maintenance]:
        thread.start()
    try:
        while not stop_event.wait(status_interval):
            log.info(
                "status: received=%d inserted=%d pending=%d | %s",
                writer.received,
                writer.inserted,
                writer.pending,
                " ".join(
                    f"{c.name}={c.emitted}/{c.dropped}" for c in collectors
                ),
            )
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=10.0)
        maintenance.join(timeout=5.0)
        writer.stop()
        log.info(
            "stopped: received=%d inserted=%d", writer.received, writer.inserted
        )
