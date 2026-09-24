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
