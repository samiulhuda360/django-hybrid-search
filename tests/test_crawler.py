from __future__ import annotations

from search.crawler import (
    CrawlConfig,
    Crawler,
    CrawlEvent,
    Outcome,
    normalise_url,
    parse_crawl_delay,
    parse_html,
)


def crawl(base: str, **kwargs: object) -> tuple[list[CrawlEvent], list[float], Crawler]:
    events: list[CrawlEvent] = []
    sleeps: list[float] = []
    now = [0.0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    config = CrawlConfig(seed_url=f"{base}/index.html", delay=0.1, user_agent="TestBot/1.0", **kwargs)  # type: ignore[arg-type]
    crawler = Crawler(config, sleep=fake_sleep, clock=lambda: now[0])
    crawler.run(events.append)
    return events, sleeps, crawler


def by_path(events: list[CrawlEvent], base: str) -> dict[str, Outcome]:
    return {e.url.removeprefix(base): e.outcome for e in events}


def test_crawler_respects_robots_sitemap_and_links(test_site: str) -> None:
    events, _, _ = crawl(test_site)
    outcomes = by_path(events, test_site)
    assert outcomes["/index.html"] is Outcome.HUB  # mostly links: followed, not indexed
    assert outcomes["/docs/a.html"] is Outcome.INDEXED  # from the sitemap
    assert outcomes["/docs/b.html"] is Outcome.INDEXED  # only in the sitemap
    assert outcomes["/docs/c.html"] is Outcome.INDEXED  # from a link, fragment removed
    assert outcomes["/private/secret.html"] is Outcome.BLOCKED
    assert outcomes["/notes.txt"] is Outcome.NOT_HTML
    assert outcomes["/docs/hidden.html"] is Outcome.NOINDEX
    assert outcomes["/docs/copy.html"] is Outcome.DUPLICATE  # query string removed, same text as A
    assert outcomes["/missing.html"] is Outcome.HTTP_ERROR
    assert "/docs/skip.html" not in outcomes  # rel=nofollow
    assert not any("elsewhere.example" in e.url for e in events)  # stays on the host


def test_blocked_pages_are_never_requested(test_site: str) -> None:
    events, _, crawler = crawl(test_site)
    blocked = [e for e in events if e.outcome is Outcome.BLOCKED]
    assert blocked and all(e.status is None for e in blocked)
    assert not crawler.allowed(f"{test_site}/private/secret.html")


def test_crawl_delay_from_robots_spaces_requests(test_site: str) -> None:
    _, sleeps, crawler = crawl(test_site)
    assert crawler.delay == 0.5  # robots.txt Crawl-delay beats the job's 0.1 s
    assert sleeps and all(abs(s - 0.5) < 1e-9 for s in sleeps)


def test_max_pages_limits_fetches(test_site: str) -> None:
    events, _, _ = crawl(test_site, max_pages=2)
    fetched = [e for e in events if e.outcome is not Outcome.BLOCKED]
    assert len(fetched) == 2


def test_without_sitemap_unlinked_pages_are_missed(test_site: str) -> None:
    events, _, _ = crawl(test_site, use_sitemap=False)
    assert "/docs/b.html" not in by_path(events, test_site)


def test_path_prefix_limits_scope(test_site: str) -> None:
    events, _, _ = crawl(test_site, path_prefix="/docs/")
    assert all(e.url.startswith(f"{test_site}/docs/") for e in events)


def test_indexed_text_excludes_page_chrome(test_site: str) -> None:
    events, _, _ = crawl(test_site)
    page_a = next(e for e in events if e.url.endswith("/docs/a.html"))
    assert page_a.page is not None
    assert page_a.page.title == "Page A"
    assert page_a.page.text == "## Section\n\nAlpha content about rollbacks."


def test_parse_crawl_delay_variants() -> None:
    robots = "User-agent: TestBot\nCrawl-delay: 3\n\nUser-agent: *\nDisallow: /x\nCrawl-delay: 0.5\n"
    assert parse_crawl_delay(robots, "TestBot/2.0") == 3.0
    assert parse_crawl_delay(robots, "OtherBot/1.0") == 0.5
    assert parse_crawl_delay("User-agent: *\nDisallow:\n", "Bot") is None


def test_normalise_url() -> None:
    assert normalise_url("HTTP://Example.COM/a.html?x=1#top") == "http://example.com/a.html"
    assert normalise_url("http://example.com") == "http://example.com/"


def test_link_ratio_measures_navigation_pages() -> None:
    hub = parse_html(
        '<main><p>Pages:</p><ul><li><a href="/a">Alpha page</a></li><li><a href="/b">Beta</a></li></ul></main>',
        "http://x/",
    )
    assert hub.link_ratio == 0.75
    article = parse_html(
        "<main><p>A long paragraph of real content with one <a href='/a'>link</a>.</p></main>", "http://x/"
    )
    assert article.link_ratio < 0.2


def test_parse_html_meta_nofollow_blocks_links() -> None:
    html = '<html><head><meta name="robots" content="nofollow"></head><body><p>Hi</p><a href="/x">x</a></body></html>'
    page = parse_html(html, "http://example.com/")
    assert page.links == [] and not page.noindex
