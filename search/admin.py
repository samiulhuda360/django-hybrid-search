"""Django admin: create crawl jobs, run them, inspect pages and rebuild the index."""

from __future__ import annotations

from django.contrib import admin, messages
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from . import services
from .models import CrawlJob, Page, QueryLog


@admin.register(CrawlJob)
class CrawlJobAdmin(admin.ModelAdmin):
    list_display = ("name", "seed_url", "status_badge", "pages_indexed", "pages_skipped", "pages_failed", "finished_at")
    list_filter = ("status",)
    search_fields = ("name", "seed_url")
    readonly_fields = (
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "pages_indexed",
        "pages_skipped",
        "pages_failed",
        "log",
    )
    fieldsets = (
        (None, {"fields": ("name", "seed_url", "path_prefix")}),
        ("Politeness and limits", {"fields": ("max_pages", "delay_seconds", "use_sitemap", "rebuild_index")}),
        ("Last run", {"fields": readonly_fields}),
    )
    actions = ("run_jobs", "rebuild_index")
    formfield_overrides = {models.URLField: {"assume_scheme": "https"}}  # noqa: RUF012 - Django admin API

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj: CrawlJob) -> str:
        colour = {"pending": "#6b6b5e", "running": "#a86a00", "done": "#1f6f5b", "failed": "#b3261e"}[obj.status]
        return format_html('<strong style="color:{}">{}</strong>', colour, obj.get_status_display())

    @admin.action(description="Run selected crawl jobs now (in the background)")
    def run_jobs(self, request: HttpRequest, queryset: QuerySet[CrawlJob]) -> None:
        started = 0
        for job in queryset:
            if job.status == CrawlJob.Status.RUNNING:
                self.message_user(request, f"{job.name} is already running.", messages.WARNING)
                continue
            job.status = CrawlJob.Status.RUNNING
            job.save(update_fields=["status"])
            services.start_job_in_background(job.pk)
            started += 1
        if started:
            self.message_user(request, f"Started {started} crawl job(s). Refresh this page to follow progress.")

    @admin.action(description="Rebuild the search index from stored pages")
    def rebuild_index(self, request: HttpRequest, queryset: QuerySet[CrawlJob]) -> None:
        index = services.build_index()
        self.message_user(request, f"Index rebuilt: {index.page_count} pages, {len(index.chunks)} passages.")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title_or_url", "outcome", "http_status", "words", "job", "fetched_at")
    list_filter = ("outcome", "job")
    search_fields = ("url", "title", "text")
    readonly_fields = ("url", "title", "text", "content_hash", "http_status", "outcome", "detail", "job", "fetched_at")

    @admin.display(description="Page")
    def title_or_url(self, obj: Page) -> str:
        return format_html('{}<br><small><a href="{}">{}</a></small>', obj.title or "-", obj.url, obj.url)

    @admin.display(description="Words")
    def words(self, obj: Page) -> int:
        return obj.word_count

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False


@admin.register(QueryLog)
class QueryLogAdmin(admin.ModelAdmin):
    list_display = ("query", "mode", "results", "created_at")
    list_filter = ("mode",)
    search_fields = ("query",)
