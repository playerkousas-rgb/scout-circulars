#!/usr/bin/env python3
"""
test_render_api.py — /api/render（PDF → 圖片）離線測試
============================================================
運行：pip install pymupdf && python test_render_api.py

驗證：
  1. 網址清理：只收 http(s)、中文/空格 encode、Drive 轉直鏈、已 encode 嘅唔會 double-encode
  2. SSRF 防護：內網 / loopback / link-local / CGNAT 一律擋
  3. 轉圖：手砌一份「冇內嵌 CJK 字型」PDF，畫出嚟一定要有筆劃（唔係空白 / 亂碼豆腐）
  4. 錯誤處理：非 PDF、頁數超出、密碼保護 → 正確錯誤碼
  5. 整個 HTTP handler：起一個本機 PDF 伺服器，走一次完整流程（含 header / cache-control）
全部離線，唔會打任何區會網站。
"""

import http.server
import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))
os.environ["RENDER_ALLOW_PRIVATE"] = "1"    # 測試要抓 127.0.0.1；render.ALLOW_PRIVATE 亦會照住

import render  # noqa: E402
from render import RenderError  # noqa: E402

passed = failed = 0


def test(name, got, want):
    global passed, failed
    ok = got == want
    print(f"{'✅' if ok else '❌'} {name}")
    if not ok:
        print(f"   期望: {want!r}\n   實際: {got!r}")
        failed += 1
    else:
        passed += 1


def expect_error(name, fn, code):
    global passed, failed
    try:
        fn()
    except RenderError as e:
        test(name, e.code, code)
        return
    print(f"❌ {name}\n   期望拋 RenderError({code})，實際冇拋")
    failed += 1


