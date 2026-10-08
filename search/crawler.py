"""A polite, single-site web crawler.

Politeness rules:

* robots.txt is read first. Disallowed URLs are never requested, and its Crawl-delay is honoured.
* Requests to the site are spaced at least ``delay`` seconds apart (the larger of the job's delay and Crawl-delay).
* Sitemaps (from robots.txt, or /sitemap.xml) seed the queue; links found on pages are followed too.
* The crawler stays on the seed's host and path prefix, identifies itself with a User-Agent, and stops at
  ``max_pages`` fetches.
* Pages with <meta name="robots" content="noindex"> are not indexed; "nofollow" stops link discovery.

Navigation hubs (pages whose text is mostly link text, such as a table of contents) are followed but not indexed,
because they match almost every query without answering any.
"""

from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag
from defusedxml.ElementTree import fromstring as parse_xml

log = logging.getLogger(__name__)

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "template")
BLOCK_TAGS = ("h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote", "td", "dd", "dt")


class Outcome(StrEnum):
    INDEXED = "indexed"
    BLOCKED = "blocked_by_robots"
    NOT_HTML = "not_html"
    HTTP_ERROR = "http_error"
    DUPLICATE = "duplicate"
    NOINDEX = "noindex"
    HUB = "link_hub"
    ERROR = "error"


@dataclass
class CrawlConfig:
    seed_url: str
    max_pages: int = 100
    delay: float = 1.0
    use_sitemap: bool = True
    path_prefix: str = ""
    user_agent: str = "HybridSearchBot/1.0"
    timeout: float = 10.0
    max_bytes: int = 2_000_000
    max_link_ratio: float = 0.6


@dataclass
class ParsedPage:
    title: str
    text: str
    links: list[str]
    noindex: bool = False
    link_ratio: float = 0.0


@dataclass
class CrawlEvent:
    url: str
    outcome: Outcome
    status: int | None = None
    page: ParsedPage | None = None
    detail: str = ""
    content_hash: str = ""


@dataclass
class CrawlStats:
    fetched: int = 0
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    sitemap_urls: int = 0
    effective_delay: float = 0.0
    outcomes: dict[str, int] = field(default_factory=dict)


def parse_crawl_delay(robots_txt: str, user_agent: str) -> float | None:
    """Read Crawl-delay for this user agent (or "*"). Unlike urllib's parser this accepts decimals like 0.5."""
    token = user_agent.split("/")[0].strip().lower()
    delays: dict[str, float] = {}
    agents: list[str] = []
    in_rules = False
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
        else:
            in_rules = True
            if key == "crawl-delay":
                try:
                    delay = float(value)
                except ValueError:
                    continue
                for agent in agents:
                    delays[agent] = delay
    for agent, delay in delays.items():
        if agent != "*" and agent in token:
            return delay
    return delays.get("*")


def normalise_url(url: str) -> str:
    """Drop the fragment and query string, and lower-case the scheme and host."""
    url, _ = urldefrag(url)
    parts = urlsplit(url)
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def parse_html(html: str, base_url: str) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    robots_meta = soup.find("meta", attrs={"name": "robots"})
    directives = str(robots_meta.get("content", "")).lower() if isinstance(robots_meta, Tag) else ""
    links: list[str] = []
    if "nofollow" not in directives:
        for a in soup.find_all("a", href=True):
            if not isinstance(a, Tag) or "nofollow" in (a.get("rel") or []):
                continue
            href = str(a["href"]).strip()
            if href and not href.startswith(("mailto:", "javascript:", "tel:")):
                links.append(urljoin(base_url, href))

    h1 = soup.find("h1")
    title_tag = soup.find("title")
    title = (h1.get_text(" ", strip=True) if h1 else "") or (title_tag.get_text(" ", strip=True) if title_tag else "")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    all_words = len(root.get_text(" ", strip=True).split())
    link_words = sum(len(a.get_text(" ", strip=True).split()) for a in root.find_all("a"))
    blocks: list[str] = []
    for el in root.find_all(BLOCK_TAGS):
        if not isinstance(el, Tag) or el.find(BLOCK_TAGS):
            continue  # take the innermost block only, so nested lists are not repeated
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text:
            continue
        if el.name in ("h2", "h3", "h4"):
            blocks.append(f"## {text}")
        elif el.name != "h1":
            blocks.append(text)
    return ParsedPage(
        title=title or base_url,
        text="\n\n".join(blocks),
        links=links,
        noindex="noindex" in directives,
        link_ratio=link_words / all_words if all_words else 0.0,
    )


