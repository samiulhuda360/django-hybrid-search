"""Relevance evaluation: run every labelled query through each ranking mode and average the metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from urllib.parse import urlsplit

from .index import MODES, Mode, SearchIndex
from .metrics import mrr_at_k, ndcg_at_k, recall_at_k


@dataclass
class LabelledQuery:
    id: str
    query: str
    kind: str
    labels: dict[str, int]


@dataclass
class ModeScores:
    ndcg10: float
    mrr10: float
    recall5: float
    per_query: dict[str, float] = field(default_factory=dict)


def load_queries(path: Path) -> list[LabelledQuery]:
    queries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            queries.append(LabelledQuery(row["id"], row["query"], row["kind"], row["relevant"]))
    return queries


def page_key(url: str) -> str:
    """Labels refer to pages by path (e.g. /docs/rollbacks.html), so they work on any host and port."""
    return urlsplit(url).path


def evaluate(
    index: SearchIndex, queries: list[LabelledQuery], modes: tuple[Mode, ...] = MODES
) -> dict[str, dict[str, ModeScores]]:
    """Return {group: {mode: scores}} for the groups "all" and each query kind."""
    groups: dict[str, list[LabelledQuery]] = {"all": queries}
    for q in queries:
        groups.setdefault(q.kind, []).append(q)
    results: dict[str, dict[str, ModeScores]] = {g: {} for g in groups}
    for mode in modes:
        ranked = {q.id: [page_key(h.url) for h in index.search(q.query, mode, k=10).hits] for q in queries}
        for group, members in groups.items():
            ndcg = {q.id: ndcg_at_k(ranked[q.id], q.labels) for q in members}
            results[group][mode] = ModeScores(
                ndcg10=mean(ndcg.values()),
                mrr10=mean(mrr_at_k(ranked[q.id], q.labels) for q in members),
                recall5=mean(recall_at_k(ranked[q.id], q.labels) for q in members),
                per_query=ndcg,
            )
    return results
