#!/usr/bin/env python3
"""GET /api/push-config — expose only the public VAPID key to this site."""

from http.server import BaseHTTPRequestHandler

from push_common import configuration, send_json, subscriptions_enabled


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel function convention
    server_version = "scout-circulars-push-config/1.0"

    def log_message(self, fmt, *args):
        # Never log request headers; they can include browser identifiers.
        pass

    def do_GET(self):  # noqa: N802
        config = configuration()
        enabled = subscriptions_enabled()
        payload = {
            "ok": True,
            "enabled": enabled,
        }
        if enabled:
            # This key is intentionally public: browsers need it to create a
            # subscription tied to our VAPID sender identity.
            payload["vapidPublicKey"] = config["vapid_public_key"]
        send_json(self, 200, payload)

    def do_OPTIONS(self):  # noqa: N802
        send_json(self, 204, {}, {
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "86400",
        })
