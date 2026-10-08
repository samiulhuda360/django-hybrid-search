from pathlib import Path

import pytest
from django.conf import LazySettings

from search.index import SearchIndex, get_index
from tests.conftest import DOCS


def test_bm25_mode_returns_only_matching_pages(small_index: SearchIndex) -> None:
    result = small_index.search("CNAME record", "bm25")
    assert [h.page_id for h in result.hits] == [2]
    assert result.hits[0].bm25_rank == 1
    assert result.hits[0].semantic_rank is None


def test_semantic_mode_ranks_every_page(small_index: SearchIndex) -> None:
    result = small_index.search("log drain retention", "semantic")
    assert result.total == 4
    assert result.hits[0].page_id == 3


def test_hybrid_uses_reciprocal_rank_fusion(small_index: SearchIndex, settings: LazySettings) -> None:
    k = settings.SEARCH["RRF_K"]
    result = small_index.search("rollback release", "hybrid")
    top = result.hits[0]
    assert top.page_id == 1
    expected = 1 / (k + top.bm25_rank) + 1 / (k + top.semantic_rank)
    assert top.score == pytest.approx(expected)
    scores = [h.score for h in result.hits]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_snippet_passage_prefers_keyword_match(small_index: SearchIndex) -> None:
    hit = small_index.search("accidental delete", "hybrid").hits[0]
    assert hit.page_id == 4
    assert "accidental delete" in hit.passage.text


def test_offset_paginates(small_index: SearchIndex) -> None:
    first = small_index.search("app", "semantic", k=2)
    second = small_index.search("app", "semantic", k=2, offset=2)
    assert {h.page_id for h in first.hits}.isdisjoint({h.page_id for h in second.hits})


def test_empty_query_returns_nothing(small_index: SearchIndex) -> None:
    assert small_index.search("   ").hits == []


def test_save_load_round_trip_and_reload(small_index: SearchIndex, settings: LazySettings) -> None:
    directory = Path(settings.SEARCH["INDEX_DIR"])
    assert get_index() is None
    small_index.save(directory)
    loaded = get_index()
    assert loaded is not None
    assert loaded.page_count == 4
    assert [h.page_id for h in loaded.search("CNAME", "bm25").hits] == [2]
    assert get_index() is loaded  # cached until the files change

    rebuilt = SearchIndex.build(DOCS[:2], "hash")
    rebuilt.built_at += 1
    rebuilt.save(directory)
    meta = directory / "meta.json"
    import os

    stat = meta.stat()
    os.utime(meta, (stat.st_atime, stat.st_mtime + 5))
    reloaded = get_index()
    assert reloaded is not None and reloaded.page_count == 2
