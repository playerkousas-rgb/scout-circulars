#!/usr/bin/env python3
"""回歸測試：URL 尾段唔應該當成標題（港島南區 "view" bug）。

背景：Google Drive 連結格式係 https://drive.google.com/file/d/<id>/view，
舊版 fallback_title_from_url() 攞最尾一段做標題，於是港島南區 24 筆通告
標題全部變成 "view"。

執行：python test_url_title_fallback.py
"""
import sys

import core

FAILED = []


def check(desc, actual, expected):
    ok = actual == expected
    print(f"{'✅' if ok else '❌'} {desc}")
    if not ok:
        print(f"     預期 {expected!r}，實際 {actual!r}")
        FAILED.append(desc)


def check_true(desc, cond):
    print(f"{'✅' if cond else '❌'} {desc}")
    if not cond:
        FAILED.append(desc)


print("── 1. 檔案託管服務嘅操作動詞唔可以做標題 ──")
for url in [
    "https://drive.google.com/file/d/17GcPkdqtbnXWAYYSiHsPvLNSj8LE-yoU/view",
    "https://drive.google.com/file/d/1Um6PXr5OXZa5bg4zJIPQIrVJDs-mTdh6/view?usp=sharing",
    "https://drive.google.com/file/d/1sSxOk1ppyDzG-cO5ohYq7r6KuRDcuCVl/preview",
    "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/edit",
]:
    check(f"{url[:58]}… → None", core.fallback_title_from_url(url, {}), None)

print("\n── 2. 就算 anchor 文字係 view/檢視 都唔可以做標題 ──")
for bad in ["view", "View", "VIEW", "preview", "檢視", "開啟", "預覽", "瀏覽"]:
    check(f"clean_title({bad!r}) → None", core.clean_title(bad, {}), None)

print("\n── 3. 真檔名要保留，唔可以誤殺 ──")
cases = [
    ("https://x.org/files/周年大會通告.pdf", "周年大會通告"),
    ("https://x.org/docs/2026-07-18_annual-meeting.pdf", "2026 07 18 annual meeting"),
    ("https://x.org/uploads/scout-notice-2026.docx", "scout notice 2026"),
    ("https://x.org/a/TPN-CIR-S-2526-006.pdf", "TPN CIR S 2526 006"),
    ("https://x.org/files/notice.pdf", "notice"),
]
for url, expected in cases:
    check(f"{url.rsplit('/', 1)[-1]} → {expected!r}",
          core.fallback_title_from_url(url, {}), expected)

print("\n── 4. 隨機 ID 判斷 ──")
for seg, expected in [
    ("1Um6PXr5OXZa5bg4zJIPQIrVJDs-mTdh6", True),   # Drive file id
    ("17GcPkdqtbnXWAYYSiHsPvLNSj8LE-yoU", True),   # Drive file id（含 -）
    ("1FAIpQLSfU4pCvaRnjantiTV2Pm43L0wMSHncEK3E4YGOOGuRQIzP3NA", True),  # Forms id
    ("周年大會通告", False),                         # 中文標題
    ("annual-meeting-2026.pdf", False),            # 有副檔名
    ("notice", False),                             # 短
    ("scout-notice-2026", False),                  # 有意義嘅字詞
]:
    check(f"looks_like_opaque_id({seg[:34]!r}) → {expected}",
          core.looks_like_opaque_id(seg), expected)

print("\n── 5. 端對端：make_asset_record 行為 ──")
drive = "https://drive.google.com/file/d/17GcPkdqtbnXWAYYSiHsPvLNSj8LE-yoU/view"
check("Drive 連結 + 冇 anchor 文字 → 丟棄（好過砌個 'view' 出嚟）",
      core.make_asset_record(drive, "", {}), None)
check("Drive 連結 + anchor 文字係 'view' → 丟棄",
      core.make_asset_record(drive, "view", {}), None)
rec = core.make_asset_record(drive, "通告下載", {})
check_true("Drive 連結 + 有真標題 → 保留", rec is not None and rec["title"] == "通告下載")
rec2 = core.make_asset_record("https://x.org/files/周年大會通告.pdf", "", {})
check_true("普通 PDF + 冇 anchor 文字 → 由檔名救回標題",
           rec2 is not None and rec2["title"] == "周年大會通告")

print("\n── 6. cache.json 現況：港島南區唔應該再有 'view' ──")
try:
    import json
    from pathlib import Path
    p = Path(__file__).with_name("cache.json")
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8")).get("data", {})
        arr = data.get("港島南區", [])
        bad = [x for x in arr if x.get("title", "").strip().lower() in {"view", "preview"}]
        check_true(f"港島南區 {len(arr)} 筆之中，冇一筆標題係 view（實際 {len(bad)} 筆）", not bad)
        # 順帶檢查全庫
        allbad = [(s, x.get("title")) for s, a in data.items() if isinstance(a, list) for x in a
                  if x.get("title", "").strip().lower() in {"view", "preview", "edit", "open"}]
        check_true(f"全庫都冇 view/preview/edit/open 標題（實際 {len(allbad)} 筆）", not allbad)
    else:
        print("⏭  搵唔到 cache.json，略過")
except Exception as exc:  # pragma: no cover
    print(f"⏭  略過 cache 檢查：{exc}")

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗")
    sys.exit(1)
print("🎉 全部通過")
