"""Serve the bundled documentation site locally, so the crawler has a real website to visit."""

from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from django.conf import settings

SITE_ROOT = Path(settings.BASE_DIR) / "sample_site" / "public"
BUILT_FOR = "http://127.0.0.1:8765"  # the base URL written into robots.txt and sitemap.xml by the build script
REWRITE = {"/robots.txt": "text/plain; charset=utf-8", "/sitemap.xml": "application/xml"}


class SampleSiteHandler(SimpleHTTPRequestHandler):
    """Static files, with absolute URLs in robots.txt and sitemap.xml rewritten to the port actually in use."""

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in REWRITE:
            file = Path(str(self.directory)) / path.lstrip("/")
            if file.exists():
                host = self.headers.get("Host", "127.0.0.1")
                body = file.read_text(encoding="utf-8").replace(BUILT_FOR, f"http://{host}").encode()
                self.send_response(200)
                self.send_header("Content-Type", REWRITE[path])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature from the base class
        return


def start(port: int = 0, root: Path = SITE_ROOT) -> ThreadingHTTPServer:
    """Start a static file server on 127.0.0.1:<port> (0 = any free port) in a daemon thread.

    Call .shutdown() and .server_close() to stop it.
    """
    handler = functools.partial(SampleSiteHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, name="sample-site", daemon=True).start()
    return server
