#!/usr/bin/env python3
"""由 cache.json 生成「今日 Story 清單」story-queue.json。

只挑 HKT 今日新入庫（captured_date = 今日）而且 Story 必要資料齊全嘅通告：
標題、頒佈日期、來源、分類、地域、原文附件連結、截止、對象、費用。缺任何一項就跳過，
避免將佔位字或估算內容畫上 Story。唔設張數上限；可用正數 --limit 作手動測試。

每條合資格 item 會 join enrich.json（deadline/audience/fee）同分好 category
（training/service/activity/competition），供 renderer 出圖；無法歸類及「Scout System」
小工具都唔會入清單。每日自動流程只由 story-draft.yml 一次生成、
出圖及發佈；本檔亦保留畀手動 workflow_dispatch 更新清單。

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


def story_attachment_url(item: dict) -> str:
    """Story QR 直連原文附件；優先 pdf_url，欠缺時退回 url。"""
    for key in ("pdf_url", "url"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


STORY_SLOGANS = {
    "training": (
        "解鎖新技能",
        "Skill Up!",
        "學多樣，識多樣",
        "今日學，明日用",
        "升級進行中",
        "成為更勁嘅自己",
        "新手都歡迎",
        "學到就係你嘅",
    ),
    "activity": (
        "一齊玩，一齊記住",
        "下一個回憶就係呢個",
        "講少啲，做多啲",
        "唔好淨係睇，嚟體驗啦",
        "名額有限，報咗先算",
        "今次唔嚟，下次後悔",
        "新嘗試，等緊你",
        "Join Us，齊齊出動",
    ),
    "service": (
        "一齊做好事",
        "小行動，大意義",
        "出一分力，多一點好",
        "一齊做，影響更大",
        "付出時間，收穫更多",
        "為呢度加點好",
        "行動，就係改變",
        "Do Good Together",
    ),
    "competition": (
        "挑戰一下自己",
        "係時候Show實力",
        "突破自己嘅界限",
        "唔試點知得唔得",
        "團隊一齊，上！",
        "為自己而戰",
        "輸贏以外，係經歷",
        "Ready？Go！",
    ),
}

def story_slogan_candidates(item: dict) -> tuple[str, ...]:
    """Return all lines for the classified Story category."""
    category = str(item.get("category") or classify_category(item, None))
    if category not in STORY_SLOGANS:
        raise ValueError(f"Story requires a classified category: {category or 'missing'}")
    return STORY_SLOGANS[category]


def story_slogan_for_slot(category: str, slot: int) -> str:
    """The category's fixed copy at this slot; no extra signup claims."""
    lines = STORY_SLOGANS[category] if category in STORY_SLOGANS else ()
    if not lines:
        raise ValueError(f"Story requires a classified category: {category or 'missing'}")
    return lines[slot % len(lines)]


def assign_story_slogans(items: list[dict]) -> list[dict]:
    """同一日同分類逐張輪流用下一句，唔會同一日撞句。"""
    seen: dict[str, int] = {}
    for item in items:
        category = str(item.get("category") or "")
        if category not in STORY_SLOGANS:
            continue
        slot = seen.get(category, 0)
        seen[category] = slot + 1
        item["slogan"] = story_slogan_for_slot(category, slot)
    return items


def story_slogan(item: dict) -> str:
    """Return the assigned line; items outside a day's batch fall back to slot 0."""
    if item.get("slogan"):
        return str(item["slogan"])
    category = str(item.get("category") or classify_category(item, None))
    return story_slogan_for_slot(category, 0)


def _today_candidates(cache: dict, today: str, enrich: dict | None = None) -> tuple[list[dict], int]:
    """Return (complete candidates, incomplete count) for today, excluding tools."""
    items: list[dict] = []
    incomplete = 0
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
            if category not in STORY_SLOGANS:
                incomplete += 1  # 未能歸入四個 Story 分類，唔用「其他」估估下
                continue

            source_site = str(it.get("source_site") or section).strip()
            item = {
                "title": str(it.get("title") or "").strip(),
                "url": str(it.get("url") or it.get("pdf_url") or "").strip(),
                "pdf_url": str(it.get("pdf_url") or "").strip(),
                # 條目冇寫 region 就用番 cache.json 嘅 section 名
                "region": str(it.get("region") or section or source_site).strip(),
                "source_site": source_site,
                "date": str(it.get("date") or "")[:10].strip(),
                "captured_date": str(it.get("captured_date") or "")[:10],
                "deadline": str((ex or {}).get("deadline") or "")[:10].strip(),
                "audience": str((ex or {}).get("audience") or "").strip(),
                "fee": str((ex or {}).get("fee") or "").strip(),
                "category": category,
            }
            # 這些正是 Story 底部資料卡及來源標籤會顯示的欄位；
            # 不以「詳情見內文／見通告／—」等版面佔位字冒充齊料。
            required = ("title", "date", "source_site", "region", "category", "url",
                        "deadline", "audience", "fee")
            if any(not item[field] for field in required):
                incomplete += 1
                continue
            items.append(item)
    items.sort(key=lambda x: (x["date"] or NO_DATE, x["source_site"], x["title"]))
    return items, incomplete


def pick_today(cache: dict, today: str, enrich: dict | None = None) -> list[dict]:
    """只回傳 captured_date == today 且所需 Story 欄位齊全嘅通告。"""
    return _today_candidates(cache, today, enrich)[0]


def build_queue(cache: dict, today: str, limit: int | None = None,
                now: datetime | None = None, enrich: dict | None = None) -> dict:
    candidates, incomplete = _today_candidates(cache, today, enrich)
    # 預設／--limit 0 都係不限張數；正數只供明確手動測試。
    picked = candidates[:limit] if limit is not None and limit > 0 else candidates
    # 排好隊先配標語：同一日同分類逐張用下一句，穩定又唔會撞句。
    assign_story_slogans(picked)
    generated = (now or datetime.now(HKT)).astimezone(HKT)
    return {
        "version": 2,
        "today": today,
        "generated_at": generated.strftime("%Y-%m-%d %H:%M:%S %z"),
        "cache_last_updated": cache.get("last_updated") or "",
        "candidate_count": len(candidates) + incomplete,
        "skipped_incomplete": incomplete,
        "count": len(picked),
        "items": picked,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成今日 Story 清單 story-queue.json")
    ap.add_argument("--cache", default="cache.json", help="cache.json 路徑")
    ap.add_argument("--enrich", default=None,
                    help="enrich.json 路徑（預設：cache.json 同目錄；缺少截止／對象／費用資料嘅項目會跳過）")
    ap.add_argument("--out", default="story-queue.json", help="輸出路徑")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多幾多張；預設 0＝所有齊料通告，不設上限（正數只供手動測試）")
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
            print("⚠️ enrich.json 讀唔到；缺 deadline/audience/fee 嘅通告會視為不齊並跳過", file=sys.stderr)

    today = args.today or today_hkt()
    queue = build_queue(cache, today, args.limit, enrich=enrich)
    Path(args.out).write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"✅ story-queue.json：{queue['count']} 張齊料通告；"
        f"今日候選 {queue['candidate_count']} 張，跳過資料不齊 {queue['skipped_incomplete']} 張。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
