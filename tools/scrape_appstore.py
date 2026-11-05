#!/usr/bin/env python3
"""加掃 SCOUT APP STORE：將 store apps 表併入 cache.json 的 Scout System。

設計（見 APPSTORE_INTEGRATION.md 階段 2）：
- 讀取：anon key 就夠（RLS 限 visible=true SELECT），唔使 service key。
- data["Scout System"] = 全份 visible catalog（只收 visible=true，已上架的）。
  隱藏（visible=false）永遠唔會入圖書館；若舊版曾經可見但而家隱藏，下次同步會自動移除。
- 2026-11-06 用戶規則（Scout System 結構同通告唔同）：「今天更新/發布」只收
  **由未上架變成上架** 嘅小工具 —— 即係今日新上架、或者下架後重新上架。
  一直喺架上嘅舊 app 一律留喺「之前發布」，日期用返商店真實日期，唔會因為
  圖書館第一次見到個 URL 就蓋成今日（2026-10-21 同 2026-11-06 兩次全版變今日
  都係咁嚟）。
  - 同一 URL 改名、改標籤、改分類、改描述、換 icon → 只更新欄位，日期不變。
  - 新 URL 但商店 `created_at` 舊過今日 → 上架咗好耐，用 `created_at` 做日期。
  - `created_at` 係今日 → 真係今日上架，計入「今天更新/發布」。
  - 曾經上架、之後喺 store 唔見咗（隱藏／下架）→ 記錄喺 `_meta.appstore.delisted`；
    再上架就係今日。
  - 防呆：一次過有太多「未見過嘅 URL」想變今日（例如 baseline 斷咗、store 換 domain），
    唔會照單全收，改用商店真實日期並喺 log 大聲講。
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


def _parse_date(value: str):
    """'2026-11-06' / '2026-11-06T...' → date；唔合法就 None。"""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


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
    today_dt = _parse_date(today)
    first_sync = sync.get("first_sync")
    if not first_sync:
        first_sync = sync["first_sync"] = today

    known_dates: dict[str, str] = sync.setdefault("known_dates", {})
    # 「今天」＝由未上架變成上架（見檔頭 2026-11-06 規則）。delisted 記住
    # 曾經上架、而家喺 store 唔見咗嘅 URL；佢再上返架就係今日。
    delisted: dict[str, str] = sync.setdefault("delisted", {})
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

    # 上一次 catalog = 上一次真係喺架上嘅清單（core.py 每日重建時會保住佢）
    prev_dates: dict[str, str] = {}
    for e in data.get(SOURCE) or []:
        if not isinstance(e, dict):
            continue
        key = _norm_url(e.get("url") or e.get("pdf_url"))
        if key:
            prev_dates.setdefault(key, str(e.get("captured_date") or e.get("date") or ""))

    if not visible_apps:
        # 0 個上架 = store 抓唔到嘢，唔可以照寫（否則清空成個 Scout System）
        print(f"❌ {SOURCE}：store 回傳 0 個已上架 APP，拒絕寫入（保留現有 catalog）",
              file=sys.stderr)
        return 1

    # ── catalog 鏡像（全份 visible，已上架）＋ 上架日判定 ──
    # 2026-11-06 用戶規則：Scout System 同通告唔同結構，「今天更新/發布」只收
    # 由「未上架」變成「上架」嘅小工具（今日新上架／重新上架）。
    # 一直喺架上嘅舊 app 一律留喺「之前發布」，用返本身嘅上架日期 ——
    # 唔會因為圖書館第一次見到個 URL 就蓋成今日（2026-10-21、2026-11-06 兩次
    # 「全個 Scout System 變晒今日」都係咁嚟）。
    catalog = []
    today_items = []          # 今日（重新）上架：date == today
    for a in visible_apps:
        url = (a.get("url") or "").strip()
        norm_u = _norm_url(url)
        created = (a.get("created_at") or "")[:10]
        created_dt = _parse_date(created)
        published_before_today = bool(created_dt) and created_dt < today_dt

        hist_date = (
            prev_dates.get(norm_u)
            or known_dates.get(url)
            or known_norm_dates.get(norm_u)
            or (enrich_norm_map.get(norm_u) or {}).get("captured_date")
            or ""
        )
        was_delisted = norm_u in delisted or url in delisted
        evidence = False          # 有正面證據先准「今日」（新 created_at／重新上架）

        if was_delisted:
            # 下架 → 重新上架：今日
            listing_date = today
            evidence = True
        elif hist_date:
            # 一路喺架上（或者上過架）：保留原本上架日期
            listing_date = hist_date
        elif published_before_today:
            # 商店話佢好早就建立：只係圖書館歷史斷咗，唔可以當今日
            listing_date = created
        elif created_dt:
            # created_at 係今日（或未來，store 時間有問題）→ 真係今日上架
            listing_date = today
            evidence = True
        else:
            # 完全冇 created_at：有 baseline 就當今日新上架（下面防呆會把關）
            listing_date = today if has_baseline else BASELINE_DATE

        if not listing_date:
            listing_date = BASELINE_DATE
        if today_dt and _parse_date(listing_date) and _parse_date(listing_date) > today_dt:
            listing_date = today          # 唔好把未來日期寫入圖書館

        entry = {
            "title": a.get("name") or "",
            "url": url,
            "pdf_url": url,
            "date": listing_date,
            "captured_date": listing_date,
            "source_site": SOURCE,
            "region": SOURCE,
            "source_url": "https://scoutappstore.vercel.app/",
            "tags": category_to_tags(a),
            "description": a.get("description") or a.get("note") or "",
            "icon": a.get("icon") or "",
            "store_category": a.get("category") or "",
            "store_page": a.get("page") or "",
        }
        catalog.append(entry)
        if listing_date == today:
            today_items.append({
                "entry": entry,
                "evidence": evidence,
                "fallback": created if published_before_today else BASELINE_DATE,
            })

    # ── 防呆：唔可以一次過把成個 catalog 洗成今日 ──
    # 兩次事故（2026-10-21、2026-11-06）都係「baseline 一閃失 → 全部 URL 當新」。
    # 而家：無正面證據（商店 created_at 舊／冇 created_at）而又一次過多過
    # 上限，就當 baseline 斷咗，改用真實日期，並喺 log 講清楚。
    blast_limit = max(3, int(len(catalog) * 0.3))
    if has_baseline and len(today_items) > blast_limit:
        defused = 0
        for item in today_items:
            if item["evidence"]:
                continue
            entry = item["entry"]
            entry["date"] = entry["captured_date"] = item["fallback"] or BASELINE_DATE
            defused += 1
        today_items = [i for i in today_items if i["entry"]["captured_date"] == today]
        if defused:
            print(f"⚠️  {SOURCE}：{defused} 個未曾見過嘅 URL 想一次過變「今日」"
                  f"（上限 {blast_limit}）—— 當 baseline 斷咗，改用商店真實日期，"
                  f"唔會全版變今日")

    # ── 抓唔齊嘅自我保護：一次過少咁多 = store 回傳唔完整 ──
    # 與其把成個 catalog 縮水（會連 enrich、notices 一齊跌走），保留舊條目。
    visible_norms = {_norm_url((a.get("url") or "").strip()) for a in visible_apps}
    visible_norms.discard("")
    prev_by_norm: dict[str, dict] = {}
    for e in data.get(SOURCE) or []:
        if isinstance(e, dict):
            key = _norm_url(e.get("url") or e.get("pdf_url"))
            if key:
                prev_by_norm.setdefault(key, e)
    missing_norms = [k for k in prev_dates if k and k not in visible_norms]
    suspicious_shrink = bool(missing_norms) and len(missing_norms) > max(2, len(prev_dates) // 3)
    carried = 0
    if suspicious_shrink:
        for key in missing_norms:
            prev_entry = prev_by_norm.get(key)
            if prev_entry:
                catalog.append(dict(prev_entry))
                carried += 1
        print(f"⚠️  {SOURCE}：上一次 catalog 有 {len(prev_dates)} 項，今次 store 只回 "
              f"{len(visible_norms)} 項 —— 當抓唔齊，保留 {carried} 項舊資料、"
              f"唔記下架、唔清 enrich")

    new_known_dates: dict[str, str] = {
        e["url"]: e["captured_date"] for e in catalog if e.get("url")
    }

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

    # ── notices 對帳：每個已上架 app 都要有一條，日期跟 catalog ──
    # 之前只會為「新 APP」append 一條，舊 app 甩咗就永遠唔會補返（2026-11-06
    # 見到 cache 有 17 個 app 但 notices 只有 13 條）；重新上架又會疊多一條
    # 重複。而家一次過對帳：缺就補（用本身日期，唔會當今日），有就更新
    # 標題／標籤／日期，一條 app 只會有一條 notice。
    catalog_by_norm = {_norm_url(c["url"]): c for c in catalog}
    notices_by_norm: dict[str, dict] = {}
    for n in notices:
        if isinstance(n, dict) and n.get("source_site") == SOURCE:
            key = _norm_url(n.get("url") or n.get("pdf_url"))
            if key:
                notices_by_norm.setdefault(key, n)

    added_notices = 0
    for key, c_item in catalog_by_norm.items():
        n = notices_by_norm.get(key)
        if n is None:
            n = {
                "title": c_item["title"],
                "url": c_item["url"],
                "pdf_url": c_item["url"],
                "date": c_item["date"],
                "captured_date": c_item["captured_date"],
                "source_site": SOURCE,
                "region": SOURCE,
                "source_url": "https://scoutappstore.vercel.app/",
                "tags": list(c_item["tags"]),
                "description": c_item["description"],
                "icon": c_item["icon"],
            }
            notices.append(n)
            notices_by_norm[key] = n
            added_notices += 1
        else:
            n["title"] = c_item["title"]
            n["tags"] = list(c_item["tags"])
            n.setdefault("url", c_item["url"])
            n.setdefault("pdf_url", c_item["url"])
            n["date"] = c_item["date"]
            n["captured_date"] = c_item["captured_date"]

    new_notices = [i["entry"] for i in today_items]   # 只作輸出用（今日上架）

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

    # ── 下架記錄：邊啲上過架嘅 app 而家唔喺架上 ──
    # 記住嘅目的只有一個：下次再上架就當「今日」。
    for key in list(delisted):
        if key in visible_norms:
            delisted.pop(key, None)
    if not suspicious_shrink:
        for key in missing_norms:
            delisted.setdefault(key, today)

    # 移除真係下架／換新 URL 嘅舊 app enrich（只移除 source=Scout System，唔誤刪通告 enrich）
    if not suspicious_shrink:
        for url in list(enrich.keys()):
            v = enrich[url]
            if isinstance(v, dict) and v.get("source") == SOURCE and _norm_url(url) not in visible_norms:
                del enrich[url]

    # enrich 自我修復：catalog 內每個 app（包括抓唔齊時保留下嚟嘅）都要有條目。
    # 之前 enrich.json 可以一直缺 7 個 app 而冇人知（前端只係少咗描述）。
    for c_item in catalog:
        url = (c_item.get("url") or "").strip()
        if not url or isinstance(enrich.get(url), dict):
            continue
        enrich[url] = build_enrich_entry(
            {
                "name": c_item.get("title") or "",
                "description": c_item.get("description") or "",
                "tags": c_item.get("tags") or [],
                "category": c_item.get("store_category") or "",
                "page": c_item.get("store_page") or "",
            },
            c_item.get("captured_date") or BASELINE_DATE,
        )

    sync["known_dates"] = new_known_dates
    sync["delisted"] = delisted

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

    # 靜默失敗防線：每個已上架 app 一定要有 enrich 條目，否則大聲講。
    missing_enrich = [
        (c.get("url") or "").strip() for c in catalog
        if not isinstance(enrich.get((c.get("url") or "").strip()), dict)
    ]
    if missing_enrich:
        print(f"⚠️  {SOURCE}：{len(missing_enrich)} 個已上架 APP 冇 enrich 條目："
              f"{'、'.join(missing_enrich[:5])}", file=sys.stderr)

    print(f"✅ {SOURCE}：catalog {len(catalog)} 項（已上架 {len(visible_apps)}）"
          f"｜今日新上架 {len(today_items)} 個｜下架記錄 {len(delisted)} 個"
          f"｜補 notices {added_notices} 條（baseline {first_sync}）")
    for n in new_notices:
        print(f"   + {n['title']} {n['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
