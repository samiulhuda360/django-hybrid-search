"""Rebuild the search index from the pages stored in the database."""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from search.services import build_index


class Command(BaseCommand):
    help = "Rebuild the BM25 and embedding index from stored pages."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--embedder", choices=["fastembed", "hash"], default=None)

    def handle(self, *args: Any, **opts: Any) -> None:
        started = time.perf_counter()
        index = build_index(opts["embedder"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Indexed {index.page_count} pages as {len(index.chunks)} passages with the "
                f"{index.embedder_kind} embedder in {time.perf_counter() - started:.1f}s."
            )
        )
