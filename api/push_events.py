#!/usr/bin/env python3
"""POST /api/push-events — anonymous registration-funnel counters.

The site can already deliver pushes; what it could not see was *why* new
visitors never finish setting notifications up.  This endpoint stores one
daily aggregate counter per event (see FUNNEL_EVENTS in api/push_common.py).

Nothing identifying is accepted or stored: no endpoint, no client token, no
user agent, no IP, no free text.  Only the fixed event names are allowed.
Statistics are best-effort — a failure here never blocks subscribing.
"""

from http.server import BaseHTTPRequestHandler

from api.push_common import (
    ApiError,
    SupabaseError,
    bump_funnel,
    read_json_body,
    require_same_origin,
    require_subscription_configuration,
    send_error,
    send_json,
    validate_funnel_event,
)


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel function convention
    server_version = "scout-circulars-push-events/1.0"

    def log_message(self, fmt, *args):
        # Never log client identifiers.
        pass

    def do_OPTIONS(self):  # noqa: N802
        try:
            require_same_origin(self)
            send_json(self, 204, {}, {
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "86400",
            })
        except ApiError as error:
            send_error(self, error)

    def do_POST(self):  # noqa: N802
        try:
            require_same_origin(self)
            config = require_subscription_configuration()
            body = read_json_body(self)
            event = validate_funnel_event(body.get("event"))
            if not bump_funnel(event, config):
                raise SupabaseError(503, "統計暫時無法記錄")
            send_json(self, 202, {"ok": True})
        except ApiError as error:
            send_error(self, error)
        except SupabaseError:
            send_error(self, ApiError(503, "stats_unavailable", "統計暫時無法記錄"))
        except Exception:
            send_error(self, ApiError(500, "server_error", "統計暫時無法記錄"))
