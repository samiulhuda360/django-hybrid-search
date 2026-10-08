"""The search index: passages, BM25, embeddings and hybrid ranking.

Pages are split into passages. Each passage is scored by BM25 and by cosine similarity of its embedding with the
query embedding. A page takes the score of its best passage, so each method yields a page ranking. Hybrid search
merges the two rankings with Reciprocal Rank Fusion:

    rrf(page) = sum over methods m of 1 / (k + rank_m(page))

RRF needs no score calibration between methods, which matters because BM25 scores are unbounded and cosine
similarities sit in a narrow band.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
from django.conf import settings

from .bm25 import BM25
from .embeddings import Embedder, get_embedder
from .text import STOPWORDS, analyze, split_passages, words

Mode = Literal["hybrid", "bm25", "semantic"]
MODES: tuple[Mode, ...] = ("hybrid", "bm25", "semantic")
SEMANTIC_DEPTH = 50


@dataclass(frozen=True)
class SourcePage:
    page_id: int
    url: str
    title: str
    text: str


@dataclass(frozen=True)
class Chunk:
    page_id: int
    url: str
    title: str
    heading: str
    text: str

    @property
    def embed_text(self) -> str:
        return ". ".join(part for part in (self.title, self.heading, self.text) if part)


@dataclass
class Hit:
    page_id: int
    url: str
    title: str
    score: float
    passage: Chunk
    bm25_rank: int | None = None
    semantic_rank: int | None = None


@dataclass
class SearchResult:
    query: str
    mode: Mode
    hits: list[Hit]
    total: int
    terms: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


def _page_ranking(
    chunks: list[Chunk], scores: npt.NDArray[np.float64], positive_only: bool
) -> list[tuple[int, int, float]]:
    """Collapse passage scores to pages: returns (page_id, best_chunk_index, score) sorted best first."""
    best: dict[int, tuple[int, float]] = {}
    for i, score in enumerate(scores):
        if positive_only and score <= 0:
            continue
        page_id = chunks[i].page_id
        if page_id not in best or score > best[page_id][1]:
            best[page_id] = (i, float(score))
    ranked = sorted(best.items(), key=lambda item: (-item[1][1], item[0]))
    return [(page_id, idx, score) for page_id, (idx, score) in ranked]


class SearchIndex:
    def __init__(
        self,
        chunks: list[Chunk],
        chunk_terms: list[list[str]],
        vectors: npt.NDArray[np.float32],
        embedder_kind: str,
        built_at: float | None = None,
    ) -> None:
        self.chunks = chunks
        self.chunk_terms = chunk_terms
        self.vectors = vectors
        self.embedder_kind = embedder_kind
        self.built_at = built_at or time.time()
        self.bm25 = BM25(chunk_terms)
        self.page_count = len({c.page_id for c in chunks})
        self.vocabulary: Counter[str] = Counter()
        self.bigrams: Counter[tuple[str, str]] = Counter()
        self.titles: list[str] = []
        seen: set[int] = set()
        for chunk in chunks:
            self.vocabulary.update(
                w for w in words(f"{chunk.heading} {chunk.text}") if len(w) > 2 and w not in STOPWORDS
            )
            seq = words(f"{chunk.heading} {chunk.text}")
            self.bigrams.update(pairwise(seq))
            if chunk.page_id not in seen:
                seen.add(chunk.page_id)
                self.titles.append(chunk.title)

    # --- building and persistence ------------------------------------------------------------------------------
    @classmethod
    def build(cls, pages: Iterable[SourcePage], embedder_kind: str | None = None) -> SearchIndex:
        kind = embedder_kind or settings.SEARCH["EMBEDDER"]
        chunks: list[Chunk] = []
        for page in pages:
            for passage in split_passages(page.text):
                chunks.append(Chunk(page.page_id, page.url, page.title, passage.heading, passage.text))
        terms = [analyze(f"{c.title} {c.heading} {c.text}") for c in chunks]
        vectors = get_embedder(kind).embed_documents([c.embed_text for c in chunks])
        return cls(chunks, terms, vectors, kind)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {"chunks": [asdict(c) for c in self.chunks], "terms": self.chunk_terms}
        (directory / "chunks.json").write_text(json.dumps(payload), encoding="utf-8")
        np.save(directory / "vectors.npy", self.vectors)
        meta = {
            "embedder": self.embedder_kind,
            "built_at": self.built_at,
            "pages": self.page_count,
            "passages": len(self.chunks),
        }
        (directory / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> SearchIndex:
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        payload = json.loads((directory / "chunks.json").read_text(encoding="utf-8"))
        chunks = [Chunk(**c) for c in payload["chunks"]]
        vectors = np.load(directory / "vectors.npy")
        return cls(chunks, payload["terms"], vectors, meta["embedder"], meta["built_at"])

    def page_context(self, hit: Hit, max_words: int = 160) -> str:
        """The hit's best passage followed by the page's other passages, up to ``max_words`` words."""
        parts = [hit.passage] + [c for c in self.chunks if c.page_id == hit.page_id and c != hit.passage]
        out: list[str] = []
        count = 0
        for chunk in parts:
            text = f"{chunk.heading}: {chunk.text}" if chunk.heading else chunk.text
            if out and count + len(text.split()) > max_words:
                break
            out.append(text)
            count += len(text.split())
        return "\n".join(out)

    # --- querying ----------------------------------------------------------------------------------------------
    @property
    def embedder(self) -> Embedder:
        return get_embedder(self.embedder_kind)

    def search(self, query: str, mode: Mode = "hybrid", k: int = 10, offset: int = 0) -> SearchResult:
        started = time.perf_counter()
        terms = analyze(query)
        if not self.chunks or not query.strip():
            return SearchResult(query, mode, [], 0, terms)

        bm25_pages: list[tuple[int, int, float]] = []
        semantic_pages: list[tuple[int, int, float]] = []
        if mode in ("bm25", "hybrid"):
            bm25_pages = _page_ranking(self.chunks, self.bm25.scores(terms), positive_only=True)
        if mode in ("semantic", "hybrid"):
            sims = (self.vectors @ self.embedder.embed_query(query)).astype(np.float64)
            semantic_pages = _page_ranking(self.chunks, sims, positive_only=False)[:SEMANTIC_DEPTH]

        bm25_rank = {page: (r, idx) for r, (page, idx, _) in enumerate(bm25_pages, start=1)}
        sem_rank = {page: (r, idx) for r, (page, idx, _) in enumerate(semantic_pages, start=1)}

        if mode == "bm25":
            scored = [(page, idx, score) for page, idx, score in bm25_pages]
        elif mode == "semantic":
            scored = [(page, idx, score) for page, idx, score in semantic_pages]
        else:
            rrf_k = settings.SEARCH["RRF_K"]
            fused: dict[int, float] = {}
            for ranking in (bm25_rank, sem_rank):
                for page, (rank, _) in ranking.items():
                    fused[page] = fused.get(page, 0.0) + 1.0 / (rrf_k + rank)
            scored = []
            for page, score in fused.items():
                # Show the passage BM25 matched when there is one: it contains the query words to highlight.
                idx = bm25_rank[page][1] if page in bm25_rank else sem_rank[page][1]
                scored.append((page, idx, score))
            scored.sort(key=lambda item: (-item[2], item[0]))

        hits = []
        for page, idx, score in scored[offset : offset + k]:
            chunk = self.chunks[idx]
            hits.append(
                Hit(
                    page_id=page,
                    url=chunk.url,
                    title=chunk.title,
                    score=score,
                    passage=chunk,
                    bm25_rank=bm25_rank[page][0] if page in bm25_rank else None,
                    semantic_rank=sem_rank[page][0] if page in sem_rank else None,
                )
            )
        elapsed = (time.perf_counter() - started) * 1000
        return SearchResult(query, mode, hits, len(scored), terms, elapsed)


_loaded: dict[str, tuple[float, SearchIndex]] = {}


def index_dir() -> Path:
    return Path(settings.SEARCH["INDEX_DIR"])


def get_index() -> SearchIndex | None:
    """Load the index from disk, reloading it when it has been rebuilt. Returns None before the first build."""
    directory = index_dir()
    meta = directory / "meta.json"
    if not meta.exists():
        return None
    mtime = meta.stat().st_mtime
    key = str(directory)
    cached = _loaded.get(key)
    if cached is None or cached[0] != mtime:
        _loaded[key] = (mtime, SearchIndex.load(directory))
    return _loaded[key][1]
