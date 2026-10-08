"""Optional AI answers that cite the pages they use.

The top search results are numbered [1]..[n] and sent to an OpenAI-compatible chat endpoint with an instruction
to answer only from them and to cite them. Citations that point at no source are removed; an answer with no
valid citation is replaced by the extractive fallback.

Without an API key (and whenever the call fails) an extractive answer is built instead: the sentences from the
top results that share the most words with the question, each cited.

Calls are cached on disk by a hash of the model and prompt, and spaced at least MIN_INTERVAL_SECONDS apart.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from django.conf import settings

from .index import Hit
from .text import STOPWORDS, analyze

log = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[(\d+)\]")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
NOT_FOUND = "The indexed pages do not answer this question."

SYSTEM_PROMPT = (
    "You answer questions using only the numbered sources provided. "
    "Write two to four plain sentences. After each claim, cite the source it came from as [1], [2] and so on. "
    "Use only source numbers that exist. If the sources do not contain the answer, reply exactly: " + NOT_FOUND
)


@dataclass
class Source:
    n: int
    title: str
    url: str
    text: str


@dataclass
class Answer:
    text: str
    sources: list[Source]
    mode: Literal["ai", "extractive", "none"]
    cited: list[int] = field(default_factory=list)
    cached: bool = False
    note: str = ""


class ChatClient(Protocol):
    def complete(self, model: str, messages: list[dict[str, str]]) -> str: ...


class OpenAICompatibleClient:
    """Thin wrapper over the openai SDK, pointed at any OpenAI-compatible base URL."""

    def __init__(self, api_key: str, base_url: str, timeout: float) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=1)

    def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.1,
            max_tokens=400,
        )
        return (resp.choices[0].message.content or "").strip()


class RateLimiter:
    """Keeps calls at least ``interval`` seconds apart, across threads."""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                remaining = self.interval - (self.clock() - self._last)
                if remaining > 0:
                    self.sleep(remaining)
            self._last = self.clock()


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get(self, key: str) -> str | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        return str(json.loads(path.read_text(encoding="utf-8"))["answer"])

    def set(self, key: str, value: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(json.dumps({"answer": value}), encoding="utf-8")


_limiter: RateLimiter | None = None


def _default_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(settings.AI["MIN_INTERVAL_SECONDS"])
    return _limiter


def _passage_text(hit: Hit) -> str:
    return f"{hit.passage.heading}: {hit.passage.text}" if hit.passage.heading else hit.passage.text


def build_sources(hits: list[Hit], context: Callable[[Hit], str] | None = None, limit: int = 4) -> list[Source]:
    """Number the top hits as sources. ``context`` can widen each source beyond its best passage."""
    expand = context or _passage_text
    return [Source(n=i, title=h.title, url=h.url, text=expand(h)) for i, h in enumerate(hits[:limit], start=1)]


def build_messages(question: str, sources: list[Source]) -> list[dict[str, str]]:
    context = "\n\n".join(f"[{s.n}] {s.title}\n{s.text}" for s in sources)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Sources:\n\n{context}\n\nQuestion: {question}"},
    ]


def clean_citations(text: str, n_sources: int) -> tuple[str, list[int]]:
    """Remove citation markers that point at no source; return the text and the valid source numbers used."""
    cited: list[int] = []

    def repl(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if 1 <= n <= n_sources:
            if n not in cited:
                cited.append(n)
            return match.group(0)
        return ""

    cleaned = CITATION_RE.sub(repl, text)
    return re.sub(r"\s+([.,;])", r"\1", re.sub(r" {2,}", " ", cleaned)).strip(), cited


def extractive_answer(question: str, sources: list[Source], max_sentences: int = 3) -> tuple[str, list[int]]:
    """Pick the source sentences sharing the most question terms, citing each one."""
    q_terms = set(analyze(question))
    scored: list[tuple[float, int, int, str]] = []
    for source in sources:
        for position, sentence in enumerate(SENTENCE_RE.split(source.text.replace("\n", " "))):
            overlap = len(q_terms & set(analyze(sentence)))
            if overlap and len(sentence.split()) >= 5:
                # Prefer more overlap, then higher-ranked sources, then earlier sentences.
                scored.append((overlap - 0.1 * source.n - 0.01 * position, source.n, position, sentence.strip()))
    scored.sort(key=lambda item: -item[0])
    chosen = sorted(scored[:max_sentences], key=lambda item: (item[1], item[2]))
    if not chosen:
        return "", []
    text = " ".join(f"{sentence} [{n}]" for _, n, _, sentence in chosen)
    cited = sorted({n for _, n, _, _ in chosen})
    return text, cited


def answer_question(
    question: str,
    hits: list[Hit],
    context: Callable[[Hit], str] | None = None,
    client: ChatClient | None = None,
    limiter: RateLimiter | None = None,
    cache: DiskCache | None = None,
) -> Answer:
    sources = build_sources(hits, context)
    if not sources or not (set(analyze(question)) - STOPWORDS):
        return Answer(NOT_FOUND, sources, "none")

    conf = settings.AI
    if client is None and conf["API_KEY"]:
        client = OpenAICompatibleClient(conf["API_KEY"], conf["BASE_URL"], conf["TIMEOUT_SECONDS"])

    note = ""
    if client is not None:
        cache = cache or DiskCache(Path(conf["CACHE_DIR"]))
        messages = build_messages(question, sources)
        key = DiskCache.key({"model": conf["MODEL"], "messages": messages})
        raw = cache.get(key)
        cached = raw is not None
        if raw is None:
            try:
                (limiter or _default_limiter()).wait()
                raw = client.complete(conf["MODEL"], messages)
                cache.set(key, raw)
            except Exception as exc:  # noqa: BLE001 - any API failure falls back to the extractive answer
                log.warning("AI answer failed (%s); using the extractive answer", type(exc).__name__)
                note = "The AI service was unavailable, so this answer is quoted from the pages."
                raw = None
        if raw is not None:
            if raw.strip().startswith(NOT_FOUND.rstrip(".")):
                return Answer(NOT_FOUND, sources, "ai", cached=cached)
            text, cited = clean_citations(raw, len(sources))
            if cited:
                return Answer(text, sources, "ai", cited, cached)
            note = "The AI answer cited no source, so this answer is quoted from the pages."

    text, cited = extractive_answer(question, sources)
    if not text:
        return Answer(NOT_FOUND, sources, "none", note=note)
    return Answer(text, sources, "extractive", cited, note=note)
