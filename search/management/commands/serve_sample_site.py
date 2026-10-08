"""Serve the bundled Acme Deploy docs site on http://127.0.0.1:8766/ until interrupted."""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from search import sample_site


class Command(BaseCommand):
    help = "Serve the bundled documentation site for the crawler."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--port", type=int, default=8766)

    def handle(self, *args: Any, **opts: Any) -> None:
        server = sample_site.start(opts["port"])
        self.stdout.write(f"Serving the sample docs site on http://127.0.0.1:{opts['port']}/ (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
