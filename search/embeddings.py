"""Sentence embeddings for semantic search.

The default embedder runs BAAI/bge-small-en-v1.5 through fastembed (ONNX Runtime on the CPU, no PyTorch). The
hashing embedder needs no model download; the tests and CI use it so they stay fast and offline.
"""

from __future__ import annotations

import os
import zlib
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from django.conf import settings

from .text import analyze

Matrix = npt.NDArray[np.float32]


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> Matrix: ...

    def embed_query(self, text: str) -> Matrix: ...


def _normalise(matrix: Matrix) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    result: Matrix = (matrix / norms).astype(np.float32)
    return result


class HashingEmbedder:
    """Feature hashing of stemmed words and character trigrams into a fixed-size unit vector.

    It catches spelling variants and shared word stems, not meaning. It is a stand-in for tests, not a model.
    """

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"hash-{dim}"

    def _vector(self, text: str) -> npt.NDArray[np.float32]:
        vec = np.zeros(self.dim, dtype=np.float32)
        for term in analyze(text):
            vec[zlib.crc32(term.encode()) % self.dim] += 1.0
            padded = f"#{term}#"
            for i in range(len(padded) - 2):
                vec[zlib.crc32(padded[i : i + 3].encode()) % self.dim] += 0.3
        return vec

    def embed_documents(self, texts: list[str]) -> Matrix:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalise(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> Matrix:
        vector: Matrix = self.embed_documents([text])[0]
        return vector


class FastEmbedEmbedder:
    """A small sentence-embedding model run locally with ONNX Runtime."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.name = model_name
        self.cache_dir = cache_dir
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from fastembed import TextEmbedding

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(self.name, cache_dir=str(self.cache_dir))
        return self._model

    def embed_documents(self, texts: list[str]) -> Matrix:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        return _normalise(np.stack(list(self._load().passage_embed(texts))).astype(np.float32))

    def embed_query(self, text: str) -> Matrix:
        vector: Matrix = _normalise(np.stack(list(self._load().query_embed([text]))).astype(np.float32))[0]
        return vector


_cache: dict[str, Embedder] = {}


def get_embedder(kind: str | None = None) -> Embedder:
    """Return the configured embedder (one shared instance per kind)."""
    conf = settings.SEARCH
    kind = kind or conf["EMBEDDER"]
    if kind not in _cache:
        if kind == "hash":
            _cache[kind] = HashingEmbedder()
        elif kind == "fastembed":
            _cache[kind] = FastEmbedEmbedder(conf["EMBED_MODEL"], conf["MODEL_CACHE_DIR"])
        else:
            raise ValueError(f"Unknown embedder {kind!r}; use 'fastembed' or 'hash'")
    return _cache[kind]
