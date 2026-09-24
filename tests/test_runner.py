import threading

from socialsentiment import storage
from socialsentiment.runner import purge_expired, refresh_trending, run


def test_run_collects_synthetic_posts(db_path):
    stop = threading.Event()
    timer = threading.Timer(1.5, stop.set)
    timer.start()
    run(["synthetic"], db_path=db_path, terms=(), langs=("en",),
        collector_options={"synthetic": {"rate_per_second": 100}},
        stop_event=stop, status_interval=0.5)
    conn = storage.connect(db_path)
    assert storage.count_posts(conn) > 20
    assert storage.source_counts(conn) == {"synthetic": storage.count_posts(conn)}


def test_refresh_trending_and_purge(seeded):
    assert refresh_trending(seeded, sample_size=600, top_n=5) > 0
    trending, _ = storage.get_meta(seeded, "trending")
    assert len(trending) <= 5
    assert purge_expired(seeded, retention_days=0) == 600
