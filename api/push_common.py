#!/usr/bin/env python3
"""Shared security and Supabase helpers for anonymous Web Push endpoints.

The browser never talks to Supabase with a service-role key.  These narrow
Vercel functions validate a browser PushSubscription and only persist the
minimum data Web Push needs to address and encrypt a notification.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "subscription_catalog.json"
MAX_REQUEST_BYTES = 24 * 1024
MAX_ENDPOINT_LENGTH = 2048
MAX_CLIENT_TOKEN_LENGTH = 128
MAX_TOPICS = 24

# Web Push endpoints are later contacted by GitHub Actions.  Restricting them
# to browser push providers prevents the subscription endpoint from becoming
# an arbitrary outbound-request/SSRF primitive.
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
)
ALLOWED_PUSH_SUFFIXES = (
    ".push.services.mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class SupabaseError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _normalise_base64_url(value: Any) -> str:
    return str(value or "").strip()


def valid_vapid_public_key(value: Any) -> bool:
    # A P-256 public VAPID key is normally an 87-char base64url string.  Keep a
    # little tolerance for encoding variants, while refusing arbitrary values.
    value = _normalise_base64_url(value)
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{60,200}", value))


def configuration() -> Dict[str, str]:
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", "").rstrip("/"),
        "supabase_key": os.environ.get("SUPABASE_SERVICE_KEY", ""),
        "vapid_public_key": os.environ.get("VAPID_PUBLIC_KEY", "").strip(),
    }


def subscriptions_enabled() -> bool:
    config = configuration()
    return bool(
        config["supabase_url"]
        and config["supabase_key"]
        and valid_vapid_public_key(config["vapid_public_key"])
    )


def require_subscription_configuration() -> Dict[str, str]:
    config = configuration()
    if not (
        config["supabase_url"]
        and config["supabase_key"]
        and valid_vapid_public_key(config["vapid_public_key"])
    ):
        raise ApiError(503, "push_unavailable", "通知服務尚未完成設定")
    return config


def load_catalog() -> Dict[str, Any]:
    try:
        with CATALOG_PATH.open("r", encoding="utf-8") as fh:
            catalog = json.load(fh)
    except Exception as exc:
        raise ApiError(503, "catalog_unavailable", "通知選項暫時無法讀取") from exc

    branches = catalog.get("branches") if isinstance(catalog, dict) else None
    topics = catalog.get("topics") if isinstance(catalog, dict) else None
    if not isinstance(branches, list) or not isinstance(topics, list):
        raise ApiError(503, "catalog_unavailable", "通知選項設定不完整")
    branch_ids = {str(entry.get("id")) for entry in branches if isinstance(entry, dict) and entry.get("id")}
    topic_ids = {str(entry.get("id")) for entry in topics if isinstance(entry, dict) and entry.get("id")}
    if not branch_ids or not topic_ids:
        raise ApiError(503, "catalog_unavailable", "通知選項設定不完整")
    catalog["_branch_ids"] = branch_ids
    catalog["_topic_ids"] = topic_ids
    return catalog


def _normalise_choice_list(value: Any, allowed: Iterable[str], field: str, max_items: int) -> List[str]:
    if not isinstance(value, list):
        raise ApiError(400, "invalid_request", f"{field} 必須是清單")
    if len(value) > max_items:
        raise ApiError(400, "too_many_choices", f"{field} 選項過多")
    allowed_set = set(allowed)
    result: List[str] = []
    for item in value:
        if not isinstance(item, str) or item not in allowed_set:
            raise ApiError(400, "invalid_choice", "包含不支援的通知選項，請重新載入頁面")
        if item not in result:
            result.append(item)
    return result


def validate_preferences(body: Mapping[str, Any]) -> Tuple[List[str], List[str], str]:
    catalog = load_catalog()
    branches = _normalise_choice_list(body.get("branches"), catalog["_branch_ids"], "支部", len(catalog["_branch_ids"]))
    topics = _normalise_choice_list(body.get("topics"), catalog["_topic_ids"], "關注項目", MAX_TOPICS)
    if not branches:
        raise ApiError(400, "missing_branch", "請至少選擇一個支部")
    if not topics:
        raise ApiError(400, "missing_topic", "請至少選擇一個關注項目")

    # The UI hides a branch-specific badge/course until an applicable branch is
    # selected. Enforce the same rule server-side so a forged request cannot
    # create a logically impossible preference combination.
    topic_by_id = {str(entry.get("id")): entry for entry in catalog.get("topics", []) if isinstance(entry, dict)}
    for topic_id in topics:
        scope = {str(value) for value in (topic_by_id.get(topic_id, {}).get("branches") or [])}
        if "*" not in scope and not scope.intersection(branches):
            raise ApiError(400, "incompatible_choice", "所選訓練項目不適用於已選支部")
    return branches, topics, str(catalog.get("version", ""))


def validate_client_token(value: Any) -> str:
    value = str(value or "").strip()
    # Browser-generated 32-byte base64url nonce (43 chars); accepting a wider
    # range makes a future browser migration possible without weakening entropy.
    if not re.fullmatch(r"[A-Za-z0-9_-]{32," + str(MAX_CLIENT_TOKEN_LENGTH) + r"}", value):
        raise ApiError(400, "invalid_client_token", "本機通知識別碼無效，請重新設定")
    return value


def client_token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _allowed_push_endpoint(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host in ALLOWED_PUSH_HOSTS or any(host.endswith(suffix) for suffix in ALLOWED_PUSH_SUFFIXES)


def validate_endpoint(value: Any) -> str:
    endpoint = str(value or "").strip()
    if not endpoint or len(endpoint) > MAX_ENDPOINT_LENGTH:
        raise ApiError(400, "invalid_subscription", "瀏覽器通知地址無效")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not _allowed_push_endpoint(parsed.hostname)
    ):
        raise ApiError(400, "invalid_subscription", "這個瀏覽器通知服務未受支援")
    return endpoint


def _validate_push_key(value: Any, field: str, min_length: int, max_length: int) -> str:
    value = str(value or "").strip()
    # Browser serialisation uses unpadded base64url, but accept standard base64
    # too; encryption library performs the final cryptographic validation.
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]{%d,%d}" % (min_length, max_length), value):
        raise ApiError(400, "invalid_subscription", f"瀏覽器通知金鑰 {field} 無效")
    return value


def validate_subscription(value: Any) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        raise ApiError(400, "invalid_subscription", "缺少瀏覽器通知資料")
    keys = value.get("keys")
    if not isinstance(keys, Mapping):
        raise ApiError(400, "invalid_subscription", "缺少瀏覽器通知金鑰")
    endpoint = validate_endpoint(value.get("endpoint"))
    return {
        "endpoint": endpoint,
        "p256dh": _validate_push_key(keys.get("p256dh"), "p256dh", 40, 300),
        "auth": _validate_push_key(keys.get("auth"), "auth", 8, 128),
    }


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _same_origin(handler: BaseHTTPRequestHandler) -> bool:
    origin = handler.headers.get("Origin", "").strip()
    if not origin:
        return False
    parsed = urlparse(origin)
    host = (handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "").split(",")[0].strip()
    proto = (handler.headers.get("X-Forwarded-Proto") or ("https" if handler.headers.get("X-Forwarded-Host") else "http")).split(",")[0].strip()
    return bool(
        parsed.scheme in ("http", "https")
        and not parsed.path.rstrip("/")
        and parsed.scheme == proto
        and parsed.netloc.lower() == host.lower()
    )


def require_same_origin(handler: BaseHTTPRequestHandler) -> None:
    if not _same_origin(handler):
        raise ApiError(403, "origin_not_allowed", "只接受本站的通知設定請求")


def cors_headers(handler: BaseHTTPRequestHandler) -> Dict[str, str]:
    origin = handler.headers.get("Origin", "").strip()
    if origin and _same_origin(handler):
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {}


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: Mapping[str, Any], headers: Optional[Mapping[str, str]] = None) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response_headers: Dict[str, str] = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
    }
    response_headers.update(cors_headers(handler))
    response_headers.update(headers or {})
    handler.send_response(status)
    for key, value in response_headers.items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler: BaseHTTPRequestHandler, error: ApiError) -> None:
    send_json(handler, error.status, {"ok": False, "error": error.code, "message": error.message})


def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    raw_length = handler.headers.get("Content-Length")
    try:
        length = int(raw_length or "-1")
    except ValueError:
        length = -1
    if length < 1 or length > MAX_REQUEST_BYTES:
        raise ApiError(413 if length > MAX_REQUEST_BYTES else 400, "invalid_request", "通知設定資料大小無效")
    try:
        raw = handler.rfile.read(length)
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(400, "invalid_request", "通知設定不是有效 JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_request", "通知設定格式無效")
    return body


def supabase_request(
    method: str,
    resource: str,
    *,
    query: Optional[Mapping[str, Any]] = None,
    payload: Any = None,
    prefer: str = "",
    config: Optional[Mapping[str, str]] = None,
) -> Tuple[int, Any]:
    config = dict(config or require_subscription_configuration())
    url = f"{config['supabase_url']}/rest/v1/{resource.lstrip('/')}"
    if query:
        url += "?" + urlencode(query, doseq=True, safe="(),.*")
    data = None
    headers = {
        "apikey": config["supabase_key"],
        "Authorization": f"Bearer {config['supabase_key']}",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            try:
                return response.status, json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return response.status, None
    except HTTPError as exc:
        # Do not return PostgREST detail to the browser: it can include schema
        # information and is not useful to a person changing notification prefs.
        raise SupabaseError(exc.code, "資料庫暫時無法更新") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SupabaseError(503, "資料庫暫時無法連線") from exc
