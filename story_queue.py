#!/usr/bin/env python3
"""由 cache.json 生成「今日 Story 清單」story-queue.json。

排程（見 .github/workflows/story-queue.yml）刻意放喺日間先行：
  - 凌晨 00:15 HKT GitHub scrape（scrape.yml）
  - 朝早 05:00 HKT 本機補底（run-local-scrape-logged.bat）
兩輪都完成之後先挑「今日新入庫」（captured_date = 今日，HKT 計）通告，
按截止日期由近到遠排序，攞頭 --limit 條。

每條 item 除咗基本資料，仲會 join 埋 enrich.json（deadline/audience/fee）
同分好 category（training/service/activity/competition/other），俾
tools/render_story_templates.py 直接食出 Story 草稿圖。「Scout System」
小工具唔會入清單（佢哋唔係通告）。

stdlib only，無第三方依賴，無網絡存取。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HKT = timezone(timedelta(hours=8))

# 排序時冇截止日期嘅通告排最尾
NO_DATE = "9999-99-99"

TOOLS_SOURCES = {"Scout System"}  # 同 index.html TOOLS_SOURCES 同步；小工具唔出 Story

_RE_COMPETITION = re.compile(r"比賽|錦標賽|大賽|競賽|錦標")
_RE_TRAINING = re.compile(r"訓練|工作坊|課程|研習|考章|徽章班|考核|講座|簡介會")
_RE_SERVICE = re.compile(r"服務|義工|義務")
_RE_ACTIVITY = re.compile(r"活動|旅行|遠足|宿營|露營|嘉年華|同樂日|晚宴|參觀|體驗|遊|市集")


def today_hkt(now: datetime | None = None) -> str:
    """以香港時區計嘅今日（YYYY-MM-DD）。seam 俾測試注入固定時間。"""
    now = now or datetime.now(HKT)
    return now.astimezone(HKT).strftime("%Y-%m-%d")


def classify_category(item: dict, ex: dict | None) -> str:
    """同 index.html itemCategories 同款語義：
    Scout System → tools；enrich.categories 優先（activity+subtype=competition 都當
    competition）；否則按標題關鍵字兜底；最後 other。"""
    if str(item.get("source_site") or "").strip() in TOOLS_SOURCES:
        return "tools"
    cats = (ex or {}).get("categories")
    if isinstance(cats, list):
        for c in cats:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            cid = c["id"]
            if cid == "competition" or (cid == "activity" and c.get("subtype") == "competition"):
                return "competition"
            if cid in ("training", "service", "activity"):
                return cid
    title = str(item.get("title") or "")
    if _RE_COMPETITION.search(title):
        return "competition"
    if _RE_TRAINING.search(title):
        return "training"
    if _RE_SERVICE.search(title):
        return "service"
    if _RE_ACTIVITY.search(title):
        return "activity"
    return "other"


def enrich_for(enrich: dict | None, item: dict) -> dict | None:
    """同前端 keying：enrich[pdf_url] || enrich[url]。"""
    if not enrich or not isinstance(enrich, dict):
        return None
    return enrich.get(item.get("pdf_url")) or enrich.get(item.get("url"))


def pick_today(cache: dict, today: str, enrich: dict | None = None) -> list[dict]:
    """由 cache.json 結構揀出 captured_date == today 嘅通告，按截止日排序。"""
    items: list[dict] = []
    for section, arr in (cache.get("data") or {}).items():
        if not isinstance(arr, list):
            continue
        for it in arr:
            if not isinstance(it, dict):
                continue
            if str(it.get("captured_date") or "")[:10] != today:
                continue
            ex = enrich_for(enrich, it)
            category = classify_category(it, ex)
            if category == "tools":
                continue  # 小工具唔係通告，唔出 Story
            items.append({
                "title": it.get("title") or "未命名通告",
                "url": it.get("url") or "",
                "pdf_url": it.get("pdf_url") or "",
                # 條目冇寫 region 就用番 cache.json 嘅 section 名
                "region": it.get("region") or section,
                "source_site": it.get("source_site") or "",
                "date": str(it.get("date") or "")[:10],
                "captured_date": str(it.get("captured_date") or "")[:10],
                "deadline": str((ex or {}).get("deadline") or "")[:10],
                "audience": str((ex or {}).get("audience") or ""),
                "fee": str((ex or {}).get("fee") or ""),
                "category": category,
            })
    items.sort(key=lambda x: (x["date"] or NO_DATE, x["source_site"], x["title"]))
    return items


def build_queue(cache: dict, today: str, limit: int,
                now: datetime | None = None, enrich: dict | None = None) -> dict:
    picked = pick_today(cache, today, enrich)[:limit]
    generated = (now or datetime.now(HKT)).astimezone(HKT)
    return {
        "version": 1,
        "today": today,
        "generated_at": generated.strftime("%Y-%m-%d %H:%M:%S %z"),
        "cache_last_updated": cache.get("last_updated") or "",
        "count": len(picked),
        "items": picked,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成今日 Story 清單 story-queue.json")
    ap.add_argument("--cache", default="cache.json", help="cache.json 路徑")
    ap.add_argument("--enrich", default=None,
                    help="enrich.json 路徑（預設：cache.json 同目錄嘅 enrich.json；冇就 skip join）")
    ap.add_argument("--out", default="story-queue.json", help="輸出路徑")
    ap.add_argument("--limit", type=int, default=20, help="最多幾多張（預設 20）")
    ap.add_argument("--today", default=None,
                    help="覆寫『今日』（YYYY-MM-DD，主要俾測試用；預設 HKT 今日）")
    args = ap.parse_args(argv)

    cache_path = Path(args.cache)
    if not cache_path.exists():
        print(f"❌ 搵唔到 {cache_path}", file=sys.stderr)
        return 1
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ 讀 cache.json 失敗：{exc}", file=sys.stderr)
        return 1

    enrich_path = Path(args.enrich) if args.enrich else cache_path.parent / "enrich.json"
    enrich = None
    if enrich_path.exists():
        try:
            enrich = json.loads(enrich_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"⚠️ enrich.json 讀唔到，deadline/audience/fee 會留空", file=sys.stderr)

    today = args.today or today_hkt()
    queue = build_queue(cache, today, args.limit, enrich=enrich)
    Path(args.out).write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ story-queue.json：{queue['count']} 張（{today} 新入庫，按截止日排序）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
