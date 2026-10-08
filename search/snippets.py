"""Result snippets with the query words highlighted.

All page text is HTML-escaped before <mark> tags are added, so crawled content can never inject markup.
"""

from __future__ import annotations

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from .text import STOPWORDS, Token, tokens


def _matches(toks: list[Token], query_stems: set[str]) -> list[bool]:
    return [t.stem in query_stems and t.word.lower() not in STOPWORDS for t in toks]


def highlight(text: str, query_stems: set[str]) -> SafeString:
    """Escape ``text`` and wrap every word whose stem is in ``query_stems`` in <mark>."""
    toks = list(tokens(text))
    out: list[str] = []
    pos = 0
    for tok, hit in zip(toks, _matches(toks, query_stems), strict=True):
        if hit:
            out.append(escape(text[pos : tok.start]))
            out.append(f"<mark>{escape(tok.word)}</mark>")
            pos = tok.end
    out.append(escape(text[pos:]))
    return mark_safe("".join(out))  # noqa: S308 - every piece above is escaped


def make_snippet(text: str, query_stems: set[str], window: int = 32) -> SafeString:
    """Pick the ``window``-word stretch of ``text`` with the most distinct query words, and highlight it."""
    toks = list(tokens(text))
    if not toks:
        return mark_safe("")
    flags = _matches(toks, query_stems)
    best_start, best_score = 0, (-1, -1)
    for start in range(0, max(1, len(toks) - window + 1)):
        span = range(start, min(len(toks), start + window))
        distinct = len({toks[i].stem for i in span if flags[i]})
        total = sum(flags[i] for i in span)
        if (distinct, total) > (best_score[0], best_score[1]):
            best_start, best_score = start, (distinct, total)
    end = min(len(toks), best_start + window)
    char_start = 0 if best_start == 0 else toks[best_start].start
    char_end = len(text) if end == len(toks) else toks[end - 1].end
    body = highlight(text[char_start:char_end], query_stems)
    prefix = "… " if char_start > 0 else ""
    suffix = " …" if char_end < len(text) else ""
    return mark_safe(f"{prefix}{body}{suffix}")  # noqa: S308 - body is escaped by highlight()
