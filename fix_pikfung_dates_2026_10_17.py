#!/usr/bin/env python3
"""Re-date 壁峰區 notices the 2026-10-17 crawl stamped as "today".

背景：2026-10-16 嘅 `follow_listing_pages` + `extract_drive_embeds` 改動令壁峰區
第一次掃埋四個「支部通訊」子頁。嗰啲 Google Sites 頁面冇任何日期，所以爬蟲按
「盲信日期」慣例將 11 個 Drive 檔案一律當 2026-10-17 新通告入庫，結果今日嘅
12 張新通告入面有 11 張係壁峰區，當中大部份其實係舊文件。

呢個腳本做嘅係「搬返去應該出現嘅日子」——離線、冇網絡、冇通知、冇發佈：

* 2025 年文件（`SINK`）：直接沉底到 `SINK_DATE`，任何時間視窗（最長 180 日）
  都唔會再出現，記錄照留（記錄只增不減）。
* 其餘：照人工覆核嘅「原文發出日期」改 `date` / `captured_date` / `published_date`。
* 一律加 `backfilled_at` + `suppress_notifications=True`：
  - `merge_reviewed_backfills()` 認得呢對欄位，remote cache refresh 唔會沖走；
  - `notify.find_new_notices()` / `find_catchup_notices()` 同 `story_queue` 會跳過
    （今日通知已經發出，舊文件亦唔應該出 Story）。

每一次改動都寫低憑據入 `enrich.json`（`date_evidence` / `reviewed_at`），
等日後覆核知道日期係點嚟。

Usage: python fix_pikfung_dates_2026_10_17.py --dry-run
       python fix_pikfung_dates_2026_10_17.py
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
REVIEW_DATE = "2026-10-17"
SOURCE = "壁峰區"
REGION = "新界東地域"
CAPTURE_DATE = "2026-10-17"   # 被誤當「今日」嘅嗰一批
SINK_DATE = "2025-01-01"      # 2025 文件沉底日：低過最長（180 日）時間視窗
SINK = "sink"                 # 標記：沉底
PENDING = ""                  # 標記：等緊人工核實嘅發出日期

# Drive ID, 修正後日期（"sink" = 沉底；"" = 未核實，跳過）, 標題, 憑據
# 日期全部由用家逐份核實原文後提供（2026-10-17）。
CORRECTIONS = [
    # ── 2025 年文件：直接沉到看不見 ──
    ("1bp-6wE5HwCfIaWB3XnvnvIspdYLudGhC", SINK, "童軍支部會員章 童軍成員免受傷害 集會編排 2025", "2025 年文件"),
    ("12WHFp8lCNZWiHBfewCSfxCnBz2aEzd4G", SINK, "深資童軍支部會員章 童軍成員免受傷害 集會編排 2025", "2025 年文件"),
    ("1AJaN0QR1ggz_hRjhtiIFgk8VZXbU5P2p", SINK, "樂行童軍支部會員章 童軍成員免受傷害 集會編排 2025", "2025 年文件"),
    ("1UWAClszPoG_we45mH4b4T7DD6aeI8XMk", SINK, "幼童軍支部會員章 童軍成員免受傷害 集會編排 2025", "2025 年文件"),
    ("1Ft1AGYQBqdpYZ2wBpqNjFi1JqjdUEy6y", SINK, "小童軍支部團員章 童軍成員免受傷害 集會編排 2025", "2025 年文件"),
    ("1aIWdp8VOmuV6K5cCOKcZ_oNgJnejgXSp", SINK, "小童軍領袖手冊", "2025 年文件"),
    # ── 用家核實咗發出日期 ──
    ("1dDN6BU9Z3s7tuz_nss9OEFuTst85wC1x", "2026-02-01", "小童軍活動指引2026",
     "原文發出日期：2026 年 2 月（用家淨核實到月份，以月初 2026-02-01 入庫）"),
    ("1mnGeK0M-UNjxtdi1-PU5xaSX-rVoG_tC", "2026-06-09", "2026 童軍先修章訓練班", "原文發出日期：2026-06-09"),
    ("12TUR24RzmsY82IqMOdu0QgHEy01VVfIH", "2026-06-10", "2026-27 小童軍親子活動—懷舊食物工作坊", "原文發出日期：2026-06-10"),
    ("1fApaZu3lZlY3UhD3B5tFLx5TVt8aP_8A", "2026-08-03", "PF 原野生活知識工作坊 A-101", "原文發出日期：2026-08-03"),
    ("1AiwtKkkP8N_tkDVJ-Mdps2VoF3sxMWfn", "2026-10-15", "PFD2627VS004 政制探究及民政訓練班", "原文發出日期：2026-10-15"),
]


def drive_url(drive_id: str) -> str:
    return f"https://drive.google.com/file/d/{drive_id}/view"


def identity(url: str) -> str:
    """Match Drive paths independently of host, query and trailing slash."""
    return urlsplit(str(url or "")).path.rstrip("/")


def apply_review(cache, enrich):
    """Return copies plus change counts; no I/O or external side effects."""
    cache, enrich = copy.deepcopy(cache), copy.deepcopy(enrich)
    grouped = cache.setdefault("data", {}).setdefault(SOURCE, [])
    notices = cache.setdefault("notices", [])
    moved, pending = [], []

    for drive_id, date, label, evidence in CORRECTIONS:
        target = identity(drive_url(drive_id))
        if date == PENDING:
            pending.append(label)
            continue
        effective = SINK_DATE if date == SINK else date
        rows = [x for x in grouped if identity(x.get("pdf_url") or x.get("url")) == target]
        for row in rows:
            # 只郁 2026-10-17 嗰一批，而且只郁一次（冇 backfilled_at 先郁）。
            if str(row.get("captured_date") or "")[:10] != CAPTURE_DATE or row.get("backfilled_at"):
                continue
            row["date"] = effective
            row["captured_date"] = effective
            row["published_date"] = effective
            row["region"] = REGION
            row["backfilled_at"] = REVIEW_DATE
            row["suppress_notifications"] = True
            for item in notices:
                if identity(item.get("pdf_url")) == target and item.get("source_site") == SOURCE:
                    item["captured_date"] = effective
                    item["published_date"] = effective
                    item["backfilled_at"] = REVIEW_DATE
                    item["suppress_notifications"] = True
            url = str(row.get("pdf_url") or row.get("url") or "")
            if url:
                entry = enrich.get(url)
                if isinstance(entry, dict) and entry.get("reviewed_at") != REVIEW_DATE:
                    enrich[url] = dict(
                        entry,
                        method="manual-reviewed-original",
                        error="",
                        reviewed_at=REVIEW_DATE,
                        date_evidence=(f"人工覆核：{evidence}；無發出日期，沉底至 {SINK_DATE}"
                                       if date == SINK else evidence),
                        evidence_url=url,
                    )
            moved.append({"title": row.get("title", ""), "date": effective, "note": label})

    if moved:
        grouped.sort(key=lambda x: (str(x.get("date") or x.get("captured_date") or ""), str(x.get("title") or "")), reverse=True)
        notices.sort(key=lambda x: (str(x.get("captured_date") or ""), str(x.get("source_site") or ""), str(x.get("title") or "")), reverse=True)
        if "total_notices" in cache.get("meta", {}):
            cache["meta"]["total_notices"] = len(notices)
    return cache, enrich, {"re_dated": len(moved), "pending": pending}


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
