#!/usr/bin/env python3
"""GET /api/health — lightweight liveness response, cached briefly at the edge."""

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel function convention
    server_version = "scout-circulars-health/1.0"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):  # noqa: N802
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=30, s-maxage=60")
        self.end_headers()
        self.wfile.write(body)
