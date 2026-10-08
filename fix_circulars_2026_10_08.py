#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性補正：2026-10-08 用戶點名嘅分類標籤、標題後綴及誤抽課程標籤。

背景（用戶報告：「今日D 通告又有D 標籤標錯左 同有1張個標題有D 怪」）
---------------------------------------------------------------------
1. 分類標籤標錯（3 張應歸「活動」）：
   - 總會      26238/SP16-.pdf  東九50樂悠遊之與你「童」行(步行籌款活動)   服務 → 活動
   - 東九龍地域 wpdmdl=5659     東九50樂悠遊之與你「童」行(步行籌款活動)   服務 → 活動
   - 總會      26338/P102-26.pdf 探尋宗教足跡-參訪寶蓮禪寺(P102/2026)     公布 → 活動

   根因：
   - `subscription_tagging.SERVICE_TERMS` 舊版收咗「籌款」，喺 `title_decisive`
     優先過 `title_hits["other"]`（「活動」），令步行籌款活動被判成「服務」；
   - `OTHER_ACTIVITY_TERMS` 只收咗「參觀」同「參訪團」，漏咗單獨「參訪」，
     令「探尋宗教足跡-參訪寶蓮禪寺」兜底跌落「公布」。

2. 標題帶雜訊後綴：
   - 旺角區 `深資及樂行童軍支部比賽2026 - 通告07.10`
     → `深資及樂行童軍支部比賽2026`（Google Drive 檔名尾綴 `- 通告07.10`）
   - 大埔北區 `香港童軍115周年 – 幼童軍度假營2026 大埔北區資助計劃 - 連結`
     → `香港童軍115周年 – 幼童軍度假營2026 大埔北區資助計劃`（WordPress 連結文字 `- 連結`）

3. 隱藏課程訂閱標籤雜訊：
   - 總會 `26342` 戶外壁畫設計比賽、`26343` 嘉年華 因為內文提及「歷奇教育」而誤中
     `course:leader-adventure-instructor`（歷奇活動教練員）。`subscription_catalog.json`
     已移除裸詞別名「歷奇教育」，呢度同步清走存量雜訊標籤。

用法
----
    python fix_circulars_2026_10_08.py --dry-run   # 只睇會改咩
    python fix_circulars_2026_10_08.py             # 實際寫入 cache.json + enrich.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from fix_rally_categories_2026_10_06 import patch_entry  # noqa: E402
from subscription_tagging import load_catalog  # noqa: E402

CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

HQ = "https://scout.org.hk/uploads/tc/circulars"
EKR = "https://hkscout-ekr.org/circulars/download/?wpdmdl="

# 1. 分類標籤要按新規則（由標題）重算嘅通告 URL
CATEGORY_URLS = (
    f"{HQ}/26238/SP16-.pdf",
    f"{EKR}5659",
    f"{HQ}/26338/P102-26.pdf",
    # 同類存量步行籌款通告（舊版因為「籌款」喺 SERVICE_TERMS 而標咗服務）
    "https://assets.ctfassets.net/g8bhf0l3d7iq/6hj5Q26rbj8a5geTRwbse8/6eea18eef9c75dfd1faaadccb0bbbc19/chairty_walk_poster.pdf",
    f"{HQ}/26021/chairty-walk_poster.pdf",
    f"{HQ}/26074/Special16.pdf",
)

# 2. 標題要剝走檔名／連結後綴嘅通告 URL → (新標題, 原列表標題)
TITLE_FIXES = {
    "https://drive.google.com/file/d/10_jGInsp0lJSjO_lnrADnYqJ3urWDKtl/view": (
        "深資及樂行童軍支部比賽2026",
        "深資及樂行童軍支部比賽2026 - 通告07.10",
    ),
    "https://tpnscout.org/wp-content/uploads/2026/10/香港童軍115周年-–-幼童軍度假營2026-大埔北區資助計劃.pdf": (
        "香港童軍115周年 – 幼童軍度假營2026 大埔北區資助計劃",
        "香港童軍115周年 – 幼童軍度假營2026 大埔北區資助計劃 - 連結",
    ),
}

# 3. 誤抽嘅課程訂閱標籤 URL → topic_id
NOISE_COURSES = {
    f"{HQ}/26342/AiS302026_慶祝香港童軍115周年戶外壁畫設計比賽.pdf": "course:leader-adventure-instructor",
    f"{HQ}/26343/AiS312026_香港童軍115周年_筆下童心挑戰高峰_嘉年華_Draft.pdf": "course:leader-adventure-instructor",
}


def find_cache_items(cache: dict, url: str) -> list[dict]:
    out = []
    for arr in (cache.get("data") or {}).values():
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, dict) and (item.get("pdf_url") or item.get("url")) == url:
                    out.append(item)
    for item in cache.get("notices") or []:
        if isinstance(item, dict) and (item.get("pdf_url") or item.get("url")) == url:
            out.append(item)
    return out


def drop_noise_tag(entry: dict, topic_id: str) -> bool:
    tags = list(entry.get("subscription_tags") or [])
    if topic_id not in tags:
        return False
    entry["subscription_tags"] = [tag for tag in tags if tag != topic_id]
    entry["subscription_tag_details"] = [
        d for d in (entry.get("subscription_tag_details") or []) if str(d.get("id")) != topic_id
    ]
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="補正 2026-10-08 點名通告嘅分類、標題及課程標籤")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會改咩，唔寫檔")
    args = ap.parse_args(argv)

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    catalog = load_catalog()
    changes = []

    # 1. 分類標籤重算（surgical patch：只換 category + category 訂閱標籤）
    for url in CATEGORY_URLS:
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            continue
        patched, note = patch_entry(entry, catalog)
        if note:
            changes.append(f"enrich.json 分類｜{entry.get('source')}｜{entry.get('title')}：{note}")
            enrich[url] = patched

    # 2. 標題後綴清理（cache.json 兩份列表 + enrich.json + listing_title 紀錄）
    for url, (clean_title, listing_title) in TITLE_FIXES.items():
        for item in find_cache_items(cache, url):
            if item.get("title") != clean_title:
                changes.append(f"cache.json 標題：{item.get('title')} → {clean_title}")
                item["title"] = clean_title
        entry = enrich.get(url)
        if isinstance(entry, dict):
            if entry.get("title") != clean_title:
                changes.append(f"enrich.json 標題：{entry.get('title')} → {clean_title}")
                entry["title"] = clean_title
            if entry.get("title_check") != "corrected" or entry.get("listing_title") != listing_title:
                entry["title_check"] = "corrected"
                entry["listing_title"] = listing_title
                changes.append(f"enrich.json 記錄 listing_title：{listing_title}")

    # 3. 清走誤抽嘅課程訂閱標籤
    for url, topic_id in NOISE_COURSES.items():
        entry = enrich.get(url)
        if isinstance(entry, dict) and drop_noise_tag(entry, topic_id):
            changes.append(f"enrich.json 移除雜訊課程標籤（{entry.get('title')}）：{topic_id}")

    if not changes:
        print("✅ 已經乾淨，冇嘢要改。")
        return 0

    for line in changes:
        print(" •", line)
    print(f"\n合共 {len(changes)} 項修改。")

    if args.dry_run:
        print("（--dry-run：未寫入任何檔案）")
        return 0

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ENRICH_PATH.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"📝 已更新 {CACHE_PATH.name} + {ENRICH_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
