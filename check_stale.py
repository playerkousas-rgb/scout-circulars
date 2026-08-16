#!/usr/bin/env python3
"""靜默失敗偵測 —— 捉「唔會報錯但實際壞咗」嘅來源。

背景
----
`cache.json._meta.last_run.error_sources` 只反映「抓取拋錯」嘅來源。
但 v5.6.22 發現三個來源長期出事而從來冇入過 error_sources：

    觀塘區      抓到分類目錄連結當通告（有嘢抓到，但抓錯嘢）
    深水埗西區   type 設錯，只兜底抽到「view」等雜項
    旺角區      Drive resourcekey 遺失，長期漏 2 個 PDF

所以 error_sources 為空 ≠ 全部健康。本工具用兩條獨立準則補位。

準則一：N 日冇新通告（預設 90 日）
--------------------------------
為何唔用「資產數少過 5 筆」（初版諗過，已推翻）：

  * 93% 來源（43/46）都有 5 筆以上，中位數 54 筆 —— 只覆蓋到最尾 7%。
    總會（838 筆）、筲箕灣區（504 筆）今日壞咗都唔會被 flag。
  * 站方定期清舊通告係常見做法，剩返兩三張唔代表壞。
  * 數量係「存量」，同「而家仲運作緊嗎」冇必然關係。

90 日門檻以實際數據校準：46 個來源歷來最長靜默 81 日，
出通告間隔 90 百分位為 37 日，故 90 日對現有來源零誤報。

準則二：內容型態（90 日門檻嘅盲點）
---------------------------------
如果來源持續抓到假嘢，captured_date 會一直更新，永遠唔會過期。
實測：純 90 日門檻回帶到修復前，三個壞來源全部走漏（距今只有 9–17 日）。
故另查標題係咪垃圾（view / 分類目錄 / 純編號 …）。

⚠️ 特意唔當「URL 有 #」為垃圾：將軍澳區等站通告內容直接寫喺 HTML，
用 notice.php#錨點 指向該則通告，係正常設計。第一版規則曾誤報 29 筆，
判斷重點係「標題有冇真內容」，唔係 URL 型態。

用法
----
    python check_stale.py              # 預設 90 日
    python check_stale.py --days 60    # 自訂門檻
    python check_stale.py --json       # 接 CI（有問題 exit 1）
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 標題係下列字樣＝抓錯嘢（唔係真通告名）
JUNK_TITLES = {
    "view", "preview", "edit", "open", "download", "下載", "檢視", "開啟",
    "預覽", "瀏覽", "通告", "表格", "詳情", "查看", "more", "read more",
}

# 「支部通告-童軍(1)」呢類係 Phoca Download 嘅分類目錄，唔係通告
CATEGORY_LISTING_RE = re.compile(r"^\d+\s*支部通告[-－]|^支部通告[-－].*\(\d+\)$|^區會\(\d+\)$")

# 純編號（PT996 之類）本身可以係合法標題，所以唔當垃圾；
# 但「淨係一個數字」就肯定唔係通告名
BARE_NUMBER_RE = re.compile(r"^\d{1,4}$")


def _parse_date(value: Optional[str]) -> Optional[datetime.date]:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _latest_date(items: List[Dict[str, Any]]) -> Optional[datetime.date]:
    dates = []
    for it in items:
        for key in ("captured_date", "date"):
            d = _parse_date(it.get(key))
            if d:
                dates.append(d)
                break
    return max(dates) if dates else None


def is_junk_title(title: Optional[str]) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower()
    if low in JUNK_TITLES:
        return True
    if CATEGORY_LISTING_RE.match(t):
        return True
    if BARE_NUMBER_RE.match(t):
        return True
    return False


def _bucket(days: Optional[int]) -> str:
    """新鮮度分欄：六欄互斥且窮盡。"""
    if days is None:
        return "超過 3 個月"
    if days <= 0:
        return "今天"
    if days <= 7:
        return "7 天內"
    if days <= 14:
        return "14 天內"
    if days <= 30:
        return "1 個月內"
    if days <= 90:
        return "3 個月內"
    return "超過 3 個月"


BUCKET_ORDER = ["今天", "7 天內", "14 天內", "1 個月內", "3 個月內", "超過 3 個月"]


def analyse(cache: Dict[str, Any], days: int, today: datetime.date) -> Dict[str, Any]:
    """回傳 stale / suspicious / empty / freshness 分佈。

    cache 結構：{"data": {來源: [通告…]}, "_meta": {...}}
    """
    meta = cache.get("_meta") or {}
    expected_empty = set(meta.get("expected_empty_sources") or [])
    error_sources = set((meta.get("last_run") or {}).get("error_sources") or [])

    stale: List[Dict[str, Any]] = []
    suspicious: List[Dict[str, Any]] = []
    empty: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    freshness = {b: 0 for b in BUCKET_ORDER}

    for source, items in (cache.get("data") or {}).items():
        if source in expected_empty:
            continue
        if not isinstance(items, list):
            continue

        if not items:
            empty.append({"source": source, "reason": "冇任何資產"})
            continue

        latest = _latest_date(items)
        age = (today - latest).days if latest else None

        row = {
            "source": source,
            "count": len(items),
            "latest": latest.isoformat() if latest else None,
            "age_days": age,
            "bucket": _bucket(age),
            "in_error_sources": source in error_sources,
        }

        # 準則二：內容型態
        junk = [it for it in items if is_junk_title(it.get("title"))]
        if junk:
            ratio = len(junk) / len(items)
            # 一兩筆雜項可能係正常噪音；過半就肯定係抓錯
            if ratio >= 0.5 or len(items) <= 3:
                row["junk_count"] = len(junk)
                row["junk_ratio"] = round(ratio, 3)
                row["junk_samples"] = [it.get("title") for it in junk[:3]]
                suspicious.append(row)

        # 準則一：N 日冇新通告
        if age is None or age > days:
            row["reason"] = f"{age} 日冇新通告" if age is not None else "冇有效日期"
            stale.append(row)

        freshness[row["bucket"]] += 1
        rows.append(row)

    rows.sort(key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0)))

    return {
        "today": today.isoformat(),
        "threshold_days": days,
        "total_sources": len(rows),
        "freshness": freshness,
        "stale": stale,
        "suspicious": suspicious,
        "empty": empty,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="靜默失敗偵測")
    ap.add_argument("--cache", default="cache.json")
    ap.add_argument("--days", type=int, default=90,
                    help="幾多日冇新通告就當靜默（預設 90，已用歷史資料校準）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（接 CI）")
    args = ap.parse_args()

    path = Path(args.cache)
    if not path.exists():
        print(f"❌ 搵唔到 {path}", file=sys.stderr)
        return 2

    cache = json.loads(path.read_text(encoding="utf-8"))
    report = analyse(cache, args.days, datetime.date.today())

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"檢查日期 {report['today']}｜門檻 {report['threshold_days']} 日"
              f"｜來源 {report['total_sources']} 個（已排除 expected_empty）")
        print("\n── 新鮮度分佈 ──")
        for b in BUCKET_ORDER:
            n = report["freshness"][b]
            bar = "█" * n
            print(f"  {b:<10} {n:>3}  {bar}")

        if report["suspicious"]:
            print(f"\n🔴 疑似抓錯內容（{len(report['suspicious'])}）")
            for r in report["suspicious"]:
                print(f"  {r['source']}：{r['junk_count']}/{r['count']} 筆垃圾標題"
                      f"（{r['junk_ratio']:.0%}）→ {r['junk_samples']}")

        if report["stale"]:
            print(f"\n🟠 長期未更新（{len(report['stale'])}）")
            for r in report["stale"]:
                print(f"  {r['source']}：{r['reason']}（最新 {r['latest']}，{r['count']} 筆）")

        if report["empty"]:
            print(f"\n⚪ 完全冇資料（{len(report['empty'])}）")
            for r in report["empty"]:
                print(f"  {r['source']}：{r['reason']}")

        if not (report["suspicious"] or report["stale"] or report["empty"]):
            print("\n🎉 全部來源健康")

    has_problem = bool(report["suspicious"] or report["stale"] or report["empty"])
    return 1 if has_problem else 0


if __name__ == "__main__":
    sys.exit(main())
