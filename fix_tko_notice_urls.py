#!/usr/bin/env python3
"""一次性修復：將軍澳區 30 筆假 URL（notice.php#slug）→ 真 URL，並保留原 captured_date。

背景
----
將軍澳區 (hkscout-tko.org/notice.php) 嘅下載掣唔係 ``<a href>``，而係
``<span class="pdfImg" data-id="206">``（站方 JS 跳 ``/notice/?nid=206``）。
舊版 core.py 嘅 ``asset_link_selector: "a[href]"`` 睇唔到佢，於是 30 筆通告：

* 0 個附件；
* ``pdf_url`` 係砌出嚟嘅假 fragment，例如
  ``https://hkscout-tko.org/notice.php#行政通告-06-2026-第25屆區務委員會就職典禮暨積極公民同樂日``
  —— 但個頁其實只有 ``#top`` 同 8 個分類 anchor（#spec/#adm/#all/#gs/#cs/#sc/#vs/#rs），
  所以 UI 㩒「開啟附件」永遠彈返列表頂；
* 標題冇截止日：畫面色水變「已截止」之後，可見嘅 deadline 就消失咗
  （但 ``whatsappImg[data-title]`` 一直保留住原截止日）。

v5.6.23 已喺 core.py 加入 ``parse_notice_card_blocks``（真 ``/notice/?nid=`` +
由 data-title 還原截止日 + 跟內頁攞真 PDF，fail-soft）。但 cache.json 入面
已寫低嘅污染資料要另外 re-key。

點解要人手 re-key 而唔係等 core.py 自己搞
----------------------------------------
core.py 用 ``(source_site, pdf_url)`` 做 key。URL 一轉，30 筆全部會被當「新通告」，
``captured_date`` 變今日 → 違反「盲信系統日期」嘅原意（captured_date 代表我哋幾時
睇到佢），而且 notify.py 會把 28 筆 2026-05-23 入庫嘅舊通告當新通告重推一次。
呢支 script 嘅唯一任務就係：**換 URL、換標題，但把原 captured_date 搬過去**。

做乜
----
1. 配對：舊假 URL record ↔ 新真 URL record（title 去掉 `` (截止: …)`` 後完全相同）
2. 新 record 繼承舊 record 嘅 captured_date（多筆撞同一 key 就攞最早嗰個）
3. 刪走已被繼承嘅舊假 URL record
4. 用 ``core.build_grouped_cache`` 重建 ``data`` + ``notices``，避免留半新半舊嘅 cache
5. ``_meta``（包括 last_run / has_errors）同 ``last_updated`` 原封不動保留

前提：要先跑一次抓取，等 cache 入面有新格式嘅 record::

    python core.py --source 將軍澳區 --force

用法
----
::

    python fix_tko_notice_urls.py --dry-run   # 只睇會改咩（唔寫入）
    python fix_tko_notice_urls.py             # 實際寫入 cache.json（會先 backup）

跟住跑 ``python enrich.py --verbose``，等佢抽新攞到嘅真 PDF 嘅參加資格／費用／截止日。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core import build_grouped_cache  # noqa: E402

SOURCE = "將軍澳區"
FAKE_MARK = "notice.php#"
# 新格式標題尾巴： " (截止: 2026-07-16)"
DEADLINE_SUFFIX_RE = re.compile(r"\s*\(截止:\s*\d{4}-\d{2}-\d{2}\)\s*$")


def title_key(title: str) -> str:
    """配對用 key：去掉截止日尾巴 + 壓縮空白。

    新 parser 還原到截止日之後，同一則通告嘅標題會由
    「06-2026 行政通告 - 第25屆區務委員會就職典禮暨積極公民同樂日」
    變成「…同樂日 (截止: 2026-07-16)」，所以配對前必須剝走尾巴。
    """
    return " ".join(DEADLINE_SUFFIX_RE.sub("", title or "").split())


def is_fake(record: Dict[str, Any]) -> bool:
    return FAKE_MARK in (record.get("pdf_url") or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="將軍澳區假 URL → 真 URL（保留 captured_date）")
    ap.add_argument("--cache", default=str(BASE_DIR / "cache.json"))
    ap.add_argument("--sources", default=str(BASE_DIR / "sources.json"))
    ap.add_argument("--dry-run", action="store_true", help="只列出改動，唔寫入")
    args = ap.parse_args()

    cache_path = Path(args.cache)
    sources_path = Path(args.sources)
    if not cache_path.exists():
        print(f"❌ 搵唔到 {cache_path}")
        return 1

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    all_sources = json.loads(sources_path.read_text(encoding="utf-8")).get("sources", {})
    records: List[Dict[str, Any]] = list(cache.get("notices") or [])

    tko = [r for r in records if r.get("source_site") == SOURCE]
    old_recs = [r for r in tko if is_fake(r)]
    new_recs = [r for r in tko if not is_fake(r)]

    print(f"📦 {SOURCE}: cache 內 {len(tko)} 筆（舊假 URL {len(old_recs)} 筆 / 新格式 {len(new_recs)} 筆）")
    if not old_recs:
        print("✅ 冇舊假 URL 剩低，唔使修。")
        return 0
    if not new_recs:
        print(
            "⚠️ cache 入面仲未有任何新格式 record。\n"
            "   請先跑：python core.py --source 將軍澳區 --force\n"
            "   （新 parser 要先攞到真 /notice/?nid= 或者真 PDF，呢支 script 先有嘢可以配對。）"
        )
        return 1

    # ── 配對：key → 舊 record（保留最早 captured_date）──
    old_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for r in old_recs:
        old_by_key.setdefault(title_key(r.get("title", "")), []).append(r)

    inherited: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    consumed: List[Dict[str, Any]] = []
    brand_new: List[Dict[str, Any]] = []

    for r in new_recs:
        key = title_key(r.get("title", ""))
        candidates = old_by_key.get(key) or []
        if candidates:
            # 同一 title 撞多筆舊 record（理論上唔會）→ 攞最早入庫嗰筆，其餘當未配對
            donor = min(candidates, key=lambda x: x.get("captured_date") or "9999")
            inherited.append((donor, r))
            consumed.append(donor)
        else:
            brand_new.append(r)

    # ⚠️ 用 id() 而唔係 `in`：dict 嘅 `in` 比值唔比身份，兩筆內容相同嘅 record 會互相誤認
    consumed_ids = {id(r) for r in consumed}
    leftover = [r for r in old_recs if id(r) not in consumed_ids]

    print(f"\n🔗 配對成功（新 record 繼承舊 captured_date）: {len(inherited)} 筆")
    for donor, r in inherited:
        print(f"   {donor.get('captured_date')}  {r.get('title', '')[:56]}")
        print(f"      舊 {donor.get('pdf_url', '')[:100]}")
        print(f"      新 {r.get('pdf_url', '')[:100]}")

    print(f"\n🆕 真．新通告（冇舊 record 可以繼承，captured_date 保持不變）: {len(brand_new)} 筆")
    for r in brand_new:
        print(f"   {r.get('captured_date')}  {r.get('title', '')[:56]}")
        print(f"      {r.get('pdf_url', '')[:100]}")

    print(f"\n🗑️  會被刪走嘅舊假 URL record: {len(consumed)} 筆")
    print(f"🚫 配對唔到、原封不動保留嘅舊假 URL record: {len(leftover)} 筆")
    for r in leftover:
        print(f"   {r.get('captured_date')}  {r.get('title', '')[:56]}")
    if leftover:
        print("   （呢啲多半係區會已經落架嘅通告 —— 新 format 搵唔到對應項，屬正常。舊嘅唔理。）")

    if not inherited:
        print("\n⚠️ 一筆都配對唔到，唔會改任何嘢。請檢查 title 格式有冇變。")
        return 1

    # ── 應用：新 record 繼承 captured_date，舊 record 刪走 ──
    for donor, r in inherited:
        r["captured_date"] = donor.get("captured_date") or r.get("captured_date")
    fixed = [r for r in records if not (r.get("source_site") == SOURCE and id(r) in consumed_ids)]

    print(
        f"\n📊 notices: {len(records)} → {len(fixed)} 筆"
        f"（淨減 {len(records) - len(fixed)}，即係被繼承後刪走嘅舊假 URL）"
    )

    rebuilt = build_grouped_cache(fixed, all_sources, cache.get("last_updated") or "")
    # _meta（last_run / has_errors / expected_empty_sources）同 last_updated 原封不動
    if isinstance(cache.get("_meta"), dict):
        rebuilt["_meta"] = cache["_meta"]
    if cache.get("last_updated"):
        rebuilt["last_updated"] = cache["last_updated"]

    if args.dry_run:
        print("\n（--dry-run，冇寫入。去掉 --dry-run 再跑先至會改 cache.json）")
        return 0

    backup = cache_path.with_name(f"{cache_path.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(cache_path, backup)
    print(f"💾 已 backup 原本 cache → {backup.name}")
    cache_path.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已寫入 {cache_path.name}")
    print("👉 跟住跑：python enrich.py --verbose   （抽新攞到嘅真 PDF 嘅參加資格／費用／截止日）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
