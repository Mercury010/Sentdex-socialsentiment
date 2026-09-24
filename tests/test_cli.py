from socialsentiment import storage
from socialsentiment.cli import main


def test_seed_stats_truncate(tmp_path, capsys):
    db = tmp_path / "cli.db"
    assert main(["--db", str(db), "--no-log-file", "seed", "--posts", "300",
                 "--hours", "1", "--seed", "1"]) == 0
    assert main(["--db", str(db), "--no-log-file", "stats"]) == 0
    out = capsys.readouterr().out
    assert "seeded 300" in out and "synthetic" in out and "trending:" in out
    assert main(["--db", str(db), "--no-log-file", "truncate", "--days", "0"]) == 0
    assert storage.count_posts(storage.connect(db)) == 0


def test_db_option_accepted_after_subcommand(tmp_path, capsys):
    db = tmp_path / "after.db"
    assert main(["seed", "--db", str(db), "--no-log-file", "--posts", "10"]) == 0
    assert main(["stats", "--db", str(db), "--no-log-file"]) == 0
    assert "posts:    10" in capsys.readouterr().out


def test_stats_and_truncate_refuse_missing_db(tmp_path, capsys):
    missing = tmp_path / "nope" / "missing.db"
    assert main(["--db", str(missing), "--no-log-file", "stats"]) == 1
    assert main(["--db", str(missing), "--no-log-file", "truncate"]) == 1
    assert "database not found" in capsys.readouterr().err
    assert not missing.parent.exists()


def test_empty_numeric_env_falls_back_to_default(monkeypatch):
    from socialsentiment.settings import _env_float, _env_int

    monkeypatch.setenv("SS_TEST_INT", "")
    monkeypatch.setenv("SS_TEST_FLOAT", "  ")
    assert _env_int("SS_TEST_INT", 7) == 7
    assert _env_float("SS_TEST_FLOAT", 1.5) == 1.5
    monkeypatch.setenv("SS_TEST_INT", "9")
    assert _env_int("SS_TEST_INT", 7) == 9


def test_run_starts_collector_and_server(tmp_path, monkeypatch):
    import threading
    import webbrowser

    import socialsentiment.dashboard as dashboard
    import socialsentiment.runner as runner

    seen = {}

    def fake_run(sources, *, db_path, terms, langs, stop_event, **kwargs):
        seen["sources"] = list(sources)
        seen["terms"] = list(terms)
        stop_event.wait(5)
        seen["stopped"] = stop_event.is_set()

    class _App:
        def run(self, host, port, debug):
            seen["server"] = (host, port, debug)

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(dashboard, "create_app", lambda db_path: _App())
    monkeypatch.setattr(webbrowser, "open", lambda url: seen.setdefault("url", url))
    db = tmp_path / "run.db"
    code = main(["--db", str(db), "--no-log-file", "run", "--source", "synthetic",
                 "--term", "btc", "--port", "8123"])
    assert code == 0
    assert seen["sources"] == ["synthetic"] and seen["terms"] == ["btc"]
    assert seen["server"] == ("127.0.0.1", 8123, False)
    assert seen["stopped"] is True
    # the browser timer fires after 1.5 s; wait for it
    for _ in range(40):
        if "url" in seen:
            break
        threading.Event().wait(0.1)
    assert seen["url"] == "http://127.0.0.1:8123/"
