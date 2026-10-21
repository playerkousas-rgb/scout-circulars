#!/usr/bin/env python3
"""加掃 SCOUT APP STORE：將 store apps 表併入 cache.json 的 Scout System。

設計（見 APPSTORE_INTEGRATION.md 階段 2）：
- 讀取：anon key 就夠（RLS 限 visible=true SELECT），唔使 service key。
- data["Scout System"] = 全份 visible catalog（只收 visible=true，已上架的）。
  隱藏（visible=false）永遠唔會入圖書館；若舊版曾經可見但而家隱藏，下次同步會自動移除。
- 以 URL 作為唯一更新判準：
  - 同一 URL 改名、改標籤、改分類、改描述、換 icon → 只同步更新欄位，保留舊 date / captured_date（留喺「之前發布」），唔算新 APP。
  - 全新 URL 上架（或超大型改版換新 URL 重新上架）→ 當日計入「今天更新/發布」（date / captured_date = 今日，並入 notices），隔日起自動歸入「之前發布」。
- 自己（scout-circulars.vercel.app）永遠 skip。
- enrich.json 同步：每個可見 app 保證有 enrich 條目（小工具分類、支部標籤、描述）；
  若現有 app 欄位無變動，唔會無故刷新 enriched_at 時間戳。

用法：
  python tools/scrape_appstore.py                # live REST（你部機／Actions）
  python tools/scrape_appstore.py --snapshot     # 離線：食 appstore.json 內 snapshot（sandbox 測試）
  python tools/scrape_appstore.py --apps-json X  # 離線：食自訂 apps 陣列檔（測試新 app 觸發）
  python tools/scrape_appstore.py --cache Y      # 指定 cache.json 路徑（測試用 copy）
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HKT = timezone(timedelta(hours=8))
SOURCE = "Scout System"
BASELINE_DATE = "2026-09-24"
SELF_URLS = {"https://scout-circulars.vercel.app/", "https://scout-circulars.vercel.app"}
# 舊版曾用大寫來源名，兼容遷移
LEGACY_SOURCES = {"SCOUT APP STORE", "SCOUT APP STORE "}


def hkt_today() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d")


def fetch_live(url: str, anon: str) -> list:
    req = urllib.request.Request(
        f"{url}/rest/v1/apps?select=id,name,url,description,note,icon,icon_source,category,page,tags,visible,sort_order,created_at"
        f"&visible=eq.true&order=sort_order&limit=1000",
        headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def category_to_tags(a: dict) -> list:
    """支部標籤（只跟 5 個支部）+ 小工具 標籤；去重保序。"""
    allowed = {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍"}
    tags = [t for t in (a.get("tags") or []) if t in allowed]
    if "小工具" not in tags:
        tags.append("小工具")
    return tags


# App Store 原分類 → Scout System 內建六類（跟 index.html SCOUT_KIND_LABELS 同步）
STORE_CATEGORY_TO_KIND = {
    "集會助手及指南": "assistant",
    "助手": "assistant",
    "小助手": "assistant",
    "電子紀錄冊": "assistant",
    "進度紀錄": "assistant",
    "紀錄冊": "assistant",
    "遊戲": "game",
    "小遊戲": "game",
    "系統": "system",
    "工具": "tool",
    "其他": "other",
    "有用連結": "link",
    "連結": "link",
}


def store_category_to_kind(cat: str) -> str:
    c = (cat or "").strip()
    if c in STORE_CATEGORY_TO_KIND:
        return STORE_CATEGORY_TO_KIND[c]
    # 模糊匹配（例如「課堂學習工具」→ 工具）
    if "遊戲" in c:
        return "game"
    if "連結" in c:
        return "link"
    if "系統" in c:
        return "system"
    if "工具" in c:
        return "tool"
    if "助手" in c or "紀錄冊" in c:
        return "assistant"
    return "other"


def build_enrich_entry(a: dict, captured_date: str) -> dict:
    """為 Scout System 工具產生 enrich 條目（小工具專屬，不經 PDF）。"""
    title = a.get("name") or ""
    desc = a.get("description") or a.get("note") or ""
    allowed_branches = {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍"}
    branch_tags = [t for t in (a.get("tags") or []) if t in allowed_branches]
    kind = store_category_to_kind(a.get("category") or "")
    # 若無支部標籤，視作全體適用（保留空，enrich 仍可分類為 tools）
    return {
        "source": SOURCE,
        "title": title,
        "deadline": "",
        "audience": "、".join(branch_tags) if branch_tags else "",
        "fee": "免費",
        "description": desc,
        "method": "system",
        "error": "",
        "captured_date": captured_date,
        "enriched_at": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S"),
        "enrich_version": "3.7",
        "categories": [{"id": "tools", "label": "小工具", "subtype": kind, "score": 1.0}],
        "branch_tags": branch_tags,
        "subscription_tags": [f"scout_kind:{kind}"],
        "ss_kind": kind,
        "ss_category": a.get("category") or "",
        "store_category": a.get("category") or "",
        "store_page": a.get("page") or "",
    }


def _norm_url(u: str | None) -> str:
    return (u or "").strip().rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true", help="離線食 appstore.json snapshot")
    ap.add_argument("--apps-json", help="自訂 apps 陣列 JSON 檔（測試）")
    ap.add_argument("--cache", default=str(ROOT / "cache.json"))
    ap.add_argument("--enrich", default=str(ROOT / "enrich.json"))
    args = ap.parse_args()

    store = json.loads((ROOT / "appstore.json").read_text(encoding="utf-8"))
    if args.apps_json:
        apps = json.loads(Path(args.apps_json).read_text(encoding="utf-8"))
    elif args.snapshot:
        apps = store["apps"]
    else:
        try:
            apps = fetch_live(store["_meta"]["supabase_url"], store["_meta"]["anon_key"])
        except Exception as e:
            # sandbox／離線：顯式用 --snapshot 先至允許 fallback，避免 PR 誤帶舊快照（64 項）
            # CI 上一定係 live，失敗就直接報錯唔好靜靜寫錯數。
            import os as _os
            if _os.environ.get("GITHUB_ACTIONS") == "true":
                print(f"❌ live fetch 失敗（{e}）—— CI 唔可以用快照 fallback，請檢查 Supabase 網絡／key", file=sys.stderr)
                raise
            print(f"⚠️ live fetch 失敗（{e}），改用 appstore.json 快照（僅本地測試）", file=sys.stderr)
            apps = store["apps"]

    # 只收已上架（visible=true）；隱藏嘅唔入圖書館
    visible_apps = [
        a for a in apps
        if a.get("visible") and (a.get("url") or "").strip() not in SELF_URLS and _norm_url(a.get("url")) not in {_norm_url(u) for u in SELF_URLS}
    ]
    # 去重：同一 url 只留第一個（避免重複投稿）
    seen = set()
    deduped = []
    for a in visible_apps:
        u = _norm_url(a.get("url"))
        if u and u not in seen:
            seen.add(u)
            deduped.append(a)
    visible_apps = deduped

    cache_path = Path(args.cache)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    data = cache.setdefault("data", {})
    notices = cache.setdefault("notices", [])
    meta = cache.setdefault("_meta", {})
    sync = meta.setdefault("appstore", {})

    enrich_path = Path(args.enrich)
    enrich = {}
    if enrich_path.exists():
        try:
            enrich = json.loads(enrich_path.read_text(encoding="utf-8"))
        except Exception:
            enrich = {}

    today = hkt_today()
    first_sync = sync.get("first_sync")
    if not first_sync:
        first_sync = sync["first_sync"] = today

    known_dates: dict[str, str] = sync.setdefault("known_dates", {})
    sync.pop("known_ids", None)

    # 現有 URL 集合（同時檢查 url 同 pdf_url，因 core.py 寫入嘅 notices 只帶 pdf_url）
    existing_urls: set[str] = set()
    existing_norm_urls: set[str] = set()
    for n in notices:
        if not isinstance(n, dict):
            continue
        u = (n.get("url") or n.get("pdf_url") or "").strip()
        if u:
            existing_urls.add(u)
            existing_norm_urls.add(_norm_url(u))
    for lst in data.values():
        if isinstance(lst, list):
            for e in lst:
                if not isinstance(e, dict):
                    continue
                u = (e.get("url") or e.get("pdf_url") or "").strip()
                if u:
                    existing_urls.add(u)
                    existing_norm_urls.add(_norm_url(u))

    # 建立現有 Scout System 的 URL 歷史記錄對照（只以 URL 為唯一識別）
    existing_map: dict[str, dict] = {}
    for n in notices:
        if isinstance(n, dict) and n.get("source_site") == SOURCE:
            u = (n.get("url") or n.get("pdf_url") or "").strip()
            if u:
                existing_map.setdefault(u, n)
                existing_map.setdefault(_norm_url(u), n)
    for lst in data.values():
        if isinstance(lst, list):
            for e in lst:
                if isinstance(e, dict) and e.get("source_site") == SOURCE:
                    u = (e.get("url") or e.get("pdf_url") or "").strip()
                    if u:
                        existing_map[u] = e
                        existing_map[_norm_url(u)] = e
    # 兼容舊大寫來源
    for legacy in LEGACY_SOURCES:
        if legacy in data and isinstance(data[legacy], list):
            for e in data[legacy]:
                if isinstance(e, dict):
                    u = (e.get("url") or e.get("pdf_url") or "").strip()
                    if u:
                        existing_map.setdefault(u, e)
                        existing_map.setdefault(_norm_url(u), e)

    known_norm_dates = {_norm_url(k): v for k, v in known_dates.items() if k and v}
    enrich_norm_map = {
        _norm_url(k): v
        for k, v in enrich.items()
        if isinstance(v, dict) and v.get("source") == SOURCE
    }
    has_baseline = bool(existing_map or known_norm_dates or enrich_norm_map)

    # ── catalog 鏡像（全份 visible，已上架）＋ 新 URL 判定 ──
    # 規則：以 URL 作為 Scout System 唯一更新點：
    # - 同一 URL（改名、改標籤、改分類、改描述）→ 保留舊 date / captured_date（之前發布），只更新內容；
    # - 新 URL（全新上架，或超大型改版換新 URL 重新上架）→ 當日歸入「今天更新/發布」（date = 今日）。
    catalog = []
    new_notices = []
    new_known_dates: dict[str, str] = {}
    for a in visible_apps:
        url = (a.get("url") or "").strip()
        norm_u = _norm_url(url)
        created = (a.get("created_at") or "")[:10]

        old = existing_map.get(url) or existing_map.get(norm_u)
        enrich_entry = enrich_norm_map.get(norm_u)

        already_known_url = bool(
            old
            or url in known_dates
            or norm_u in known_norm_dates
            or url in existing_urls
            or norm_u in existing_norm_urls
            or enrich_entry
        )

        # 若已有 baseline，任何從未出現過嘅新 URL 都視為「今天更新/發布」；
        # 若係首次空庫初始化（無 baseline），則只將 created >= first_sync 視為今日新上架，防止舊庫風暴。
        is_new_app = (not already_known_url) and (has_baseline or (bool(created) and created >= first_sync))

        if is_new_app:
            captured = today
            date_val = today
        else:
            hist_date = (
                ((old.get("captured_date") or old.get("date")) if old else None)
                or known_dates.get(url)
                or known_norm_dates.get(norm_u)
                or (enrich_entry.get("captured_date") if enrich_entry else None)
            )
            if not hist_date:
                hist_date = BASELINE_DATE
            captured = hist_date
            date_val = (old.get("date") if old and old.get("date") else captured)

        new_known_dates[url] = captured

        catalog.append({
            "title": a.get("name") or "",
            "url": url,
            "pdf_url": url,
            "date": date_val,
            "captured_date": captured,
            "source_site": SOURCE,
            "region": SOURCE,
            "source_url": "https://scoutappstore.vercel.app/",
            "tags": category_to_tags(a),
            "description": a.get("description") or a.get("note") or "",
            "icon": a.get("icon") or "",
            "store_category": a.get("category") or "",
            "store_page": a.get("page") or "",
        })

        if is_new_app:
            new_notices.append({
                "title": a.get("name") or "",
                "url": url,
                "pdf_url": url,
                "date": today,
                "captured_date": today,
                "source_site": SOURCE,
                "region": SOURCE,
                "source_url": "https://scoutappstore.vercel.app/",
                "tags": category_to_tags(a),
                "description": a.get("description") or a.get("note") or "",
                "icon": a.get("icon") or "",
            })

    sync["known_dates"] = new_known_dates

    # 按 store sort_order 排序（跟 App Store 展示順序）
    catalog.sort(key=lambda x: next((a.get("sort_order", 0) for a in visible_apps if a.get("url") == x["url"]), 0))

    # 寫入 Scout System，清理舊大寫 key
    data[SOURCE] = catalog
    for legacy in LEGACY_SOURCES:
        if legacy in data:
            del data[legacy]

    # 確保 _meta.regions / source_order 有 Scout System
    regions = meta.setdefault("regions", {})
    if SOURCE not in regions:
        regions[SOURCE] = [SOURCE]
    source_order = meta.setdefault("source_order", [])
    if SOURCE not in source_order:
        source_order.append(SOURCE)

    # 同步現有 notices 入面嘅 Scout System 條目標題與標籤（嚴格保留舊 captured_date）
    catalog_by_norm = {_norm_url(c["url"]): c for c in catalog}
    for n in notices:
        if isinstance(n, dict) and n.get("source_site") == SOURCE:
            u = _norm_url(n.get("url") or n.get("pdf_url"))
            if u in catalog_by_norm:
                c_item = catalog_by_norm[u]
                n["title"] = c_item["title"]
                n["tags"] = list(c_item["tags"])

    notices.extend(new_notices)

    # ── enrich.json 同步 ──
    # 為每個可見 app 保證有 enrich 條目 — 按 store_category 分類，舊紀錄改名／換位自動更新；
    # 若欄位無變動，保留原有 enriched_at，避免每日檢查標籤時產生無謂 diff。
    for a in visible_apps:
        url = (a.get("url") or "").strip()
        c_item = catalog_by_norm.get(_norm_url(url))
        captured_date = c_item["captured_date"] if c_item else BASELINE_DATE
        kind = store_category_to_kind(a.get("category") or "")
        if url not in enrich or not isinstance(enrich.get(url), dict):
            enrich[url] = build_enrich_entry(a, captured_date)
        else:
            e = enrich[url]
            new_title = a.get("name") or e.get("title", "")
            new_desc = a.get("description") or a.get("note") or e.get("description", "")
            allowed_branches = {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍"}
            branch_tags = [t for t in (a.get("tags") or []) if t in allowed_branches]
            new_audience = "、".join(branch_tags) if branch_tags else ""
            new_categories = [{"id": "tools", "label": "小工具", "subtype": kind, "score": 1.0}]
            new_sub_tags = [f"scout_kind:{kind}"]
            new_cat = a.get("category") or ""
            new_page = a.get("page") or ""

            changed = (
                e.get("title") != new_title
                or e.get("description") != new_desc
                or e.get("branch_tags") != branch_tags
                or e.get("audience") != new_audience
                or e.get("categories") != new_categories
                or e.get("subscription_tags") != new_sub_tags
                or e.get("ss_kind") != kind
                or e.get("ss_category") != new_cat
                or e.get("store_category") != new_cat
                or e.get("store_page") != new_page
                or e.get("captured_date") != captured_date
            )

            e["title"] = new_title
            e["description"] = new_desc
            e["branch_tags"] = branch_tags
            e["audience"] = new_audience
            e["categories"] = new_categories
            e["subscription_tags"] = new_sub_tags
            e["ss_kind"] = kind
            e["ss_category"] = new_cat
            e["store_category"] = new_cat
            e["store_page"] = new_page
            e["captured_date"] = captured_date
            if changed:
                e["enriched_at"] = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")

    # 移除已隱藏或已換新 URL 嘅舊 app enrich（只移除 source=Scout System，唔誤刪通告 enrich）
    visible_urls = {(a.get("url") or "").strip() for a in visible_apps}
    for url in list(enrich.keys()):
        v = enrich[url]
        if isinstance(v, dict) and v.get("source") == SOURCE and url not in visible_urls:
            del enrich[url]

    # 寫檔 — 永遠只計 visible，唔保留 hidden 計數
    sync["last_sync"] = today
    sync["catalog_size"] = len(catalog)
    sync["visible_count"] = len(visible_apps)
    sync.pop("hidden_skipped", None)

    # 更新 meta.total_notices / last_updated（跟 core.py 格式）
    cache["last_updated"] = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    if "meta" in cache:
        cache["meta"]["total_notices"] = len(notices)
    # 保證 data 內 Scout System 在 _meta 內被計入
    if "_meta" in cache:
        cache["_meta"]["total_sources"] = len(data)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    enrich_path.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"✅ {SOURCE}：catalog {len(catalog)} 項（已上架 {len(visible_apps)}）｜新 APP {len(new_notices)} 個（baseline {first_sync}）")
    for n in new_notices:
        print(f"   + {n['title']} {n['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
