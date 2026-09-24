#!/usr/bin/env python3
"""api/pdf_proxy.py 嘅離線單元測試（全部 mock 網絡）。

重點驗證：
  1. URL 會員檢查：只 proxy cache.json 列出嘅通告附件（防 open-relay/SSRF）
  2. 中文/空格 URL 嘅 raw 同 percent-encode 兩種寫法都認到
  3. Google Drive view 連結 → 直連轉換
  4. 4MB 上限 → 413；非 PDF（HTML 權限頁）→ 415；上游死 → 502
  5. handler：200 帶 edge cache header；403/503 出 JSON
  6. 只有 Google 網域先改寫做 Drive 直連（灣仔 index.php?…&id= 唔會被當 Drive）
  7. 分片讀 body 途中斷線 → 502 upstream_unreachable（唔好誤報 503 cache_index_unavailable）
  8. serve_local.py 借 handler.do_GET（self 係 LocalHandler）都行得通
用法：python test_pdf_proxy.py
"""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdf_proxy  # noqa: E402


CACHE = {
    "data": {
        "九龍城區": [
            {"pdf_url": "https://www.klcscout.hk/cportal/uploads/A 品酒工作坊.pdf", "url": "https://www.klcscout.hk/notice/1"},
            {"pdf_url": "https://drive.google.com/file/d/ABC-1_x/view", "url": "https://drive.google.com/file/d/ABC-1_x/view"},
        ],
        "灣仔區": [
            {"url": "https://www.wanchaiscout.org.hk/index.php?option=com_content&view=article&id=634"},
        ],
    },
}
WANCHAI = "https://www.wanchaiscout.org.hk/index.php?option=com_content&view=article&id=634"


class BrokenBodyResp:
    """header 已經返咗，但讀 body 途中斷線／逾時（上游問題）。"""

    headers = {}
    status = 206

    def read(self, n=-1):
        raise TimeoutError("read timed out")

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeResp:
    """模擬 urllib.request.urlopen 嘅 context manager response。"""

    def __init__(self, body: bytes, headers=None, status=200):
        self._body = body
        self._pos = 0
        self.headers = headers or {}
        self.status = status

    def read(self, n=-1):
        if n is None or n < 0:
            data = self._body[self._pos:]
            self._pos = len(self._body)
            return data
        data = self._body[self._pos:self._pos + n]
        self._pos += len(data)
        return data

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DummyHandler(pdf_proxy.handler):
    """唔起 server 都測到 do_GET：截 send_response，wfile 用 BytesIO。"""

    def __init__(self, path: str):
        # 刻意唔 call BaseHTTPRequestHandler.__init__（佢會等 socket）
        self.path = path
        self.headers = {}
        self.rfile = io.BytesIO()
        self.wfile = io.BytesIO()
        self.request_version = "HTTP/1.1"
        self.status = None
        self.sent_headers = {}

    def send_response(self, code, message=None):  # noqa: N802
        self.status = code
        self._headers_buffer = []

    def send_header(self, key, value):  # noqa: N802
        self.sent_headers[key] = value

    def end_headers(self):  # noqa: N802
        pass


class AllowedUrlsTests(unittest.TestCase):
    def test_collects_pdf_and_page_urls_raw_and_quoted(self):
        urls = pdf_proxy.allowed_urls_from_cache(CACHE)
        self.assertIn("https://www.klcscout.hk/cportal/uploads/A 品酒工作坊.pdf", urls)
        self.assertIn("https://www.klcscout.hk/notice/1", urls)
        quoted = [u for u in urls if "%20" in u and "%E5%93%81%E9%85%92" in u]
        self.assertTrue(quoted, "中文/空格 URL 要有 percent-encode 版本")

    def test_empty_cache_gives_empty_set(self):
        self.assertEqual(pdf_proxy.allowed_urls_from_cache({}), set())
        self.assertEqual(pdf_proxy.allowed_urls_from_cache(None), set())


