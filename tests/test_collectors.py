import threading
import time
from types import SimpleNamespace

import pytest

from socialsentiment.collectors import available_sources, create_collector
from socialsentiment.collectors.base import Collector
from socialsentiment.collectors.bluesky import parse_event
from socialsentiment.collectors.reddit import (
    RedditCollector,
    parse_comment,
    parse_submission,
)
from socialsentiment.collectors.rss import RssCollector, parse_entry
from socialsentiment.collectors.synthetic import SyntheticCollector
from socialsentiment.collectors.x_stream import (
    build_rule,
    build_rules,
    check_rules_response,
    parse_tweet,
)
from socialsentiment.models import Post

JETSTREAM_EVENT = {
    "did": "did:plc:abc",
    "time_us": 1725911162329308,
    "kind": "commit",
    "commit": {
        "rev": "r",
        "operation": "create",
        "collection": "app.bsky.feed.post",
        "rkey": "3l3q",
        "record": {
            "$type": "app.bsky.feed.post",
            "createdAt": "2024-09-09T19:46:02.102Z",
            "text": "bitcoin to 100k",
            "langs": ["en"],
        },
        "cid": "c",
    },
}


class _Sink:
    def __init__(self):
        self.posts = []

    def __call__(self, post):
        self.posts.append(post)


class _Dummy(Collector):
    name = "dummy"

    def run_once(self, stop_event):
        raise RuntimeError("boom")


def test_registry_and_unknown_source():
    assert "bluesky" in available_sources()
    with pytest.raises(ValueError):
        create_collector("nope", lambda p: None)


def test_language_and_term_filters():
    sink = _Sink()
    collector = _Dummy(sink, terms=["bitcoin"], langs=["en"])
    assert collector.emit(Post("t", "1", 1, "Bitcoin up", lang="en-US"))
    assert not collector.emit(Post("t", "2", 1, "Bitcoin up", lang="de"))
    assert not collector.emit(Post("t", "3", 1, "gold up", lang="en"))
    assert collector.emit(Post("t", "4", 1, "bitcoin", lang=""))
    assert len(sink.posts) == 2 and collector.dropped == 2


def test_run_loop_retries_then_stops():
    stop = threading.Event()
    collector = _Dummy(_Sink(), max_backoff=0.01)
    thread = threading.Thread(target=collector.run, args=(stop,))
    thread.start()
    time.sleep(0.2)
    stop.set()
    thread.join(2)
    assert not thread.is_alive()


def _with_created_at(value):
    event = dict(JETSTREAM_EVENT)
    event["commit"] = dict(JETSTREAM_EVENT["commit"])
    event["commit"]["record"] = dict(JETSTREAM_EVENT["commit"]["record"],
                                     createdAt=value)
    return event


def test_parse_jetstream_event():
    post = parse_event(JETSTREAM_EVENT)
    assert post.source == "bluesky" and post.lang == "en"
    assert post.ts_ms == 1725911162102
    assert post.url.endswith("/post/3l3q")
    assert parse_event({"kind": "identity"}) is None
    assert parse_event(_with_created_at("garbage")).ts_ms == 1725911162329


def test_parse_jetstream_distrusts_implausible_created_at():
    arrival = 1725911162329
    assert parse_event(_with_created_at("2100-01-01T00:00:00Z")).ts_ms == arrival
    ancient = parse_event(_with_created_at("0001-01-01T00:00:00+01:00"))
    assert ancient.ts_ms == arrival
    assert parse_event(_with_created_at("2020-01-01T00:00:00Z")).ts_ms == arrival
    recent = parse_event(_with_created_at("2024-09-09T19:40:00Z"))
    assert recent.ts_ms == 1725910800000  # six minutes before arrival


def test_parse_jetstream_tolerates_malformed_records():
    broken = dict(JETSTREAM_EVENT)
    broken["commit"] = dict(JETSTREAM_EVENT["commit"], record=["not", "a", "dict"])
    assert parse_event(broken) is None
    no_langs = _with_created_at("2024-09-09T19:46:02.102Z")
    no_langs["commit"]["record"]["langs"] = "en"
    assert parse_event(no_langs).lang == ""


def test_parse_reddit_objects():
    comment = SimpleNamespace(body="to the moon", fullname="t1_a",
                              created_utc=1.5, author="u", permalink="/r/x")
    post = parse_comment(comment)
    assert post.source_id == "t1_a" and post.ts_ms == 1500
    assert parse_comment(SimpleNamespace(body="[deleted]", fullname="t1_b",
                                         created_utc=1, author=None,
                                         permalink="")) is None
    submission = SimpleNamespace(title="Title", selftext="[removed]",
                                 fullname="t3_a", created_utc=2, author="u",
                                 permalink="/r/y")
    assert parse_submission(submission).text == "Title"


def test_parse_rss_entry_and_poll(monkeypatch):
    entry = {"link": "https://x/1", "id": "1", "title": "Bitcoin &amp; ETFs",
             "summary": "<p>Inflows <b>surge</b></p>",
             "published_parsed": time.gmtime(1_700_000_000)}
    post = parse_entry("CoinDesk", entry)
    assert post.text == "Bitcoin & ETFs. Inflows surge"
    assert post.ts_ms == 1_700_000_000_000 and post.author == "CoinDesk"
    assert parse_entry("f", {"title": "no id"}) is None

    fake = SimpleNamespace(
        entries=[entry, {"link": "https://x/2", "title": "Gold falls"}],
        feed={"title": "Feed"},
        get=lambda key, default=None: False,
    )
    monkeypatch.setattr(RssCollector, "_fetch", lambda self, url: fake)
    sink = _Sink()
    collector = RssCollector(sink, feeds=["https://feed"], terms=["bitcoin"],
                             add_google_news=False)
    assert collector.poll() == 1
    assert sink.posts[0].source_id == "Feed|1"


