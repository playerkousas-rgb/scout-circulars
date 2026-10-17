#!/usr/bin/env python3
"""剷走壁峰區 6 筆標題嘅「Drive, 」前綴（Google Sites 嵌入 Drive 檔嘅介面字眼）。

背景：壁峰區嘅 Google Sites 用 Drive 嵌入通告，連結文字係「Drive, <檔名>」，
爬蟲照字面收，於是 6 筆通告標題開頭多咗「Drive, 」。全 repo 得壁峰區中招。

同一條規則已經加咗落 `core.clean_title()`（日後入庫自動剷），呢個腳本只係清
已經寫入 `cache.json` / `enrich.json` 嘅 6 筆舊資料——data 同 notices 兩邊、
以及 enrich 嘅 title 都要同步，否則前端同 IG Story 會出兩個名。

用法：python fix_pikfung_titles_2026_10_17.py --dry-run
      python fix_pikfung_titles_2026_10_17.py
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = "壁峰區"
REVIEW_DATE = "2026-10-17"
# 同 core.clean_title() 入面嗰條一致（唔 import core：呢度唔想拉埋爬蟲依賴）
DRIVE_PREFIX = re.compile(r"^\s*Drive\s*,\s*", re.I)


def apply_review(cache, enrich):
    """Return copies plus change counts; no I/O or external side effects."""
    cache, enrich = copy.deepcopy(cache), copy.deepcopy(enrich)
    grouped = cache.setdefault("data", {}).setdefault(SOURCE, [])
    notices = cache.setdefault("notices", [])
    fixed = []

    for row in grouped:
        title = str(row.get("title") or "")
        cleaned = DRIVE_PREFIX.sub("", title).strip()
        if not cleaned or cleaned == title:
            continue
        url = str(row.get("pdf_url") or row.get("url") or "")
        row["title"] = cleaned
        for item in notices:
            if item.get("source_site") == SOURCE and str(item.get("pdf_url") or "") == url:
                item["title"] = cleaned
        entry = enrich.get(url)
        if isinstance(entry, dict) and entry.get("title"):
            entry["title"] = DRIVE_PREFIX.sub("", str(entry["title"])).strip()
        fixed.append({"from": title, "to": cleaned})

    if fixed:
        grouped.sort(key=lambda x: (str(x.get("date") or x.get("captured_date") or ""), str(x.get("title") or "")), reverse=True)
        notices.sort(key=lambda x: (str(x.get("captured_date") or ""), str(x.get("source_site") or ""), str(x.get("title") or "")), reverse=True)
    return cache, enrich, {"titles_fixed": len(fixed), "changes": fixed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cp, ep = ROOT / "cache.json", ROOT / "enrich.json"
    old_cache, old_enrich = json.loads(cp.read_text()), json.loads(ep.read_text())
    cache, enrich, counts = apply_review(old_cache, old_enrich)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    if not args.dry_run:
        for path, old, new in ((cp, old_cache, cache), (ep, old_enrich, enrich)):
            if new != old:
                path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
