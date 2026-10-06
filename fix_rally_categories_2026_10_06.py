#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性補正：2026-10-06 用戶規則「大會操＝活動，失物認領除外」嘅資料欠帳。

背景
----
用戶 2026-10-06 點名兩條通告：

    總會    2026年香港童軍大會操(四)
    荃灣區  香港童軍大會操荃灣區會旅遊巴士安排

兩條都被判「比賽」，因為「會操」喺 subscription_tagging.COMPETITION_TERMS
入面。但香港童軍大會操（Scout Rally）係全港週年活動／典禮，唔係比賽——
訂咗「所有比賽」嘅訂閱者會收到旅遊巴士安排呢類資訊。

規則（subscription_tagging.extract_categories 已改，見 test_enrich.py ⑧）
------------------------------------------------------------------------
  - 標題有「香港童軍大會操」→ 活動（activity/other）
  - 唯一例外：失物認領／失物待領 → 公布（行政公告）
  - 其他會操（「九龍地域會操」「聯隊週年大會操」）未經用戶確認，**唔改**

呢個 script 做嘅嘢
------------------
未來防錯規則改咗，但 enrich.json 入面已入庫嘅舊值仍然欠帳。呢度逐條用
**同一個** subscription_tagging 規則由標題重算分類，再補返訂閱標籤：

  - 有 categories 嘅 entry：換走舊嘅 category topic
    （category:competition → activity:other / category:announcement），
    其他標籤（課程／支部）一個字都唔掂——佢哋係由 PDF 內文抽出嚟嘅，
    離線冇內文，重算只會弄丟嘢。
  - 完全冇 categories 嘅舊 entry（enrich_version 1.0）：由標題＋已存嘅對象
    補返一套標籤。呢啲 entry 嘅 enrich_version 保持不變，所以之後
    `enrich.py --backfill-categories` 仍然會執返佢哋落 PDF 重抽。

零下載、唔改 cache.json（列表標題本來就正確，category 只住喺 enrich.json）。

用法
----
    python fix_rally_categories_2026_10_06.py --dry-run   # 只睇會改咩
    python fix_rally_categories_2026_10_06.py             # 實際寫入 enrich.json

（可重複執行：第二次 run 會顯示「已經乾淨」。）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from subscription_tagging import (  # noqa: E402
    LOST_PROPERTY_TERMS,
    RALLY_ACTIVITY_TERMS,
    _term_hits,
    _topic_detail,
    extract_categories,
    extract_subscription_metadata,
    load_catalog,
)

ENRICH_PATH = BASE_DIR / "enrich.json"

# 同 subscription_tagging.extract_subscription_metadata 入面嘅 mapping 一致。
CATEGORY_TOPIC = {
    "training": "category:training",
    "service": "category:service",
    "competition": "category:competition",
    "tools": "category:tools",
    "announcement": "category:announcement",
}


def topic_id_for(category: dict) -> str:
    """category dict → 訂閱 topic id（activity 用 subtype 分大露營／營火會／其他）。"""
    if category.get("id") == "activity":
        return "activity:{}".format(str(category.get("subtype") or "other").replace("_", "-"))
    return CATEGORY_TOPIC.get(str(category.get("id") or ""), "")


def is_rally_or_lost_property(title: str) -> bool:
    return bool(_term_hits(title, RALLY_ACTIVITY_TERMS) or _term_hits(title, LOST_PROPERTY_TERMS))


def patch_entry(entry: dict, catalog: dict) -> tuple[dict, str]:
    """回傳（新 entry, 改動說明）；冇嘢改就回傳原 entry 同空字串。"""
    title = str(entry.get("title") or "")
    source = str(entry.get("source") or "")
    new_categories = extract_categories(title, "", source)
    if not new_categories:
        return entry, ""
    new_cat = new_categories[0]
    new_topic = topic_id_for(new_cat)

    # 舊 entry（enrich_version 1.0）完全冇分類欄位：由標題＋已存對象補返一套。
    if "categories" not in entry:
        meta = extract_subscription_metadata(title, "", entry.get("audience", ""),
                                             source=source, catalog=catalog)
        patched = dict(entry)
        patched["categories"] = meta["categories"]
        patched["branch_tags"] = meta["branch_tags"]
        patched["subscription_tags"] = meta["subscription_tags"]
        patched["subscription_tag_details"] = meta["subscription_tag_details"]
        patched["subscription_catalog_version"] = meta["catalog_version"]
        return patched, f"補返分類（由標題）→ {new_cat['label']}｜tags={meta['subscription_tags']}"

    old_categories = entry.get("categories") or []
    old_topic = topic_id_for(old_categories[0]) if old_categories else ""
    if [c.get("id") for c in old_categories] == [c.get("id") for c in new_categories] and \
            [c.get("subtype") for c in old_categories] == [c.get("subtype") for c in new_categories]:
        return entry, ""

    tags = [t for t in (entry.get("subscription_tags") or []) if t != old_topic]
    if new_topic and new_topic not in tags:
        tags.append(new_topic)

    details = [d for d in (entry.get("subscription_tag_details") or [])
               if str(d.get("id")) != old_topic]
    topic_entry = catalog.get("_topic_by_id", {}).get(new_topic)
    if topic_entry:
        details.append(_topic_detail(topic_entry, new_cat.get("evidence", [])))
    detail_map = {str(d["id"]): d for d in details}
    details = [detail_map[key] for key in sorted(detail_map)]

    patched = dict(entry)
    patched["categories"] = new_categories
    patched["subscription_tags"] = sorted(tags)
    patched["subscription_tag_details"] = details
    old_label = "／".join(str(c.get("label") or "") for c in old_categories) or "（冇分類）"
    return patched, f"{old_label} → {new_cat['label']}｜{old_topic or '—'} → {new_topic}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只報告，唔寫檔")
    args = ap.parse_args(argv)

    catalog = load_catalog()
    with ENRICH_PATH.open("r", encoding="utf-8") as fh:
        enrich = json.load(fh)

    changed = 0
    for url, entry in enrich.items():
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "")
        if not is_rally_or_lost_property(title):
            continue
        patched, note = patch_entry(entry, catalog)
        if not note:
            continue
        changed += 1
        print(f"  {entry.get('source', '?')}｜{title}\n     {note}\n     {url}")
        if not args.dry_run:
            enrich[url] = patched

    if not changed:
        print("✅ 已經乾淨：大會操／失物認領通告嘅分類全部同現行規則一致。")
        return 0

    if args.dry_run:
        print(f"\n（dry-run：以上 {changed} 條未寫入；要真改請去掉 --dry-run）")
        return 0

    with ENRICH_PATH.open("w", encoding="utf-8") as fh:
        json.dump(enrich, fh, ensure_ascii=False, indent=2)
    print(f"\n✅ 已更新 {changed} 條 → {ENRICH_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
