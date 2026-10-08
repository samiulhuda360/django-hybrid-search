"""Ranking metrics for graded relevance labels (2 = answers the query, 1 = related)."""

from __future__ import annotations

import math
from collections.abc import Sequence


def dcg(gains: Sequence[float]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked: list[str], labels: dict[str, int], k: int = 10) -> float:
    """Normalised discounted cumulative gain with exponential gain 2^rel - 1."""
    ideal = dcg(sorted(labels.values(), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([labels.get(doc, 0) for doc in ranked[:k]]) / ideal


def mrr_at_k(ranked: list[str], labels: dict[str, int], k: int = 10, min_grade: int = 2) -> float:
    """Reciprocal rank of the first result with at least ``min_grade`` (0 if none in the top k)."""
    for i, doc in enumerate(ranked[:k], start=1):
        if labels.get(doc, 0) >= min_grade:
            return 1.0 / i
    return 0.0


def recall_at_k(ranked: list[str], labels: dict[str, int], k: int = 5, min_grade: int = 2) -> float:
    relevant = {doc for doc, grade in labels.items() if grade >= min_grade}
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)
