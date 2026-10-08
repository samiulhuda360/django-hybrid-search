from search.index import SearchIndex
from search.snippets import highlight, make_snippet
from search.suggest import did_you_mean, suggest
from search.text import analyze


def test_highlight_marks_stemmed_matches() -> None:
    html = str(highlight("Rolling back releases is safe", set(analyze("roll back release"))))
    assert html == "<mark>Rolling</mark> <mark>back</mark> <mark>releases</mark> is safe"


def test_highlight_escapes_page_text() -> None:
    html = str(highlight('<script>alert("x")</script> deploy', {"deploy"}))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert html.endswith("<mark>deploy</mark>")


def test_highlight_ignores_stopwords() -> None:
    assert "<mark>" not in str(highlight("the and of", {"the", "and"}))


def test_snippet_picks_window_with_query_words() -> None:
    text = " ".join(["filler"] * 60) + " the CNAME record points to your app " + " ".join(["tail"] * 60)
    snippet = str(make_snippet(text, set(analyze("CNAME record")), window=12))
    assert "<mark>CNAME</mark> <mark>record</mark>" in snippet
    assert snippet.startswith("… ") and snippet.endswith(" …")


def test_snippet_of_short_text_has_no_ellipsis() -> None:
    assert str(make_snippet("Short text.", {"short"})) == "<mark>Short</mark> text."


def test_suggest_completes_last_word(small_index: SearchIndex) -> None:
    suggestions = suggest("custom do", small_index)
    assert "custom domains" in suggestions or "custom domain" in suggestions


def test_suggest_includes_past_queries_and_titles(small_index: SearchIndex) -> None:
    suggestions = suggest("roll", small_index, past_queries=["roll back a deploy"])
    assert suggestions[0] == "roll back a deploy"
    assert "roll back a release" in suggestions


def test_suggest_empty_prefix(small_index: SearchIndex) -> None:
    assert suggest("  ", small_index) == []


def test_did_you_mean_fixes_misspelling(small_index: SearchIndex) -> None:
    assert did_you_mean("databse backup", small_index) == "database backup"
    assert did_you_mean("database backup", small_index) is None