class Crawler:
    def __init__(
        self,
        config: CrawlConfig,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = config.user_agent
        self.sleep = sleep
        self.clock = clock
        seed = urlsplit(config.seed_url)
        self.scheme_host = f"{seed.scheme}://{seed.netloc}"
        self.host = seed.netloc.lower()
        self.prefix = config.path_prefix or "/"
        self.robots = RobotFileParser()
        self.delay = config.delay
        self._last_request: float | None = None

    # --- politeness --------------------------------------------------------------------------------------------
    def _wait_turn(self) -> None:
        if self._last_request is not None:
            wait = self.delay - (self.clock() - self._last_request)
            if wait > 0:
                self.sleep(wait)
        self._last_request = self.clock()

    def _get(self, url: str) -> requests.Response:
        self._wait_turn()
        return self.session.get(url, timeout=self.config.timeout, allow_redirects=True)

    def _load_robots(self) -> list[str]:
        url = f"{self.scheme_host}/robots.txt"
        try:
            resp = self._get(url)
        except requests.RequestException as exc:
            log.warning("robots.txt unreachable (%s); crawling with default rules", exc)
            self.robots.parse([])
            return []
        if resp.status_code in (401, 403):
            self.robots.parse(["User-agent: *", "Disallow: /"])  # the site refuses robots entirely
            return []
        if resp.status_code >= 400:
            self.robots.parse([])  # no robots.txt means everything is allowed
            return []
        self.robots.parse(resp.text.splitlines())
        crawl_delay = parse_crawl_delay(resp.text, self.config.user_agent)
        if crawl_delay is not None:
            self.delay = max(self.delay, float(crawl_delay))
        return list(self.robots.site_maps() or [])

    def allowed(self, url: str) -> bool:
        return self.robots.can_fetch(self.config.user_agent, url)

    def in_scope(self, url: str) -> bool:
        parts = urlsplit(url)
        return (
            parts.scheme in ("http", "https")
            and parts.netloc.lower() == self.host
            and parts.path.startswith(self.prefix)
        )

    # --- sitemaps ----------------------------------------------------------------------------------------------
    def _sitemap_urls(self, sitemap_url: str, depth: int = 0) -> list[str]:
        if depth > 2 or urlsplit(sitemap_url).netloc.lower() != self.host:
            return []
        try:
            resp = self._get(sitemap_url)
            if resp.status_code >= 400:
                return []
            root = parse_xml(resp.content)  # defusedxml refuses entity-expansion attacks
        except (requests.RequestException, ET.ParseError) as exc:
            log.warning("Skipping sitemap %s: %s", sitemap_url, exc)
            return []
        urls: list[str] = []
        if root.tag == f"{SITEMAP_NS}sitemapindex":
            for loc in root.iter(f"{SITEMAP_NS}loc"):
                if loc.text:
                    urls.extend(self._sitemap_urls(loc.text.strip(), depth + 1))
        else:
            urls.extend(loc.text.strip() for loc in root.iter(f"{SITEMAP_NS}loc") if loc.text)
        return urls

    # --- main loop ---------------------------------------------------------------------------------------------
    def run(self, on_event: Callable[[CrawlEvent], None]) -> CrawlStats:
        stats = CrawlStats()
        sitemaps = self._load_robots()
        stats.effective_delay = self.delay
        queue: deque[str] = deque([normalise_url(self.config.seed_url)])
        if self.config.use_sitemap:
            for sm in sitemaps or [f"{self.scheme_host}/sitemap.xml"]:
                found = self._sitemap_urls(sm)
                stats.sitemap_urls += len(found)
                queue.extend(normalise_url(u) for u in found)
        seen: set[str] = set()
        hashes: set[str] = set()

        def emit(event: CrawlEvent) -> None:
            stats.outcomes[event.outcome.value] = stats.outcomes.get(event.outcome.value, 0) + 1
            if event.outcome is Outcome.INDEXED:
                stats.indexed += 1
            elif event.outcome in (Outcome.HTTP_ERROR, Outcome.ERROR):
                stats.failed += 1
            else:
                stats.skipped += 1
            on_event(event)

        while queue and stats.fetched < self.config.max_pages:
            url = queue.popleft()
            if url in seen or not self.in_scope(url):
                continue
            seen.add(url)
            if not self.allowed(url):
                emit(CrawlEvent(url, Outcome.BLOCKED, detail="disallowed by robots.txt"))
                continue
            try:
                resp = self._get(url)
            except requests.RequestException as exc:
                stats.fetched += 1
                emit(CrawlEvent(url, Outcome.ERROR, detail=type(exc).__name__))
                continue
            stats.fetched += 1
            final_url = normalise_url(resp.url or url)
            seen.add(final_url)
            if resp.status_code >= 400:
                emit(CrawlEvent(url, Outcome.HTTP_ERROR, status=resp.status_code))
                continue
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if ctype not in ("text/html", "application/xhtml+xml"):
                emit(CrawlEvent(url, Outcome.NOT_HTML, status=resp.status_code, detail=ctype or "unknown"))
                continue
            page = parse_html(resp.text[: self.config.max_bytes], final_url)
            for link in page.links:
                normalised = normalise_url(link)
                if normalised not in seen and self.in_scope(normalised):
                    queue.append(normalised)
            digest = hashlib.sha256(page.text.encode()).hexdigest()
            if page.noindex:
                emit(CrawlEvent(final_url, Outcome.NOINDEX, status=resp.status_code))
            elif page.link_ratio > self.config.max_link_ratio:
                emit(CrawlEvent(final_url, Outcome.HUB, status=resp.status_code, detail=f"{page.link_ratio:.0%} links"))
            elif digest in hashes:
                emit(CrawlEvent(final_url, Outcome.DUPLICATE, status=resp.status_code, content_hash=digest))
            else:
                hashes.add(digest)
                emit(CrawlEvent(final_url, Outcome.INDEXED, resp.status_code, page, content_hash=digest))
        return stats
