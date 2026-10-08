"""Search pages and JSON endpoints."""

from __future__ import annotations

import re
from typing import Any

from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.html import escape
from django.views.decorators.http import require_GET

from .answer import answer_question
from .index import MODES, Mode, SearchResult, get_index
from .models import CrawlJob, Page, QueryLog
from .snippets import highlight, make_snippet
from .suggest import did_you_mean, suggest

PER_PAGE = 10
EXAMPLES = ["undo a bad release", "custom domain CNAME record", "files disappear after every deploy"]


def _mode(request: HttpRequest) -> Mode:
    mode = request.GET.get("mode", "hybrid")
    return mode if mode in MODES else "hybrid"


def _query(request: HttpRequest) -> str:
    return " ".join(request.GET.get("q", "").split())[:300]


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    index = get_index()
    context = {
        "page_count": index.page_count if index else 0,
        "passage_count": len(index.chunks) if index else 0,
        "embedder": index.embedder.name if index else None,
        "examples": EXAMPLES,
        "last_job": CrawlJob.objects.first(),
    }
    return render(request, "search/home.html", context)


@require_GET
def results(request: HttpRequest) -> HttpResponse:
    query, mode = _query(request), _mode(request)
    index = get_index()
    if index is None:
        return render(request, "search/results.html", {"query": query, "mode": mode, "no_index": True}, status=503)
    page_number = max(1, int(request.GET.get("page", "1")) if request.GET.get("page", "1").isdigit() else 1)
    result = index.search(query, mode, k=PER_PAGE, offset=(page_number - 1) * PER_PAGE) if query else None
    stems = set(result.terms) if result else set()
    rows = []
    for hit in result.hits if result else []:
        rows.append(
            {
                "hit": hit,
                "title": highlight(hit.title, stems),
                "snippet": make_snippet(hit.passage.text, stems),
                "heading": hit.passage.heading,
            }
        )
    if query and page_number == 1:
        QueryLog.objects.create(query=query, mode=mode, results=result.total if result else 0)
    paginator = Paginator(range(result.total if result else 0), PER_PAGE)
    context: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "modes": MODES,
        "result": result,
        "rows": rows,
        "suggestion": did_you_mean(query, index) if query else None,
        "page_obj": paginator.get_page(page_number) if result and result.total else None,
        "start_rank": (page_number - 1) * PER_PAGE,
    }
    return render(request, "search/results.html", context)


def _result_json(result: SearchResult) -> dict[str, Any]:
    stems = set(result.terms)
    return {
        "query": result.query,
        "mode": result.mode,
        "total": result.total,
        "elapsed_ms": round(result.elapsed_ms, 2),
        "results": [
            {
                "url": h.url,
                "title": h.title,
                "score": round(h.score, 5),
                "bm25_rank": h.bm25_rank,
                "semantic_rank": h.semantic_rank,
                "snippet_html": str(make_snippet(h.passage.text, stems)),
            }
            for h in result.hits
        ],
    }


@require_GET
def api_search(request: HttpRequest) -> JsonResponse:
    index = get_index()
    if index is None:
        return JsonResponse({"error": "The index has not been built yet."}, status=503)
    return JsonResponse(_result_json(index.search(_query(request), _mode(request))))


@require_GET
def api_suggest(request: HttpRequest) -> JsonResponse:
    prefix = _query(request)
    index = get_index()
    if index is None or len(prefix) < 2:
        return JsonResponse({"suggestions": []})
    past = (
        QueryLog.objects.filter(query__istartswith=prefix, results__gt=0)
        .values_list("query", flat=True)
        .distinct()[:20]
    )
    # Past searches are only offered when they are spelled like the indexed text.
    clean = [q for q in past if did_you_mean(q, index) is None]
    return JsonResponse({"suggestions": suggest(prefix, index, past_queries=clean)})


@require_GET
def api_answer(request: HttpRequest) -> JsonResponse:
    query = _query(request)
    index = get_index()
    if index is None or not query:
        return JsonResponse({"mode": "none", "html": "", "sources": []})
    hits = index.search(query, _mode(request), k=4).hits
    answer = answer_question(query, hits, context=index.page_context)
    html = str(escape(answer.text))
    html = re.sub(r"`([^`<>]+)`", r"<code>\1</code>", html)
    html = re.sub(r"\[(\d+)\]", r'<a class="cite" href="#source-\1">[\1]</a>', html)
    return JsonResponse(
        {
            "mode": answer.mode,
            "html": html,
            "cached": answer.cached,
            "note": answer.note,
            "sources": [
                {"n": s.n, "title": s.title, "url": s.url, "cited": s.n in answer.cited} for s in answer.sources
            ],
        }
    )


@require_GET
def about(request: HttpRequest) -> HttpResponse:
    index = get_index()
    counts = {label: Page.objects.filter(outcome=value).count() for value, label in Page.Outcome.choices}
    return render(
        request,
        "search/about.html",
        {"index": index, "counts": counts, "jobs": CrawlJob.objects.all()[:5]},
    )
