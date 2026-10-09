#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性補正：2026-10-09 用戶點名嘅分類標籤、欄位表式標題同港島南區殘留 'view' 標題。

背景（用戶報告：「標籤錯……標題錯……修改後同時吸取經驗更改規則」）
---------------------------------------------------------------------
1. 分類標籤標錯（5 張）：
   - 總會 26366/I_MA04_26_Shenzhen.pdf
     探索歷史典藏、清真文化與創新科技之行            服務 → 活動
     （根因：PDF 內文一句「探訪」搶去服務；標題「……之行」係行程活動。
      規則修復：OTHER_ACTIVITY_TERMS 加「之行／之旅」，標題字眼行先。）
   - 總會 26370/Prog64a_26_BadmintonClubRecruitForm.pdf
     港島地域羽毛球會-入會表格                        訓練 → 公布
     （根因：PDF 內文提及「訓練班」搶去訓練；入會表格係行政表格。
      規則修復：MEMBERSHIP_ADMIN_TERMS「入會／招收／招募」→ 公布。）
   - 總會 26369/Prog64_26_BadmintonClubMemberRecruit.pdf
     港島地域羽毛球會-招收2026-2027年度下半年新會員   比賽 → 公布
     （根因：PDF 內文提及「比賽」搶去比賽；招收新會員係行政公布。
      同上規則修復。）
   - 總會 26380/CircularList-2026-10.pdf
     港島地域通告便覽(2026年10月)                     服務 → 公布
     （根因：便覽內文包含晒全月通告字眼（「工作人員」⋯⋯）；便覽係
      參考文件。規則修復：REFERENCE_TITLE_TERMS 加「便覽」。）
   - 總會 26363/Prog62_26_BirdwatcherSeminar.pdf
     港島童軍生態小組-觀鳥章(興趣組)領袖座談會        公布 → 訓練
     （根因：標題冇類別字眼，兜底公布；領袖座談會同講座／簡介會同類。
      規則修復：TRAINING_TERMS 加「座談會」。）

   同類存量（同一個系列／同一根因、舊數據未分類或標錯）一齊補返：
   2026-01 至 2026-09 港島地域通告便覽（總會＋港島地域兩組 URL）→ 公布；
   2026-05 羽毛球會招收新會員／入會表格兩張 → 公布；
   2026-05 觀鳥章(興趣組)領袖座談會 → 訓練；
   靜觀品茶工作坊地域版（25838 Dist06）→ 訓練（工作坊）。

   同場加映：「探索歷史典藏、清真文化與創新科技之行-報名表格」（26372）
   跟活動歸活動（同「童探索‧大灣區航天科技考察團 2027 - 報名表格」一致），
   令同一個活動嘅通告＋表格標籤一致。

2. 標題錯：港島南區 Google Drive 連結（14jcQZLdwlwqPBdu5eDCYHdhTt8cLSyLE）
   嘅 anchor 文字係成份通告內文（「深資及樂行童軍支部 活動名稱: 靜觀品茶
   工作坊 活動日期:… 通告下載」，170 字）。標題應為活動名稱「靜觀品茶工作坊」
   （同 core.clean_title 新規則 extract_activity_name_title 嘅輸出一致，
   之後 core.py 重建 cache 都唔會蓋走）。
   規則修復：core.clean_title 認到「活動名稱」欄位就抽欄位值做標題。

3. 港島南區 24 筆殘留 'view' 標題（Google Drive /view 尾段被當標題嘅舊 bug，
   core.py 早已修好，但 cache 舊數據一直未清，test_url_title_fallback.py 第 6
   節因此長期紅）。用 fix_hks_titles.TITLE_BY_FILE_ID（逐份開 PDF 核實過）補
   返——今次連 cache notices 副本都一齊清（fix_hks_titles.py 只處理 data）。

用法
----
    python fix_circulars_2026_10_09.py --dry-run   # 只睇會改咩
    python fix_circulars_2026_10_09.py             # 實際寫入 cache.json + enrich.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from fix_hks_titles import TITLE_BY_FILE_ID  # noqa: E402  （人手核實嘅港島南區真標題）
