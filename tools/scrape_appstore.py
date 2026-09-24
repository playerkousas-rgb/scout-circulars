#!/usr/bin/env python3
"""加掃 SCOUT APP STORE：將 store apps 表併入 cache.json（未來取代 scrape.yml 嘅加掃組件）。

設計（見 APPSTORE_INTEGRATION.md 階段 2）：
- 讀取：anon key 就夠（RLS 限 visible=true SELECT），唔使 service key。
- data["SCOUT APP STORE"] = 全份 visible catalog（鏡像 "Scout System" 嘅結構）。
- notices 只收「first-sync baseline 之後」先出現嘅 app（store created_at 比較），
  避免首次同步一刻將 60+ 舊 app 當新通告派發 push／story 風暴。
- url 去重：已喺任何來源（含手動加入）出現過嘅 url 唔入 notices。
- 新 notice 嘅 date／captured_date = 系統捕獲日（HKT），跟現有哲學。
- 自己（scout-circulars.vercel.app）永遠 skip。

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
SOURCE = "SCOUT APP STORE"
SELF_URLS = {"https://scout-circulars.vercel.app/"}


def hkt_today() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d")


def fetch_live(url: str, anon: str) -> list:
    req = urllib.request.Request(
        f"{url}/rest/v1/apps?select=id,name,url,description,note,icon,category,tags,visible,sort_order,created_at"
        f"&visible=eq.true&order=sort_order&limit=1000",
        headers={"apikey": anon, "Authorization": f"Bearer {anon}"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true", help="離線食 appstore.json snapshot")
    ap.add_argument("--apps-json", help="自訂 apps 陣列 JSON 檔（測試）")
    ap.add_argument("--cache", default=str(ROOT / "cache.json"))
    args = ap.parse_args()

    store = json.loads((ROOT / "appstore.json").read_text(encoding="utf-8"))
    if args.apps_json:
        apps = json.loads(Path(args.apps_json).read_text(encoding="utf-8"))
    elif args.snapshot:
        apps = store["apps"]
    else:
        apps = fetch_live(store["_meta"]["supabase_url"], store["_meta"]["anon_key"])

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

    existing_urls = {n.get("url") for n in notices} | SELF_URLS
    for lst in data.values():
        if isinstance(lst, list):
            existing_urls |= {e.get("url") for e in lst if isinstance(e, dict)}

    # ── catalog 鏡像（全份 visible）──
    catalog = []
    for a in apps:
        if not a.get("visible") or a.get("url") in SELF_URLS:
            continue
        catalog.append({
            "title": a.get("name") or "",
            "url": a.get("url"),
            "pdf_url": a.get("url"),
            "date": today,
            "captured_date": today,
            "source_site": SOURCE,
            "region": SOURCE,
            "tags": [t for t in (a.get("tags") or []) if t] + ["小工具"],
            "description": a.get("description") or a.get("note") or "",
            "icon": a.get("icon") or "",
            "store_category": a.get("category") or "",
        })
    data[SOURCE] = catalog

    # ── 新 app → notices（baseline 之後 created_at，且 url 未收錄）──
    new_notices = []
    for a in apps:
        url = a.get("url")
        if not a.get("visible") or url in existing_urls:
            continue
        created = (a.get("created_at") or "")[:10]
        if not created or created <= first_sync:
            continue  # 舊 app，唔溯及
        new_notices.append({
            "title": a.get("name") or "",
            "url": url,
            "pdf_url": url,
            "date": today,
            "captured_date": today,
            "source_site": SOURCE,
            "region": SOURCE,
            "tags": [t for t in (a.get("tags") or []) if t] + ["小工具"],
            "description": a.get("description") or a.get("note") or "",
            "icon": a.get("icon") or "",
        })
    notices.extend(new_notices)

    sync["last_sync"] = today
    sync["catalog_size"] = len(catalog)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ {SOURCE}：catalog {len(catalog)} 項｜新通告 {len(new_notices)} 張（baseline {first_sync}）")
    for n in new_notices:
        print(f"   + {n['title']} {n['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
