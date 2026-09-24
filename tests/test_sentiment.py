from socialsentiment.sentiment import (
    FINANCE_LEXICON,
    SentimentScorer,
    classify,
    get_scorer,
)


def test_finance_terms_shift_scores():
    scorer = SentimentScorer()
    assert scorer.score("BTC is mooning, so bullish!") > 0.5
    assert scorer.score("Total rugpull, liquidations everywhere") < -0.5


def test_neutral_text_is_near_zero():
    assert abs(get_scorer().score("Volume is average today")) < 0.1


def test_extra_lexicon_overrides():
    scorer = SentimentScorer(extra_lexicon={"bullish": -3.0})
    assert scorer.score("bullish") < 0


def test_classify_threshold():
    assert classify(0.5) == 1
    assert classify(-0.5) == -1
    assert classify(0.05) == 0
    assert classify(0.2, threshold=0.3) == 0


def test_lexicon_is_lowercase_and_in_range():
    for term, valence in FINANCE_LEXICON.items():
        assert term == term.lower()
        assert -4.0 <= valence <= 4.0
