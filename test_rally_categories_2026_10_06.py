#!/usr/bin/env python3
"""
test_rally_categories_2026_10_06.py — 「大會操＝活動，失物認領除外」驗收測試
==========================================================================
背景
----
用戶 2026-10-06 點名兩條通告都被錯判做「比賽」：

    總會    2026年香港童軍大會操(四)
    荃灣區  香港童軍大會操荃灣區會旅遊巴士安排

根因：「會操」喺 subscription_tagging.COMPETITION_TERMS 入面。規則已改
（fix_rally_categories_2026_10_06.py 補正咗 enrich.json 嘅 11 條欠帳）。
本測試釘住：

  1. 規則本身：標題有「香港童軍大會操」＝活動；失物認領／失物待領＝公布；
     「有服務XX 一定是歸服務」贏過大會操＝活動（「服務獎勵」呢類表揚通告除外）；
     用戶只收全名，其他會操（九龍地域會操／聯隊週年大會操）維持原判；
  2. enrich.json 入面嘅大會操／失物認領通告全部同規則一致（冇漏改）；
  3. 大會操通告嘅訂閱標籤係 activity:other，唔可以再係 category:competition；
  4. 鐵律：呢批 entry 嘅其他欄位（截止／費用／對象／enrich_version）冇被
     補正 script 順手改走。

運行：python test_rally_categories_2026_10_06.py
（只讀 enrich.json，唔會改檔。）
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from subscription_tagging import (  # noqa: E402
    LOST_PROPERTY_TERMS, RALLY_ACTIVITY_TERMS, _term_hits, extract_categories,
)

TEST_RESULTS = []


def test(name, got, want):
    ok = got == want
    TEST_RESULTS.append(ok)
    print(f"{'✅' if ok else '❌'} {name}")
    if not ok:
        print(f"   期望: {want!r}")
        print(f"   實際: {got!r}")
    return int(ok)


def cat(title):
    """標題 → 分類標籤（同 enrich.py 用同一個規則）。"""
    cats = extract_categories(title, "")
    return cats[0]["label"] if cats else ""


def main():
    passed = 0

    # ① 規則：用戶點名嘅兩條 + 同一系列其餘幾條
    passed += test(
        "① 大會操一律＝活動（總會(一)～(四)、午宴活動、荃灣區旅遊巴士安排）",
        [cat(t) for t in (
            "2026年香港童軍大會操(四)",
            "香港童軍大會操荃灣區會旅遊巴士安排",
            "2026 年香港童軍大會操",
            "2026年香港童軍大會操(二)",
            "2026年香港童軍大會操(三)",
            "參與2026年香港童軍大會操暨午宴活動",
            "2010 年香港童軍大會操",
        )],
        ["活動"] * 7,
    )
    passed += test(
        "① 大會操 subtype＝other（訂閱標籤 activity:other）",
        [(c["id"], c.get("subtype")) for c in
         extract_categories("2026年香港童軍大會操(四)", "")],
        [("activity", "other")],
    )
    passed += test(
        "① 失物認領／失物待領＝公布（大會操規則嘅唯一例外）",
        [cat(t) for t in (
            "2026年香港童軍大會操失物認領安排",
            "2026年香港童軍大會操 - 失物待領",
            "香港童軍115周年國際賽船大會-失物待領",
            "29-11-2017 行政通告第03-2017號 智狼一班 失物待領",
        )],
        ["公布"] * 4,
    )
    passed += test(
        "① 內文有『比賽』字眼都唔可以搶走大會操嘅分類（標題為準）",
        cat("2026年香港童軍大會操(四)"),
        "活動",
    )
    passed += test(
        "① 用戶：只收全名「香港童軍大會操」→ 其他會操維持原判（唔好順手改）",
        [cat("九龍地域會操2023(預告)"), cat("聯隊週年大會操暨檢閱禮2026"),
         cat("東九龍地域步操、團呼及快樂傘比賽2026 - 成績公布")],
        ["比賽", "比賽", "比賽"],
    )
    passed += test(
        "① 「有服務XX 一定是歸服務」→ 贏過大會操＝活動",
        [cat(t) for t in (
            "2026年香港童軍大會操(五) - 服務邀請",
            "香港童軍大會操義工招募",
            "香港童軍大會操義務工作人員招募",
            "2026年香港童軍大會操社區服務日",
        )],
        ["服務"] * 4,
    )
    passed += test(
        "① 「服務獎勵」係表揚通告（2026-10-03 規則）→ 唔會因為『有服務』就變服務",
        [cat("香港童軍大會操(六) 服務獎勵頒發"), cat("童軍服務獎勵計劃")],
        ["活動", "公布"],
    )

    # ② enrich.json：大會操／失物認領通告嘅存量資料要同規則一致
    enrich = json.loads((BASE_DIR / "enrich.json").read_text(encoding="utf-8"))
    named = []
    mismatched = []
    for url, entry in enrich.items():
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "")
        if not _term_hits(title, RALLY_ACTIVITY_TERMS) and not _term_hits(title, LOST_PROPERTY_TERMS):
            continue
        named.append((url, entry))
        want = extract_categories(title, "", str(entry.get("source") or ""))
        got = entry.get("categories") or []
        if [(c.get("id"), c.get("subtype")) for c in got] != \
                [(c.get("id"), c.get("subtype")) for c in want]:
            mismatched.append((entry.get("source"), title, got, want))

    passed += test("② enrich.json 有 11 條大會操／失物認領通告", len(named), 11)
    passed += test("② 全部同現行規則一致（冇漏改）", mismatched, [])

    # ③ 訂閱標籤：大會操唔可以再掛住「所有比賽」
    rally_with_competition = [
        (e.get("source"), e.get("title"), e.get("subscription_tags"))
        for _u, e in named
        if _term_hits(str(e.get("title") or ""), RALLY_ACTIVITY_TERMS)
        and "category:competition" in (e.get("subscription_tags") or [])
    ]
    passed += test("③ 冇大會操通告仲掛住 category:competition", rally_with_competition, [])
    passed += test(
        "③ 大會操通告嘅訂閱標籤包含 activity:other",
        sorted({t for _u, e in named
                if _term_hits(str(e.get("title") or ""), RALLY_ACTIVITY_TERMS)
                for t in (e.get("subscription_tags") or [])}),
        ["activity:other"],
    )
    passed += test(
        "③ 失物認領通告嘅訂閱標籤係 category:announcement",
        sorted({t for _u, e in named
                if _term_hits(str(e.get("title") or ""), LOST_PROPERTY_TERMS)
                for t in (e.get("subscription_tags") or [])}),
        ["category:announcement"],
    )

    # ④ 用戶點名兩條：其他欄位冇被補正 script 改走
    by_url = {url: entry for url, entry in named}
    hq = by_url.get("https://scout.org.hk/uploads/tc/circulars/26332/RCR0426C.pdf") or {}
    tw = by_url.get("https://www.twdscout.org.hk/documents/notices/A202603.pdf") or {}
    passed += test(
        "④ 總會 26332 大會操(四)：分類＝活動，截止 2026-11-08，enrich_version 冇被改",
        ([c["label"] for c in hq.get("categories") or []], hq.get("deadline"),
         hq.get("enrich_version")),
        (["活動"], "2026-11-08", "3.6"),
    )
    passed += test(
        "④ 荃灣區 A202603 旅遊巴士安排：分類＝活動，對象／費用／截止保留",
        ([c["label"] for c in tw.get("categories") or []], tw.get("audience"),
         tw.get("fee"), tw.get("deadline"), tw.get("branch_tags")),
        (["活動"], "童軍、領袖", "HK$20", "2026-10-20", ["童軍", "領袖"]),
    )

    total = len(TEST_RESULTS)
    failed = total - passed
    print(f"\n結果：{passed}/{total} 通過")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
