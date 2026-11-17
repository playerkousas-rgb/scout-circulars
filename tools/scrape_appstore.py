#!/usr/bin/env python3
"""加掃 SCOUT APP STORE：將 store apps 表併入 cache.json 的 Scout System。

設計（見 APPSTORE_INTEGRATION.md 階段 2）：
- 讀取：anon key 就夠（RLS 唔會過濾 visible=false），唔使 service key。
- data["Scout System"] = 全份 catalog：已上架（visible=true）照常；
  **2026-11-15 新規則（用戶確認）：曾經公開上架、而家喺 APP STORE 收埋
  （visible=false）嘅 app —— 唔刪 cache.json / enrich.json 記錄、保留首次
  公開日**；純粹以 store-hidden.json 為信號，由前端顯示層喺正常瀏覽／搜尋／
  分類／計數全部收埋，只喺「⭐ 我的收藏」標示已下架兼鎖死開啟掣。
  從未公開過而 visible=false 嘅 app：仍然係「未上架」（見下面狀態 2），
  永遠唔入 catalog、唔計數。
- **2026-11-07 用戶規則（取代 2026-11-06）：上架日＝「公開」嘅日子，唔係「入庫」嘅日子。**
  `created_at` 係 store 建立紀錄嘅時間（入庫日），`visible=true` 先至係公開；
  圖書館第一次見到個 URL、或者個 app 今日先建立，都唔等於今日公開。
  四種狀態：
    1. **今天公開 = 今天上架**：第一次觀察到 `visible=true` → 上架日 = 今日；
    2. **今天入庫但沒公開 = 未上架**：`visible=false` → 唔入 catalog、唔計今日、
       記喺 `_meta.appstore.pending`；
    3. **之前入庫，但今天公開 = 今天上架**：`created_at` 舊過今日都好，只要
       之前從未公開過、今日首次公開，就係今日上架（「遊戲學習」個案）。
    4. **曾經上架、而家收埋（APP STORE `visible=false`）= 記錄保留**（2026-11-15 新規則）：
       唔刪 cache.json / enrich.json 記錄、保留原首次公開日；再放出（`visible=true`）
       就當冇收埋過，唔會變成今天。從未上架過而隱藏嘅維持「未上架」。
  其餘：
  - 一直喺架上（已有首次公開日）→ 保留本身上架日；改名／改標籤／改分類／
    改描述／換 icon 都唔改日期。
  - 曾經上架、之後喺 store 完全唔見咗（紀錄被刪）→ `_meta.appstore.delisted`；
    再上架＝今日重新上架（`visible=false` 收埋唔再當下架，見狀態 4）。
  - `created_at` **只**做「首次同步／baseline 全失」時嘅 fallback 日期，
    唔再用嚟判斷「今日」。
  - 防呆：一次過有太多從未公開過嘅 URL 想變今日（baseline 斷咗／store 換 domain），
    唔會照單全收，改用 `created_at`（或 BASELINE_DATE）並喺 log 大聲講。
- 自己（scout-circulars.vercel.app）永遠 skip。
- enrich.json 同步：每個可見 app 保證有 enrich 條目（小工具分類、支部標籤、描述）；
  若現有 app 欄位無變動，唔會無故刷新 enriched_at 時間戳。

用法：
  python tools/scrape_appstore.py                # live REST（你部機／Actions）
  python tools/scrape_appstore.py --snapshot     # 離線：食 appstore.json 內 snapshot（sandbox 測試）
  python tools/scrape_appstore.py --apps-json X  # 離線：食自訂 apps 陣列檔（測試新 app 觸發）
  python tools/scrape_appstore.py --cache Y      # 指定 cache.json 路徑（測試用 copy）
  python tools/scrape_appstore.py --hidden Z     # 指定 store-hidden.json 輸出路徑（測試用）
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

# 2026-11-07 一次性修正：11-07 嗰次 RUN 仍然用緊舊規則（新 URL + created_at
# 舊過今日 → 用 created_at），把「遊戲學習」(created 11-06、11-07 先公開)
# 寫成 11-06。呢個 dict 釘死真正嘅首次公開日；只有當現存日期仍然等於
# 舊規則抄落嘅 created_at 先至修正（見 main 嘅 wrong_date），改完就由
# first_public 正常接管，將來下架再上架唔會被舊日期蓋返。
FIRST_PUBLIC_OVERRIDES = {
    "https://app.astra-ai.co/lab": "2026-11-07",
}


def hkt_today() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d")


def _parse_date(value: str):
    """'2026-11-06' / '2026-11-06T...' → date；唔合法就 None。"""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def fetch_live(url: str, anon: str) -> list:
    # 連 visible=false 一齊撈返嚟：先有辦法分辨「收埋咗但曾經公開過」（保留記錄）
    # 同「從未公開」（未上架）。
    # ⚠️ RLS（website migrations/20260924-market.sql：policy "public catalogue"
    # `using (visible = true)`）：anon key **睇唔到** visible=false 列。
    # 隱藏同步靠 ACTION 帶 service key 先行：fetch_live 會優先用
    # STORE_SERVICE_KEY（workflow 注入 SUPABASE_SERVICE_KEY）；冇 service key
    # 就退回 anon（此時 visible=false  rows 會整批唔見——曾經上架而收埋嘅 app
    # 會當 store-missing（delisted）處理，重現規則同以前一樣）。
    req = urllib.request.Request(
        f"{url}/rest/v1/apps?select=id,name,url,description,note,icon,icon_source,category,page,tags,visible,sort_order,created_at"
        f"&order=sort_order&limit=1000",
        headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def category_to_tags(a: dict) -> list:
    """支部標籤（只跟 5 個支部）+ 大類標籤（小工具／連結）；去重保序。

    2026-11-12 用戶規則：Scout System 只分兩大類——自家出品「小工具」同
    他人網站／APP「連結」。store 嘅 links page 一律當連結，唔好再因為
    原分類叫「xxx工具」而混入小工具。
    """
    allowed = {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍"}
    tags = [t for t in (a.get("tags") or []) if t in allowed]
    group_tag = "連結" if (a.get("page") or "").strip().lower() == "links" else "小工具"
    if group_tag not in tags:
        tags.append(group_tag)
    return tags


# App Store 原分類 → 自家出品小工具嘅細分類（跟 index.html SCOUT_KIND_LABELS 同步）
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


def store_app_kind(a: dict) -> str:
    """Scout System 分類：store page 最權威。

    * links page ＝ 他人嘅網站／APP → 一律「連結」，唔再細分（就算原分類
      叫「課堂學習工具」都唔會變成工具）；
    * apps／cards／ppt ＝ 自家出品 → 按原分類細分（助手／遊戲／系統／工具／其他）。
    """
    page = (a.get("page") or "").strip().lower()
    if page == "links":
        return "link"
    return store_category_to_kind(a.get("category") or "")


def build_enrich_entry(a: dict, captured_date: str) -> dict:
    """為 Scout System 工具產生 enrich 條目（小工具專屬，不經 PDF）。"""
    title = a.get("name") or ""
    desc = a.get("description") or a.get("note") or ""
    allowed_branches = {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍"}
    branch_tags = [t for t in (a.get("tags") or []) if t in allowed_branches]
    kind = store_app_kind(a)
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
    """URL 正規化（前後端必須一致）：trim + 去晒尾斜線；唔改 scheme／host／path 大小寫。"""
    return (u or "").strip().rstrip("/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true", help="離線食 appstore.json snapshot")
    ap.add_argument("--apps-json", help="自訂 apps 陣列 JSON 檔（測試）")
    ap.add_argument("--cache", default=str(ROOT / "cache.json"))
    ap.add_argument("--enrich", default=str(ROOT / "enrich.json"))
    ap.add_argument("--hidden", default=str(ROOT / "store-hidden.json"),
                    help="store-hidden.json 輸出路徑（APP STORE 收埋咗嘅曾經上架 app 清單）")
    ap.add_argument("--today", help="覆寫 HKT 今日（只供離線測試日期規則）")
    args = ap.parse_args()

    # 上一次 store-hidden.json：store 回應疑似唔完整時維持原狀，唔會因一次
    # 抓唔齊就把全館 app 一齊收埋。
    previous_hidden: list[str] = []
    try:
        _prev_doc = json.loads(Path(args.hidden).read_text(encoding="utf-8"))
        previous_hidden = sorted({
            u for u in (_norm_url(u) for u in (_prev_doc.get("hidden") or [])) if u
        })
    except Exception:
        previous_hidden = []

    store = json.loads((ROOT / "appstore.json").read_text(encoding="utf-8"))
    if args.apps_json:
        apps = json.loads(Path(args.apps_json).read_text(encoding="utf-8"))
    elif args.snapshot:
        apps = store["apps"]
    else:
        try:
            import os as _os
            # RLS 只畀 anon 睇 visible=true；要靠 visible=false 列分辨「收埋咗」，
            # 一定要 service key（workflow 已注入 STORE_SERVICE_KEY）。
            service = (_os.environ.get("STORE_SERVICE_KEY") or _os.environ.get("SUPABASE_SERVICE_KEY") or "").strip()
            if not service and _os.environ.get("GITHUB_ACTIONS") == "true":
                print("::warning::冇 STORE_SERVICE_KEY/SUPABASE_SERVICE_KEY——RLS 只界 anon 睇 visible=true；"
                      "「曾經上架而收埋」會當 store-missing（delisted）處理，store-hidden.json 會係空嘅", flush=True)
            key = service or store["_meta"]["anon_key"]
            key_kind = "service key（可見 visible=false）" if service else "anon key（RLS 只見 visible=true）"
            print(f"ℹ️ APP STORE live fetch：{key_kind}")
            apps = fetch_live(store["_meta"]["supabase_url"], key)
        except Exception as e:
            # sandbox／離線：顯式用 --snapshot 先至允許 fallback，避免 PR 誤帶舊快照（64 項）
            # CI 上一定係 live，失敗就直接報錯唔好靜靜寫錯數。
            import os as _os
            if _os.environ.get("GITHUB_ACTIONS") == "true":
                print(f"❌ live fetch 失敗（{e}）—— CI 唔可以用快照 fallback，請檢查 Supabase 網絡／key", file=sys.stderr)
                raise
            print(f"⚠️ live fetch 失敗（{e}），改用 appstore.json 快照（僅本地測試）", file=sys.stderr)
            apps = store["apps"]

    # store-hidden.json 需要見到全部行（visible=false 都要讀返），先有辦法分辨
    # 「收埋但曾經公開」（保留記錄）同「從未公開」（未上架）。
    hidden_apps = [
        a for a in apps
        if not a.get("visible") and (a.get("url") or "").strip()
        and (a.get("url") or "").strip() not in SELF_URLS
        and _norm_url(a.get("url")) not in {_norm_url(u) for u in SELF_URLS}
    ]
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

    today = args.today or hkt_today()
    today_dt = _parse_date(today)
    first_sync = sync.get("first_sync")
    if not first_sync:
        first_sync = sync["first_sync"] = today

    known_dates: dict[str, str] = sync.setdefault("known_dates", {})
    # 2026-11-07：first_public（normalized URL → 首次公開日）先係權威嘅「上架日」。
    # 舊 snapshot 只有 known_dates（舊規則下可能係抄 created_at），所以第一次
    # 見到呢個欄位時由 known_dates 遷移，之後由下面嘅判定寫入真正公開日。
    first_public: dict[str, str] = sync.setdefault("first_public", {})
    for _k, _v in known_dates.items():
        if _k and _v:
            first_public.setdefault(_norm_url(_k), _v)
    # 未上架：store 有紀錄但未公開（或曾經上架而家隱藏）嘅 URL。
    pending: dict[str, dict] = sync.setdefault("pending", {})
    # delisted 記住曾經上架、而家喺 store 唔見咗嘅 URL；再上返架就係今日。
    delisted: dict[str, str] = sync.setdefault("delisted", {})
    sync["rule"] = "first-public-visible-2026-11-07"
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
    has_baseline = bool(existing_map or known_norm_dates or enrich_norm_map or first_public)

    # 上一次 catalog = 上一次真係喺架上（或曾經公開後收埋保留）嘅清單
    # （core.py 每日重建時會保住佢）
    prev_dates: dict[str, str] = {}
    for e in data.get(SOURCE) or []:
        if not isinstance(e, dict):
            continue
        key = _norm_url(e.get("url") or e.get("pdf_url"))
        if key:
            prev_dates.setdefault(key, str(e.get("captured_date") or e.get("date") or ""))

    # ── 2026-11-15 新規則：曾經公開上架 → 收埋亦保留 ──────────────────
    # 「曾經公開過」嘅證據：舊 catalog（prev_dates）或 first_public /
    # known_dates / enrich（含舊版 _meta 記錄）。有證據：保留 cache/enrich
    # 記錄同首次公開日，並寫入 store-hidden.json（前端收埋）。
    # 冇證據（從未公開）：仍然係「未上架」，唔入 catalog、唔計數。
    def publication_evidence(key: str, url: str) -> str:
        return (
            prev_dates.get(key)
            or first_public.get(key)
            or known_dates.get(url)
            or known_norm_dates.get(key)
            or (enrich_norm_map.get(key) or {}).get("captured_date")
            or ""
        )

    keep_hidden_apps: list[tuple[dict, str]] = []   # (store 行, 首次公開日)
    for a in hidden_apps:
        url = (a.get("url") or "").strip()
        key = _norm_url(url)
        pub = publication_evidence(key, url)
        if pub:
            keep_hidden_apps.append((a, pub))

    if not visible_apps:
        # 0 個上架 = store 抓唔到嘢，唔可以照寫（否則清空成個 Scout System）
        print(f"❌ {SOURCE}：store 回傳 0 個已上架 APP，拒絕寫入（保留現有 catalog）",
              file=sys.stderr)
        return 1

    # ── catalog 鏡像（全份 visible，已上架）＋ 上架日判定 ──
    # 2026-11-07 用戶規則：上架日＝首次「公開」（第一次見到 visible=true），
    # 唔係 store 入庫日 created_at，亦唔係圖書館第一次見到個 URL 嘅日子。
    #   * 之前從未公開、今日公開（created_at 舊都好）→ 今日上架；
    #   * 之前公開過 → 保留首次公開日；
    #   * store 有紀錄但未公開 → 未上架（唔入 catalog）；
    #   * 冇任何 baseline（首次同步／全失）→ 用 created_at / BASELINE_DATE，
    #     唔會全版變今日（2026-10-21、2026-11-06 兩次事故）。
    catalog = []
    today_items = []          # 今日公開／重新上架：date == today
    publication_events: dict[str, str] = {}   # norm url → 今次判定，用嚟寫 first_public
    for a in visible_apps:
        url = (a.get("url") or "").strip()
        norm_u = _norm_url(url)
        created = (a.get("created_at") or "")[:10]
        created_dt = _parse_date(created)
        published_before_today = bool(created_dt) and created_dt < today_dt

        hist_date = (
            prev_dates.get(norm_u)
            or first_public.get(norm_u)
            or known_dates.get(url)
            or known_norm_dates.get(norm_u)
            or (enrich_norm_map.get(norm_u) or {}).get("captured_date")
            or ""
        )
        override = FIRST_PUBLIC_OVERRIDES.get(norm_u) or FIRST_PUBLIC_OVERRIDES.get(url)
        was_delisted = norm_u in delisted or url in delisted
        # 一次性修正只針對「現存日期仍然係舊規則抄落嘅 created_at」嘅紀錄；
        # 改完（first_public／known_dates 已係正確日期）唔會再觸發。
        wrong_date = bool(
            override and created and hist_date == created and created < override
        )
        evidence = False          # 有正面證據先准喺防呆時保留「今日」

        if was_delisted:
            # 下架 → 重新上架：今日公開（優先過一次性修正，唔會俾舊日期蓋返）
            listing_date = today
            evidence = True
            publication_events[norm_u] = "relisted"
        elif wrong_date:
            listing_date = override
            evidence = True
            publication_events[norm_u] = "repaired"
        elif hist_date:
            # 一路喺架上（之前公開過）：保留原本嘅首次公開日
            listing_date = hist_date
            publication_events[norm_u] = "kept"
        elif not has_baseline:
            # 首次同步／baseline 全失：冇任何「之前公開」紀錄，唔可以當今日
            listing_date = created or BASELINE_DATE
            publication_events[norm_u] = "baseline"
        else:
            # 從未公開過、今日首次觀察到 visible=true → 今日公開 = 今日上架。
            # created_at 舊過今日唔再壓住呢個判定（「之前入庫但今天公開」個案）。
            listing_date = today
            # 今日入庫＋今日公開係雙重正面證據；其餘交畀下面防呆把關，
            # 一次過太多「從未公開」URL 時會被降級，避免全版變今日。
            evidence = bool(created_dt and created_dt == today_dt)
            publication_events[norm_u] = "first_public"

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

    # 收埋咗但曾經公開：保留商店提供嘅最新名稱／icon／描述，
    # 日期一律用原首次公開日；永遠唔會當今天新上架。
    for a, pub in keep_hidden_apps:
        url = (a.get("url") or "").strip()
        entry = {
            "title": a.get("name") or "",
            "url": url,
            "pdf_url": url,
            "date": pub,
            "captured_date": pub,
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

    # ── 防呆：唔可以一次過把成個 catalog 洗成今日 ──
    # 兩次事故（2026-10-21、2026-11-06）都係「baseline 一閃失 → 全部 URL 當新」。
    # 而家：無正面證據（非今日入庫／非重新上架／非明確修正）而又一次過多過
    # 上限，就當 baseline 斷咗，改用入庫日／BASELINE_DATE，並喺 log 講清楚。
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
            print(f"⚠️  {SOURCE}：{defused} 個未曾公開過嘅 URL 想一次過變「今日」"
                  f"（上限 {blast_limit}）—— 當 baseline 斷咗，改用商店入庫日，"
                  f"唔會全版變今日")

    # ── 抓唔齊嘅自我保護：一次過少咁多 = store 回傳唔完整 ──
    # 與其把成個 catalog 縮水（會連 enrich、notices 一齊跌走），保留舊條目。
    visible_norms = {_norm_url((a.get("url") or "").strip()) for a in visible_apps}
    visible_norms.discard("")
    kept_hidden_norms = {_norm_url((a.get("url") or "").strip()) for a, _ in keep_hidden_apps}
    kept_hidden_norms.discard("")
    # 「喺上一次 catalog、今次連紀錄都搵唔到」先當消失；
    # visible=false 但商店話語權仲喺度嘅，已經喺上面保留，唔算縮水。
    present_norms = visible_norms | kept_hidden_norms
    prev_by_norm: dict[str, dict] = {}
    for e in data.get(SOURCE) or []:
        if isinstance(e, dict):
            key = _norm_url(e.get("url") or e.get("pdf_url"))
            if key:
                prev_by_norm.setdefault(key, e)
    absent_norms = [k for k in prev_dates if k and k not in present_norms]
    suspicious_shrink = bool(absent_norms) and len(absent_norms) > max(2, len(prev_dates) // 3)
    carried = 0
    if suspicious_shrink:
        for key in absent_norms:
            prev_entry = prev_by_norm.get(key)
            if prev_entry:
                catalog.append(dict(prev_entry))
                carried += 1
        print(f"⚠️  {SOURCE}：上一次 catalog 有 {len(prev_dates)} 項，今次 store 只見到 "
              f"{len(visible_norms)} 項已上架＋{len(kept_hidden_norms)} 項收埋 —— 當抓唔齊，保留 {carried} 項舊資料、"
              f"唔記下架、唔清 enrich、store-hidden.json 維持原狀")

    # ── 四種狀態落簿 ──────────────────────────────────────────────
    # 上架：first_public[url] = 首次公開日（以最終 catalog 為準，防呆降級後都唔會寫錯）
    for e in catalog:
        key = _norm_url(e.get("url") or e.get("pdf_url"))
        if not key:
            continue
        state = publication_events.get(key)
        date = str(e.get("captured_date") or "")
        if state in ("relisted", "repaired", "first_public"):
            first_public[key] = date
        else:
            first_public.setdefault(key, date)
    # 未上架：store 有紀錄但從未公開。呢類 app 永遠唔入 catalog、唔計今日。
    # 曾經公開但而家收埋（keep_hidden_apps）唔算未上架 —— 佢哋留喺 catalog、
    # 保留首次公開日，寫入 store-hidden.json。
    for a in hidden_apps:
        key = _norm_url(a.get("url"))
        if key and key not in visible_norms and key not in kept_hidden_norms:
            pending.setdefault(key, {
                "name": a.get("name") or "",
                "created_at": (a.get("created_at") or "")[:10],
                "first_seen_hidden": today,
                "state": "未上架",
            })
    # 今日公開咗就唔再係未上架（重新上架由 delisted 判定做今日）
    for key in visible_norms | kept_hidden_norms:
        pending.pop(key, None)

    new_known_dates: dict[str, str] = {
        e["url"]: e["captured_date"] for e in catalog if e.get("url")
    }

    # 按 store sort_order 排序（跟 App Store 展示順序）
    sort_orders = {_norm_url((a.get("url") or "").strip()): a.get("sort_order", 0) for a in apps}
    catalog.sort(key=lambda x: sort_orders.get(_norm_url(x.get("url") or x.get("pdf_url")), 0))

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

    new_notices = [i["entry"] for i in today_items]   # 只作輸出用（今日公開／重新上架）

    # ── enrich.json 同步 ──
    # 為每個 app 保證有 enrich 條目（包括收埋但曾經公開嘅，佢哋嘅記錄照舊保留）—
    # 按 store_category 分類，舊紀錄改名／換位自動更新；
    # 若欄位無變動，保留原有 enriched_at，避免每日檢查標籤時產生無謂 diff。
    for a in list(visible_apps) + [a for a, _ in keep_hidden_apps]:
        url = (a.get("url") or "").strip()
        c_item = catalog_by_norm.get(_norm_url(url))
        captured_date = c_item["captured_date"] if c_item else BASELINE_DATE
        kind = store_app_kind(a)
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

    # ── 下架記錄：只記「store 完全回唔到」嘅曾經上架 app ──
    # 2026-11-15 新規則：visible=false（APP STORE 收埋）唔再當下架——保留記錄
    # ＋原首次公開日，寫入 store-hidden.json；再放出就當冇收埋過。
    # 呢度只處理「紀錄喺 store 消失」（例如被刪、換 URL）：再出現＝今日重新上架。
    for key in list(delisted):
        if key in visible_norms:
            delisted.pop(key, None)
    if not suspicious_shrink:
        for key in absent_norms:
            delisted.setdefault(key, today)
            pending.setdefault(key, {"state": "未上架", "hidden_since": today})

    # 移除真係下架／換新 URL 嘅舊 app enrich（只移除 source=Scout System，唔誤刪通告 enrich）。
    # 收埋保留（kept_hidden_norms）入面嘅 enrich 永遠唔會喺呢度被刪。
    if not suspicious_shrink:
        kept_norms = visible_norms | kept_hidden_norms
        for url in list(enrich.keys()):
            v = enrich[url]
            if isinstance(v, dict) and v.get("source") == SOURCE and _norm_url(url) not in kept_norms:
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
    sync["first_public"] = first_public
    sync["pending"] = pending

    # ── store-hidden.json：APP STORE 收埋咗嘅曾經上架 app ──
    # 前端靠佢喺正常瀏覽／搜尋／側欄計數收埋；「⭐ 我的收藏」會標示已下架兼鎖死開啟掣。
    # store 回應疑似唔完整（suspicious_shrink）時維持原狀，
    # 唔會因一次抓唔齊就把成館 app 一齊收埋。
    if suspicious_shrink:
        hidden_list = previous_hidden
        print(f"⚠️  store-hidden.json 維持原狀（{len(hidden_list)} 項）—— "
              f"今次回應疑似唔完整，呃唔住寫全館收埋", file=sys.stderr)
    else:
        hidden_list = sorted(kept_hidden_norms)
    sync["hidden_count"] = len(hidden_list)

    # 寫檔 — 今日新上架只計 visible；hidden 清單另寫 store-hidden.json
    sync["last_sync"] = today
    sync["catalog_size"] = len(catalog)
    sync["visible_count"] = len(visible_apps)
    sync["pending_count"] = len(pending)
    sync.pop("hidden_skipped", None)

    # 更新 meta.total_notices / last_updated（跟 core.py 格式）
    cache["last_updated"] = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    if "meta" in cache:
        cache["meta"]["total_notices"] = len(notices)
    # 保證 data 內 Scout System 在 _meta 內被計入
    if "_meta" in cache:
        cache["_meta"]["total_sources"] = len(data)

    # store-hidden.json 先寫（失敗就喺未郁過 cache 之前大聲报錯）——
    # 前端缺咗佢唔會爆畫面，但 stale 嘅 catalog 配 stale hidden 會導致
    # 「收埋咗嘅 app 又見到」，所以唔明示就唔可以出。
    hidden_path = Path(args.hidden)
    hidden_path.write_text(json.dumps({"hidden": hidden_list}, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
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

    print(f"✅ {SOURCE}：catalog {len(catalog)} 項（已上架 {len(visible_apps)}，收埋保留 {len(kept_hidden_norms)}）"
          f"｜今日新上架 {len(today_items)} 個｜未上架 {len(pending)} 個"
          f"｜下架記錄 {len(delisted)} 個｜補 notices {added_notices} 條"
          f"｜store-hidden {len(hidden_list)} 項（baseline {first_sync}）")
    print("   判定：上架日＝首次公開（visible=true）；created_at 只係入庫日／baseline fallback")
    for n in new_notices:
        print(f"   + {n['title']} {n['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
