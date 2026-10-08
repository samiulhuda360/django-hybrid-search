"""Database models: crawl jobs, crawled pages and the search log."""

from __future__ import annotations

from django.db import models


class CrawlJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=100)
    seed_url = models.URLField(max_length=500, help_text="Start page; the crawler stays on this host.")
    path_prefix = models.CharField(max_length=200, blank=True, help_text="Only crawl paths starting with this.")
    max_pages = models.PositiveIntegerField(default=100)
    delay_seconds = models.FloatField(default=1.0, help_text="Minimum gap between requests (Crawl-delay may raise it).")
    use_sitemap = models.BooleanField(default=True)
    rebuild_index = models.BooleanField(default=True, help_text="Rebuild the search index when the crawl finishes.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    pages_indexed = models.PositiveIntegerField(default=0)
    pages_skipped = models.PositiveIntegerField(default=0)
    pages_failed = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"


class Page(models.Model):
    class Outcome(models.TextChoices):
        INDEXED = "indexed", "Indexed"
        BLOCKED = "blocked_by_robots", "Blocked by robots.txt"
        NOT_HTML = "not_html", "Not HTML"
        HTTP_ERROR = "http_error", "HTTP error"
        DUPLICATE = "duplicate", "Duplicate content"
        NOINDEX = "noindex", "noindex"
        HUB = "link_hub", "Mostly links (followed, not indexed)"
        ERROR = "error", "Network error"

    job = models.ForeignKey(CrawlJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="pages")
    url = models.URLField(max_length=500, unique=True)
    title = models.CharField(max_length=300, blank=True)
    text = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    detail = models.CharField(max_length=200, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["url"]

    def __str__(self) -> str:
        return self.title or self.url

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class QueryLog(models.Model):
    query = models.CharField(max_length=300)
    mode = models.CharField(max_length=10)
    results = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.query
