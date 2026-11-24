"""A temporary database per test, and a small local website to scrape."""
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import sources  # noqa: E402

TODAY = date(2026, 11, 17)


class TempDB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._db = mock.patch.object(config, "DB_PATH", os.path.join(self.tmp.name, "test.db"))
        self._db.start()
        # Channel settings must come from the test, never from this PC's environment.
        self._env = mock.patch.dict(os.environ, {k: "" for k in os.environ if k.startswith("INTERNSHIPS_")})
        self._env.start()
        # "Today" is fixed, so the fixtures' last dates (late 2026) stay open.
        self._today = mock.patch.object(sources, "today", return_value=TODAY)
        self._today.start()

    def tearDown(self):
        self._today.stop()
        self._env.stop()
        self._db.stop()
        self.tmp.cleanup()


class Site:
    """Serves `pages` (path -> html) and records every JSON POST (a webhook)."""

    def __init__(self):
        self.pages, self.posts = {}, []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = site.pages.get(self.path)
                self.send_response(200 if body is not None else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write((body or "not found").encode("utf-8"))

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                site.posts.append(json.loads(self.rfile.read(length) or b"{}"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
