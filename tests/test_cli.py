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
