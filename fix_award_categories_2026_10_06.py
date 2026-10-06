#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性補正：2026-10-06「獎勵／津貼／嘉許一類＝公布」規則嘅資料欠帳。

背景
----
用戶 2026-10-06 確認：「服務獎勵應該歸獎勵」——即係同童軍獎勵／旅團獎勵／
優異旅團／傑出旅團／功績獎勵／津貼計劃／嘉許計劃一樣，全部屬**公布**
（`ANNOUNCEMENT_OVERRIDE_TERMS`，2026-10-03 已定；「青年獎勵計劃」除外，
佢係訓練）。

規則本身冇問題，但 enrich.json 有兩條舊 entry 係喺規則生效之前抽嘅，
分類仍然係「服務」：

    總會  地域服務獎勵計劃 - 附件(一)     categories=[服務]  ver=3.1
    總會  地域服務獎勵計劃 - 附件 (一)    categories=[服務]  ver=3.2

呢個唔係純顯示問題：`notify.py notice_metadata()` 係
`extra.get("subscription_tags") or fallback[...]`——**存量標籤優先**，
所以呢兩條會推畀訂咗「服務」嘅人，而唔係訂「公布」嘅人。

呢個 script 做嘅嘢
------------------
揀出「標題撞中 ANNOUNCEMENT_OVERRIDE_TERMS（青年獎勵除外）、但存檔分類同
現行規則唔一致」嘅 entry，用**同一個** `extract_categories()` 由標題重算，
再換走舊嘅 category 訂閱標籤（同 `fix_rally_categories_2026_10_06.py` 同一套
surgical patch：其他標籤一個字都唔掂）。

完全冇 categories 嘅舊 entry **唔會**喺呢度處理：`notify.py` 對佢哋會用標題
fallback（結果正確），而且前端 `itemCategories()` 對空陣列亦兜底做「公布」。

零下載、唔改 cache.json、唔改 enrich_version。

用法
----
    python fix_award_categories_2026_10_06.py --dry-run   # 只睇會改咩
    python fix_award_categories_2026_10_06.py             # 實際寫入 enrich.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from fix_rally_categories_2026_10_06 import ENRICH_PATH, patch_entry  # noqa: E402
from subscription_tagging import (  # noqa: E402
    ANNOUNCEMENT_OVERRIDE_EXCLUDE_TERMS,
    ANNOUNCEMENT_OVERRIDE_TERMS,
    _term_hits,
    extract_categories,
    load_catalog,
)


def is_stale_award_entry(entry: dict) -> bool:
    """標題係獎勵／津貼／嘉許一類（青年獎勵除外），但存檔分類同現行規則唔一致。"""
    title = str(entry.get("title") or "")
    if not _term_hits(title, ANNOUNCEMENT_OVERRIDE_TERMS):
        return False
    if _term_hits(title, ANNOUNCEMENT_OVERRIDE_EXCLUDE_TERMS):
        return False            # 青年獎勵計劃＝訓練，唔係公布
    stored = entry.get("categories")
    if not isinstance(stored, list) or not stored:
        return False            # 冇存檔分類 → notify.py 會用標題 fallback，唔使改
    want = extract_categories(title, "", str(entry.get("source") or ""))
    got = [(c.get("id"), c.get("subtype")) for c in stored]
    return got != [(c.get("id"), c.get("subtype")) for c in want]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只報告，唔寫檔")
    args = ap.parse_args(argv)

    catalog = load_catalog()
    with ENRICH_PATH.open("r", encoding="utf-8") as fh:
        enrich = json.load(fh)

    changed = 0
    for url, entry in enrich.items():
        if not isinstance(entry, dict) or not is_stale_award_entry(entry):
            continue
        patched, note = patch_entry(entry, catalog)
        if not note:
            continue
        changed += 1
        print(f"  {entry.get('source', '?')}｜{entry.get('title')}\n     {note}\n     {url}")
        if not args.dry_run:
            enrich[url] = patched

    if not changed:
        print("✅ 已經乾淨：獎勵／津貼／嘉許一類通告嘅分類全部同現行規則一致。")
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
