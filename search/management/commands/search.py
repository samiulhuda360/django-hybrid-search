"""Search from the terminal: python manage.py search "undo a bad release" --mode hybrid"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from search.index import MODES, get_index


class Command(BaseCommand):
    help = "Run a query against the index and print the ranked pages."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("query")
        parser.add_argument("--mode", choices=MODES, default="hybrid")
        parser.add_argument("-k", type=int, default=5)

    def handle(self, *args: Any, **opts: Any) -> None:
        index = get_index()
        if index is None:
            raise CommandError("No index yet. Run `python manage.py demo` or `python manage.py crawl <url>` first.")
        result = index.search(opts["query"], opts["mode"], k=opts["k"])
        self.stdout.write(f'{result.total} pages for "{result.query}" ({result.mode}, {result.elapsed_ms:.1f} ms)\n')
        for rank, hit in enumerate(result.hits, start=1):
            ranks = f"bm25 #{hit.bm25_rank or '-'}  semantic #{hit.semantic_rank or '-'}"
            self.stdout.write(f"{rank:>2}. {hit.title}  [{ranks}]")
            self.stdout.write(f"    {hit.url}")
