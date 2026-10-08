import math

import numpy as np
import pytest

from search.bm25 import BM25
from search.text import analyze, split_passages, stem


def test_analyze_stems_and_drops_stopwords() -> None:
    assert analyze("How do I roll back the deploys?") == ["roll", "back", "deploy"]
    assert stem("Deploying") == stem("deployed") == "deploy"


def test_split_passages_keeps_headings_and_size_limit() -> None:
    body = "Intro text.\n\n## Setup\n\n" + " ".join(["word"] * 80) + "\n\n" + " ".join(["more"] * 80)
    passages = split_passages(body, max_words=120, min_words=0)
    assert [p.heading for p in passages] == ["", "Setup", "Setup"]
    assert passages[0].text == "Intro text."


def test_split_passages_folds_short_intro_into_next_section() -> None:
    passages = split_passages("Intro text.\n\n## Setup\n\nRun the installer.\n\n## Usage\n\n" + "x " * 30)
    assert passages[0].heading == ""
    assert passages[0].text.startswith("Intro text. Setup: Run the installer.")


def test_bm25_matches_hand_calculation() -> None:
    docs = [["roll", "back"], ["domain", "dns", "dns"], ["log"]]
    bm25 = BM25(docs, k1=1.2, b=0.75)
    scores = bm25.scores(["dns"])
    idf = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))
    avgdl = (2 + 3 + 1) / 3
    expected = idf * 2 * 2.2 / (2 + 1.2 * (1 - 0.75 + 0.75 * 3 / avgdl))
    assert scores[1] == pytest.approx(expected)
    assert scores[0] == scores[2] == 0


def test_bm25_rare_terms_weigh_more() -> None:
    bm25 = BM25([["deploy", "rollback"], ["deploy"], ["deploy"]])
    assert bm25.idf["rollback"] > bm25.idf["deploy"] > 0
    assert int(np.argmax(bm25.scores(["deploy", "rollback"]))) == 0


def test_bm25_empty_index() -> None:
    assert BM25([]).scores(["x"]).shape == (0,)
