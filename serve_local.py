#!/usr/bin/env python3
"""
serve_local.py — 本機一次過開 index.html + Vercel API
========================================================
Vercel 上面嘅 Python Function 用 `python -m http.server` 測唔到。呢個小
伺服器模仿需要的路由：

  /api/push-config           → api/push_config.py（公開 VAPID 狀態）
  /api/push-subscriptions    → api/push_subscriptions.py（匿名訂閱）
  /api/pdf-proxy             → api/pdf_proxy.py（PDF byte bridge，畀 pdf.js 內容出圖）
  其他路徑                   → 靜態檔（index.html / cache.json …）

用法：
  python serve_local.py                    # http://localhost:8000
  python serve_local.py --port 3000

歷史：2026-09-16 之前呢度仲掛載 server-side render（PDF → 圖片）；已移除
（見 README「Vercel 用量」）。2026-09-21 起 PDF→圖搬到用戶瀏覽器（pdf.js），
/api/pdf-proxy 只係 stdlib byte bridge，唔畫圖、唔儲存。
"""

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))


def build_handler(push_config_handler, push_subscriptions_handler, pdf_proxy_handler):
    # 多重繼承：需要的 /api/* 路由直接借用 Vercel handler；其他路徑行靜態檔。
    class LocalHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            SimpleHTTPRequestHandler.__init__(self, *a, directory=ROOT, **kw)

        def _api_path(self):
            return urlparse(self.path).path.rstrip("/")

        def _is_push_config(self):
            return self._api_path() in ("/api/push-config", "/api/push_config", "/api/push_config.py")

        def _is_push_subscriptions(self):
            return self._api_path() in ("/api/push-subscriptions", "/api/push_subscriptions", "/api/push_subscriptions.py")

        def _is_pdf_proxy(self):
            return self._api_path() in ("/api/pdf-proxy", "/api/pdf_proxy", "/api/pdf_proxy.py")

        def do_GET(self):   # noqa: N802
            if self._is_push_config():
                return push_config_handler.do_GET(self)
            if self._is_pdf_proxy():
                return pdf_proxy_handler.do_GET(self)
            return SimpleHTTPRequestHandler.do_GET(self)

        def do_POST(self):  # noqa: N802
            if self._is_push_subscriptions():
                return push_subscriptions_handler.do_POST(self)
            self.send_error(404, "Not found")

        def do_HEAD(self):   # noqa: N802
            return SimpleHTTPRequestHandler.do_HEAD(self)

        def do_OPTIONS(self):   # noqa: N802
            if self._is_push_config():
                return push_config_handler.do_OPTIONS(self)
            if self._is_push_subscriptions():
                return push_subscriptions_handler.do_OPTIONS(self)
            if self._is_pdf_proxy():
                return pdf_proxy_handler.do_OPTIONS(self)
            self.send_response(204)
            self.end_headers()

        def end_headers(self):
            # 本機開發：靜態檔唔好俾瀏覽器 cache 住舊 index.html
            # pdf-proxy 靠自己嘅長 cache header 俾 edge/CDN cache，唔好冚佢
            if not (self._is_push_config() or self._is_push_subscriptions() or self._is_pdf_proxy()):
                self.send_header("Cache-Control", "no-store")
            SimpleHTTPRequestHandler.end_headers(self)

        def log_message(self, fmt, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return LocalHandler


def main():
    ap = argparse.ArgumentParser(description="本機同時提供靜態頁 + /api/push-*")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    import pdf_proxy
    import push_config
    import push_subscriptions

    # 各 handler 都係 BaseHTTPRequestHandler 子類；我哋借用其 do_* 方法，
    # self 會係 LocalHandler 實例，方法簽名相容。
    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(push_config.handler, push_subscriptions.handler, pdf_proxy.handler),
    )
    print(f"▶ http://localhost:{args.port}/index.html   （/api/push-* 已掛載）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
