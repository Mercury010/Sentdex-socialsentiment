import pandas as pd

from socialsentiment import storage
from socialsentiment.trending import related_terms, term_stats, trending_terms


def test_term_stats_counts_posts_not_occurrences():
    texts = ["gold gold gold rally", "gold dump", "silver"]
    stats = term_stats(texts, [0.5, -0.5, 0.0], tokenizer=str.split,
                       top_n=5, min_count=1)
    assert stats["gold"] == [0.0, 2]
    assert stats["rally"] == [0.5, 1]


def test_related_terms_excludes_the_query(seeded):
    posts = storage.fetch_posts(seeded, "bitcoin", limit=500)
    stats = related_terms(posts, "bitcoin", top_n=10)
    assert stats and "bitcoin" not in stats
    for mean, count in stats.values():
        assert -1.0 <= mean <= 1.0 and count >= 2


def test_trending_terms_finds_tickers(seeded):
    posts = storage.fetch_posts(seeded, "", limit=600)
    stats = trending_terms(posts, top_n=8)
    assert {"btc", "nvda", "tsla"} & set(stats)


def test_empty_frames():
    empty = pd.DataFrame(columns=["text", "sentiment"])
    assert related_terms(empty, "x") == {}
    assert trending_terms(empty) == {}
