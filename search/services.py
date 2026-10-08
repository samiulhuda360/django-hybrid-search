"""Glue between the crawler, the database and the index."""

from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .crawler import CrawlConfig, Crawler, CrawlEvent, Outcome
from .index import SearchIndex, SourcePage, index_dir
from .models import CrawlJob, Page

log = logging.getLogger(__name__)


def run_crawl_job(job: CrawlJob) -> CrawlJob:
    """Crawl the job's site, store every page outcome, and optionally rebuild the index."""
    job.status = CrawlJob.Status.RUNNING
    job.started_at = timezone.now()
    job.finished_at = None
    job.pages_indexed = job.pages_skipped = job.pages_failed = 0
    job.log = ""
    job.save()
    lines: list[str] = []

    def on_event(event: CrawlEvent) -> None:
        page = event.page
        Page.objects.update_or_create(
            url=event.url,
            defaults={
                "job": job,
                "title": (page.title if page else "")[:300],
                "text": page.text if page and event.outcome is Outcome.INDEXED else "",
                "content_hash": event.content_hash,
                "http_status": event.status,
                "outcome": event.outcome.value,
                "detail": event.detail[:200],
            },
        )
        lines.append(f"{event.outcome.value:<18} {event.status or '-':<4} {event.url}")
        if event.outcome is Outcome.INDEXED:
            job.pages_indexed += 1
        elif event.outcome in (Outcome.HTTP_ERROR, Outcome.ERROR):
            job.pages_failed += 1
        else:
            job.pages_skipped += 1
        if len(lines) % 10 == 0:
            job.log = "\n".join(lines)
            job.save(update_fields=["pages_indexed", "pages_skipped", "pages_failed", "log"])

    config = CrawlConfig(
        seed_url=job.seed_url,
        max_pages=job.max_pages,
        delay=job.delay_seconds,
        use_sitemap=job.use_sitemap,
        path_prefix=job.path_prefix,
        user_agent=settings.SEARCH["USER_AGENT"],
    )
    try:
        stats = Crawler(config).run(on_event)
        lines.append(
            f"\nDone: {stats.fetched} fetched, {stats.indexed} indexed, {stats.skipped} skipped, "
            f"{stats.failed} failed. Sitemap URLs: {stats.sitemap_urls}. Delay between requests: "
            f"{stats.effective_delay:.2f}s."
        )
        if job.rebuild_index:
            built = build_index()
            lines.append(f"Index rebuilt: {built.page_count} pages, {len(built.chunks)} passages.")
        job.status = CrawlJob.Status.DONE
    except Exception as exc:
        log.exception("Crawl job %s failed", job.pk)
        lines.append(f"\nFailed: {type(exc).__name__}: {exc}")
        job.status = CrawlJob.Status.FAILED
    job.log = "\n".join(lines)
    job.finished_at = timezone.now()
    job.save()
    return job


def build_index(embedder_kind: str | None = None) -> SearchIndex:
    """Index every page the crawler stored as indexed, and save the index to disk."""
    pages = [
        SourcePage(p.pk, p.url, p.title, p.text)
        for p in Page.objects.filter(outcome=Page.Outcome.INDEXED).exclude(text="").order_by("pk")
    ]
    index = SearchIndex.build(pages, embedder_kind)
    index.save(index_dir())
    return index


def start_job_in_background(job_id: int) -> threading.Thread:
    """Run a crawl job on a background thread (used by the admin "Run" action)."""

    def target() -> None:
        close_old_connections()
        try:
            run_crawl_job(CrawlJob.objects.get(pk=job_id))
        finally:
            close_old_connections()

    thread = threading.Thread(target=target, name=f"crawl-job-{job_id}", daemon=True)
    thread.start()
    return thread