def test_rss_poll_survives_one_failing_feed(monkeypatch):
    good = SimpleNamespace(
        entries=[{"link": "https://x/9", "id": "9", "title": "Bitcoin news"}],
        feed={"title": "Good"},
        get=lambda key, default=None: False,
    )

    def fetch(self, url):
        if "bad" in url:
            raise ConnectionResetError("peer reset")
        return good

    monkeypatch.setattr(RssCollector, "_fetch", fetch)
    sink = _Sink()
    collector = RssCollector(sink, feeds=["https://bad", "https://good"],
                             add_google_news=False)
    assert collector.poll() == 1
    assert sink.posts[0].source_id == "Good|9"


def test_rss_fetch_uses_timeout(monkeypatch):
    import urllib.request

    seen = {}

    class _Resp:
        headers = {"content-type": "application/rss+xml"}

        def read(self):
            return b"<rss><channel><title>T</title></channel></rss>"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        seen["timeout"] = timeout
        seen["ua"] = request.get_header("User-agent")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    collector = RssCollector(lambda p: None, feeds=["https://feed"],
                             fetch_timeout=7.5, add_google_news=False)
    parsed = collector._fetch("https://feed")
    assert seen["timeout"] == 7.5 and "socialsentiment" in seen["ua"]
    assert parsed.feed.get("title") == "T"


def test_rss_google_news_feeds_from_terms():
    collector = RssCollector(lambda p: None, feeds=[], terms=["fed rate"])
    assert any("news.google.com" in url for url in collector.feeds)
    assert "fed+rate" in collector.feeds[0]


def test_x_rule_and_parse():
    assert build_rule(["bitcoin", "fed rate"], ["en"]) == (
        '(bitcoin OR "fed rate") -is:retweet lang:en'
    )
    with pytest.raises(ValueError):
        build_rule([])
    rules = build_rules([f"term{i}" for i in range(60)], ["en"], max_length=120)
    assert len(rules) > 1 and all(len(r) <= 120 for r in rules)
    assert " ".join(rules).count("term") == 60
    with pytest.raises(ValueError):
        build_rules(["x" * 600], max_length=512)
    check_rules_response(SimpleNamespace(errors=[], meta={"summary": {"created": 2}}))
    with pytest.raises(RuntimeError):
        check_rules_response(SimpleNamespace(errors=[{"title": "bad"}], meta={}))
    with pytest.raises(RuntimeError):
        check_rules_response(
            SimpleNamespace(errors=[], meta={"summary": {"created": 0}})
        )
    post = parse_tweet({"id": "1", "text": "hi", "lang": "en",
                        "created_at": "2024-01-01T00:00:00.000Z"})
    assert post.ts_ms == 1_704_067_200_000 and post.url.endswith("/1")
    assert parse_tweet({"id": "", "text": "x"}) is None


def test_synthetic_collector_emits_until_stopped():
    sink = _Sink()
    stop = threading.Event()
    collector = SyntheticCollector(sink, rate_per_second=200, seed=1)
    thread = threading.Thread(target=collector.run, args=(stop,))
    thread.start()
    time.sleep(0.3)
    stop.set()
    thread.join(2)
    assert len(sink.posts) > 10
    assert len({p.source_id for p in sink.posts}) == len(sink.posts)


def test_timestamp_filters():
    now_ms = int(time.time() * 1000)
    collector = _Dummy(_Sink(), max_age_ms=60_000, max_future_ms=1_000)
    assert collector.emit(Post("t", "1", now_ms, "fresh"))
    assert not collector.emit(Post("t", "2", now_ms - 120_000, "stale"))
    assert not collector.emit(Post("t", "3", now_ms + 60_000, "future"))
    unfiltered = _Dummy(_Sink())
    assert unfiltered.emit(Post("t", "4", 1, "epoch"))


def _fake_reddit(comment_items, submission_items):
    def comments(**kwargs):
        for item in comment_items:
            if isinstance(item, Exception):
                raise item
            yield item

    def submissions(**kwargs):
        for item in submission_items:
            yield item
        while True:
            time.sleep(0.05)
            yield None

    stream = SimpleNamespace(comments=comments, submissions=submissions)
    subreddit = SimpleNamespace(stream=stream)
    return SimpleNamespace(subreddit=lambda name: subreddit)


def test_reddit_worker_death_triggers_reconnect(monkeypatch):
    comment = SimpleNamespace(body="btc up", fullname="t1_a", created_utc=1,
                              author="u", permalink="/r/x")
    fake = _fake_reddit([comment, RuntimeError("500 from reddit")], [])
    sink = _Sink()
    collector = RedditCollector(sink, subreddits=["x"], client_id="id",
                                client_secret="secret")
    monkeypatch.setattr(collector, "_reddit", lambda: fake)
    stop = threading.Event()
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        collector.run_once(stop)
    assert time.monotonic() - started < 5
    assert [p.source_id for p in sink.posts] == ["t1_a"]
    assert collector._connections == 1


def test_synthetic_live_stream_drifts():
    sink = _Sink()
    stop = threading.Event()
    collector = SyntheticCollector(sink, rate_per_second=5000, seed=3)
    thread = threading.Thread(target=collector.run, args=(stop,))
    thread.start()
    while len(sink.posts) < 1200 and thread.is_alive():
        time.sleep(0.05)
    stop.set()
    thread.join(2)
    from socialsentiment.sentiment import get_scorer

    scorer = get_scorer()
    first = [scorer.score(p.text) for p in sink.posts[0:300]]
    second = [scorer.score(p.text) for p in sink.posts[300:600]]
    assert sum(second) / len(second) > sum(first) / len(first)
