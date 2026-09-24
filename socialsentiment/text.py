"""Text helpers: tokenising, stop words, tags and FTS5 query building."""

from __future__ import annotations

import html
import re
from collections import Counter
from collections.abc import Iterable

_ENGLISH_STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am",
    "an", "and", "any", "are", "aren", "as", "at", "back", "be", "because",
    "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "cannot", "could", "couldn", "day", "did", "didn", "do", "does",
    "doesn", "doing", "don", "down", "during", "each", "even", "ever",
    "every", "few", "for", "from", "further", "get", "gets", "getting",
    "go", "goes", "going", "gone", "good", "got", "had", "hadn", "has",
    "hasn", "have", "haven", "having", "he", "her", "here", "hers",
    "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "isn", "it", "its", "itself", "just", "know", "let", "like",
    "ll", "look", "lot", "made", "make", "makes", "many", "may", "me",
    "might", "more", "most", "much", "must", "mustn", "my", "myself",
    "need", "needn", "never", "new", "no", "nor", "not", "now", "of", "off",
    "on", "once", "one", "only", "or", "other", "our", "ours", "ourselves",
    "out", "over", "own", "people", "really", "right", "s", "same", "say",
    "said", "says", "see", "shan", "she", "should", "shouldn", "since", "so",
    "some", "something", "still", "such", "t", "take", "than", "that",
    "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "thing", "things", "think", "this", "those", "though",
    "through", "time", "to", "today", "too", "under", "until", "up", "us",
    "ve", "very", "want", "was", "wasn", "way", "we", "well", "were",
    "weren", "what", "when", "where", "which", "while", "who", "whom",
    "why", "will", "with", "won", "would", "wouldn", "y", "year", "years",
    "yes", "yet", "you", "your", "yours", "yourself", "yourselves",
}
_WEB_STOP_WORDS = {
    "amp", "com", "gt", "html", "http", "https", "lt", "nbsp", "org", "rt",
    "utm", "via", "www",
}
STOP_WORDS: frozenset[str] = frozenset(
    _ENGLISH_STOP_WORDS | _WEB_STOP_WORDS | set("abcdefghijklmnopqrstuvwxyz")
)

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})(?![A-Za-z0-9])")
HASHTAG_RE = re.compile(r"#([^\W\d_]\w{1,})")
# A word starts with a letter and may contain inner apostrophes or hyphens.
WORD_RE = re.compile(r"[^\W\d_](?:[^\W_]|['’-](?=[^\W_]))*")
_FTS_TOKEN_RE = re.compile(r"\w+")
_SENTENCE_END = frozenset(".!?:;\n")


def strip_html(text: str) -> str:
    """Unescape entities, drop tags and collapse whitespace."""
    cleaned = HTML_TAG_RE.sub(" ", html.unescape(text or ""))
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def strip_urls(text: str) -> str:
    return URL_RE.sub(" ", text or "")


def extract_tags(text: str) -> list[str]:
    """Return cashtags and hashtags, lower-cased, in order, de-duplicated."""
    seen: set[str] = set()
    tags: list[str] = []
    for prefix, pattern in (("$", CASHTAG_RE), ("#", HASHTAG_RE)):
        for match in pattern.finditer(text or ""):
            tag = prefix + match.group(1).lower()
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def tokenize(text: str, min_length: int = 3) -> list[str]:
    """Lower-cased content words, without URLs, stop words or short tokens."""
    words = (m.group(0).lower() for m in WORD_RE.finditer(strip_urls(text)))
    return [w for w in words if len(w) >= min_length and w not in STOP_WORDS]


def name_candidates(text: str, min_length: int = 2) -> list[str]:
    """Heuristic proper-noun and ticker extraction without a POS tagger.

    A token qualifies when it is a cashtag or hashtag, is ALL CAPS (a ticker
    such as ``NVDA``), or starts with a capital letter and is not the first
    word of a sentence.  Results are lower-cased.
    """
    cleaned = strip_urls(text)
    found: list[str] = [tag[1:] for tag in extract_tags(cleaned)]
    last_end = 0
    for match in WORD_RE.finditer(cleaned):
        word = match.group(0)
        gap = cleaned[last_end:match.start()]
        starts_sentence = last_end == 0 or any(
            ch in _SENTENCE_END for ch in gap
        )
        last_end = match.end()
        lowered = word.lower()
        if len(lowered) < min_length or lowered in STOP_WORDS:
            continue
        is_ticker = word.isupper() and 2 <= len(word) <= 6
        if is_ticker or (word[0].isupper() and not starts_sentence):
            found.append(lowered)
    return found


def term_counts(
    texts: Iterable[str],
    exclude: Iterable[str] = (),
    min_length: int = 3,
) -> Counter[str]:
    """Count content words across ``texts`` (occurrences, not posts)."""
    excluded = {term.lower() for term in exclude}
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(
            token
            for token in tokenize(text, min_length=min_length)
            if token not in excluded
        )
    return counter


def fts_query(term: str) -> str:
    """Build a safe FTS5 prefix query from free text.

    Every alphanumeric token becomes a quoted prefix term, so user input such
    as ``$btc etf`` becomes ``"btc"* "etf"*`` and FTS5 operators or quotes in
    the input cannot alter the query.  Returns ``""`` for empty input.
    """
    tokens = _FTS_TOKEN_RE.findall(term or "")
    return " ".join(f'"{token}"*' for token in tokens)


def contains_any(text: str, terms: Iterable[str]) -> bool:
    """Case-insensitive substring test against a list of terms."""
    lowered = (text or "").lower()
    return any(term.lower() in lowered for term in terms)
