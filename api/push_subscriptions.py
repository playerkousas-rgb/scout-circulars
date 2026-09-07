#!/usr/bin/env python3
"""POST /api/push-subscriptions — anonymous browser Web Push lifecycle API."""

from http.server import BaseHTTPRequestHandler

from push_common import (
    ApiError,
    SupabaseError,
    client_token_hash,
    endpoint_hash,
    read_json_body,
    require_same_origin,
    require_subscription_configuration,
    send_error,
    send_json,
    supabase_request,
    utc_now,
    validate_client_token,
    validate_endpoint,
    validate_preferences,
    validate_subscription,
)


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel function convention
    server_version = "scout-circulars-push-subscriptions/1.0"

    def log_message(self, fmt, *args):
        # In particular, do not log a PushSubscription endpoint.
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
            action = body.get("action")
            token = validate_client_token(body.get("clientToken"))
            token_digest = client_token_hash(token)

            if action == "upsert":
                subscription = validate_subscription(body.get("subscription"))
                branches, topics, catalog_version = validate_preferences(body)
                now = utc_now()
                record = {
                    "endpoint_hash": endpoint_hash(subscription["endpoint"]),
                    "endpoint": subscription["endpoint"],
                    "p256dh": subscription["p256dh"],
                    "auth": subscription["auth"],
                    "client_token_hash": token_digest,
                    "branch_ids": branches,
                    "topic_ids": topics,
                    "catalog_version": catalog_version,
                    "enabled": True,
                    "last_seen_at": now,
                }
                supabase_request(
                    "POST",
                    "push_subscriptions",
                    query={"on_conflict": "endpoint_hash"},
                    payload=record,
                    prefer="resolution=merge-duplicates,return=minimal",
                    config=config,
                )
                # Deliberately do not return a subscription id or endpoint.
                send_json(self, 201, {"ok": True, "status": "saved"})
                return

            if action == "delete":
                # Delete needs the opaque local token *and* endpoint.  A plain
                # endpoint alone is never enough to remove another device.
                raw_sub = body.get("subscription")
                endpoint = validate_endpoint(raw_sub.get("endpoint") if isinstance(raw_sub, dict) else body.get("endpoint"))
                supabase_request(
                    "DELETE",
                    "push_subscriptions",
                    query={
                        "endpoint_hash": f"eq.{endpoint_hash(endpoint)}",
                        "client_token_hash": f"eq.{token_digest}",
                    },
                    prefer="return=minimal",
                    config=config,
                )
                # Idempotent by design: do not disclose whether a row existed.
                send_json(self, 200, {"ok": True, "status": "deleted"})
                return

            raise ApiError(400, "invalid_action", "不支援的通知設定操作")
        except ApiError as error:
            send_error(self, error)
        except SupabaseError:
            send_error(self, ApiError(503, "storage_unavailable", "通知設定暫時無法儲存，請稍後再試"))
        except Exception:
            # Unexpected errors remain opaque to avoid leaking stack traces or
            # storage details to the public endpoint.
            send_error(self, ApiError(500, "server_error", "通知設定暫時無法處理"))
