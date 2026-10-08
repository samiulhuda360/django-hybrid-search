"""Shared fixtures. Tests never download a model or call an AI service."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from django.conf import LazySettings

from search import sample_site
from search.index import SearchIndex, SourcePage

DOCS = [
    SourcePage(
        1,
        "http://docs.test/docs/rollbacks.html",
        "Roll back a release",
        "Every successful deploy creates a release.\n\n## Rolling back\n\nRun acme rollback to return to the "
        "previous release. The old image starts again without a new build.",
    ),
    SourcePage(
        2,
        "http://docs.test/docs/custom-domains.html",
        "Custom domains",
        "Serve your app from your own domain name.\n\n## DNS records\n\nCreate a CNAME record pointing to your "
        "app address. DNS changes can take up to 48 hours.",
    ),
    SourcePage(
        3,
        "http://docs.test/docs/logs.html",
        "Logs",
        "Anything your app prints is collected as logs.\n\n## Retention\n\nLogs are kept for 7 days on the "
        "Starter plan. A log drain forwards every line to another service.",
    ),
    SourcePage(
        4,
        "http://docs.test/docs/backups.html",
        "Database backups",
        "A full backup is taken every day.\n\n## Point-in-time recovery\n\nRestore the database to any minute, "
        "for example after an accidental delete or a bad migration.",
    ),
]


@pytest.fixture(autouse=True)
def isolated_settings(settings: LazySettings, tmp_path: Path) -> LazySettings:
    settings.SEARCH = {**settings.SEARCH, "INDEX_DIR": tmp_path / "index", "EMBEDDER": "hash"}
    settings.AI = {**settings.AI, "API_KEY": "", "CACHE_DIR": tmp_path / "llm-cache", "MIN_INTERVAL_SECONDS": 2.5}
    return settings


@pytest.fixture
def small_index() -> SearchIndex:
    return SearchIndex.build(DOCS, "hash")


@pytest.fixture
def saved_index(small_index: SearchIndex, settings: LazySettings) -> SearchIndex:
    small_index.save(Path(settings.SEARCH["INDEX_DIR"]))
    return small_index


ROBOTS = """User-agent: *
Disallow: /private/
Crawl-delay: 0.5

Sitemap: {base}/sitemap.xml
"""

PAGE = """<!doctype html><html><head><title>{title} - Test docs</title>{meta}</head><body>
<header><a href="/">Home</a></header>
<nav><a href="/docs/a.html">A</a></nav>
<main><h1>{title}</h1><h2>Section</h2><p>{body}</p>{links}</main>
<footer>Footer text that must not be indexed</footer>
<script>var tracking = "must not be indexed";</script>
</body></html>"""


def write_site(root: Path, base: str) -> None:
    def page(path: str, title: str, body: str, links: str = "", meta: str = "") -> None:
        target = root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(PAGE.format(title=title, body=body, links=links, meta=meta), encoding="utf-8")

    (root / "robots.txt").write_text(ROBOTS.format(base=base), encoding="utf-8")
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{base}/docs/a.html</loc></url><url><loc>{base}/docs/b.html</loc></url>"
        "<url><loc>https://elsewhere.example/off-site.html</loc></url></urlset>",
        encoding="utf-8",
    )
    page(
        "/index.html",
        "Home",
        "Index.",
        links='<a href="/docs/c.html#part">C</a> <a href="/private/secret.html">Private</a> '
        '<a href="/notes.txt">Notes</a> <a href="https://elsewhere.example/">Elsewhere</a> '
        '<a href="/docs/hidden.html">Hidden</a> <a href="/docs/copy.html?ref=1">Copy</a> '
        '<a href="/missing.html">Missing</a> <a href="/docs/skip.html" rel="nofollow">Skip</a>',
    )
    page("/docs/a.html", "Page A", "Alpha content about rollbacks.")
    page("/docs/b.html", "Page B", "Bravo content about domains.")
    page("/docs/c.html", "Page C", "Charlie content about logs.")
    page("/docs/copy.html", "Page A", "Alpha content about rollbacks.")  # same text as A
    page("/docs/hidden.html", "Hidden", "Draft page.", meta='<meta name="robots" content="noindex">')
    page("/docs/skip.html", "Skip", "Only linked with rel=nofollow.")
    page("/private/secret.html", "Secret", "Robots.txt forbids this page.")
    (root / "notes.txt").write_text("plain text file", encoding="utf-8")


@pytest.fixture
def test_site(tmp_path: Path) -> Iterator[str]:
    """A tiny static website on a random local port. Yields its base URL."""
    root = tmp_path / "site"
    root.mkdir()
    server = sample_site.start(0, root)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    write_site(root, base)
    try:
        yield base
    finally:
        server.shutdown()
        server.server_close()
