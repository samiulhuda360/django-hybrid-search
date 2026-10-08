"""Text analysis shared by indexing, querying, snippets and suggestions."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

import snowballstemmer

WORD_RE = re.compile(r"[A-Za-z0-9]+")

_STOPWORD_TEXT = """
a about above after again against all am an and any are as at be because been before being below between both but
by can could did do does doing down during each few for from further had has have having he her here hers herself
him himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or
other our ours ourselves out over own same she should so some such than that the their theirs them themselves then
there these they this those through to too under until up very was we were what when where which while who whom why
will with would you your yours yourself yourselves get got
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())

_stemmer = snowballstemmer.stemmer("english")


@lru_cache(maxsize=50_000)
def stem(word: str) -> str:
    """Lower-case and stem one word, so "deploys", "deploying" and "deployed" all become "deploy"."""
    return str(_stemmer.stemWord(word.lower()))


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    word: str
    stem: str


def tokens(text: str) -> Iterator[Token]:
    """Yield every word with its character offsets (stopwords included, for highlighting)."""
    for match in WORD_RE.finditer(text):
        word = match.group(0)
        yield Token(match.start(), match.end(), word, stem(word))


def analyze(text: str) -> list[str]:
    """Turn text into the stemmed terms used by the BM25 index. Stopwords are dropped."""
    return [stem(w) for w in WORD_RE.findall(text) if w.lower() not in STOPWORDS]


def words(text: str) -> list[str]:
    """Lower-case surface words, used to build the suggestion vocabulary."""
    return [w.lower() for w in WORD_RE.findall(text)]


@dataclass(frozen=True)
class Passage:
    heading: str
    text: str


def split_passages(body: str, max_words: int = 120, min_words: int = 25) -> list[Passage]:
    """Split page text into passages under their headings.

    Page text is stored as blocks separated by blank lines; a block starting with "## " is a heading. Passages
    stay under ``max_words`` unless a single paragraph is longer. A passage shorter than ``min_words`` (such as a
    one-line introduction) is not closed at the next heading; the heading text is folded into it instead.
    """
    passages: list[Passage] = []
    heading = ""
    buffer: list[str] = []
    count = 0

    def flush() -> None:
        nonlocal buffer, count
        if buffer:
            passages.append(Passage(heading, " ".join(buffer)))
        buffer, count = [], 0

    for block in (b.strip() for b in body.split("\n\n")):
        if not block:
            continue
        if block.startswith("## "):
            title = block[3:].strip()
            if buffer and count < min_words:
                buffer.append(f"{title}:")
                count += len(title.split())
                continue
            flush()
            heading = title
            continue
        n = len(block.split())
        if buffer and count + n > max_words:
            flush()
        buffer.append(block)
        count += n
    flush()
    return passages
