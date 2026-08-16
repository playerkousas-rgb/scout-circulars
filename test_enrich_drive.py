#!/usr/bin/env python3
"""enrich.py Google Drive 支援測試

原則：**寧願唔抽，都唔好抽錯。**

Drive 連結（/file/d/<id>/view）本身係 HTML 檢視頁，直接下載會攞到 HTML。
要轉成 uc?export=download&id=<id> 先攞到檔案。但轉換成功唔代表攞到 PDF ——
Drive 會回權限頁、病毒掃描中介頁、登入頁，全部都係 HTML。

所以有兩道閘：
  1. 認唔出 URL 格式 → 唔猜，直接放棄
  2. 下載返嚟唔係 %PDF 開頭 → 當 not_pdf 丟棄，唔會塞 HTML 落去當通告內容

執行：python test_enrich_drive.py
"""
import sys

import enrich

FAILED = []


def check(desc, cond):
    print(f"{'✅' if cond else '❌'} {desc}")
    if not cond:
        FAILED.append(desc)


print("── 1. URL 轉換：認得出嘅格式 ──")
for url, want_id in [
    ("https://drive.google.com/file/d/1Um6PXr5OXZa5bg4zJIPQIrVJDs-mTdh6/view",
     "1Um6PXr5OXZa5bg4zJIPQIrVJDs-mTdh6"),
    ("https://drive.google.com/file/d/AAA/view?usp=sharing", "AAA"),
    ("https://drive.google.com/file/d/BBB/preview", "BBB"),
    ("https://drive.google.com/open?id=CCC", "CCC"),
    ("https://docs.google.com/uc?id=DDD&export=download", "DDD"),
]:
    got = enrich.drive_direct_url(url)
    check(f"{url[:52]}… → id={want_id}",
          got is not None and f"id={want_id}" in got and "export=download" in got)

print("\n── 2. 認唔出就唔好猜（寧願唔抽）──")
for url in [
    "https://drive.google.com/drive/folders/FOLDERID",   # 資料夾唔係單一檔案
    "https://example.org/notice.pdf",                    # 唔係 Drive
    "https://drive.google.com/",                         # 冇 id
]:
    check(f"{url[:52]}… → None（唔猜）", enrich.drive_direct_url(url) is None)

print("\n── 3. 下載返嚟唔係 PDF 就要丟棄，唔可以當通告內容 ──")
_orig = enrich.download

fake_bodies = {
    "html_permission": b"<html><body>You need access to view this file</body></html>",
    "html_scan": b"<html><body>Google Drive can't scan this file for viruses</body></html>",
    "html_login": b"<!DOCTYPE html><html><head><title>Sign in</title></head></html>",
}
for name, body in fake_bodies.items():
    enrich.download = lambda u, timeout=25, _b=body: _b
    res = enrich.enrich_one("https://drive.google.com/file/d/XYZ/view", use_ocr=False)
    check(f"Drive 回 {name} → not_pdf 丟棄，唔會抽到欄位",
          res.get("_error") == "not_pdf"
          and not res.get("deadline") and not res.get("audience") and not res.get("fee"))

# 認唔出格式：連下載都唔應該試
called = {"n": 0}
def _should_not_run(u, timeout=25):
    called["n"] += 1
    return b"%PDF-1.4 whatever"
enrich.download = _should_not_run
res = enrich.enrich_one("https://drive.google.com/drive/folders/FOLDERID", use_ocr=False)
check("認唔出格式 → 標記 drive_unrecognized 且完全冇發出下載請求",
      res.get("_error") == "drive_unrecognized" and called["n"] == 0)

# 下載失敗要照樣安全收場
def _boom(u, timeout=25):
    raise TimeoutError("timed out")
enrich.download = _boom
res = enrich.enrich_one("https://drive.google.com/file/d/XYZ/view", use_ocr=False)
check("下載拋錯 → 記低 error，唔會炸咗成個流程",
      str(res.get("_error", "")).startswith("download:"))

enrich.download = _orig

print("\n── 4. collect_targets 收得返 Drive 連結 ──")
import json
from pathlib import Path

p = Path(__file__).with_name("cache.json")
if p.exists():
    cache = json.loads(p.read_text(encoding="utf-8"))
    targets = enrich.collect_targets(cache, "2026-08-16", False, True)
    urls = {t[2] for t in targets}
    drive_n = sum(1 for u in urls if "drive.google" in u or "docs.google" in u)
    hks = [t for t in targets if t[0] == "港島南區"]
    check(f"backfill 收到 Drive 連結（{drive_n} 條，之前係 0）", drive_n > 0)
    check(f"港島南區 {len(hks)} 筆已納入（之前完全冇 enrich）", len(hks) > 0)
    # 資料夾連結唔應該入 targets
    check("Drive 資料夾連結唔會入 targets",
          not any("/drive/folders/" in u for u in urls))
else:
    print("⏭  搵唔到 cache.json，略過")

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗")
    sys.exit(1)
print("🎉 全部通過")
