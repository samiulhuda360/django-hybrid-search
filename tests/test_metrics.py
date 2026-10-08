import math
from pathlib import Path

import pytest

from search.evaluation import evaluate, load_queries
from search.index import SearchIndex
from search.metrics import mrr_at_k, ndcg_at_k, recall_at_k


def test_ndcg_perfect_and_reversed() -> None:
    labels = {"a": 2, "b": 1}
    assert ndcg_at_k(["a", "b", "c"], labels) == pytest.approx(1.0)
    reversed_dcg = 1 / math.log2(2) + 3 / math.log2(3)
    ideal = 3 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(["b", "a"], labels) == pytest.approx(reversed_dcg / ideal)
    assert ndcg_at_k(["x"], {}) == 0.0


def test_mrr_uses_first_fully_relevant_result() -> None:
    labels = {"a": 1, "b": 2}
    assert mrr_at_k(["a", "c", "b"], labels) == pytest.approx(1 / 3)
    assert mrr_at_k(["c"], labels) == 0.0


def test_recall_at_k() -> None:
    labels = {"a": 2, "b": 2, "c": 1}
    assert recall_at_k(["a", "x", "c"], labels, k=5) == 0.5


def test_evaluate_groups_by_query_kind(small_index: SearchIndex, tmp_path: Path) -> None:
    path = tmp_path / "q.jsonl"
    path.write_text(
        '{"id": "1", "query": "CNAME record", "kind": "keyword", "relevant": {"/docs/custom-domains.html": 2}}\n'
        '{"id": "2", "query": "undo a release", "kind": "natural", "relevant": {"/docs/rollbacks.html": 2}}\n',
        encoding="utf-8",
    )
    results = evaluate(small_index, load_queries(path))
    assert set(results) == {"all", "keyword", "natural"}
    assert results["keyword"]["bm25"].ndcg10 == pytest.approx(1.0)
    for by_mode in results.values():
        for scores in by_mode.values():
            assert 0.0 <= scores.ndcg10 <= 1.0
