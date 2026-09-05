#!/usr/bin/env python3
"""
serve_local.py — 本機一次過開 index.html + /api/render
============================================================
Vercel 上面 /api/render.py 係 Python Function，本機用 `python -m http.server`
淨係得靜態檔，測試唔到「分享圖片」。呢個小伺服器模仿 Vercel 路由：

  /api/render?url=...   → 交畀 api/render.py 嘅 handler
  其他路徑              → 當靜態檔（index.html / errors.html / cache.json …）

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


def build_handler(render_handler):
    # 多重繼承：/api/render 行 render.handler 嘅 do_GET；其他路徑行 SimpleHTTPRequestHandler
    class LocalHandler(render_handler, SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            SimpleHTTPRequestHandler.__init__(self, *a, directory=ROOT, **kw)

        def _is_render(self):
            path = urlparse(self.path).path.rstrip("/")
            return path in ("/api/render", "/api/render.py")

        def do_GET(self):   # noqa: N802
            if self._is_render():
                return render_handler.do_GET(self)
            return SimpleHTTPRequestHandler.do_GET(self)

        def do_HEAD(self):   # noqa: N802
            return SimpleHTTPRequestHandler.do_HEAD(self)

        def do_OPTIONS(self):   # noqa: N802
            if self._is_render():
                return render_handler.do_OPTIONS(self)
            self.send_response(204)
            self.end_headers()

        def end_headers(self):
            # 本機開發：靜態檔唔好俾瀏覽器 cache 住舊 index.html
            if not self._is_render():
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
    if args.allow_private:
        render.ALLOW_PRIVATE = True

    # render.handler 係 BaseHTTPRequestHandler 子類；我哋借用佢嘅 do_GET / do_OPTIONS，
    # self 會係 LocalHandler 實例（同樣係 BaseHTTPRequestHandler），方法簽名相容。
    server = ThreadingHTTPServer((args.host, args.port), build_handler(render.handler))
    print(f"▶ http://localhost:{args.port}/index.html   （/api/render 已掛載"
          f"{'，允許內網' if args.allow_private else ''}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
