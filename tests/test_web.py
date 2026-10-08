from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client

from search import services
from search.index import SearchIndex, get_index
from search.models import CrawlJob, Page, QueryLog

pytestmark = pytest.mark.django_db


def test_home_without_index(client: Client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert b"No index yet" in response.content


def test_results_page_highlights_and_logs(client: Client, saved_index: SearchIndex) -> None:
    response = client.get("/search", {"q": "CNAME record", "mode": "bm25"})
    body = response.content.decode()
    assert response.status_code == 200
    assert "Custom domains" in body
    assert "<mark>CNAME</mark>" in body
    assert QueryLog.objects.get().query == "CNAME record"


def test_results_unknown_mode_falls_back_to_hybrid(client: Client, saved_index: SearchIndex) -> None:
    response = client.get("/search", {"q": "logs", "mode": "nonsense"})
    assert response.context["mode"] == "hybrid"


def test_results_did_you_mean(client: Client, saved_index: SearchIndex) -> None:
    response = client.get("/search", {"q": "databse"})
    assert response.context["suggestion"] == "database"


def test_results_without_index_is_503(client: Client) -> None:
    assert client.get("/search", {"q": "x"}).status_code == 503


def test_api_search(client: Client, saved_index: SearchIndex) -> None:
    data = client.get("/api/search", {"q": "log drain"}).json()
    assert data["results"][0]["title"] == "Logs"
    assert data["results"][0]["bm25_rank"] == 1


def test_api_suggest(client: Client, saved_index: SearchIndex) -> None:
    QueryLog.objects.create(query="custom domain https", mode="hybrid", results=3)
    data = client.get("/api/suggest", {"q": "custom"}).json()
    assert data["suggestions"][0] == "custom domain https"


def test_did_you_mean_leaves_real_words_alone(client: Client, saved_index: SearchIndex) -> None:
    response = client.get("/search", {"q": "pages load slowly"})
    assert response.context["suggestion"] is None


def test_api_answer_without_key_quotes_pages(client: Client, saved_index: SearchIndex) -> None:
    data = client.get("/api/answer", {"q": "how do I roll back a release"}).json()
    assert data["mode"] == "extractive"
    assert 'href="#source-1"' in data["html"]
    assert data["sources"][0]["cited"] is True


def test_about_page(client: Client, saved_index: SearchIndex) -> None:
    assert client.get("/about").status_code == 200


def test_crawl_command_builds_index(test_site: str, settings: Any) -> None:
    out = StringIO()
    call_command("crawl", f"{test_site}/index.html", "--delay", "0", stdout=out)
    assert "Status: Done" in out.getvalue()
    job = CrawlJob.objects.get()
    assert job.status == CrawlJob.Status.DONE
    assert job.pages_indexed == 3  # A, B, C (home is a link hub)
    assert Page.objects.filter(outcome="blocked_by_robots").exists()
    index = get_index()
    assert index is not None and index.page_count == 3
    assert Path(settings.SEARCH["INDEX_DIR"], "meta.json").exists()


def test_search_and_evaluate_commands(test_site: str, tmp_path: Path) -> None:
    call_command("crawl", f"{test_site}/index.html", "--delay", "0", stdout=StringIO())
    out = StringIO()
    call_command("search", "rollbacks", "--mode", "bm25", stdout=out)
    assert "Page A" in out.getvalue()
    queries = tmp_path / "q.jsonl"
    queries.write_text('{"id": "1", "query": "domains", "kind": "keyword", "relevant": {"/docs/b.html": 2}}\n')
    out = StringIO()
    call_command("evaluate", "--queries", str(queries), "--out", str(tmp_path / "eval"), stdout=out)
    assert "BM25" in out.getvalue()
    assert (tmp_path / "eval" / "results.json").exists()


def test_admin_run_action_starts_background_job(
    client: Client, test_site: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    User.objects.create_superuser("admin", "admin@example.com", "test-password-not-real")
    client.login(username="admin", password="test-password-not-real")
    job = CrawlJob.objects.create(name="Test", seed_url=f"{test_site}/index.html", delay_seconds=0)
    started: list[int] = []

    def run_inline(job_id: int) -> None:
        started.append(job_id)
        services.run_crawl_job(CrawlJob.objects.get(pk=job_id))

    monkeypatch.setattr(services, "start_job_in_background", run_inline)
    response = client.post("/admin/search/crawljob/", {"action": "run_jobs", "_selected_action": [job.pk]}, follow=True)
    assert response.status_code == 200
    assert started == [job.pk]
    job.refresh_from_db()
    assert job.status == CrawlJob.Status.DONE and job.pages_indexed == 3
    assert client.get("/admin/search/page/").status_code == 200
    assert client.get(f"/admin/search/crawljob/{job.pk}/change/").status_code == 200


def test_failed_crawl_is_recorded() -> None:
    job = CrawlJob.objects.create(name="Bad", seed_url="http://127.0.0.1:9/", delay_seconds=0, max_pages=1)
    job = services.run_crawl_job(job)
    assert job.status == CrawlJob.Status.DONE
    assert job.pages_failed == 1