from fix_rally_categories_2026_10_06 import patch_entry  # noqa: E402
from subscription_tagging import load_catalog  # noqa: E402

CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

HQ = "https://scout.org.hk/uploads/tc/circulars"
HQ_WWW = "https://www.scout.org.hk/uploads/tc/circulars"

# 1. 分類標籤要按新規則（由標題）重算嘅通告 URL：
#    用戶點名 5 張 + 同場報名表格 + 同類存量（同一個系列／根因）。
CATEGORY_URLS = (
    # ── 用戶點名（2026-10-09）──
    f"{HQ}/26366/I_MA04_26_Shenzhen.pdf",                   # 之行 → 活動
    f"{HQ}/26372/I_MA04a_26_Shenzhen_form.pdf",             # 之行-報名表格 → 活動（同場）
    f"{HQ}/26370/Prog64a_26_BadmintonClubRecruitForm.pdf",  # 入會表格 → 公布
    f"{HQ}/26369/Prog64_26_BadmintonClubMemberRecruit.pdf",  # 招收新會員 → 公布
    f"{HQ}/26380/CircularList-2026-10.pdf",                 # 便覽 → 公布
    f"{HQ}/26363/Prog62_26_BirdwatcherSeminar.pdf",         # 座談會 → 訓練
    # ── 同類存量：港島地域通告便覽（便覽＝公布）──
    f"{HQ}/23238/CircularList-2026-01.pdf",
    f"{HQ_WWW}/23238/CircularList-2026-01.pdf",
    f"{HQ}/23566/CircularList-2026-02.pdf",
    f"{HQ_WWW}/23566/CircularList-2026-02.pdf",
    f"{HQ}/23955/CircularList-2026-03.pdf",
    f"{HQ_WWW}/23955/CircularList-2026-03.pdf",
    f"{HQ}/24390/CircularList-2026-04.pdf",
    f"{HQ_WWW}/24390/CircularList-2026-04.pdf",
    f"{HQ}/24707/CircularList-2026-05.pdf",
    f"{HQ_WWW}/24707/CircularList-2026-05.pdf",
    f"{HQ}/24969/CircularList-2026-06.pdf",
    f"{HQ_WWW}/24969/CircularList-2026-06.pdf",
    f"{HQ}/25266/CircularList-2026-07.pdf",
    f"{HQ_WWW}/25266/CircularList-2026-07.pdf",
    f"{HQ}/25711/CircularList-2026-08.pdf",
    f"{HQ_WWW}/25711/circularlist-2026-08.pdf",
    f"{HQ}/25943/CircularList-2026-09.pdf",
    f"{HQ_WWW}/25943/CircularList-2026-09.pdf",
    # ── 同類存量：羽毛球會入會系列（入會／招收＝公布）──
    f"{HQ}/23940/Prog20_26_BadmintonClubMemberRecruit.pdf",
    f"{HQ_WWW}/23940/Prog20_26_BadmintonClubMemberRecruit.pdf",
    f"{HQ}/23941/Prog20a_26_BadmintonClubMemberRecruitForm.pdf",
    f"{HQ_WWW}/23941/Prog20a_26_BadmintonClubMemberRecruitForm.pdf",
    # ── 同類存量：觀鳥章領袖座談會（座談會＝訓練）──
    f"{HQ_WWW}/23563/Prog13_26_BirdwatcherSeminar.pdf",
    # ── 同類存量：靜觀品茶工作坊地域版（工作坊＝訓練）──
    f"{HQ}/25838/Dist06_26_HKS_MindfulTeaTastingWorkshop.pdf",
    f"{HQ_WWW}/25838/Dist06_26_HKS_MindfulTeaTastingWorkshop.pdf",
)

