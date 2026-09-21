#!/usr/bin/env python3
"""由總會官網捉齊 49 個童軍組織徽號落 icons/orgs/src/。

用途：sandbox / 整合環境出唔到 scout.org.hk，但 GitHub Actions 同你部機
（香港網絡）都得。stdlib only，idempotent：已存在嘅檔會 skip，重跑安全。

之後行 tools/build_org_avif.mjs（node + sharp）正規化成 AVIF。
一鍵全自動版見 .github/workflows/org-icons.yml（Actions 手動撳掣行）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORGS_JSON = ROOT / "icons" / "orgs" / "official_urls.json"
SRC_DIR = ROOT / "icons" / "orgs" / "src"

UA = "scout-circulars-icon-fetcher/1.0 (+https://scout-circulars.vercel.app)"


def main() -> int:
    spec = json.loads(ORGS_JSON.read_text(encoding="utf-8"))
    base = spec["_meta"]["badge_base"]
    SRC_DIR.mkdir(parents=True, exist_ok=True)

    ok = skip = fail = 0
    for org in spec["orgs"]:
        rel = org.get("badge_url")
        if not rel:
            print(f"— {org['name']}：官網冇單獨檔，跳過（用已 harvest 嘅版本或 fallback）")
            skip += 1
            continue
        existing = list(SRC_DIR.glob(f"{org['slug']}-*"))
        if existing:
            print(f"= {org['name']}：已有 {existing[0].name}，跳過")
            skip += 1
            continue
        ext = rel.rsplit(".", 1)[-1].lower() or "img"
        dest = SRC_DIR / f"{org['slug']}-{org['name']}.{ext}"
        try:
            req = urllib.request.Request(base + rel, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as res:
                data = res.read()
            if len(data) < 800:  # 細過 800B 多數係 error page / 1px 圖
                raise ValueError(f"回應得 {len(data)} bytes，似係無效圖")
            dest.write_bytes(data)
            ok += 1
            print(f"✅ {org['name']}：{rel} → {dest.name}（{len(data)//1024}KB）")
            time.sleep(0.4)  # 有禮貌啲，唔好轟官網
        except Exception as exc:  # noqa: BLE001 — 單個失敗唔阻其他
            fail += 1
            print(f"❌ {org['name']}：{rel} — {exc}", file=sys.stderr)

    print(f"\n搞掂：{ok} 新增 / {skip} 已有 / {fail} 失敗")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
