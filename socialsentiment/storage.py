"""SQLite persistence with FTS5 full-text search.

One writer thread (:class:`BatchWriter`) owns inserts; any number of readers
may open their own connection.  WAL journalling lets the dashboard read while
the collector process writes.
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from socialsentiment.models import Post
from socialsentiment.sentiment import get_scorer
from socialsentiment.text import fts_query

log = logging.getLogger(__name__)

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        ts_ms INTEGER NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        lang TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL,
        sentiment REAL NOT NULL,
        url TEXT NOT NULL DEFAULT '',
        UNIQUE (source, source_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_posts_ts ON posts (ts_ms DESC)",
    """
    CREATE INDEX IF NOT EXISTS ix_posts_source_ts
    ON posts (source, ts_ms DESC)
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
        text,
        content='posts',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 2',
        prefix='2 3'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
        INSERT INTO posts_fts (rowid, text) VALUES (new.id, new.text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
        INSERT INTO posts_fts (posts_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
        INSERT INTO posts_fts (posts_fts, rowid, text)
        VALUES ('delete', old.id, old.text);
        INSERT INTO posts_fts (rowid, text) VALUES (new.id, new.text);
    END
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_ms INTEGER NOT NULL
    )
    """,
)

_POST_SELECT = (
    "SELECT p.id, p.source, p.source_id, p.ts_ms, p.author, p.lang, "
    "p.text, p.sentiment, p.url"
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _enable_wal(conn: sqlite3.Connection, retry_seconds: float) -> None:
    """Switch the connection to WAL, retrying on SQLITE_BUSY.

    The busy timeout does not cover the journal-mode switch on a brand-new
    database file, so two connections opening the same fresh file at the
    same moment can see "database is locked" here.  Retry briefly instead
    of failing the caller.
    """
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0])
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)
            continue
        if mode.lower() in {"wal", "memory"}:
            return
        if time.monotonic() > deadline:
            raise sqlite3.OperationalError(
                f"could not enable WAL (journal_mode={mode})"
            )
        time.sleep(0.01)


def connect(
    db_path: Path | str, *, wal_retry_seconds: float = 10.0
) -> sqlite3.Connection:
    """Open (and create if needed) the database in WAL mode.

    ``isolation_level=None`` puts the connection in autocommit mode so that
    explicit ``BEGIN``/``COMMIT`` control every transaction.
    """
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), isolation_level=None, check_same_thread=False, timeout=30
    )
    try:
        _enable_wal(conn, wal_retry_seconds)
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        conn.close()
        raise
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)


def insert_posts(conn: sqlite3.Connection, posts: Iterable[Post]) -> int:
    """Score (if needed) and insert posts; return how many were new."""
    scorer = get_scorer()
    rows = []
    for post in posts:
        sentiment = post.sentiment
        if sentiment is None:
            sentiment = scorer.score(post.text)
        rows.append(
            (
                post.source,
                post.source_id,
                int(post.ts_ms),
                post.author or "",
                post.lang or "",
                post.text,
                float(sentiment),
                post.url or "",
            )
        )
    if not rows:
        return 0
    conn.execute("BEGIN")
    try:
        cursor = conn.executemany(
            "INSERT OR IGNORE INTO posts "
            "(source, source_id, ts_ms, author, lang, text, sentiment, url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return max(cursor.rowcount, 0)


def _source_filter(sources: Sequence[str] | None) -> tuple[str, list[str]]:
    if not sources:
        return "", []
    placeholders = ", ".join("?" for _ in sources)
    return f" AND p.source IN ({placeholders})", list(sources)


def fetch_posts(
    conn: sqlite3.Connection,
    term: str = "",
    sources: Sequence[str] | None = None,
    limit: int = 1000,
    since_ms: int | None = None,
) -> pd.DataFrame:
    """Return the newest posts matching ``term`` (FTS5 prefix search).

    "Newest" means by post timestamp (``ts_ms``), not by insertion order,
    so a feed that delivers day-old items cannot hijack the live window.
    Columns: ``id, source, source_id, ts_ms, author, lang, text, sentiment,
    url``.  An empty ``term`` returns the newest posts regardless of
    content.  ``since_ms`` keeps only posts stamped at or after that time.
    """
    query = fts_query(term)
    clause, params = _source_filter(sources)
    if since_ms is not None:
        clause += " AND p.ts_ms >= ?"
        params.append(int(since_ms))
    if query:
        sql = (
            f"{_POST_SELECT} FROM posts_fts "
            "JOIN posts p ON p.id = posts_fts.rowid "
            f"WHERE posts_fts MATCH ?{clause} "
            "ORDER BY p.ts_ms DESC, p.id DESC LIMIT ?"
        )
        params = [query, *params, int(limit)]
    else:
        sql = (
            f"{_POST_SELECT} FROM posts p WHERE 1 = 1{clause} "
            "ORDER BY p.ts_ms DESC, p.id DESC LIMIT ?"
        )
        params = [*params, int(limit)]
    return pd.read_sql_query(sql, conn, params=params)


def count_posts(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0])


def latest_ts_ms(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(ts_ms) FROM posts").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def source_counts(
    conn: sqlite3.Connection, since_ms: int | None = None
) -> dict[str, int]:
    """Posts per source, optionally only those newer than ``since_ms``."""
    if since_ms is None:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM posts GROUP BY source"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM posts WHERE ts_ms >= ? "
            "GROUP BY source",
            (int(since_ms),),
        ).fetchall()
    return {str(source): int(count) for source, count in rows}


def list_sources(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT source FROM posts ORDER BY source"
    ).fetchall()
    return [str(row[0]) for row in rows]


def purge_older_than(conn: sqlite3.Connection, cutoff_ms: int) -> int:
    """Delete posts older than ``cutoff_ms``; the FTS index follows."""
    conn.execute("BEGIN")
    try:
        cursor = conn.execute(
            "DELETE FROM posts WHERE ts_ms < ?", (int(cutoff_ms),)
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    deleted = max(cursor.rowcount, 0)
    if deleted:
        conn.execute("INSERT INTO posts_fts (posts_fts) VALUES ('optimize')")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return deleted


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Store a JSON-serialisable value under ``key``."""
    conn.execute(
        "INSERT INTO meta (key, value, updated_ms) VALUES (?, ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
        "updated_ms = excluded.updated_ms",
        (key, json.dumps(value), now_ms()),
    )


def get_meta(
    conn: sqlite3.Connection, key: str, default: Any = None
) -> tuple[Any, int | None]:
    """Return ``(value, updated_ms)`` for ``key`` or ``(default, None)``."""
    row = conn.execute(
        "SELECT value, updated_ms FROM meta WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return default, None
    return json.loads(row[0]), int(row[1])


class BatchWriter(threading.Thread):
    """Background thread that scores and inserts posts in batches.

    Collectors call :meth:`submit` from any thread; rows are flushed every
    ``flush_seconds`` (or when ``max_batch`` items are waiting) in a single
    transaction, which keeps SQLite fast even at firehose rates.

    If the database cannot be opened the thread records the exception in
    :attr:`failed` and exits; :meth:`submit` then drops posts instead of
    queueing them forever, and callers should check :meth:`is_alive`.
    """

    def __init__(
        self,
        db_path: Path | str,
        flush_seconds: float = 1.0,
        max_batch: int = 2000,
    ) -> None:
        super().__init__(name="batch-writer", daemon=True)
        self.db_path = Path(db_path)
        self.flush_seconds = flush_seconds
        self.max_batch = max_batch
        self._queue: queue.Queue[Post] = queue.Queue()
        self._stop_event = threading.Event()
        self.received = 0
        self.inserted = 0
        self.dropped = 0
        self.failed: BaseException | None = None

    def submit(self, post: Post) -> None:
        if self.failed is not None:
            self.dropped += 1
            return
        self._queue.put(post)
        self.received += 1

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def run(self) -> None:
        try:
            conn = connect(self.db_path)
            init_schema(conn)
        except Exception as exc:
            self.failed = exc
            log.exception("batch writer could not open %s", self.db_path)
            return
        try:
            while not (self._stop_event.is_set() and self._queue.empty()):
                batch = self._drain()
                if not batch:
                    continue
                try:
                    self.inserted += insert_posts(conn, batch)
                except Exception:
                    self.dropped += len(batch)
                    log.exception(
                        "insert failed; dropping %d posts", len(batch)
                    )
        finally:
            conn.close()

    def _drain(self) -> list[Post]:
        batch: list[Post] = []
        deadline = time.monotonic() + self.flush_seconds
        while len(batch) < self.max_batch:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                batch.append(self._queue.get(timeout=remaining))
            except queue.Empty:
                break
        return batch

    def stop(self, timeout: float = 10.0) -> None:
        """Flush what is queued, then stop the thread."""
        self._stop_event.set()
        self.join(timeout)