class ResolveTests(unittest.TestCase):
    def setUp(self):
        # 每個 test 都 preset 名單，唔駛真係去 GitHub Raw
        pdf_proxy._cache_urls = pdf_proxy.allowed_urls_from_cache(CACHE)
        pdf_proxy._cache_loaded_at = float("inf")  # TTL 永遠新鮮

    def tearDown(self):
        pdf_proxy._cache_urls = set()
        pdf_proxy._cache_loaded_at = 0.0

    def test_rejects_unlisted_url_open_relay(self):
        with self.assertRaises(pdf_proxy.ProxyError) as caught:
            pdf_proxy.resolve_fetch_url("https://evil.example.com/x.pdf")
        self.assertEqual((caught.exception.status, caught.exception.code), (403, "not_a_listed_notice"))

    def test_rejects_bad_scheme_and_empty(self):
        for bad in ("ftp://www.klcscout.hk/x.pdf", "javascript:alert(1)", "", "x" * 3000):
            with self.subTest(bad=bad[:30]), self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.resolve_fetch_url(bad)
            self.assertEqual(caught.exception.status, 400)

    def test_accepts_raw_and_percent_encoded_forms(self):
        raw = "https://www.klcscout.hk/cportal/uploads/A 品酒工作坊.pdf"
        self.assertEqual(pdf_proxy.resolve_fetch_url(raw), raw)
        encoded = "https://www.klcscout.hk/cportal/uploads/A%20%E5%93%81%E9%85%92%E5%B7%A5%E4%BD%9C%E5%9D%8A.pdf"
        self.assertEqual(pdf_proxy.resolve_fetch_url(encoded), encoded)

    def test_drive_view_link_becomes_direct_download(self):
        out = pdf_proxy.resolve_fetch_url("https://drive.google.com/file/d/ABC-1_x/view")
        self.assertEqual(out, "https://drive.google.com/uc?export=download&id=ABC-1_x")

    def test_only_google_hosts_are_rewritten_to_drive(self):
        # 之前 [?&]id= 冇睇網域：灣仔 index.php?…&id=634 會變咗去 Drive 攞 id=634
        self.assertIsNone(pdf_proxy.drive_direct_url(WANCHAI))
        self.assertEqual(pdf_proxy.resolve_fetch_url(WANCHAI), WANCHAI)
        self.assertEqual(
            pdf_proxy.drive_direct_url("https://docs.google.com/uc?export=download&id=Q1-z"),
            "https://drive.google.com/uc?export=download&id=Q1-z",
        )
        self.assertIsNone(pdf_proxy.drive_direct_url("https://evil.example.com/file/d/ABC/view"))

    def test_cache_refresh_failure_fails_closed(self):
        pdf_proxy._cache_urls = set()
        pdf_proxy._cache_loaded_at = 0.0
        with patch("urllib.request.urlopen", side_effect=OSError("github down")):
            with self.assertRaises(OSError):
                pdf_proxy.resolve_fetch_url("https://www.klcscout.hk/notice/1")


