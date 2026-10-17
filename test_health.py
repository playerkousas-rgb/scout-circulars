#!/usr/bin/env python3
"""Offline tests for the Vercel health endpoint."""

import io
import json
import unittest

from api import health


class HealthHandlerTests(unittest.TestCase):
    def test_get_has_short_public_edge_cache(self):
        class DummyHandler(health.handler):
            def __init__(self):
                self.wfile = io.BytesIO()
                self.status = None
                self.sent_headers = {}

            def send_response(self, code, message=None):
                self.status = code

            def send_header(self, key, value):
                self.sent_headers[key] = value

            def end_headers(self):
                pass

        h = DummyHandler()
        h.do_GET()
        self.assertEqual(h.status, 200)
        self.assertEqual(h.sent_headers["Cache-Control"], "public, max-age=30, s-maxage=60")
        self.assertEqual(h.sent_headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(h.sent_headers["Content-Length"], str(len(h.wfile.getvalue())))
        self.assertEqual(json.loads(h.wfile.getvalue()), {"ok": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
