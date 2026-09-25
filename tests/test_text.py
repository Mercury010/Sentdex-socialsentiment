from socialsentiment.text import (
    STOP_WORDS,
    contains_any,
    extract_tags,
    fts_query,
    name_candidates,
    strip_html,
    strip_urls,
    term_counts,
    tokenize,
)


def test_tokenize_drops_urls_stop_words_and_short_tokens():
    tokens = tokenize("Bitcoin ETF inflows hit $1bn as $BTC breaks out "
                      "https://example.com/x #crypto")
    assert tokens == ["bitcoin", "etf", "inflows", "hit", "btc", "breaks",
                      "crypto"]
    assert "the" in STOP_WORDS


def test_extract_tags_dedupes_and_lowercases():
    assert extract_tags("$BTC $eth #Gold #gold $12 $btc") == [
        "$btc", "$eth", "#gold"
    ]


def test_name_candidates_skips_sentence_starts():
    names = name_candidates(
        "Today Nvidia and Tesla rallied. Fed chair Powell spoke. $BTC"
    )
    assert "today" not in names
    assert "fed" not in names  # sentence start
    assert {"nvidia", "tesla", "powell", "btc"} <= set(names)


def test_name_candidates_keeps_tickers():
    assert "nvda" in name_candidates("NVDA up 5% premarket")


def test_fts_query_is_injection_safe():
    assert fts_query('$btc etf "OR" drop; --') == '"btc"* "etf"* "OR"* "drop"*'
    assert fts_query("") == ""
    assert fts_query("   ") == ""


def test_strip_helpers():
    assert strip_html("<p>Inflows &amp; <b>surge</b></p>") == "Inflows & surge"
    assert strip_urls("see https://a.b/c now").split() == ["see", "now"]


def test_term_counts_and_contains_any():
    counts = term_counts(["bitcoin rally", "bitcoin dump"], exclude=["bitcoin"])
    assert counts["rally"] == 1 and counts["bitcoin"] == 0
    assert contains_any("Big BITCOIN move", ["bitcoin"])
    assert not contains_any("gold", ["bitcoin", "eth"])


def test_terms_match_whole_words_only():
    assert contains_any("$ETH is pumping", ["eth"])
    assert contains_any("bitcoin's rally", ["bitcoin"])
    assert contains_any("BTC/USD at 84k", ["btc"])
    assert contains_any("the fed rate decision", ["fed rate"])
    assert not contains_any("whether we go together", ["eth"])
    assert not contains_any("method acting", ["eth"])
    assert not contains_any("bitcoins", ["bitcoin"])
    assert not contains_any("anything", [])


def test_strip_html_keeps_escaped_brackets():
    assert strip_html("Bitcoin drops &lt;5%&gt; as <b>ETF</b> outflows") == (
        "Bitcoin drops <5%> as ETF outflows"
    )


def test_contractions_do_not_become_content_words():
    assert tokenize("I don't think it's a trap, bitcoin's rally") == [
        "trap", "bitcoin", "rally"
    ]
