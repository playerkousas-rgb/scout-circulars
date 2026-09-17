#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_staff_recruit_categories.py — 2026-09-18 馬拉松分類事故修復
=====================================================================

背景：渣打香港馬拉松2027「工作人員大招募」被分類做「比賽」——listing 標題
寫明係招募工作人員，但分類當時只睇 PDF 標題（「特別通告第18/26號」），
內文滿係「比賽」就中招。subscription_tagging.py 已新增規則
（STAFF_RECRUIT_TITLE_TERMS：標題有工作人員／義工／籌委會招募 → 一定係服務），
CLASSIFIER_VERSION bump 到 3.1。

呢個腳本一次過修復存量資料，唔重新下載任何 PDF：

  1. enrich.json 入面，cache listing 標題（或 enrich 標題）命中招募規則、
     而現時分類唔係「只有服務」嘅記錄 → 用新分類器重算
     （title=enrich 核實標題，listing_title=cache listing 標題，text=""——
     規則命中時分類結果同內文無關，服務唯一）；
  2. cache 入面有招募標題但冇 enrich 記錄嘅非 PDF 通告（例如馬拉松嘅
     兩張 .xls 報名表格，enrich.py 從來唔處理非 PDF）→ 補返 手動服務記錄，
     等前端唔好顯示「未分類」。

只會寫 enrich.json，唔掂 cache.json。跑一次就夠，保留返嚟做審計。
用法：python fix_staff_recruit_categories.py [--dry-run]
"""

import argparse
import datetime
import json
import sys

sys.path.insert(0, ".")

from enrich import ENRICH_FILE, ENRICH_VERSION, CACHE_FILE  # noqa: E402
from subscription_tagging import (  # noqa: E402
    CLASSIFIER_VERSION,
    STAFF_RECRUIT_TITLE_TERMS,
    _term_hits,
    extract_subscription_metadata,
)

NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def notice_url(item):
    return str(item.get("pdf_url") or item.get("url") or "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="只報告，唔寫 enrich.json")
    args = ap.parse_args()

    with open(CACHE_FILE, encoding="utf-8") as fh:
        cache = json.load(fh)
    with open(ENRICH_FILE, encoding="utf-8") as fh:
        enrich = json.load(fh)

    # cache listing 標題：分類修復嘅主要線索
    listing_by_url = {}
    for item in cache.get("notices") or []:
        url = notice_url(item)
        title = str(item.get("title") or "").strip()
        if url and title:
            listing_by_url[url] = (title, str(item.get("source_site") or ""))

    fixed, manual, unchanged = [], [], []

    # ── 1. 修正現有 enrich 記錄 ──────────────────────────────
    for url, entry in enrich.items():
        if not isinstance(entry, dict):
            continue
        cache_title, _src = listing_by_url.get(url, ("", ""))
        candidate_titles = " ".join({str(entry.get("title") or ""), cache_title})
        if not _term_hits(candidate_titles, STAFF_RECRUIT_TITLE_TERMS):
            continue
        current_ids = sorted(str(c.get("id") or "") for c in entry.get("categories") or [])
        new_meta = extract_subscription_metadata(
            entry.get("title") or cache_title,
            "",  # 規則命中時分類只由標題決定；唔為修復而重新下載 PDF
            entry.get("audience") or "",
            source=entry.get("source") or _src,
            listing_title=cache_title or entry.get("title") or "",
        )
        new_ids = sorted(str(c.get("id") or "") for c in new_meta["categories"])
        if current_ids == new_ids and new_ids == ["service"] \
                and entry.get("classifier_version") == CLASSIFIER_VERSION:
            unchanged.append(url)
            continue
        if args.dry_run:
            fixed.append((url, current_ids, new_ids))
            continue
        entry["categories"] = new_meta["categories"]
        entry["subscription_tags"] = new_meta["subscription_tags"]
        entry["subscription_tag_details"] = new_meta["subscription_tag_details"]
        entry["subscription_catalog_version"] = new_meta["catalog_version"]
        entry["classifier_version"] = CLASSIFIER_VERSION
        if cache_title:
            entry["listing_title"] = cache_title
        entry["enrich_version"] = ENRICH_VERSION
        entry["enriched_at"] = NOW
        fixed.append((url, current_ids, new_ids))

    # ── 2. 非 PDF 通告補手動記錄 ─────────────────────────────
    for url, (cache_title, source_site) in listing_by_url.items():
        if url in enrich:
            continue
        if url.lower().endswith(".pdf") or "drive.google" in url or "docs.google" in url:
            continue  # PDF / Drive 係 enrich.py 嘅正常對象，唔喺呢度搶做
        if not _term_hits(cache_title, STAFF_RECRUIT_TITLE_TERMS):
            continue
        meta = extract_subscription_metadata(
            cache_title, "", "", source=source_site, listing_title=cache_title)
        if args.dry_run:
            manual.append((url, [str(c.get("id")) for c in meta["categories"]]))
            continue
        enrich[url] = {
            "source": source_site,
            "title": cache_title,
            "listing_title": cache_title,
            "deadline": "",
            "audience": "",
            "fee": "",
            "categories": meta["categories"],
            "branch_tags": meta["branch_tags"],
            "subscription_tags": meta["subscription_tags"],
            "subscription_tag_details": meta["subscription_tag_details"],
            "subscription_catalog_version": meta["catalog_version"],
            "classifier_version": CLASSIFIER_VERSION,
            # method=manual：呢條係規則修復寫入，唔係 PDF 抽取；enrich.py
            # 唔會掂佢（collect_targets 只收 .pdf / Drive）。
            "method": "manual",
            "error": "",
            "title_check": "unverified",
            "enriched_at": NOW,
            "enrich_version": ENRICH_VERSION,
        }
        manual.append((url, [str(c.get("id")) for c in meta["categories"]]))

    print(f"修正現有記錄：{len(fixed)} 條；補手動記錄：{len(manual)} 條；無需變更：{len(unchanged)} 條")
    for url, old, new in fixed:
        print(f"  ✏️  {old} → {new}\n      {url}")
    for url, new in manual:
        print(f"  ➕ {new}\n      {url}")

    if args.dry_run:
        print("（dry-run，未寫入）")
        return 0

    if fixed or manual:
        with open(ENRICH_FILE, "w", encoding="utf-8") as fh:
            json.dump(enrich, fh, ensure_ascii=False, indent=2)
        print(f"已寫入 {ENRICH_FILE}")
    else:
        print("冇嘢要改。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
