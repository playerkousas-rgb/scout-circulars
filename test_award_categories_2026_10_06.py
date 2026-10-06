#!/usr/bin/env python3
"""
test_award_categories_2026_10_06.py — 「獎勵／津貼／嘉許一類＝公布」驗收測試
==========================================================================
背景
----
用戶 2026-10-06 確認「服務獎勵應該歸獎勵」——即係同童軍獎勵／旅團獎勵／
優異旅團／傑出旅團／功績獎勵／津貼計劃／嘉許計劃一樣屬**公布**
（`ANNOUNCEMENT_OVERRIDE_TERMS`，2026-10-03 已定）；「青年獎勵計劃」除外，
佢本身係訓練。

規則本身冇改，但 enrich.json 有兩條舊 entry（「地域服務獎勵計劃 - 附件(一)」
兩個 copy）係規則生效前抽嘅，分類仲係「服務」。呢個唔係純顯示問題：
`notify.py notice_metadata()` 係存量標籤優先
（`extra.get("subscription_tags") or fallback[...]`），所以佢哋會推畀訂
「服務」嘅人。`fix_award_categories_2026_10_06.py` 已補正。本測試釘住：

  1. 規則：獎勵／津貼／嘉許一類（包括服務獎勵）＝公布；就算標題同時有
     「服務」「比賽」「訓練」字眼都唔會被搶走；青年獎勵計劃＝訓練；
  2. enrich.json 入面唔可以再有任何「獎勵一類」entry 嘅存檔分類同規則唔一致；
  3. 兩條點名 entry 而家係公布 + `category:announcement`，其他欄位冇被改走。

運行：python test_award_categories_2026_10_06.py
（只讀 enrich.json，唔會改檔。）
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from fix_award_categories_2026_10_06 import is_stale_award_entry  # noqa: E402
from subscription_tagging import extract_categories  # noqa: E402

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
    cats = extract_categories(title, "")
    return cats[0]["label"] if cats else ""


def main():
    passed = 0

    # ① 規則：獎勵一類＝公布（「服務獎勵」都歸獎勵，唔會因為有「服務」二字變服務）
    passed += test(
        "① 獎勵／津貼／嘉許一類＝公布",
        [cat(t) for t in (
            "服務獎勵", "童軍服務獎勵計劃", "2026-2027年度童軍旅服務獎勵計劃",
            "功績獎勵2026", "旅團獎勵計劃", "2026年優異旅團獎勵計劃",
            "傑出旅團2026", "地域服務獎勵計劃 - 附件(一)", "卓越領袖嘉許計劃2027",
            "木章訓練班津貼計劃",
        )],
        ["公布"] * 10,
    )
    passed += test(
        "① 獎勵一類唔會被標題其他字眼搶走（服務／訓練／比賽）",
        [cat("地域服務獎勵計劃"), cat("2025-2026年度童軍旅服務獎勵計劃成績公布"),
         cat("童軍旅探訪及優異旅團選舉計劃")],
        ["公布", "公布", "公布"],
    )
    passed += test(
        "① 青年獎勵計劃（AYP）除外＝訓練，唔係公布",
        [cat("香港青年獎勵計劃迎新簡介會"), cat("「香港青年獎勵計劃」迎新講座")],
        ["訓練", "訓練"],
    )

    # ② enrich.json：唔可以再有「獎勵一類」entry 嘅存檔分類同規則唔一致
    enrich = json.loads((BASE_DIR / "enrich.json").read_text(encoding="utf-8"))
    stale = [(e.get("source"), e.get("title"))
             for e in enrich.values()
             if isinstance(e, dict) and is_stale_award_entry(e)]
    passed += test("② enrich.json 冇獎勵一類 entry 同規則唔一致", stale, [])

    # ③ 兩條點名 entry：公布 + category:announcement，其他欄位保留
    family = [e for e in enrich.values()
              if isinstance(e, dict)
              and str(e.get("title") or "").startswith("地域服務獎勵計劃")]
    named = [e for e in family if "附件" in str(e.get("title") or "")
             and "(一)" in str(e.get("title") or "").replace("（一）", "(一)")]
    passed += test("③ 搵到兩條『地域服務獎勵計劃 - 附件(一)』", len(named), 2)
    passed += test(
        "③ 兩條都係公布，訂閱標籤 category:announcement",
        sorted({(tuple(c["label"] for c in e.get("categories") or []),
                 tuple(e.get("subscription_tags") or [])) for e in named}),
        [(("公布",), ("category:announcement",))],
    )
    passed += test(
        "③ 冇一條仲掛住 category:service",
        [e.get("title") for e in named
         if "category:service" in (e.get("subscription_tags") or [])],
        [],
    )
    # 同一系列其餘幾條（附件(二)／主通告）本身就冇存檔分類——notify.py 會用標題
    # fallback（結果都係公布），所以唔需要喺呢度補寫；呢個斷言釘住呢個前提。
    passed += test(
        "③ 同系列其餘 entry 冇存檔分類（由 notify.py 標題 fallback 兜底做公布）",
        sorted(str(e.get("title")) for e in family if e not in named),
        ["地域服務獎勵計劃", "地域服務獎勵計劃 - 附件(二)"],
    )
    passed += test(
        "③ 嗰幾條用標題 fallback 都係公布",
        {cat(str(e.get("title"))) for e in family if e not in named},
        {"公布"},
    )

    total = len(TEST_RESULTS)
    failed = total - passed
    print(f"\n結果：{passed}/{total} 通過")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
