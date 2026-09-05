#!/usr/bin/env python3
"""
/api/render — 把通告 PDF 轉做圖片（Vercel Python Function）
============================================================
用途：前端「分享圖片」功能。想把成張通告當圖片貼落 WhatsApp / IG / Facebook，
就要先有一張圖。區會網站絕大部分冇 CORS，瀏覽器直接讀唔到 PDF，
所以由呢個 function 代為下載 + 轉圖（PyMuPDF 內建 CJK 後備字型，
冇內嵌字型嘅 Word 出品通告都畫得正）。

GET /api/render?url=<pdf 網址>&page=1&dpi=130
  → 200 image/jpeg（header X-Pdf-Pages = 總頁數、X-Pdf-Page = 今次頁數）
  → 4xx/5xx application/json {"error": "<code>", "message": "..."}

錯誤碼：bad_url / not_pdf / too_large / encrypted / page_out_of_range /
        fetch_failed / fetch_timeout / render_failed / renderer_unavailable

設計原則（同 core.py / enrich.py 一致）：
  - 唔亂轉：下載返嚟一定要過 %PDF magic bytes 先當係 PDF
  - 唔打爆原站：成功結果交畀 Vercel CDN 快取一日（s-maxage），
    同一張通告無論幾多人分享，每個 CDN 節點最多抓原站一次
  - 唔做開放代理：只回傳「由 PDF 畫出嚟嘅圖片」，永遠唔會原樣轉發
    下載內容；內網 / loopback / link-local 位址一律拒絕（防 SSRF），
    跟 redirect 每一跳都會重新檢查

本機測試：python serve_local.py --allow-private（見該檔說明）
"""

import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

MAX_PDF_BYTES = 25 * 1024 * 1024        # 超過就唔轉（通告好少過 5MB）
FETCH_TIMEOUT = 20                      # 秒；區會站有時好慢
MAX_REDIRECTS = 5
DPI_DEFAULT, DPI_MIN, DPI_MAX = 130, 60, 200
MAX_PIXELS = 8_000_000                  # 大於呢個像素數就自動縮細（防 A0 海報炸記憶體）
JPEG_QUALITY = 85
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 scout-circulars-render/1.0"

# 只喺本機開發先可以抓 127.0.0.1 之類（serve_local.py --allow-private 會設定）
ALLOW_PRIVATE = os.environ.get("RENDER_ALLOW_PRIVATE") == "1"

CACHE_OK = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800"
CACHE_PERMANENT_ERROR = "public, max-age=300, s-maxage=3600"    # not_pdf 之類：一個鐘內唔使再問原站
CACHE_TRANSIENT_ERROR = "public, max-age=0, s-maxage=120"       # 原站暫時死咗：兩分鐘內唔好狂打


class RenderError(Exception):
    def __init__(self, status, code, message, permanent=False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.permanent = permanent


# ─── 網址處理 ────────────────────────────────────────────────
def drive_direct_url(url):
    """Google Drive 分享連結 → 直接下載連結；認唔出就回 None（同 enrich.py 一致）。"""
    m = re.search(r"/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if not m:
        return None
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}"


def normalize_pdf_url(url):
    """清理前端傳入嘅網址：只收 http(s)、中文/空格要 percent-encode、Drive 轉直鏈。"""
    url = (url or "").strip()
    if not url:
        raise RenderError(400, "bad_url", "缺少 url 參數", permanent=True)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RenderError(400, "bad_url", "只支援 http / https 網址", permanent=True)
    host = parsed.hostname or ""
    if "drive.google.com" in host or "docs.google.com" in host:
        direct = drive_direct_url(url)
        if direct:
            url = direct
    # 保留已 encode 嘅 %XX，其餘非 ASCII / 空格先 encode（同 enrich.download 一致）
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


# ─── SSRF 防護 ───────────────────────────────────────────────
def is_public_ip(ip_text):
    """公網位址先可以抓。私網 / loopback / link-local（169.254 = 雲端 metadata）/ 保留位址一律唔得。"""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"):
        return False   # CGNAT 共享位址空間，Python 3.11 嘅 is_private 唔會當佢私網
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or getattr(ip, "is_site_local", False)
    )


def assert_public_host(hostname, allow_private=None):
    """解析主機名，所有位址都要係公網先放行。"""
    if allow_private is None:
        allow_private = ALLOW_PRIVATE
    if allow_private:
        return
    host = (hostname or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise RenderError(400, "bad_url", "唔接受內部主機名", permanent=True)
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise RenderError(502, "fetch_failed", f"解析唔到主機名 {host}")
    addrs = {info[4][0] for info in infos}
    if not addrs or not all(is_public_ip(a) for a in addrs):
        raise RenderError(400, "bad_url", "唔接受內網位址", permanent=True)


# ─── 下載 ────────────────────────────────────────────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):   # noqa: N802
        return None


def _open(url, verify_ssl=True):
    ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    })
    return opener.open(req, timeout=FETCH_TIMEOUT)


def _read_capped(resp, cap):
    buf = bytearray()
    while True:
        chunk = resp.read(256 * 1024)
        if not chunk:
            break
        buf += chunk
        if len(buf) > cap:
            raise RenderError(413, "too_large", f"PDF 超過 {cap // (1024 * 1024)}MB，唔轉圖", permanent=True)
    return bytes(buf)


