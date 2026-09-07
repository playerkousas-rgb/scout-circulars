#!/usr/bin/env python3
"""
serve_local.py — 本機一次過開 index.html + Vercel API
========================================================
Vercel 上面嘅 Python Function 用 `python -m http.server` 測唔到。呢個小
伺服器模仿需要的路由：

  /api/render?url=...       → api/render.py（PDF 圖片）
  /api/push-config           → api/push_config.py（公開 VAPID 狀態）
  /api/push-subscriptions    → api/push_subscriptions.py（匿名訂閱）
  其他路徑                   → 靜態檔（index.html / cache.json …）

用法：
  pip install pymupdf            # 或 pip install -r api/requirements.txt
  python serve_local.py                    # http://localhost:8000
  python serve_local.py --port 3000
  python serve_local.py --allow-private    # 容許 render 抓 127.0.0.1 之類（跑測試用）

--allow-private 只係本機測試用；Vercel 上永遠唔會開（防 SSRF）。
"""

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))


def build_handler(render_handler, push_config_handler, push_subscriptions_handler):
    # 多重繼承：需要的 /api/* 路由直接借用 Vercel handler；其他路徑行靜態檔。
    class LocalHandler(render_handler, SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            SimpleHTTPRequestHandler.__init__(self, *a, directory=ROOT, **kw)

        def _api_path(self):
            return urlparse(self.path).path.rstrip("/")

        def _is_render(self):
            return self._api_path() in ("/api/render", "/api/render.py")

        def _is_push_config(self):
            return self._api_path() in ("/api/push-config", "/api/push_config", "/api/push_config.py")

        def _is_push_subscriptions(self):
            return self._api_path() in ("/api/push-subscriptions", "/api/push_subscriptions", "/api/push_subscriptions.py")

        def do_GET(self):   # noqa: N802
            if self._is_render():
                return render_handler.do_GET(self)
            if self._is_push_config():
                return push_config_handler.do_GET(self)
            return SimpleHTTPRequestHandler.do_GET(self)

        def do_POST(self):  # noqa: N802
            if self._is_push_subscriptions():
                return push_subscriptions_handler.do_POST(self)
            self.send_error(404, "Not found")

        def do_HEAD(self):   # noqa: N802
            return SimpleHTTPRequestHandler.do_HEAD(self)

        def do_OPTIONS(self):   # noqa: N802
            if self._is_render():
                return render_handler.do_OPTIONS(self)
            if self._is_push_config():
                return push_config_handler.do_OPTIONS(self)
            if self._is_push_subscriptions():
                return push_subscriptions_handler.do_OPTIONS(self)
            self.send_response(204)
            self.end_headers()

        def end_headers(self):
            # 本機開發：靜態檔唔好俾瀏覽器 cache 住舊 index.html
            if not (self._is_render() or self._is_push_config() or self._is_push_subscriptions()):
                self.send_header("Cache-Control", "no-store")
            SimpleHTTPRequestHandler.end_headers(self)

        def log_message(self, fmt, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return LocalHandler


def main():
    ap = argparse.ArgumentParser(description="本機同時提供靜態頁 + /api/render")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--allow-private", action="store_true",
                    help="容許 /api/render 抓內網位址（只限本機測試）")
    args = ap.parse_args()

    if args.allow_private:
        os.environ["RENDER_ALLOW_PRIVATE"] = "1"

    import render   # api/render.py（要喺設定完環境變數之後先 import）
    import push_config
    import push_subscriptions
    if args.allow_private:
        render.ALLOW_PRIVATE = True

    # 各 handler 都係 BaseHTTPRequestHandler 子類；我哋借用其 do_* 方法，
    # self 會係 LocalHandler 實例，方法簽名相容。
    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(render.handler, push_config.handler, push_subscriptions.handler),
    )
    print(f"▶ http://localhost:{args.port}/index.html   （/api/render + /api/push-* 已掛載"
          f"{'，允許內網' if args.allow_private else ''}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