def make_cjk_pdf(pages=1, text="筲箕灣區 幼童軍繩結章訓練班"):
    """手砌一份用 Adobe CNS1 CID 字型（唔內嵌）嘅 PDF —— Word / 舊排版軟件出嘅通告就係咁。"""
    hexs = text.encode("utf-16-be").hex().upper()
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages)).encode()
    objs.append(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % pages)
    font_obj_no = 3 + pages * 2
    for i in range(pages):
        content = f"BT /F1 28 Tf 60 740 Td <{hexs}> Tj ET BT /F1 14 Tf 60 700 Td <{('第%d頁' % (i + 1)).encode('utf-16-be').hex().upper()}> Tj ET".encode()
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font_obj_no, 4 + i * 2))
        objs.append(b"<< /Length %d >>stream\n" % len(content) + content + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /MSung-Light /Encoding /UniCNS-UCS2-H /DescendantFonts [%d 0 R] >>" % (font_obj_no + 1))
    objs.append(b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /MSung-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (CNS1) /Supplement 0 >> /FontDescriptor %d 0 R /DW 1000 >>" % (font_obj_no + 2))
    objs.append(b"<< /Type /FontDescriptor /FontName /MSung-Light /Flags 4 /FontBBox [0 -200 1000 900] /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def main():
    # ── 1. 網址清理 ──
    test("Drive /file/d/<id>/view → uc?export=download",
         render.normalize_pdf_url("https://drive.google.com/file/d/1D3cQigfmJFmBnjgg-jWweJSLsHlqJrQa/view"),
         "https://drive.google.com/uc?export=download&id=1D3cQigfmJFmBnjgg-jWweJSLsHlqJrQa")
    test("中文 + 空格 percent-encode",
         render.normalize_pdf_url("https://chaiwanscout.org.hk/chw2//upload/Invitation Letter_旅團.pdf"),
         "https://chaiwanscout.org.hk/chw2//upload/Invitation%20Letter_%E6%97%85%E5%9C%98.pdf")
    test("已 encode 嘅唔會 double-encode",
         render.normalize_pdf_url("https://www.scout.org.hk/uploads/acr_%E7%99%BC.pdf"),
         "https://www.scout.org.hk/uploads/acr_%E7%99%BC.pdf")
    test("query string 保留", render.normalize_pdf_url("https://hkscout-ekr.org/circulars/download/?wpdmdl=5637"),
         "https://hkscout-ekr.org/circulars/download/?wpdmdl=5637")
    expect_error("file:// 拒絕", lambda: render.normalize_pdf_url("file:///etc/passwd"), "bad_url")
    expect_error("javascript: 拒絕", lambda: render.normalize_pdf_url("javascript:alert(1)"), "bad_url")
    expect_error("空 url 拒絕", lambda: render.normalize_pdf_url(""), "bad_url")
    expect_error("冇 host 拒絕", lambda: render.normalize_pdf_url("https:///x.pdf"), "bad_url")

    # ── 2. SSRF ──
    for host in ["127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
                 "[::1]", "0.0.0.0", "100.64.0.1", "foo.local", "api.localhost"]:
        expect_error(f"SSRF：{host} 擋", lambda h=host: render.assert_public_host(h, allow_private=False), "bad_url")
    test("is_public_ip 8.8.8.8", render.is_public_ip("8.8.8.8"), True)
    test("is_public_ip ::ffff:127.0.0.1（IPv4-mapped loopback）", render.is_public_ip("::ffff:127.0.0.1"), False)
    test("is_public_ip fd00::1（ULA）", render.is_public_ip("fd00::1"), False)
    test("is_public_ip 2606:4700::1111", render.is_public_ip("2606:4700::1111"), True)

    # ── 3. 轉圖（CJK 非內嵌字型）──
    pdf = make_cjk_pdf(pages=2)
    jpeg, count, w, h = render.render_page(pdf, 1, 130)
    test("JPEG magic bytes", jpeg[:3], b"\xff\xd8\xff")
    test("頁數 = 2", count, 2)
    test("A4 @130dpi 闊度 ≈ 1074px", abs(w - 1074) <= 2, True)
    # 畫咗嘢出嚟：用 PyMuPDF 重開圖片數深色像素（唔靠 PIL）
    import pymupdf
    pix = pymupdf.Pixmap(jpeg)
    samples = pix.samples          # property 每次讀都會複製成個 buffer，只讀一次
    dark = sum(1 for b in samples[::15] if b < 100)
    test("畫到中文字（深色像素 > 300）", dark > 300, True)
    # 豆腐（notdef 方格）會係一個個空心框，像素會比正常字多好多 —— 粗略上限保護
    test("唔係全黑 / 豆腐（深色像素 < 20000）", dark < 20000, True)
    jpeg2, _, _, _ = render.render_page(pdf, 2, 130)
    test("第 2 頁畫得出而且同第 1 頁唔同", jpeg2[:3] == b"\xff\xd8\xff" and jpeg2 != jpeg, True)
    expect_error("第 3 頁 → page_out_of_range", lambda: render.render_page(pdf, 3), "page_out_of_range")
    expect_error("第 0 頁 → page_out_of_range", lambda: render.render_page(pdf, 0), "page_out_of_range")
    expect_error("非 PDF bytes → not_pdf", lambda: render.render_page(b"<html>hi</html>", 1), "not_pdf")
    # dpi 上下限
    _, _, w_lo, _ = render.render_page(pdf, 1, 10)
    _, _, w_hi, _ = render.render_page(pdf, 1, 999)
    test("dpi 下限 60 生效", abs(w_lo - 496) <= 2, True)
    test("dpi 上限 200 生效", abs(w_hi - 1653) <= 2, True)
    # 密碼保護
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    enc = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    expect_error("密碼 PDF → encrypted", lambda: render.render_page(enc, 1), "encrypted")

    # ── 4. 完整 HTTP 流程 ──
    # 測試期間將上限縮到 1MB：唔使真係傳 25MB，而且 fetch 中途斬線嗰下唔會拖慢成個測試
    render.MAX_PDF_BYTES = 1 * 1024 * 1024
    files = {
        "/a.pdf": (pdf, "application/pdf"),
        "/page.html": (b"<html><body>not a pdf</body></html>", "text/html"),
        "/big.pdf": (b"%PDF-1.4" + b"0" * (render.MAX_PDF_BYTES + 10), "application/pdf"),
        "/redir": None,   # 302 → /a.pdf
    }

    class Upstream(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError):
                pass   # render 讀到超過上限會即刻斬線，呢邊唔使嘈

        def do_GET(self):
            if self.path == "/redir":
                self.send_response(302)
                self.send_header("Location", "/a.pdf")
                self.end_headers()
                return
            if self.path not in files:
                self.send_response(404)
                self.end_headers()
                return
            body, ctype = files[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    up_port = up.server_address[1]
    threading.Thread(target=up.serve_forever, daemon=True).start()

    api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), render.handler)
    api_port = api.server_address[1]
    threading.Thread(target=api.serve_forever, daemon=True).start()

    def call(qs):
        req = urllib.request.Request(f"http://127.0.0.1:{api_port}/api/render?{qs}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    from urllib.parse import urlencode
    U = f"http://127.0.0.1:{up_port}"

    st, hd, body = call(urlencode({"url": f"{U}/a.pdf", "page": 1}))
    test("HTTP 200 image/jpeg", (st, hd.get("Content-Type")), (200, "image/jpeg"))
    test("X-Pdf-Pages = 2", hd.get("X-Pdf-Pages"), "2")
    test("成功結果有 CDN cache（s-maxage=86400）", "s-maxage=86400" in hd.get("Cache-Control", ""), True)
    test("CORS header", hd.get("Access-Control-Allow-Origin"), "*")
    test("Expose X-Pdf-Pages 俾前端讀", "X-Pdf-Pages" in hd.get("Access-Control-Expose-Headers", ""), True)

    st, hd, body = call(urlencode({"url": f"{U}/a.pdf", "page": 2}))
    test("page=2 → 200 + X-Pdf-Page=2", (st, hd.get("X-Pdf-Page")), (200, "2"))

    st, hd, body = call(urlencode({"url": f"{U}/a.pdf", "page": 3}))
    test("page=3 → 404 page_out_of_range", (st, json.loads(body)["error"]), (404, "page_out_of_range"))

    st, hd, body = call(urlencode({"url": f"{U}/page.html"}))
    test("HTML → 415 not_pdf", (st, json.loads(body)["error"]), (415, "not_pdf"))
    test("永久錯誤都有短 cache（唔使再問原站）", "s-maxage=3600" in hd.get("Cache-Control", ""), True)

    st, hd, body = call(urlencode({"url": f"{U}/nope.pdf"}))
    test("原站 404 → 502 fetch_failed", (st, json.loads(body)["error"]), (502, "fetch_failed"))
    test("暫時性錯誤 cache 好短", "s-maxage=120" in hd.get("Cache-Control", ""), True)

    st, hd, body = call(urlencode({"url": f"{U}/big.pdf"}))
    test("超大檔 → 413 too_large", (st, json.loads(body)["error"]), (413, "too_large"))

    st, hd, body = call(urlencode({"url": f"{U}/redir"}))
    test("跟 302 redirect 後成功轉圖", (st, hd.get("Content-Type")), (200, "image/jpeg"))

    st, hd, body = call(urlencode({"url": f"http://127.0.0.1:1/x.pdf"}))
    test("連唔到原站 → 502 fetch_failed", (st, json.loads(body)["error"]), (502, "fetch_failed"))

    st, hd, body = call("")
    test("冇 url → 400 bad_url", (st, json.loads(body)["error"]), (400, "bad_url"))

    st, hd, body = call(urlencode({"url": f"{U}/a.pdf", "page": "abc", "dpi": "xyz"}))
    test("page/dpi 亂入 → 用預設值照樣 200", st, 200)

    # 關閉 allow_private 之後，內網一定要擋（模擬 Vercel 上嘅情況）
    render.ALLOW_PRIVATE = False
    st, hd, body = call(urlencode({"url": f"{U}/a.pdf"}))
    test("生產模式（唔允許內網）→ 400 bad_url", (st, json.loads(body)["error"]), (400, "bad_url"))
    render.ALLOW_PRIVATE = True

    up.shutdown()
    api.shutdown()

    print(f"\n{'🎉 全部通過' if not failed else f'❌ {failed} 項失敗'}（{passed}/{passed + failed}）")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
