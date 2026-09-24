import json
from types import SimpleNamespace

import pytest

from socialsentiment.cli import main
from socialsentiment.collectors.rss import RssCollector
from socialsentiment.doctor import (
    CheckResult,
    check_bluesky,
    check_reddit,
    check_rss,
    check_x,
    format_report,
    run_checks,
)

EVENT = json.dumps({
    "did": "did:plc:abc", "time_us": 1725911162329308, "kind": "commit",
    "commit": {"operation": "create", "collection": "app.bsky.feed.post",
               "rkey": "k", "record": {"text": "bitcoin to 100k",
                                       "createdAt": "2024-09-09T19:46:02Z",
                                       "langs": ["en"]}},
})


class _FakeSocket:
    def __init__(self, messages):
        self._messages = list(messages)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def recv(self, timeout=None):
        if not self._messages:
            raise TimeoutError
        return self._messages.pop(0)


def test_check_bluesky_counts_posts(monkeypatch):
    import websockets.sync.client as client

    monkeypatch.setattr(client, "connect",
                        lambda *a, **k: _FakeSocket([EVENT, "{}", EVENT]))
    result = check_bluesky(seconds=0.2)
    assert result.ok and "posts/s" in result.detail and "bitcoin" in result.detail


def test_check_bluesky_reports_connection_failure(monkeypatch):
    import websockets.sync.client as client

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(client, "connect", boom)
    result = check_bluesky(seconds=0.1)
    assert not result.ok and "OSError" in result.detail and result.hint


def test_check_bluesky_no_posts(monkeypatch):
    import websockets.sync.client as client

    monkeypatch.setattr(client, "connect", lambda *a, **k: _FakeSocket([]))
    assert not check_bluesky(seconds=0.1).ok


def test_check_rss_per_feed(monkeypatch):
    good = SimpleNamespace(entries=[{"title": "a"}, {"title": "b"}],
                           feed={"title": "Good"},
                           get=lambda k, d=None: False)
    empty = SimpleNamespace(entries=[], feed={},
                            get=lambda k, d=None: True if k == "bozo" else "x")

    def fetch(self, url):
        if "bad" in url:
            raise TimeoutError("timed out")
        return empty if "empty" in url else good

    monkeypatch.setattr(RssCollector, "_fetch", fetch)
    results = check_rss(["https://good.example/rss", "https://bad.example/rss",
                         "https://empty.example/rss"])
    assert [r.ok for r in results] == [True, False, False]
    assert results[0].detail.startswith("2 entries")
    assert "TimeoutError" in results[1].detail


def test_check_reddit_and_x_without_credentials():
    assert not check_reddit(client_id="", client_secret="").ok
    assert not check_x(bearer_token="").ok


def test_check_reddit_with_fake_client(monkeypatch):
    import praw

    class _Reddit:
        def __init__(self, **kwargs):
            self.read_only = False

        def subreddit(self, name):
            return SimpleNamespace(
                new=lambda limit: iter([SimpleNamespace(title="Fresh post")])
            )

    monkeypatch.setattr(praw, "Reddit", _Reddit)
    result = check_reddit(subreddits=["stocks"], client_id="i",
                          client_secret="s")
    assert result.ok and "Fresh post" in result.detail


def test_check_x_with_fake_client(monkeypatch):
    import tweepy

    class _Client:
        def __init__(self, token, **kwargs):
            pass

        def get_rules(self):
            return SimpleNamespace(data=[1, 2])

    monkeypatch.setattr(tweepy, "StreamingClient", _Client)
    assert check_x(bearer_token="t").ok


def test_run_checks_and_report(monkeypatch):
    import socialsentiment.doctor as doctor

    monkeypatch.setattr(doctor, "check_bluesky",
                        lambda seconds: CheckResult("bluesky", True, "ok"))
    monkeypatch.setattr(doctor, "check_rss",
                        lambda terms: [CheckResult("rss a", False, "down",
                                                   "fix it")])
    results = run_checks(["bluesky", "rss", "synthetic", "nope"])
    assert [r.ok for r in results] == [True, False, True, False]
    report = format_report(results)
    assert "2/4 checks passed" in report and "hint: fix it" in report


def test_check_command_exit_code(monkeypatch, capsys):
    import socialsentiment.doctor as doctor

    monkeypatch.setattr(doctor, "check_x",
                        lambda: CheckResult("x", False, "no token", "set it"))
    assert main(["--no-log-file", "check", "--source", "x"]) == 1
    assert "FAIL  x" in capsys.readouterr().out
    monkeypatch.setattr(doctor, "check_x",
                        lambda: CheckResult("x", True, "fine"))
    assert main(["--no-log-file", "check", "--source", "x"]) == 0


@pytest.mark.parametrize("source", ["bluesky", "rss", "reddit", "x"])
def test_run_checks_dispatches_every_source(monkeypatch, source):
    import socialsentiment.doctor as doctor

    calls = []
    monkeypatch.setattr(doctor, "check_bluesky",
                        lambda seconds: calls.append("bluesky") or
                        CheckResult("bluesky", True, ""))
    monkeypatch.setattr(doctor, "check_rss",
                        lambda terms: calls.append("rss") or [])
    monkeypatch.setattr(doctor, "check_reddit",
                        lambda: calls.append("reddit") or
                        CheckResult("reddit", True, ""))
    monkeypatch.setattr(doctor, "check_x",
                        lambda: calls.append("x") or CheckResult("x", True, ""))
    run_checks([source])
    assert calls == [source]
