import random
import sqlite3
import threading
import time

from socialsentiment import storage
from socialsentiment.collectors.synthetic import generate_posts
from socialsentiment.models import Post


def _post(i, text="hello bitcoin", ts=None, source="t"):
    return Post(source=source, source_id=str(i), ts_ms=ts or 1_000 + i,
                text=text)


def test_insert_scores_and_dedupes(conn):
    assert storage.insert_posts(conn, [_post(1), _post(2)]) == 2
    assert storage.insert_posts(conn, [_post(1)]) == 0
    assert storage.count_posts(conn) == 2
    row = conn.execute("SELECT sentiment FROM posts WHERE source_id='1'")
    assert isinstance(row.fetchone()[0], float)


def test_precomputed_sentiment_is_kept(conn):
    post = Post(source="t", source_id="x", ts_ms=1, text="bad", sentiment=0.9)
    storage.insert_posts(conn, [post])
    assert conn.execute("SELECT sentiment FROM posts").fetchone()[0] == 0.9


def test_fts_prefix_search_and_source_filter(conn):
    storage.insert_posts(conn, [
        _post(1, "Bitcoin ETF approved", source="a"),
        _post(2, "gold rallies", source="b"),
        _post(3, "bitcoiners rejoice", source="b"),
    ])
    hits = storage.fetch_posts(conn, "bitcoin")
    assert sorted(hits["source_id"]) == ["1", "3"]
    only_b = storage.fetch_posts(conn, "bitcoin", sources=["b"])
    assert list(only_b["source_id"]) == ["3"]
    assert len(storage.fetch_posts(conn, "")) == 3
    assert storage.fetch_posts(conn, 'x" OR "gold').empty


def test_fetch_is_newest_first_and_limited(conn):
    storage.insert_posts(conn, [_post(i) for i in range(10)])
    frame = storage.fetch_posts(conn, "", limit=3)
    assert list(frame["source_id"]) == ["9", "8", "7"]


def test_counts_and_latest(conn):
    storage.insert_posts(conn, [_post(1, source="a", ts=10),
                                _post(2, source="b", ts=20)])
    assert storage.source_counts(conn) == {"a": 1, "b": 1}
    assert storage.source_counts(conn, since_ms=15) == {"b": 1}
    assert storage.list_sources(conn) == ["a", "b"]
    assert storage.latest_ts_ms(conn) == 20


def test_purge_removes_rows_and_fts_entries(conn):
    storage.insert_posts(conn, [_post(1, "old bitcoin", ts=10),
                                _post(2, "new bitcoin", ts=100)])
    assert storage.purge_older_than(conn, 50) == 1
    assert list(storage.fetch_posts(conn, "bitcoin")["source_id"]) == ["2"]


def test_meta_roundtrip(conn):
    assert storage.get_meta(conn, "missing", {}) == ({}, None)
    storage.set_meta(conn, "k", {"a": [0.5, 3]})
    value, updated = storage.get_meta(conn, "k")
    assert value == {"a": [0.5, 3]} and updated is not None


def test_batch_writer_flushes(db_path):
    writer = storage.BatchWriter(db_path, flush_seconds=0.05)
    writer.start()
    for i in range(50):
        writer.submit(_post(i))
    writer.stop()
    assert writer.inserted == 50
    other = sqlite3.connect(db_path)
    assert other.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 50


def test_bulk_insert_is_fast(conn):
    now = storage.now_ms()
    posts = list(generate_posts(3000, start_ms=now - 1000, end_ms=now,
                                rng=random.Random(1)))
    started = time.perf_counter()
    assert storage.insert_posts(conn, posts) == 3000
    assert time.perf_counter() - started < 5.0


def test_fetch_orders_by_timestamp_not_insertion(conn):
    storage.insert_posts(conn, [_post(1, "bitcoin now", ts=1_000_000),
                                _post(2, "bitcoin later", ts=2_000_000)])
    # a stale feed item inserted last must not become the "newest" post
    storage.insert_posts(conn, [_post(3, "bitcoin stale", ts=500)])
    assert list(storage.fetch_posts(conn, "bitcoin")["source_id"]) == ["2", "1", "3"]
    assert list(storage.fetch_posts(conn, "")["source_id"]) == ["2", "1", "3"]


def test_concurrent_connect_on_fresh_database(tmp_path):
    errors = []

    def open_db(path):
        try:
            c = storage.connect(path)
            storage.init_schema(c)
            c.close()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    for trial in range(40):
        path = tmp_path / f"fresh{trial}.db"
        threads = [threading.Thread(target=open_db, args=(path,)) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == []


def test_batch_writer_records_open_failure(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    writer = storage.BatchWriter(blocker / "x.db", flush_seconds=0.05)
    writer.start()
    writer.join(5)
    assert not writer.is_alive() and writer.failed is not None
    writer.submit(_post(1))
    assert writer.dropped == 1 and writer.received == 0


def test_batch_writer_drops_bad_batch_and_keeps_going(db_path):
    writer = storage.BatchWriter(db_path, flush_seconds=0.05)
    writer.start()
    writer.submit(Post(source="t", source_id="bad", ts_ms=None, text="x"))
    time.sleep(0.3)
    writer.submit(_post(2))
    writer.stop()
    assert writer.inserted == 1 and writer.dropped == 1
