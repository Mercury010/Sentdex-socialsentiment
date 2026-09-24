"""Sentiment scoring: VADER plus a conservative finance/crypto lexicon."""

from __future__ import annotations

from functools import lru_cache

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from socialsentiment import settings

# Valence on VADER's -4 .. +4 scale.  Only terms whose market meaning is
# reasonably unambiguous are included; this is a heuristic extension of the
# general-purpose VADER lexicon, not a trained financial model.  Ambiguous
# words ("moon", "tank", "rug", "short", "dip") are deliberately left out.
FINANCE_LEXICON: dict[str, float] = {
    # positive
    "bullish": 2.5,
    "mooning": 2.3,
    "rally": 2.0,
    "rallies": 2.0,
    "rallying": 2.0,
    "surge": 2.0,
    "surges": 2.0,
    "surging": 2.0,
    "soar": 2.3,
    "soars": 2.3,
    "soaring": 2.3,
    "breakout": 1.8,
    "ath": 2.0,
    "hodl": 1.2,
    "undervalued": 1.5,
    "upgrade": 1.5,
    "upgraded": 1.5,
    "outperform": 1.8,
    "outperforms": 1.8,
    "outperformed": 1.8,
    "dovish": 0.8,
    "oversold": 0.6,
    # negative
    "bearish": -2.5,
    "dump": -2.3,
    "dumps": -2.3,
    "dumping": -2.3,
    "dumped": -2.3,
    "crash": -2.8,
    "crashes": -2.8,
    "crashing": -2.8,
    "plunge": -2.5,
    "plunges": -2.5,
    "plunging": -2.5,
    "tanking": -2.3,
    "rugpull": -3.5,
    "rugpulled": -3.5,
    "fud": -1.8,
    "liquidated": -2.5,
    "liquidation": -2.0,
    "liquidations": -2.0,
    "bagholder": -2.0,
    "bagholders": -2.0,
    "overvalued": -1.5,
    "downgrade": -1.5,
    "downgraded": -1.5,
    "underperform": -1.8,
    "underperforms": -1.8,
    "underperformed": -1.8,
    "selloff": -2.2,
    "sell-off": -2.2,
    "recession": -2.0,
    "hawkish": -0.8,
    "overbought": -0.6,
}


class SentimentScorer:
    """Thin wrapper around VADER with the finance lexicon merged in."""

    def __init__(self, extra_lexicon: dict[str, float] | None = None) -> None:
        self._analyzer = SentimentIntensityAnalyzer()
        self._analyzer.lexicon.update(FINANCE_LEXICON)
        if extra_lexicon:
            self._analyzer.lexicon.update(extra_lexicon)

    def score(self, text: str) -> float:
        """Return VADER's compound score for ``text`` (-1 .. +1)."""
        return float(self._analyzer.polarity_scores(text)["compound"])


@lru_cache(maxsize=1)
def get_scorer() -> SentimentScorer:
    """Process-wide scorer instance (building the lexicon is not free)."""
    return SentimentScorer()


def classify(
    score: float, threshold: float = settings.POSITIVE_THRESHOLD
) -> int:
    """Map a compound score to ``1`` (positive), ``0`` (neutral), ``-1``."""
    if score >= threshold:
        return 1
    if score <= -threshold:
        return -1
    return 0
