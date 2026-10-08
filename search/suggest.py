"""Query suggestions ("search as you type") and spelling correction ("did you mean")."""

from __future__ import annotations

import difflib
from collections.abc import Iterable

from .index import SearchIndex
from .text import STOPWORDS, stem


def _key(text: str) -> str:
    return " ".join(stem(w) for w in text.lower().split())


def suggest(prefix: str, index: SearchIndex, past_queries: Iterable[str] = (), limit: int = 8) -> list[str]:
    """Suggest full queries for what the user has typed so far.

    Sources, in order: earlier searches that start with the text, page titles that start with it, and the
    typed words with the last word completed from the index vocabulary (most frequent first).
    """
    typed = " ".join(prefix.lower().split())
    if not typed:
        return []
    out: list[str] = []

    seen = {_key(typed)}

    def add(item: str) -> None:
        item = " ".join(item.split())
        if item and _key(item) not in seen:  # "custom domain" and "custom domains" count as one suggestion
            seen.add(_key(item))
            out.append(item)

    for query in past_queries:
        if query.lower().startswith(typed):
            add(query.lower())
    for title in index.titles:
        if title.lower().startswith(typed) or any(w.startswith(typed) for w in title.lower().split()[1:]):
            add(title.lower())

    head, _, last = typed.rpartition(" ")
    if last:
        for word in complete_word(last, head.split()[-1] if head else "", index, limit):
            add(f"{head} {word}".strip())
    return out[:limit]


def complete_word(partial: str, previous: str, index: SearchIndex, limit: int) -> list[str]:
    # Words that follow the previous word somewhere in the corpus come first, then the most frequent words.
    # Only one form per stem is offered, so "domain" and "domains" do not both appear.
    candidates = [w for w in index.vocabulary if w.startswith(partial) and w != partial]
    if previous:
        followed = [w for w in candidates if index.bigrams.get((previous, w), 0)]
        candidates = followed or candidates
    candidates.sort(key=lambda w: (-index.bigrams.get((previous, w), 0), -index.vocabulary[w], w))
    chosen: list[str] = []
    stems: set[str] = set()
    for word in candidates:
        if stem(word) not in stems:
            stems.add(stem(word))
            chosen.append(word)
    return chosen[:limit]


def did_you_mean(query: str, index: SearchIndex) -> str | None:
    """Return a corrected query when some words are not in the index but a close spelling is, else None."""
    vocab = [w for w, n in index.vocabulary.items() if n >= 1]
    known = set(vocab)
    changed = False
    fixed: list[str] = []
    for word in query.split():
        lower = word.lower()
        if len(lower) < 4 or lower in known or lower in STOPWORDS or not lower.isalpha():
            fixed.append(word)
            continue
        match = difflib.get_close_matches(lower, vocab, n=1, cutoff=0.85)
        if match:
            fixed.append(match[0])
            changed = True
        else:
            fixed.append(word)
    return " ".join(fixed) if changed else None
