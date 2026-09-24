import signal
import threading

import pytest

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


def test_run_raises_when_writer_cannot_open(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(Exception):
        run(["synthetic"], db_path=blocker / "x.db", stop_event=threading.Event(),
            status_interval=0.5)


def test_run_restores_signal_handlers(db_path):
    before = signal.getsignal(signal.SIGINT)
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    run(["synthetic"], db_path=db_path, stop_event=stop, status_interval=0.2,
        collector_options={"synthetic": {"rate_per_second": 50}})
    assert signal.getsignal(signal.SIGINT) is before
