"""One-command demo: crawl the bundled docs site, build the index and start the web app."""

from __future__ import annotations

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

from search import sample_site
from search.models import CrawlJob
from search.services import run_crawl_job


class Command(BaseCommand):
    help = "Migrate, crawl the bundled Acme Deploy docs, build the index, and run the site on :8000."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--site-port", type=int, default=0, help="Port for the sample site (0 = any free port).")
        parser.add_argument("--port", default="8000")
        parser.add_argument("--no-serve", action="store_true", help="Stop after building the index.")

    def handle(self, *args: Any, **opts: Any) -> None:
        call_command("migrate", verbosity=0)
        server = sample_site.start(opts["site_port"])
        seed = f"http://127.0.0.1:{server.server_address[1]}/"
        try:
            job = CrawlJob.objects.create(
                name="Acme Deploy docs (bundled)", seed_url=seed, max_pages=200, delay_seconds=0.05
            )
            self.stdout.write(f"Crawling {seed} (robots.txt, sitemap, rate limit) ...")
            job = run_crawl_job(job)
            summary = job.log.rsplit("\n\n", 1)[-1].strip()
            self.stdout.write(summary)
            if job.status != CrawlJob.Status.DONE:
                self.stderr.write(job.log)
                return
            self._ensure_admin()
            if opts["no_serve"]:
                return
            self.stdout.write(self.style.SUCCESS(f"Open http://127.0.0.1:{opts['port']}/ (admin at /admin/)"))
            call_command("runserver", opts["port"], use_reloader=False)
        finally:
            server.shutdown()
            server.server_close()

    def _ensure_admin(self) -> None:
        user_model = get_user_model()
        if user_model.objects.filter(username="admin").exists():
            return
        password = secrets.token_urlsafe(9)
        user_model.objects.create_superuser("admin", "admin@example.com", password)
        self.stdout.write(f"Created admin user 'admin' with password {password} (local demo only).")
