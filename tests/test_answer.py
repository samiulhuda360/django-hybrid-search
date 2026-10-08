from __future__ import annotations

from pathlib import Path

from search.answer import NOT_FOUND, DiskCache, RateLimiter, answer_question, clean_citations
from search.index import SearchIndex


class FakeClient:
    def __init__(self, reply: str = "Run acme rollback to go back [1]. Old images restart [1][7].") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.reply


class FailingClient:
    def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        raise TimeoutError("network down")


class NoWaitLimiter(RateLimiter):
    def __init__(self) -> None:
        super().__init__(0)


def hits(index: SearchIndex, query: str) -> list:  # type: ignore[type-arg]
    return index.search(query, "hybrid", k=4).hits


def test_without_key_returns_cited_extractive_answer(small_index: SearchIndex) -> None:
    answer = answer_question("how do I roll back a release", hits(small_index, "roll back a release"))
    assert answer.mode == "extractive"
    assert "acme rollback" in answer.text
    assert "[1]" in answer.text and answer.cited == [1]
    assert answer.sources[0].title == "Roll back a release"


def test_ai_answer_removes_invalid_citations(small_index: SearchIndex, tmp_path: Path) -> None:
    client = FakeClient()
    answer = answer_question(
        "undo a release",
        hits(small_index, "undo a release"),
        client=client,
        limiter=NoWaitLimiter(),
        cache=DiskCache(tmp_path),
    )
    assert answer.mode == "ai"
    assert "[7]" not in answer.text
    assert answer.cited == [1]
    prompt = client.calls[0][1]["content"]
    assert "[1] Roll back a release" in prompt


def test_ai_answers_are_cached_on_disk(small_index: SearchIndex, tmp_path: Path) -> None:
    client = FakeClient()
    found = hits(small_index, "rollback")
    kwargs = {"client": client, "limiter": NoWaitLimiter(), "cache": DiskCache(tmp_path)}
    first = answer_question("rollback", found, **kwargs)  # type: ignore[arg-type]
    second = answer_question("rollback", found, **kwargs)  # type: ignore[arg-type]
    assert len(client.calls) == 1
    assert not first.cached and second.cached
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_uncited_ai_answer_falls_back(small_index: SearchIndex, tmp_path: Path) -> None:
    answer = answer_question(
        "rollback release",
        hits(small_index, "rollback release"),
        client=FakeClient("Just roll it back."),
        limiter=NoWaitLimiter(),
        cache=DiskCache(tmp_path),
    )
    assert answer.mode == "extractive"
    assert "cited no source" in answer.note


def test_api_failure_falls_back(small_index: SearchIndex, tmp_path: Path) -> None:
    answer = answer_question(
        "rollback release",
        hits(small_index, "rollback release"),
        client=FailingClient(),
        limiter=NoWaitLimiter(),
        cache=DiskCache(tmp_path),
    )
    assert answer.mode == "extractive"
    assert "unavailable" in answer.note


def test_model_can_say_not_found(small_index: SearchIndex, tmp_path: Path) -> None:
    answer = answer_question(
        "pizza recipe",
        hits(small_index, "rollback"),
        client=FakeClient(NOT_FOUND),
        limiter=NoWaitLimiter(),
        cache=DiskCache(tmp_path),
    )
    assert answer.text == NOT_FOUND


def test_no_hits_means_no_answer() -> None:
    assert answer_question("anything", []).mode == "none"


def test_rate_limiter_spaces_calls() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2.5, clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    now[0] += 1.0
    limiter.wait()
    limiter.wait()
    assert slept == [1.5, 2.5]


def test_clean_citations() -> None:
    assert clean_citations("A [1]. B [3]. C [2] [9].", 2) == ("A [1]. B. C [2].", [1, 2])