def fetch_pdf(url, allow_private=None):
    """手動跟 redirect（每跳都做 SSRF 檢查），限制大小，SSL 壞證書時降級重試（同 core.py 做法）。"""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlparse(current)
        assert_public_host(parsed.hostname, allow_private)
        try:
            try:
                resp = _open(current, verify_ssl=True)
            except urllib.error.URLError as e:
                if isinstance(getattr(e, "reason", None), ssl.SSLError) and parsed.scheme == "https":
                    resp = _open(current, verify_ssl=False)   # 部分區會站證書鏈唔齊，同 core.py 一樣降級
                else:
                    raise
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if not location:
                    raise RenderError(502, "fetch_failed", "原站回覆 redirect 但冇 Location")
                current = urllib.parse.urljoin(current, location)
                continue
            raise RenderError(502, "fetch_failed", f"原站回覆 HTTP {e.code}")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise RenderError(504, "fetch_timeout", "原站回應超時")
            raise RenderError(502, "fetch_failed", f"連唔到原站：{type(reason).__name__}")
        except (socket.timeout, TimeoutError):
            raise RenderError(504, "fetch_timeout", "原站回應超時")
        except OSError as e:
            raise RenderError(502, "fetch_failed", f"連唔到原站：{type(e).__name__}")

        with resp:
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > MAX_PDF_BYTES:
                raise RenderError(413, "too_large", f"PDF 超過 {MAX_PDF_BYTES // (1024 * 1024)}MB，唔轉圖", permanent=True)
            data = _read_capped(resp, MAX_PDF_BYTES)

        # magic bytes：Drive 權限頁 / 病毒掃描頁 / 區會文章網頁全部係 HTML，喺呢度擋落嚟
        if b"%PDF" not in data[:1024]:
            raise RenderError(415, "not_pdf", "呢個連結唔係 PDF 檔", permanent=True)
        return data
    raise RenderError(502, "fetch_failed", "redirect 太多次")


# ─── 轉圖 ────────────────────────────────────────────────────
_pymupdf = None


def _mupdf():
    global _pymupdf
    if _pymupdf is None:
        try:
            import pymupdf  # PyMuPDF（api/requirements.txt）
        except ImportError:
            raise RenderError(500, "renderer_unavailable", "伺服器未安裝 PyMuPDF")
        try:
            pymupdf.TOOLS.mupdf_display_errors(False)
        except Exception:
            pass
        _pymupdf = pymupdf
    return _pymupdf


def render_page(pdf_bytes, page_no=1, dpi=DPI_DEFAULT):
    """回傳 (jpeg_bytes, page_count, width_px, height_px)。page_no 由 1 開始。"""
    pymupdf = _mupdf()
    dpi = max(DPI_MIN, min(DPI_MAX, int(dpi)))
    # MuPDF 會將任何垃圾 bytes 當成「1 頁空白文件」開到（is_pdf=False），所以自己先驗 magic bytes
    if b"%PDF" not in (pdf_bytes or b"")[:1024]:
        raise RenderError(415, "not_pdf", "呢個連結唔係 PDF 檔", permanent=True)
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        raise RenderError(415, "not_pdf", "PDF 檔案損壞，開唔到", permanent=True)
    try:
        if not doc.is_pdf:
            raise RenderError(415, "not_pdf", "呢個連結唔係 PDF 檔", permanent=True)
        if doc.needs_pass and not doc.authenticate(""):
            raise RenderError(422, "encrypted", "呢個 PDF 有密碼保護", permanent=True)
        count = doc.page_count
        if count < 1:
            raise RenderError(415, "not_pdf", "PDF 冇任何頁面", permanent=True)
        if page_no < 1 or page_no > count:
            raise RenderError(404, "page_out_of_range", f"呢份 PDF 只有 {count} 頁", permanent=True)
        page = doc[page_no - 1]
        zoom = dpi / 72.0
        rect = page.rect
        pixels = (rect.width * zoom) * (rect.height * zoom)
        if pixels > MAX_PIXELS:
            zoom *= (MAX_PIXELS / pixels) ** 0.5
        try:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            data = pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
        except RenderError:
            raise
        except Exception as e:
            raise RenderError(500, "render_failed", f"畫唔到呢頁：{type(e).__name__}")
        return data, count, pix.width, pix.height
    finally:
        doc.close()


# ─── HTTP handler（Vercel 會 import 呢個 class）────────────────
def _parse_int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


class handler(BaseHTTPRequestHandler):   # noqa: N801 — Vercel 規定名叫 handler
    server_version = "scout-circulars-render/1.0"

    def log_message(self, fmt, *args):   # Vercel log 已經有 request line，唔使再印
        pass

    def _send(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "X-Pdf-Pages, X-Pdf-Page")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, err):
        body = json.dumps({"error": err.code, "message": err.message}, ensure_ascii=False).encode("utf-8")
        cache = CACHE_PERMANENT_ERROR if err.permanent else CACHE_TRANSIENT_ERROR
        self._send(err.status, body, "application/json; charset=utf-8", {"Cache-Control": cache})

    def do_OPTIONS(self):   # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):   # noqa: N802
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        page_no = _parse_int(query.get("page", ["1"])[0], 1, 1, 500)
        dpi = _parse_int(query.get("dpi", [DPI_DEFAULT])[0], DPI_DEFAULT, DPI_MIN, DPI_MAX)
        try:
            url = normalize_pdf_url(query.get("url", [""])[0])
            pdf = fetch_pdf(url)
            jpeg, count, width, height = render_page(pdf, page_no, dpi)
        except RenderError as e:
            self._send_error(e)
            return
        except Exception as e:   # 任何預期以外嘅錯都要回 JSON，唔好俾前端收到 HTML 500 頁
            self._send_error(RenderError(500, "render_failed", f"{type(e).__name__}: {e}"))
            return
        self._send(200, jpeg, "image/jpeg", {
            "Cache-Control": CACHE_OK,
            "X-Pdf-Pages": str(count),
            "X-Pdf-Page": str(page_no),
            "X-Image-Size": f"{width}x{height}",
        })
