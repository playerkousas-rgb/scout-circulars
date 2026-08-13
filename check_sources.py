#!/usr/bin/env python3
"""
健康檢查腳本（唯讀，不寫 cache / fingerprints）
================================================
對 sources.json 內每個來源跑一次 core.py 同款抓取 + 抽取邏輯，
回報每個來源的狀態：

  OK        抓得到頁面且抽到 ≥1 個資產
  EMPTY     頁面抓得到但抽不到資產（選擇器失效 / 網站改版 / 真的沒通告）
  FETCH_FAIL 完全抓不到（HTTP 錯誤 / 超時 / SSL / 被封）
  PW_ONLY   需要 Playwright 但本環境無瀏覽器（無法驗證）

用法:  python check_sources.py [來源名 ...]   # 不給參數 = 檢查全部
"""
from __future__ import annotations

import io
import json
import sys
import time
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import core
from bs4 import BeautifulSoup

# 本沙盒無法下載 Chromium：把 Playwright 路徑標記為不可用，
# 讓檢查走 requests fallback（與 core.py 在 PW 失敗時的行為一致）。
_PW_NOTE = []


def _pw_unavailable(name, config, url=None):
    _PW_NOTE.append(name)
    return None


core.fetch_with_playwright = _pw_unavailable


def check_one(name: str, config: dict, expected_empty: bool) -> dict:
    out = {"name": name, "url": config.get("url", ""), "type": config.get("type", "")}
    buf = io.StringIO()
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(buf):
            result = core.fetch_main_page(name, config)
    except Exception as e:
        out["status"] = "FETCH_FAIL"
        out["error"] = f"{type(e).__name__}: {e}"
        out["seconds"] = round(time.time() - t0, 1)
        out["log"] = buf.getvalue()[-800:]
        return out

    if result is None:
        out["status"] = "FETCH_FAIL"
        out["error"] = "fetch_main_page 回傳 None"
        out["seconds"] = round(time.time() - t0, 1)
        out["log"] = buf.getvalue()[-1500:]
        return out

    soup = BeautifulSoup(result.html, "html.parser")
    fp_sel = config.get("fingerprint_selector", "body")
    try:
        fp_nodes = soup.select(fp_sel) if fp_sel else []
        out["fingerprint_matches"] = len(fp_nodes)
    except Exception as e:
        out["fingerprint_matches"] = -1
        out["fingerprint_error"] = str(e)

    # 只做列表頁抽取，不深挖內頁（健康檢查要快）
    try:
        with contextlib.redirect_stdout(buf):
            assets = core.extract_assets_from_listing(
                name=name, soup=soup, page_url=result.url, config=config, max_detail_pages=0
            )
    except Exception as e:
        out["status"] = "EMPTY"
        out["error"] = f"extract exception: {type(e).__name__}: {e}"
        out["assets"] = 0
        out["seconds"] = round(time.time() - t0, 1)
        out["log"] = buf.getvalue()[-1500:]
        return out

    out["engine"] = result.engine
    out["status_code"] = result.status_code
    out["assets"] = len(assets)
    out["sample_titles"] = [(a.get("title") or "")[:40] for a in assets[:3]]
    out["sample_urls"] = [a.get("pdf_url", "")[:90] for a in assets[:2]]
    out["html_len"] = len(result.html)
    out["follow_detail_pages"] = core.should_follow_detail_pages(config)
    out["follow_listing_pages"] = bool(config.get("follow_listing_pages"))
    out["expected_empty"] = expected_empty
    out["seconds"] = round(time.time() - t0, 1)
    out["log_tail"] = buf.getvalue()[-400:]

    if assets:
        out["status"] = "OK"
    else:
        out["status"] = "EMPTY"
    return out


def main():
    with open(core.SOURCES_PATH, "r", encoding="utf-8") as f:
        root = json.load(f)
    sources = root.get("sources", {})
    expected_empty = set(root.get("_meta", {}).get("expected_empty_sources") or
                         json.load(open("cache.json")).get("_meta", {}).get("expected_empty_sources", []))

    only = sys.argv[1:]
    names = [n for n in sources if not only or n in only]

    results = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(check_one, n, sources[n], n in expected_empty): n for n in names}
        for fut in as_completed(futs):
            r = fut.result()
            results[r["name"]] = r
            mark = {"OK": "✅", "EMPTY": "🟡", "FETCH_FAIL": "❌"}.get(r["status"], "?")
            extra = f" assets={r.get('assets')}" if r["status"] != "FETCH_FAIL" else f" {r.get('error', '')[:60]}"
            print(f"{mark} {r['name']:<10} {r['status']:<10}{extra} ({r['seconds']}s)", flush=True)

    print("\n" + "═" * 70)
    ok = [n for n, r in results.items() if r["status"] == "OK"]
    empty = [n for n, r in results.items() if r["status"] == "EMPTY"]
    fail = [n for n, r in results.items() if r["status"] == "FETCH_FAIL"]
    print(f"總計 {len(results)} | ✅ OK {len(ok)} | 🟡 EMPTY {len(empty)} | ❌ FETCH_FAIL {len(fail)}")
    for n in empty:
        r = results[n]
        tag = " (expected_empty)" if r.get("expected_empty") else ""
        print(f"  🟡 {n}{tag}: fp_matches={r.get('fingerprint_matches')} html={r.get('html_len')}")
    for n in fail:
        r = results[n]
        print(f"  ❌ {n}: {r.get('error')}")

    with open("health_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n詳細報告已寫入 health_report.json")


if __name__ == "__main__":
    main()
