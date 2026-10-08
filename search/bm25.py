"""Okapi BM25 over an in-memory inverted index."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np
import numpy.typing as npt


class BM25:
    """Scores documents (here: passages) for a bag of query terms.

    score(d, q) = sum over terms t in q of  idf(t) * tf(t, d) * (k1 + 1) / (tf(t, d) + k1 * (1 - b + b * |d| / avgdl))
    with the non-negative idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5)).
    """

    def __init__(self, documents: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.n_docs = len(documents)
        self.doc_len = np.array([len(d) for d in documents], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.n_docs else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for doc_id, terms in enumerate(documents):
            for term, tf in Counter(terms).items():
                self.postings.setdefault(term, []).append((doc_id, tf))
        self.idf = {
            term: math.log(1 + (self.n_docs - len(p) + 0.5) / (len(p) + 0.5)) for term, p in self.postings.items()
        }

    def doc_freq(self, term: str) -> int:
        return len(self.postings.get(term, ()))

    def scores(self, query_terms: list[str]) -> npt.NDArray[np.float64]:
        out = np.zeros(self.n_docs, dtype=np.float64)
        if not self.n_docs:
            return out
        norm = self.k1 * (1 - self.b + self.b * self.doc_len / self.avgdl)
        for term in set(query_terms):
            postings = self.postings.get(term)
            if not postings:
                continue
            ids = np.fromiter((d for d, _ in postings), dtype=np.int64, count=len(postings))
            tfs = np.fromiter((tf for _, tf in postings), dtype=np.float64, count=len(postings))
            out[ids] += self.idf[term] * tfs * (self.k1 + 1) / (tfs + norm[ids])
        return out
