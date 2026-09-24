"""Synthetic post generator for offline demos and tests.

Produces plausible finance/crypto chatter at a configurable rate so the
dashboard can be exercised without network access or API credentials.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Iterator, Sequence
from typing import Any

from socialsentiment import settings
from socialsentiment.collectors.base import Collector, Sink
from socialsentiment.models import Post
from socialsentiment.storage import now_ms

TOPICS: tuple[str, ...] = (
    "bitcoin",
    "ethereum",
    "solana",
    "nvidia",
    "tesla",
    "apple",
    "gold",
    "oil",
    "the fed",
    "inflation",
)
TAGS: dict[str, str] = {
    "bitcoin": "$BTC",
    "ethereum": "$ETH",
    "solana": "$SOL",
    "nvidia": "$NVDA",
    "tesla": "$TSLA",
    "apple": "$AAPL",
    "gold": "#gold",
    "oil": "#oil",
    "the fed": "#FOMC",
    "inflation": "#CPI",
}
POSITIVE_TEMPLATES: tuple[str, ...] = (
    "{topic} looks bullish today, strong breakout above resistance {tag}",
    "Great earnings, {topic} rallying hard. Love it {tag}",
    "{topic} is mooning again, hodl and enjoy the ride {tag}",
    "Upgraded my view on {topic}: undervalued and gaining momentum {tag}",
    "Massive inflows into {topic}, this rally has legs {tag}",
)
NEGATIVE_TEMPLATES: tuple[str, ...] = (
    "{topic} dumping hard, bearish structure everywhere {tag}",
    "Terrible news for {topic}, liquidations piling up {tag}",
    "{topic} crashing after the downgrade, sell-off continues {tag}",
    "Worried about {topic}, recession fears and hawkish fed {tag}",
    "Bagholders of {topic} getting wrecked today {tag}",
)
NEUTRAL_TEMPLATES: tuple[str, ...] = (
    "{topic} trading sideways, waiting for the CPI print {tag}",
    "Volume on {topic} is average, nothing to see yet {tag}",
    "Watching {topic} levels: support at the 50 day moving average {tag}",
    "{topic} news roundup: ETF flows, options expiry, funding rates {tag}",
    "Anyone tracking {topic} order books this afternoon? {tag}",
)
AUTHORS: tuple[str, ...] = (
    "quant_kate",
    "macro_mike",
    "athens_trader",
    "sat_stacker",
    "delta_neutral",
    "fomo_fred",
    "risk_off_rita",
)
# Number of live posts over which the sentiment mix completes one drift
# cycle (bearish -> bullish -> bearish).
LIVE_CYCLE_POSTS = 600


def make_post(
    rng: random.Random,
    *,
    ts_ms: int,
    source_id: str,
    phase: float,
    topics: Sequence[str] = TOPICS,
) -> Post:
    """One synthetic post; ``phase`` in [0, 1) steers the sentiment mix."""
    swing = 1.0 if phase > 0.5 else -1.0
    positive_bias = 0.35 + 0.3 * rng.random() * swing
    roll = rng.random()
    if roll < positive_bias:
        template = rng.choice(POSITIVE_TEMPLATES)
    elif roll < positive_bias + 0.3:
        template = rng.choice(NEGATIVE_TEMPLATES)
    else:
        template = rng.choice(NEUTRAL_TEMPLATES)
    topic = rng.choice(topics)
    text = template.format(topic=topic, tag=TAGS.get(topic, "")).strip()
    return Post(
        source="synthetic",
        source_id=source_id,
        ts_ms=ts_ms,
        text=text,
        author=rng.choice(AUTHORS),
        lang="en",
    )


def generate_posts(
    count: int,
    *,
    start_ms: int,
    end_ms: int,
    rng: random.Random | None = None,
    topics: Sequence[str] = TOPICS,
) -> Iterator[Post]:
    """Yield ``count`` posts with timestamps spread over ``[start, end]``.

    The sentiment mix drifts over the window so the charts show a trend
    rather than white noise.
    """
    rng = rng or random.Random()
    span = max(end_ms - start_ms, 1)
    for index in range(count):
        ts_ms = start_ms + int(span * index / max(count, 1))
        yield make_post(
            rng,
            ts_ms=ts_ms,
            source_id=f"{ts_ms}-{index}-{rng.randrange(1_000_000)}",
            phase=index / max(count, 1),
            topics=topics,
        )


class SyntheticCollector(Collector):
    name = "synthetic"

    def __init__(
        self,
        sink: Sink,
        *,
        rate_per_second: float = settings.SYNTHETIC_RATE_PER_SECOND,
        seed: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(sink, **kwargs)
        self.rate_per_second = max(rate_per_second, 0.01)
        self._rng = random.Random(seed)
        self._counter = 0

    def run_once(self, stop_event: threading.Event) -> None:
        interval = 1.0 / self.rate_per_second
        while not stop_event.is_set():
            stamp = now_ms()
            self._counter += 1
            phase = (self._counter % LIVE_CYCLE_POSTS) / LIVE_CYCLE_POSTS
            self.emit(
                make_post(
                    self._rng,
                    ts_ms=stamp,
                    source_id=f"{stamp}-{self._counter}",
                    phase=phase,
                )
            )
            if stop_event.wait(interval):
                break
