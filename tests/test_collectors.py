import threading
import time
from types import SimpleNamespace

import pytest

from socialsentiment.collectors import available_sources, create_collector
from socialsentiment.collectors.base import Collector
from socialsentiment.collectors.bluesky import parse_event
from socialsentiment.collectors.reddit import parse_comment, parse_submission
from socialsentiment.collectors.rss import RssCollector, parse_entry
from socialsentiment.collectors.synthetic import SyntheticCollector
from socialsentiment.collectors.x_stream import build_rule, parse_tweet
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


def test_parse_jetstream_event():
    post = parse_event(JETSTREAM_EVENT)
    assert post.source == "bluesky" and post.lang == "en"
    assert post.ts_ms == 1725911162102
    assert post.url.endswith("/post/3l3q")
    assert parse_event({"kind": "identity"}) is None
    bad_time = dict(JETSTREAM_EVENT)
    bad_time["commit"] = dict(JETSTREAM_EVENT["commit"])
    bad_time["commit"]["record"] = dict(JETSTREAM_EVENT["commit"]["record"],
                                        createdAt="garbage")
    assert parse_event(bad_time).ts_ms == 1725911162329


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

    import feedparser

    fake = SimpleNamespace(
        entries=[entry, {"link": "https://x/2", "title": "Gold falls"}],
        feed={"title": "Feed"},
        get=lambda key, default=None: False,
    )
    monkeypatch.setattr(feedparser, "parse", lambda url, agent=None: fake)
    sink = _Sink()
    collector = RssCollector(sink, feeds=["https://feed"], terms=["bitcoin"],
                             add_google_news=False)
    assert collector.poll() == 1
    assert sink.posts[0].source_id == "Feed|1"


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
