"""Evaluate ranking quality on the labelled query set and write eval/results.json and eval/results.md."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from search.evaluation import evaluate, load_queries
from search.index import get_index

LABELS = {"bm25": "BM25", "semantic": "Semantic (embeddings)", "hybrid": "Hybrid (RRF)"}


class Command(BaseCommand):
    help = "Compare BM25, semantic and hybrid ranking with nDCG@10, MRR@10 and Recall@5."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--queries", default=str(Path(settings.BASE_DIR) / "eval" / "queries.jsonl"))
        parser.add_argument("--out", default=str(Path(settings.BASE_DIR) / "eval"), help="Folder for the results.")
        parser.add_argument("--no-write", action="store_true")

    def handle(self, *args: Any, **opts: Any) -> None:
        index = get_index()
        if index is None:
            raise CommandError("No index yet. Run `python manage.py demo --no-serve` first.")
        queries = load_queries(Path(opts["queries"]))
        results = evaluate(index, queries)
        counts = {g: sum(1 for q in queries if g in ("all", q.kind)) for g in results}

        lines = [
            f"Corpus: {index.page_count} pages, {len(index.chunks)} passages. Embedder: {index.embedder.name}.",
            f"Queries: {len(queries)} labelled ({counts.get('keyword', 0)} keyword, "
            f"{counts.get('natural', 0)} natural-language).",
            "",
        ]
        md = ["| Queries | Method | nDCG@10 | MRR@10 | Recall@5 |", "|---|---|---|---|---|"]
        for group, by_mode in results.items():
            lines.append(f"{group} ({counts[group]} queries)")
            lines.append(f"  {'method':<24}{'nDCG@10':>9}{'MRR@10':>9}{'Recall@5':>10}")
            for mode, s in by_mode.items():
                lines.append(f"  {LABELS[mode]:<24}{s.ndcg10:>9.3f}{s.mrr10:>9.3f}{s.recall5:>10.3f}")
                md.append(
                    f"| {group} ({counts[group]}) | {LABELS[mode]} | {s.ndcg10:.3f} | {s.mrr10:.3f} | {s.recall5:.3f} |"
                )
            lines.append("")
        self.stdout.write("\n".join(lines).rstrip())

        if not opts["no_write"]:
            out = Path(opts["out"])
            out.mkdir(parents=True, exist_ok=True)
            payload = {
                "embedder": index.embedder.name,
                "pages": index.page_count,
                "passages": len(index.chunks),
                "queries": len(queries),
                "results": {g: {m: asdict(s) for m, s in by_mode.items()} for g, by_mode in results.items()},
            }
            (out / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            (out / "results.md").write_text("\n".join([*lines[:2], "", *md]) + "\n", encoding="utf-8")
            self.stdout.write(f"\nWrote {out / 'results.json'} and {out / 'results.md'}")
