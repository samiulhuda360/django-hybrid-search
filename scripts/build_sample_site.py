"""Build the bundled "Acme Deploy" documentation site from sample_site/source.txt.

The output in sample_site/public/ is a small static site the crawler can visit like any real one. It includes:

* a robots.txt that blocks /internal/ and sets a crawl delay;
* a sitemap.xml that lists most pages (one page is only reachable through a link);
* an internal page the crawler must skip, and a plain-text download it must not index.
"""

from __future__ import annotations

import html
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "sample_site" / "source.txt"
OUT = ROOT / "sample_site" / "public"
BASE_URL = "http://127.0.0.1:8765"
NOT_IN_SITEMAP = {"maintenance-mode"}


@dataclass
class Doc:
    slug: str
    title: str
    section: str
    blocks: list[tuple[str, str]] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)


def parse(text: str) -> list[Doc]:
    docs: list[Doc] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and not line.startswith("## ")):
            continue
        if line.startswith("@@ "):
            slug, title, section = (part.strip() for part in line[3:].split("|"))
            docs.append(Doc(slug, title, section))
        elif line.startswith("## "):
            docs[-1].blocks.append(("h2", line[3:]))
        elif line.startswith("-> "):
            docs[-1].see_also.append(line[3:].strip())
        else:
            docs[-1].blocks.append(("p", line))
    return docs


def layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} - Acme Deploy docs</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/assets/docs.css">
</head>
<body>
<header class="top"><a href="/index.html">Acme Deploy docs</a>
<nav><a href="/index.html?ref=nav">All pages</a> <a href="/downloads/acme-cli-cheatsheet.txt">CLI cheat sheet</a></nav>
</header>
<main>
{body}
</main>
<footer>Acme Deploy is a fictional product used to demonstrate a search engine.</footer>
</body>
</html>
"""


def render_doc(doc: Doc, titles: dict[str, str]) -> str:
    parts = [f'<nav class="section">{html.escape(doc.section)}</nav>', f"<h1>{html.escape(doc.title)}</h1>"]
    for kind, text in doc.blocks:
        parts.append(f"<{kind}>{html.escape(text)}</{kind}>")
    if doc.see_also:
        links = "".join(
            f'<li><a href="/docs/{slug}.html">{html.escape(titles[slug])}</a></li>' for slug in doc.see_also
        )
        parts.append(f"<aside><h2>See also</h2><ul>{links}</ul></aside>")
    return layout(doc.title, "\n".join(parts))


def render_index(docs: list[Doc]) -> str:
    sections: dict[str, list[Doc]] = {}
    for doc in docs:
        sections.setdefault(doc.section, []).append(doc)
    parts = ["<h1>Acme Deploy documentation</h1>", "<p>Guides for deploying and running apps on Acme Deploy.</p>"]
    for section, items in sections.items():
        visible = [d for d in items if d.slug not in NOT_IN_SITEMAP]
        links = "".join(f'<li><a href="/docs/{d.slug}.html">{html.escape(d.title)}</a></li>' for d in visible)
        parts.append(f"<h2>{html.escape(section)}</h2><ul>{links}</ul>")
    parts.append('<p class="staff">Staff only: <a href="/internal/oncall-runbook.html">on-call runbook</a></p>')
    return layout("Documentation", "\n".join(parts))


INTERNAL = layout(
    "On-call runbook (internal)",
    "<h1>On-call runbook</h1><p>Internal page for staff. The robots.txt file asks crawlers not to visit it, "
    "so it must never appear in search results.</p><p>Escalation rota, pager settings and the rollback checklist "
    "for platform engineers.</p>",
)

CSS = """body{font:16px/1.6 Georgia,serif;max-width:46rem;margin:0 auto;padding:1rem;color:#1d2a2a;background:#fbfaf6}
.top{display:flex;justify-content:space-between;border-bottom:1px solid #d8d3c4;padding-bottom:.5rem}
a{color:#1f5f5b}.section{text-transform:uppercase;font-size:.8rem;letter-spacing:.08em;color:#6b6b5e}
footer{margin-top:3rem;font-size:.8rem;color:#6b6b5e}"""

CHEATSHEET = """acme login            sign in
acme init             create a project
acme deploy           build and release
acme rollback         return to the previous release
acme logs --tail      follow logs
"""


def main() -> None:
    docs = parse(SOURCE.read_text(encoding="utf-8"))
    titles = {d.slug: d.title for d in docs}
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "docs").mkdir(parents=True)
    (OUT / "internal").mkdir()
    (OUT / "assets").mkdir()
    (OUT / "downloads").mkdir()
    for doc in docs:
        missing = [s for s in doc.see_also if s not in titles]
        if missing:
            raise SystemExit(f"{doc.slug}: unknown see-also links {missing}")
        (OUT / "docs" / f"{doc.slug}.html").write_text(render_doc(doc, titles), encoding="utf-8")
    (OUT / "index.html").write_text(render_index(docs), encoding="utf-8")
    (OUT / "internal" / "oncall-runbook.html").write_text(INTERNAL, encoding="utf-8")
    (OUT / "assets" / "docs.css").write_text(CSS, encoding="utf-8")
    (OUT / "downloads" / "acme-cli-cheatsheet.txt").write_text(CHEATSHEET, encoding="utf-8")
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nDisallow: /internal/\nCrawl-delay: 0.2\n\nSitemap: {BASE_URL}/sitemap.xml\n",
        encoding="utf-8",
    )
    urls = [f"{BASE_URL}/index.html"] + [f"{BASE_URL}/docs/{d.slug}.html" for d in docs if d.slug not in NOT_IN_SITEMAP]
    entries = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{entries}\n</urlset>\n',
        encoding="utf-8",
    )
    print(f"Wrote {len(docs)} documentation pages to {OUT}")


if __name__ == "__main__":
    main()