class FetchPdfTests(unittest.TestCase):
    def test_oversized_pdf_gives_413(self):
        big = b"%PDF-1.7" + b"x" * (pdf_proxy.MAX_PDF_BYTES + 10)
        with patch("urllib.request.urlopen", return_value=FakeResp(big)):
            with self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.fetch_pdf("https://www.klcscout.hk/notice/1")
        self.assertEqual((caught.exception.status, caught.exception.code), (413, "pdf_too_large"))

    def test_html_permission_page_gives_415(self):
        with patch("urllib.request.urlopen", return_value=FakeResp(b"<html>permission denied</html>")):
            with self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.fetch_pdf("https://drive.google.com/uc?export=download&id=x")
        self.assertEqual((caught.exception.status, caught.exception.code), (415, "not_a_pdf"))

    def test_upstream_down_gives_502(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.fetch_pdf("https://www.klcscout.hk/notice/1")
        self.assertEqual((caught.exception.status, caught.exception.code), (502, "upstream_unreachable"))

    def test_small_pdf_passes_through(self):
        body = b"%PDF-1.4 tiny"
        with patch("urllib.request.urlopen", return_value=FakeResp(body)):
            self.assertEqual(pdf_proxy.fetch_pdf("https://www.klcscout.hk/notice/1"), body)

    def test_content_length_over_4mb_is_413_without_reading_body(self):
        body = b"%PDF-1.4 " + b"x" * 100
        headers = {"Content-Length": str(pdf_proxy.MAX_PDF_BYTES + 50)}
        with patch("urllib.request.urlopen", return_value=FakeResp(body, headers=headers)):
            with self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.fetch_pdf("https://www.klcscout.hk/notice/1")
        self.assertEqual(caught.exception.code, "pdf_too_large")
        self.assertEqual(caught.exception.extra.get("bytes"), pdf_proxy.MAX_PDF_BYTES + 50)

    def test_slice_never_returns_more_than_vercel_cap(self):
        body = b"%PDF-1.4\n" + b"y" * (pdf_proxy.MAX_PDF_BYTES * 2)
        with patch("urllib.request.urlopen", return_value=FakeResp(body, status=200)):
            data, eof = pdf_proxy.fetch_pdf_slice(
                "https://www.klcscout.hk/notice/1", 0, pdf_proxy.LOCAL_DRAW_MAX,
            )
        self.assertLessEqual(len(data), pdf_proxy.MAX_PDF_BYTES)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertFalse(eof)

    def test_slice_past_local_cap_is_rejected(self):
        with self.assertRaises(pdf_proxy.ProxyError) as caught:
            pdf_proxy.fetch_pdf_slice("https://www.klcscout.hk/notice/1", pdf_proxy.LOCAL_DRAW_MAX, 10)
        self.assertEqual(caught.exception.status, 400)

    def test_oversized_total_is_not_pulled_through_slices(self):
        headers = {"Content-Length": str(pdf_proxy.LOCAL_DRAW_MAX + 8)}
        body = b"%PDF-1.4 huge"
        with patch("urllib.request.urlopen", return_value=FakeResp(body, headers=headers, status=200)):
            with self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.fetch_pdf_slice("https://www.klcscout.hk/notice/1", 0, 1024)
        self.assertEqual((caught.exception.status, caught.exception.code), (413, "pdf_too_large"))


    def test_slice_body_read_error_is_502_not_503(self):
        with patch("urllib.request.urlopen", return_value=BrokenBodyResp()):
            with self.assertRaises(pdf_proxy.ProxyError) as caught:
                pdf_proxy.fetch_pdf_slice("https://www.klcscout.hk/notice/1", 0, 1024)
        self.assertEqual((caught.exception.status, caught.exception.code), (502, "upstream_unreachable"))


class HandlerTests(unittest.TestCase):
    def setUp(self):
        pdf_proxy._cache_urls = pdf_proxy.allowed_urls_from_cache(CACHE)
        pdf_proxy._cache_loaded_at = float("inf")

    def tearDown(self):
        pdf_proxy._cache_urls = set()
        pdf_proxy._cache_loaded_at = 0.0

    def test_200_streams_pdf_with_edge_cache_headers(self):
        body = b"%PDF-1.4 sample-bytes"
        from urllib.parse import quote
        u = quote("https://www.klcscout.hk/cportal/uploads/A 品酒工作坊.pdf", safe="")
        h = DummyHandler("/api/pdf-proxy?u=" + u)
        with patch("urllib.request.urlopen", return_value=FakeResp(body)):
            h.do_GET()
        self.assertEqual(h.status, 200)
        self.assertEqual(h.sent_headers.get("Content-Type"), "application/pdf")
        self.assertIn("s-maxage", h.sent_headers.get("Cache-Control", ""))
        self.assertEqual(h.wfile.getvalue(), body)

    def test_unlisted_url_returns_json_403(self):
        from urllib.parse import quote
        h = DummyHandler("/api/pdf-proxy?u=" + quote("https://evil.example.com/x.pdf", safe=""))
        h.do_GET()
        self.assertEqual(h.status, 403)
        payload = json.loads(h.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload["error"], "not_a_listed_notice")

    def test_slice_query_stays_under_4mb_and_marks_eof(self):
        body = b"%PDF-1.4 " + b"z" * 300
        from urllib.parse import quote
        h = DummyHandler("/api/pdf-proxy?u=" + quote("https://www.klcscout.hk/notice/1", safe="") + "&off=0&n=1000")
        with patch("urllib.request.urlopen", return_value=FakeResp(body, status=200)):
            h.do_GET()
        self.assertEqual(h.status, 200)
        out = h.wfile.getvalue()
        self.assertEqual(out, body)
        self.assertLessEqual(len(out), pdf_proxy.MAX_PDF_BYTES)
        self.assertEqual(h.sent_headers.get("X-Pdf-EOF"), "1")

    def test_cache_index_down_returns_503(self):
        pdf_proxy._cache_urls = set()
        pdf_proxy._cache_loaded_at = 0.0
        h = DummyHandler("/api/pdf-proxy?u=https%3A%2F%2Fwww.klcscout.hk%2Fnotice%2F1")
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            h.do_GET()
        self.assertEqual(h.status, 503)
        self.assertIn(b"cache_index_unavailable", h.wfile.getvalue())


class ServeLocalCompatTests(unittest.TestCase):
    """serve_local.py 借 pdf_proxy.handler.do_GET 嚟用，self 係 LocalHandler（唔係 pdf_proxy.handler 子類）。

    2026-09-24：_send_pdf 做咗 handler method，本機一 proxy PDF 就 AttributeError → 空回應。
    """

    def setUp(self):
        pdf_proxy._cache_urls = pdf_proxy.allowed_urls_from_cache(CACHE)
        pdf_proxy._cache_loaded_at = float("inf")

    def tearDown(self):
        pdf_proxy._cache_urls = set()
        pdf_proxy._cache_loaded_at = 0.0

    def _local_handler(self, path):
        import serve_local

        local_cls = serve_local.build_handler(object, object, pdf_proxy.handler)
        self.assertFalse(issubclass(local_cls, pdf_proxy.handler))

        class Probe(local_cls):
            def __init__(self, p):  # 唔起 socket
                self.path = p
                self.headers = {}
                self.wfile = io.BytesIO()
                self.request_version = "HTTP/1.1"
                self.status = None
                self.sent_headers = {}

            def send_response(self, code, message=None):  # noqa: N802
                self.status = code

            def send_header(self, key, value):  # noqa: N802
                self.sent_headers[key] = value

            def end_headers(self):  # noqa: N802
                pass

        return Probe(path)

    def test_full_pdf_and_slice_work_through_local_dev_server(self):
        from urllib.parse import quote

        body = b"%PDF-1.4 local-dev"
        u = quote("https://www.klcscout.hk/notice/1", safe="")
        for suffix in ("", "&off=0&n=1000"):
            with self.subTest(suffix=suffix or "full"):
                h = self._local_handler("/api/pdf-proxy?u=" + u + suffix)
                with patch("urllib.request.urlopen", return_value=FakeResp(body)):
                    h.do_GET()
                self.assertEqual(h.status, 200)
                self.assertEqual(h.sent_headers.get("Content-Type"), "application/pdf")
                self.assertEqual(h.wfile.getvalue(), body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
