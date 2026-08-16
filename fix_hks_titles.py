#!/usr/bin/env python3
"""一次性修復：港島南區 24 筆標題為 "view" 的通告。

背景
----
Google Sites 首頁嘅 Drive 連結，如果 anchor 完全冇文字，core.py 舊版
fallback_title_from_url() 會攞 URL 最尾一段做標題。Google Drive 連結格式係
    https://drive.google.com/file/d/<id>/view
最尾一段就係 "view"，於是 24 筆通告嘅標題全部變咗 "view"。

呢個 bug 已經喺 core.py 修好（見 URL_TAIL_NOT_A_FILENAME / looks_like_opaque_id），
但已經寫入 cache.json 嘅 24 筆污染資料要另外清。

標題來源
--------
逐份開 PDF 攞內文標題。注意：**唔可以用 PDF metadata title**，因為好多份
都錯寫成「港島南區幼童軍支部比賽2023」（明顯係用舊檔另存為時冇改 metadata），
亦有亂碼（"v\ufffd\ufffdW\ufffd.pdf"）。內文第一個標題行先係真正標題。

用法
----
    python fix_hks_titles.py --dry-run   # 只睇會改咩
    python fix_hks_titles.py             # 實際寫入 cache.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Drive file id → 由 PDF 內文人手核實嘅真標題
# （每條都逐份開過 PDF 對過內文，唔係靠 metadata）
TITLE_BY_FILE_ID = {
    "1Um6PXr5OXZa5bg4zJIPQIrVJDs-mTdh6": "港島南區 40 周年活動 の「童」賀聖誕營火會",
    "1HeblqJTx0OAEmYHPxWPBYTdi9g7WeJAm": "南區童軍 40 周年－「童」心「童」慶‧創未來",
    "1vL7XyLUsOhyb5fyV-Wz7qUyZwEag8XyG": "「積極公民」獎章系列－防騙先鋒章 防騙工作坊",
    "1BdF8rK-Ffjjyz8sj0E2Pg1t_yG7Avboo": "結伴「童」「航」嘉年華",
    "176KN9c9S6QHDbTuovjijfhndYaqR04eQ": "港島南區深資童軍／樂行童軍支部（陶藝）體驗班",
    "1-iZMvyGkhFYTaHZkx2d-MZC7J0PMOXC_": "單車遠足分享會 暨 童「樂」日本、四國「深」度遊單車之旅籌組會議",
    "1t4RoRBXO-nYVfUy_9HRD_k5SEeSPKziC": "港島南區深資童軍／樂行童軍支部比賽 2025",
    "1LpIHOEy_WOOjWa8tMQKrVp98Cq8fIpeG": "港島南區深資童軍／樂行童軍支部（咖啡調製及拉花）體驗班",
    "1hNTmeHWXNcANc_jWkBsEFg-4W-CYK4Kq": "第 543 屆童軍領導才訓練班",
    "1H7ixz1T8M8-HcuhJ_qHYgS2AOT-Zvr7S": "原野烹飪章訓練班",
    "1PIHZNKB9tfCW1MAN8EMATBpmzo_BSJMx": "港島南區童軍支部比賽 2025",
    "1VLzplzLf3DANUX3GKHeNqWm99sCzEr3P": "童軍領導才訓練班",
    "1OZaDHCVaPPrXM7ObGio8D76MMDKpdWN2": "幼童軍金紫荊獎章考驗營 2024（一）",
    "1PGejVpFX6NIVwzhEBZzBQKScx9sGYk-D": "幼童軍金紫荊獎章考驗營 2024（二）",
    "1e0eU8_l6uE43N1R8OGOxEnxigemlSPhV": "港島南區幼童軍支部比賽 2025",
    "1WyzSBa_f8EJU_RuSAKtAOGuQBZx4A7o2": "幼童軍金紫荊獎章考驗營 2025",
    "1skryWAFlKatxfiNUyhkq_2LoIbmylAzk": "幼童軍繩結章訓練班",
    "1yBT3oyL3s7e8Q7utgOfBfOz43Ab08r60": "幼童軍氣槍射擊體驗日",
    "1N9s7cSDgSaJVLbYiu1bZTeVtnsmc_pZS": "六色積木親子體驗日",
    "1dQeqgjeROm3OwxMqkK4UCVYesa8VFoHd": "親子動植物公園遊蹤日",
    "17GcPkdqtbnXWAYYSiHsPvLNSj8LE-yoU": "小童軍禪畫親子體驗日",
    "1sgvnCRoCid_TYkS2oyE-kNY5d0GFAQCk": "桌上遊戲親子體驗日",
    "15SRzXLMi0QjeuniMW00RUfBo_A5ys8eC": "小童軍聖誕老人村派對",
    "1sSxOk1ppyDzG-cO5ohYq7r6KuRDcuCVl": "小童軍親子動動樂",
}

SOURCE = "港島南區"
BAD_TITLE = "view"


def file_id_from_url(url: str) -> str | None:
    """由 Drive URL 抽出 file id。"""
    marker = "/file/d/"
    if marker not in url:
        return None
    return url.split(marker, 1)[1].split("/", 1)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="cache.json")
    ap.add_argument("--dry-run", action="store_true", help="只列出改動，唔寫入")
    args = ap.parse_args()

    cache_path = Path(args.cache)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    arr = cache.get("data", {}).get(SOURCE)
    if not arr:
        print(f"❌ cache 入面搵唔到來源「{SOURCE}」")
        return 1

    fixed, missing = [], []
    for item in arr:
        if item.get("title") != BAD_TITLE:
            continue
        fid = file_id_from_url(item.get("pdf_url", ""))
        title = TITLE_BY_FILE_ID.get(fid or "")
        if not title:
            missing.append(item.get("pdf_url", ""))
            continue
        item["title"] = title
        fixed.append((fid, title))

    print(f"來源「{SOURCE}」共 {len(arr)} 筆")
    print(f"修正 {len(fixed)} 筆標題：")
    for fid, title in fixed:
        print(f"  {fid[:12]}…  {title}")
    if missing:
        print(f"\n⚠️  仲有 {len(missing)} 筆搵唔到對應標題：")
        for u in missing:
            print("   ", u)

    if not fixed:
        print("\n冇嘢要改（可能已經修過）。")
        return 0

    if args.dry_run:
        print("\n（--dry-run，冇寫入）")
        return 0

    backup = cache_path.with_suffix(f".json.bak-{datetime.now():%Y%m%d%H%M%S}")
    shutil.copy2(cache_path, backup)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ 已寫入 {cache_path}（備份：{backup.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