# 2. 標題要由「欄位表」抽出活動名稱嘅通告 URL → (新標題, 原列表標題)
#    新標題同 core.clean_title 新規則嘅輸出一致（見 extract_activity_name_title）。
TEA_WORKSHOP_DUMP_TITLE = (
    "深資及樂行童軍支部 活動名稱: 靜觀品茶工作坊 活動日期:2026年 10 月 25 日"
    "(星期 日 ) 截止日期:2026年 10 月 9 日(星期五 ) 參加資格: 1. 持有有效成員"
    "紀錄冊之深資童軍,(港島南區成員將獲優先取錄);及 2. 持有有效成員紀錄冊之"
    "樂行童軍,(港島南區成員將獲優先取錄) 3. 區會職員及各級領袖。 通告下載"
)
TITLE_FIXES = {
    "https://drive.google.com/file/d/14jcQZLdwlwqPBdu5eDCYHdhTt8cLSyLE/view": (
        "靜觀品茶工作坊",
        TEA_WORKSHOP_DUMP_TITLE,
    ),
}

# 3. 港島南區殘留 'view' 標題：Drive file id → 人手核實真標題（fix_hks_titles）。
#    連 cache notices 副本一齊清（舊 fix_hks_titles.py 只處理 data）。
VIEW_TITLE_IDS = set(TITLE_BY_FILE_ID)


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


def drive_file_id(url: str) -> str:
    marker = "/file/d/"
    if marker not in (url or ""):
        return ""
    return url.split(marker, 1)[1].split("/", 1)[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="補正 2026-10-09 點名通告嘅分類、欄位表標題及 view 標題")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會改咩，唔寫檔")
    args = ap.parse_args(argv)

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    catalog = load_catalog()
    changes = []

    # 1. 分類標籤重算（surgical patch：只換 category + category 訂閱標籤，
    #    或為未分類存量補返一整套標籤）
    for url in CATEGORY_URLS:
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            continue
        patched, note = patch_entry(entry, catalog)
        if note:
            changes.append(f"enrich.json 分類｜{entry.get('source')}｜{entry.get('title')}：{note}")
            enrich[url] = patched

    # 2. 標題：欄位表抽活動名稱（cache.json 兩份列表 + enrich.json + listing_title 紀錄）
    for url, (clean_title, listing_title) in TITLE_FIXES.items():
        for item in find_cache_items(cache, url):
            if item.get("title") != clean_title:
                changes.append(f"cache.json 標題：{item.get('title')[:40]}… → {clean_title}")
                item["title"] = clean_title
        entry = enrich.get(url)
        if isinstance(entry, dict):
            if entry.get("title") != clean_title:
                changes.append(f"enrich.json 標題：{str(entry.get('title'))[:40]}… → {clean_title}")
                entry["title"] = clean_title
            if entry.get("title_check") != "corrected" or entry.get("listing_title") != listing_title:
                entry["title_check"] = "corrected"
                entry["listing_title"] = listing_title
                changes.append(f"enrich.json 記錄 listing_title（原貌 {len(listing_title)} 字欄位表）")

    # 3. 港島南區殘留 'view' 標題（data + notices 兩份列表）
    seen_view_urls = set()
    for arr_name, arr in [("data", (cache.get("data") or {}).get("港島南區") or []),
                          ("notices", cache.get("notices") or [])]:
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            url = item.get("pdf_url") or item.get("url") or ""
            if (item.get("title") or "").strip().lower() not in {"view", "preview"}:
                continue
            fid = drive_file_id(url)
            title = TITLE_BY_FILE_ID.get(fid or "")
            if not title:
                changes.append(f"⚠️ cache.json {arr_name} 'view' 標題搵唔到對應真標題：{url}")
                continue
            item["title"] = title
            seen_view_urls.add(url)
            changes.append(f"cache.json {arr_name} view 標題 → {title}")
    for url in sorted(seen_view_urls):
        entry = enrich.get(url)
        if isinstance(entry, dict) and (entry.get("title") or "").strip().lower() in {"view", "preview"}:
            entry["title"] = TITLE_BY_FILE_ID[drive_file_id(url)]
            changes.append(f"enrich.json view 標題 → {entry['title']}")

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
