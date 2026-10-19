#!/usr/bin/env python3
"""加掃 SCOUT APP STORE：將 store apps 表併入 cache.json 的 Scout System。

設計（見 APPSTORE_INTEGRATION.md 階段 2）：
- 讀取：anon key 就夠（RLS 限 visible=true SELECT），唔使 service key。
- data["Scout System"] = 全份 visible catalog（只收 visible=true，已上架的）。
  隱藏（visible=false）永遠唔會入圖書館；若舊版曾經可見但而家隱藏，下次同步會自動移除。
- notices 只收「first-sync baseline 之後」先出現嘅 app（store created_at 比較），
  避免首次同步一刻將舊 app 當新通告派發 push／story 風暴。
- url 去重：已喺任何來源（含手動加入）出現過嘅 url 唔入 notices。
- 新 notice 嘅 date／captured_date = 系統捕獲日（HKT），跟現有哲學。
- 自己（scout-circulars.vercel.app）永遠 skip。
- enrich.json 同步：每個可見 app 保證有 enrich 條目（小工具分類、支部標籤、描述）。

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
    """保持與舊版一致：支部標籤 + 小工具 標籤；去重保序。"""
    tags = [t for t in (a.get("tags") or []) if t]
    if "小工具" not in tags:
        tags.append("小工具")
    return tags


def build_enrich_entry(a: dict) -> dict:
    """為 Scout System 工具產生 enrich 條目（小工具專屬，不經 PDF）。"""
    title = a.get("name") or ""
    desc = a.get("description") or a.get("note") or ""
    branch_tags = [t for t in (a.get("tags") or []) if t in
                   {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍", "領袖", "家長", "會務委員"}]
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
        "enriched_at": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S"),
        "enrich_version": "3.7",
        "categories": [{"id": "tools", "label": "小工具", "subtype": "assistant", "score": 1.0}],
        "branch_tags": branch_tags,
        "subscription_tags": ["category:tools"],
    }


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
    visible_apps = [a for a in apps if a.get("visible") and a.get("url") not in SELF_URLS]
    # 去重：同一 url 只留第一個（避免重複投稿）
    seen = set()
    deduped = []
    for a in visible_apps:
        u = a.get("url")
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

    today = hkt_today()
    first_sync = sync.get("first_sync")
    if not first_sync:
        first_sync = sync["first_sync"] = today  # baseline：之後先批准嘅 app 先算「新」

    # 現有 URL → 舊 entry（用嚟保留 captured_date）
    existing_urls = {n.get("url") for n in notices if n.get("url")}
    for lst in data.values():
        if isinstance(lst, list):
            existing_urls |= {e.get("url") for e in lst if isinstance(e, dict) and e.get("url")}

    # 建立現有 Scout System 的 captured_date 對照（保留歷史日期）
    existing_map = {}
    for lst in data.values():
        if isinstance(lst, list):
            for e in lst:
                if e.get("source_site") == SOURCE and e.get("url"):
                    existing_map[e["url"]] = e
    # 兼容舊大寫來源
    for legacy in LEGACY_SOURCES:
        if legacy in data:
            for e in data[legacy]:
                if e.get("url"):
                    existing_map.setdefault(e["url"], e)

    # ── catalog 鏡像（全份 visible，已上架）→ Scout System ──
    catalog = []
    for a in visible_apps:
        url = a.get("url")
        old = existing_map.get(url)
        # 保留舊 captured_date / date，唔好令舊工具日日變「今日新上架」
        captured = old.get("captured_date") if old and old.get("captured_date") else today
        date_val = old.get("date") if old and old.get("date") else captured
        catalog.append({
            "title": a.get("name") or "",
            "url": url,
            "pdf_url": url,
            "date": date_val,
            "captured_date": captured,
            "source_site": SOURCE,
            "region": SOURCE,
            "tags": category_to_tags(a),
            "description": a.get("description") or a.get("note") or "",
            "icon": a.get("icon") or "",
            "store_category": a.get("category") or "",
            "store_page": a.get("page") or "",
        })
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

    # ── 新 app → notices（baseline 之後 created_at，且 url 未收錄）──
    new_notices = []
    for a in visible_apps:
        url = a.get("url")
        if url in existing_urls:
            continue
        created = (a.get("created_at") or "")[:10]
        # 若 snapshot 無 created_at（舊快照），以 captured 之後先算新 → 唔會觸發舊 app 風暴
        if not created:
            continue
        if created < first_sync:
            continue  # 舊 app，唔溯及（同日新上架視為新，避免 baseline=今日時即日新 app 被漏）
        new_notices.append({
            "title": a.get("name") or "",
            "url": url,
            "pdf_url": url,
            "date": today,
            "captured_date": today,
            "source_site": SOURCE,
            "region": SOURCE,
            "tags": category_to_tags(a),
            "description": a.get("description") or a.get("note") or "",
            "icon": a.get("icon") or "",
        })
    notices.extend(new_notices)

    # ── enrich.json 同步 ──
    enrich_path = Path(args.enrich)
    enrich = {}
    if enrich_path.exists():
        try:
            enrich = json.loads(enrich_path.read_text(encoding="utf-8"))
        except Exception:
            enrich = {}
    # 為每個可見 app 保證有 enrich 條目
    for a in visible_apps:
        url = a.get("url")
        if url not in enrich:
            enrich[url] = build_enrich_entry(a)
        else:
            # 更新可變欄位（標題、描述、支部），保留已抽取嘅其他欄
            e = enrich[url]
            e["title"] = a.get("name") or e.get("title", "")
            e["description"] = a.get("description") or a.get("note") or e.get("description", "")
            branch_tags = [t for t in (a.get("tags") or []) if t in
                           {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍", "領袖", "家長", "會務委員"}]
            if branch_tags:
                e["audience"] = "、".join(branch_tags)
                e["branch_tags"] = branch_tags
            # 若舊 entry 無 categories，補上小工具分類
            if not e.get("categories"):
                e["categories"] = [{"id": "tools", "label": "小工具", "subtype": "assistant", "score": 1.0}]
                e["subscription_tags"] = ["category:tools"]

    # 移除已隱藏 app 的 enrich（若該 app 而家唔再可見，對應 url 在本輪無出現）
    # 注意：只移除「本工具曾經產生」的條目（source=Scout System），唔好誤刪通告 enrich
    visible_urls = {a.get("url") for a in visible_apps}
    for url in list(enrich.keys()):
        v = enrich[url]
        if v.get("source") == SOURCE and url not in visible_urls:
            # 已下架／隱藏 → 移除
            del enrich[url]

    # 寫檔 — 永遠只計 visible，唔保留 hidden 計數
    sync["last_sync"] = today
    sync["catalog_size"] = len(catalog)
    sync["visible_count"] = len(visible_apps)
    sync.pop("hidden_skipped", None)
    # 若快照無 created_at，baseline 第二次 run 不應重複計算舊 app
    # 已透過 existing_urls 去重保證。

    # 更新 meta.total_notices / last_updated（跟 core.py 格式）
    cache["last_updated"] = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    if "meta" in cache:
        cache["meta"]["total_notices"] = len(notices)
    # 保證 data 內 Scout System 在 _meta 內被計入
    if "_meta" in cache:
        cache["_meta"]["total_sources"] = len(data)

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    enrich_path.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"✅ {SOURCE}：catalog {len(catalog)} 項（已上架 {len(visible_apps)}）｜新通告 {len(new_notices)} 張（baseline {first_sync}）")
    for n in new_notices:
        print(f"   + {n['title']} {n['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
