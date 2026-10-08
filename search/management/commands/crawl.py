"""Create a crawl job and run it: python manage.py crawl http://127.0.0.1:8765/ --max-pages 100"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from search.models import CrawlJob
from search.services import run_crawl_job


class Command(BaseCommand):
    help = "Crawl a website politely (robots.txt, sitemap, rate limit) and rebuild the index."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("seed_url")
        parser.add_argument("--name", default="")
        parser.add_argument("--max-pages", type=int, default=100)
        parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (minimum).")
        parser.add_argument("--prefix", default="", help="Only crawl paths starting with this prefix.")
        parser.add_argument("--no-sitemap", action="store_true")
        parser.add_argument("--no-index", action="store_true", help="Do not rebuild the index afterwards.")

    def handle(self, *args: Any, **opts: Any) -> None:
        job = CrawlJob.objects.create(
            name=opts["name"] or opts["seed_url"],
            seed_url=opts["seed_url"],
            max_pages=opts["max_pages"],
            delay_seconds=opts["delay"],
            path_prefix=opts["prefix"],
            use_sitemap=not opts["no_sitemap"],
            rebuild_index=not opts["no_index"],
        )
        self.stdout.write(f"Crawl job #{job.pk}: {job.seed_url}")
        job = run_crawl_job(job)
        self.stdout.write(job.log)
        style = self.style.SUCCESS if job.status == CrawlJob.Status.DONE else self.style.ERROR
        self.stdout.write(style(f"Status: {job.get_status_display()}"))
