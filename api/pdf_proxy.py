#!/usr/bin/env python3
"""GET /api/pdf-proxy?u=<通告附件 URL> — stdlib-only PDF byte bridge。

用途：
- 「分享 → 轉換內文做圖」用 pdf.js 喺 **用戶部機** 將 PDF 內文 rasterize 做
  PNG（重嘢全部 client-side，Vercel 唔畫圖）。但 49 個區會來源站大部分
  冇 CORS header，瀏覽器 fetch 唔到 PDF bytes；呢個 function 淨係做
  byte bridge，回應加長 cache —— Vercel edge CDN cache 咗之後，同一份
  通告第二個人再出圖係 CDN 直出，唔會重跑 function。

紅線（同 /requirements.txt 註解、vercel-bundle-guard.yml 一致）：
- 100% Python 標準庫：唔會令 function bundle 脹（2026-09-17 爆
  Functions Storage 11.82GB 嘅真兇係 Python 依賴入 bundle，
  見 VERCEL_EMERGENCY_CLEANUP_2026-09-19.md）。
- 零寫入：唔掂 /tmp、唔掂 blob storage。

防 open-relay（SSRF）濫用：
- ``u`` 必須出現喺 live cache.json（同前端同一來源：GitHub Raw）嘅
  ``pdf_url`` / ``url`` 欄位 → 淨係 proxy「圖書館而家真係列出嘅通告」。
- 單次回應硬上限 4 MB（Vercel serverless response 上限 ~4.5 MB）。
  全檔超過就回 413（可帶 ``bytes``）。前端本機畫圖上限係 20 MB：
  先試用戶自己條網；CORS 唔得先用 ``off``／``n`` 分片（每片 ≤4 MB）拼返再畫。
  超過 20 MB 唔再經呢度拉。
- ``%PDF`` magic bytes 檢查：Drive 有時回 HTML 權限頁，唔好塞返出去當 PDF。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

# 生產環境直接用 GitHub Raw（同前端）；本機/特殊網絡可用 env 指去
# 本地副本（例如 http://127.0.0.1:8000/cache.json）方便測試。
RAW_CACHE_URL = os.environ.get(
    "PDF_PROXY_CACHE_URL",
    "https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/main/cache.json",
)
CACHE_TTL_SECONDS = 10 * 60          # in-process；Vercel warm instance 重用
MAX_PDF_BYTES = 4 * 1024 * 1024      # 低過 Vercel ~4.5MB response cap；單次回應唔可以再大
LOCAL_DRAW_MAX = 20 * 1024 * 1024    # 本機畫圖上限；分片總和唔好超過呢個
FETCH_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 scout-circulars-pdf-proxy/1.0"
)

_cache_urls: set = set()
_cache_loaded_at = 0.0


def _quote(url: str) -> str:
    # 同 enrich.py download() 一致：中文/空格 percent-encode，保留已 encode 部分
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def allowed_urls_from_cache(cache_obj) -> set:
    """cache.json 入面全部通告附件 URL（raw + percent-encode 兩個寫法都收）。"""
    urls = set()
    data = (cache_obj or {}).get("data") or {}
    for items in data.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            for key in ("pdf_url", "url"):
                raw = str(it.get(key) or "").strip()
                if not raw:
                    continue
                urls.add(raw)
                urls.add(_quote(raw))
    return urls


def drive_direct_url(url):
    """Google Drive 分享連結 → 直接下載連結；認唔出就回 None（同 enrich.py）。"""
    m = re.search(r"/file/d/([\w-]+)", url)
    if not m:
        m = re.search(r"[?&]id=([\w-]+)", url)
    if not m:
        return None
    return "https://drive.google.com/uc?export=download&id=" + m.group(1)


class ProxyError(Exception):
    def __init__(self, status: int, code: str, extra: dict | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.extra = extra or {}


def refresh_allowed_urls(force: bool = False) -> set:
    global _cache_urls, _cache_loaded_at
    if not force and _cache_urls and (time.time() - _cache_loaded_at) < CACHE_TTL_SECONDS:
        return _cache_urls
    req = urllib.request.Request(RAW_CACHE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310（URL 寫死 GitHub Raw）
        payload = json.loads(resp.read().decode("utf-8"))
    _cache_urls = allowed_urls_from_cache(payload)
    _cache_loaded_at = time.time()
    return _cache_urls


def resolve_fetch_url(u: str) -> str:
    """驗證 u 係圖書館列出嘅通告附件 → 回真正要攞嘅 URL（Drive 轉直連）。

    任何攞唔到 allowed list 嘅情況都 fail closed（ProxyError 向上傳）。
    """
    if not u or len(u) > 2048:
        raise ProxyError(400, "bad_url")
    scheme = urllib.parse.urlsplit(u).scheme.lower()
    if scheme not in ("http", "https"):
        raise ProxyError(400, "bad_scheme")
    allowed = refresh_allowed_urls()
    if u not in allowed and urllib.parse.unquote(u) not in allowed and _quote(u) not in allowed:
        raise ProxyError(403, "not_a_listed_notice")
    return drive_direct_url(u) or u


def _header(resp, name: str):
    headers = getattr(resp, "headers", None)
    if not headers or not hasattr(headers, "get"):
        return None
    return headers.get(name)


def _content_length(resp):
    raw = _header(resp, "Content-Length")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _content_range_total(resp):
    raw = str(_header(resp, "Content-Range") or "")
    if "/" not in raw:
        return None
    total = raw.rsplit("/", 1)[-1].strip()
    return int(total) if total.isdigit() else None


def _query_int(qs, key: str):
    raw = (qs.get(key) or [""])[0]
    if raw == "":
        return None
    if not re.fullmatch(r"-?\d+", raw):
        raise ProxyError(400, "bad_range")
    return int(raw)


def fetch_pdf(url: str) -> bytes:
    req = urllib.request.Request(_quote(url), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:  # noqa: S310（URL 已過名單檢查）
            length = _content_length(resp)
            if length is not None and length > MAX_PDF_BYTES:
                raise ProxyError(413, "pdf_too_large", extra={"bytes": length})
            data = resp.read(MAX_PDF_BYTES + 1)
    except ProxyError:
        raise
    except Exception as exc:
        raise ProxyError(502, "upstream_unreachable") from exc
    if len(data) > MAX_PDF_BYTES:
        raise ProxyError(413, "pdf_too_large")
    if not data.startswith(b"%PDF"):
        raise ProxyError(415, "not_a_pdf")
    return data


def fetch_pdf_slice(url: str, off: int, n: int) -> tuple[bytes, bool]:
    """回 (bytes, eof)。單次回應永遠 ≤ MAX_PDF_BYTES；唔會讀過 LOCAL_DRAW_MAX。"""
    if off < 0 or n < 1 or off >= LOCAL_DRAW_MAX:
        raise ProxyError(400, "bad_range")
    n = min(int(n), MAX_PDF_BYTES, LOCAL_DRAW_MAX - off)
    end = off + n - 1
    req = urllib.request.Request(
        _quote(url),
        headers={"User-Agent": USER_AGENT, "Range": f"bytes={off}-{end}"},
    )
    try:
        resp_cm = urllib.request.urlopen(req, timeout=FETCH_TIMEOUT)  # noqa: S310
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return b"", True
        raise ProxyError(502, "upstream_unreachable") from exc
    except ProxyError:
        raise
    except Exception as exc:
        raise ProxyError(502, "upstream_unreachable") from exc
    with resp_cm as resp:
        code = getattr(resp, "status", None) or resp.getcode()
        if code == 416:
            return b"", True
        total = _content_range_total(resp) or _content_length(resp)
        if total is not None and total > LOCAL_DRAW_MAX:
            raise ProxyError(413, "pdf_too_large", extra={"bytes": total})
        if code == 206:
            data = resp.read(n)
            if off == 0 and data and not data.startswith(b"%PDF"):
                raise ProxyError(415, "not_a_pdf")
            eof = len(data) < n or (total is not None and off + len(data) >= total)
            return data, eof
        # 上游忽略 Range，回 200 全檔。丟棄 off，只回 n，保護 Vercel 回應上限。
        skipped = 0
        while skipped < off:
            chunk = resp.read(min(64 * 1024, off - skipped))
            if not chunk:
                return b"", True
            skipped += len(chunk)
        data = resp.read(n)
        if off == 0 and data and not data.startswith(b"%PDF"):
            raise ProxyError(415, "not_a_pdf")
        extra = resp.read(1)
        eof = not extra
        if not eof and off + len(data) >= LOCAL_DRAW_MAX:
            raise ProxyError(413, "pdf_too_large", extra={"bytes": LOCAL_DRAW_MAX + 1})
        return data, eof


def _send_json(h: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    h.wfile.write(body)


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel function convention
    server_version = "scout-circulars-pdf-proxy/1.0"

    def log_message(self, fmt, *args):
        # 記錄 query 會留低附件 URL；同其他 api 一致，乜都唔記。
        pass

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            u = (qs.get("u") or [""])[0]
            fetch_url = resolve_fetch_url(u)
            if "off" in qs or "n" in qs:
                off = _query_int(qs, "off")
                n = _query_int(qs, "n")
                data, eof = fetch_pdf_slice(fetch_url, 0 if off is None else off, MAX_PDF_BYTES if n is None else n)
                self._send_pdf(data, eof=eof)
                return
            data = fetch_pdf(fetch_url)
        except ProxyError as exc:
            _send_json(self, exc.status, {"ok": False, "error": exc.code, **exc.extra})
            return
        except Exception:
            # raw cache 攞唔到／JSON 異常：fail closed，唔好無名單照 proxy
            _send_json(self, 503, {"ok": False, "error": "cache_index_unavailable"})
            return
        self._send_pdf(data, eof=True)

    def _send_pdf(self, data: bytes, eof: bool = True) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        # 通告 PDF 基本唔變：edge CDN cache 一星期，重複出圖零 function 成本。
        # 分片都 cache：同一片第二個人係 CDN 直出，唔會重跑 function。
        self.send_header("Cache-Control", "public, max-age=86400, s-maxage=604800, stale-while-revalidate=86400")
        self.send_header("Content-Disposition", "inline")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Pdf-EOF", "1" if eof else "0")
        self.end_headers()
        self.wfile.write(data)
