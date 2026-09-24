"""Trending and related-term statistics computed from post samples.

Both functions return ``{term: [mean_sentiment, post_count]}`` so the result
is JSON-serialisable and can be cached in the ``meta`` table.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence

import pandas as pd

from socialsentiment.text import name_candidates, tokenize

TermStats = dict[str, list[float]]


def term_stats(
    texts: Iterable[str],
    sentiments: Iterable[float],
    *,
    tokenizer: Callable[[str], Sequence[str]],
    exclude: Iterable[str] = (),
    top_n: int = 15,
    min_count: int = 2,
) -> TermStats:
    """Most frequent terms with the mean sentiment of the posts using them.

    A term is counted once per post, so a single spammy post cannot dominate
    the ranking.  Everything is computed in memory from the sample handed
    in; no additional database queries are needed.
    """
    excluded = {term.lower() for term in exclude}
    token_sets: list[set[str]] = []
    scores: list[float] = []
    for text, sentiment in zip(texts, sentiments):
        tokens = set(tokenizer(text)) - excluded
        if tokens:
            token_sets.append(tokens)
            scores.append(float(sentiment))

    counter: Counter[str] = Counter()
    for tokens in token_sets:
        counter.update(tokens)
    top = [(t, c) for t, c in counter.most_common(top_n) if c >= min_count]
    if not top:
        return {}

    wanted = {term for term, _ in top}
    sums: dict[str, float] = dict.fromkeys(wanted, 0.0)
    for tokens, score in zip(token_sets, scores):
        for term in tokens & wanted:
            sums[term] += score
    return {
        term: [round(sums[term] / count, 4), count] for term, count in top
    }


def related_terms(
    posts: pd.DataFrame, term: str, top_n: int = 15
) -> TermStats:
    """Words that co-occur with ``term`` in ``posts`` and their sentiment."""
    if posts.empty:
        return {}
    exclude = set(tokenize(term, min_length=1)) | {term.lower()}
    return term_stats(
        posts["text"],
        posts["sentiment"],
        tokenizer=tokenize,
        exclude=exclude,
        top_n=top_n,
    )


def trending_terms(posts: pd.DataFrame, top_n: int = 12) -> TermStats:
    """Names, tickers and tags that are frequent in the sample."""
    if posts.empty:
        return {}
    return term_stats(
        posts["text"],
        posts["sentiment"],
        tokenizer=name_candidates,
        top_n=top_n,
        min_count=3,
    )
