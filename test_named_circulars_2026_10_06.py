#!/usr/bin/env python3
"""
test_named_circulars_2026_10_06.py — 2026-10-06 點名通告補正驗收測試
====================================================================
背景
----
PR #51 修好咗未來防錯規則之後，fix_named_circulars_2026_10_06.py 按官方
PDF 補正咗 13 條通告（東九龍地域 7 條＋總會 6 條）。本測試釘住呢批資料：

  1. 東九龍地域 7 條 ?wpdmdl= key 全部喺 enrich.json 有自己嘅紀錄
     （來源＝東九龍地域，唔係由總會站搬欄位）；
  2. 每條嘅分類／截止／費用／對象同官方 PDF 核實值一致；
  3. 總會 4 條點名補正（26228 售價、26239 對象、26241 分類、26242 對象）生效；
  4. 總會 26229／26232 核對值正確；
  5. 鐵律：enrich.json 冇任何 derived_from；
  6. 同一份通告兩個來源（東九龍地域＋總會）抽取結果一致——各自抽、
     結果自然一樣；唔一致即係規則又走樣。

運行：python test_named_circulars_2026_10_06.py
（只讀 enrich.json／cache.json，唔會改檔。）
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

TEST_RESULTS = []


def test(name, got, want):
    ok = got == want
    TEST_RESULTS.append(ok)
    tag = "✅" if ok else "❌"
    print(f"{tag} {name}")
    if not ok:
        print(f"   期望: {want!r}")
        print(f"   實際: {got!r}")
    return int(ok)


def main():
    passed = 0
    enrich = json.loads((BASE_DIR / "enrich.json").read_text(encoding="utf-8"))
    cache = json.loads((BASE_DIR / "cache.json").read_text(encoding="utf-8"))

    EKR = "https://hkscout-ekr.org/circulars/download/?wpdmdl="
    HQ = "https://scout.org.hk/uploads/tc/circulars"

    # ── 官方 PDF 核實值（2026-10-06，逐字對過 hkscout-ekr.org／scout.org.hk）──
    # (key, 標題, 分類, 截止, 費用, 對象)
    ekr_expected = [
        ("5653", "三級童軍標準艇訓練班", "訓練", "2026-12-11", "HK$160",
         "深資童軍、樂行童軍、童軍、領袖"),
        ("5651", "2027年童軍獎券籌募活動 - 回條", "活動", "2026-11-30", "", ""),
        ("5650", "2027年童軍獎券籌募活動", "活動", "2026-11-30", "HK$10", ""),
        ("5646", "卓越領袖嘉許計劃2027", "公布", "2027-04-15", "", "領袖"),
        ("5654", "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 一個石籃的故事",
         "活動", "2026-12-18", "全免",
         "幼童軍、深資童軍、樂行童軍、童軍、領袖、會務委員"),
        ("5655", "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
         "訓練", "2026-12-19", "", "童軍、領袖、會務委員"),
        ("5649", "東九龍地域步操、團呼及快樂傘比賽2026 - 成績公布",
         "比賽", "", "", ""),
    ]

    # ── ① 東九龍地域 7 條 key：enrich.json 有自己嘅紀錄，欄位全對 ──
    for wpdmdl, title, category, deadline, fee, audience in ekr_expected:
        url = EKR + wpdmdl
        entry = enrich.get(url)
        passed += test(
            f"東九龍 {wpdmdl}：enrich.json 有自己嘅 entry（來源＝東九龍地域）",
            (isinstance(entry, dict), entry and entry.get("source")),
            (True, "東九龍地域"),
        )
        if not isinstance(entry, dict):
            continue
        passed += test(
            f"東九龍 {wpdmdl}：分類／截止／費用／對象（官方 PDF 核實）",
            (entry.get("title"), [c.get("label") for c in entry.get("categories") or []],
             entry.get("deadline"), entry.get("fee"), entry.get("audience")),
            (title, [category], deadline, fee, audience),
        )
        passed += test(
            f"東九龍 {wpdmdl}：冇 derived_from；抽取成功（error 空）",
            ("derived_from" in entry, entry.get("error")),
            (False, ""),
        )

    # ── 特別把關：地址／按金兩個舊坑唔可以再發生 ──
    passed += test(
        "東九龍 5651：回條「致：東九龍地域總部辦事處…香港童軍中心 9 樓 923 室」"
        "係郵寄地址，唔可以抽成參加對象",
        enrich.get(EKR + "5651", {}).get("audience"),
        "",
    )
    passed += test(
        "東九龍 5655／HQ 26242：按金 $300（可退）唔可以當費用",
        (enrich.get(EKR + "5655", {}).get("fee"), enrich.get(f"{HQ}/26242/SA71.pdf", {}).get("fee")),
        ("", ""),
    )
    passed += test(
        "東九龍 5649：成績公布＝比賽（唔係公布）",
        [c.get("label") for c in enrich.get(EKR + "5649", {}).get("categories") or []],
        ["比賽"],
    )

    # ── ② 總會點名補正 ──
    e = enrich.get(f"{HQ}/26228/Adm25.pdf", {})
    passed += test(
        "總會 26228：獎券主通告＝活動／截止 2026-11-30／售價 HK$10",
        ([c.get("label") for c in e.get("categories") or []], e.get("deadline"), e.get("fee")),
        (["活動"], "2026-11-30", "HK$10"),
    )
    e = enrich.get(f"{HQ}/26239/SA69.pdf", {})
    passed += test(
        "總會 26239：訓練／截止 2026-12-11／HK$160；對象補齊童軍、深資童軍、樂行童軍及領袖",
        ([c.get("label") for c in e.get("categories") or []], e.get("deadline"), e.get("fee"),
         e.get("audience")),
        (["訓練"], "2026-12-11", "HK$160", "深資童軍、樂行童軍、童軍、領袖"),
    )
    passed += test(
        "總會 26239：對象補齊後支部訓練標籤齊（深資／樂行都收到推送）",
        {"training:深資童軍", "training:樂行童軍", "training:童軍"}.issubset(set(e.get("subscription_tags") or [])),
        True,
    )
    e = enrich.get(f"{HQ}/26241/SA70.pdf", {})
    passed += test(
        "總會 26241：石籃故事由公布改為活動；截止 2026-12-18／全免／保留 PDF 完整對象",
        ([c.get("label") for c in e.get("categories") or []], e.get("deadline"), e.get("fee"),
         e.get("audience")),
        (["活動"], "2026-12-18", "全免", "幼童軍、深資童軍、樂行童軍、童軍、領袖、會務委員"),
    )
    e = enrich.get(f"{HQ}/26242/SA71.pdf", {})
    passed += test(
        "總會 26242：訓練／截止 2026-12-19；對象補上童軍人士；按金唔當費用",
        ([c.get("label") for c in e.get("categories") or []], e.get("deadline"), e.get("fee"),
         e.get("audience")),
        (["訓練"], "2026-12-19", "", "童軍、領袖、會務委員"),
    )

    # ── ③ 總會核對項（現值正確，無須改）──
    e = enrich.get(f"{HQ}/26229/Adm25-app.pdf", {})
    passed += test(
        "總會 26229：獎券回條＝活動／截止 2026-11-30",
        ([c.get("label") for c in e.get("categories") or []], e.get("deadline")),
        (["活動"], "2026-11-30"),
    )
    e = enrich.get(f"{HQ}/26232/Adm28.pdf", {})
    passed += test(
        "總會 26232：卓越領袖嘉許計劃＝公布／截止 2027-04-15／領袖對象",
        ([c.get("label") for c in e.get("categories") or []], e.get("deadline"), e.get("audience")),
        (["公布"], "2027-04-15", "領袖"),
    )

    # ── ④ 鐵律：enrich.json 唔可以有 derived_from（2026-10-06 撤回搬字過紙後）──
    passed += test(
        "enrich.json 全檔冇 derived_from",
        [u for u, v in enrich.items() if isinstance(v, dict) and "derived_from" in v],
        [],
    )

    # ── ⑤ 同一份通告兩個來源：各自抽、結果要一致 ──
    twin_pairs = [
        ("5650", f"{HQ}/26228/Adm25.pdf"),
        ("5651", f"{HQ}/26229/Adm25-app.pdf"),
        ("5646", f"{HQ}/26232/Adm28.pdf"),
        ("5649", None),  # 總會站冇對應 copy
        ("5653", f"{HQ}/26239/SA69.pdf"),
        ("5654", f"{HQ}/26241/SA70.pdf"),
        ("5655", f"{HQ}/26242/SA71.pdf"),
    ]
    for wpdmdl, hq_url in twin_pairs:
        if hq_url is None:
            continue
        ekr_entry = enrich.get(EKR + wpdmdl) or {}
        hq_entry = enrich.get(hq_url) or {}
        passed += test(
            f"跨來源一致：東九龍 {wpdmdl} ↔ 總會 {hq_url.rsplit('/', 2)[-2]}"
            f"（各自按自己 PDF 抽，分類／截止／費用／對象應該一樣）",
            ([c.get("label") for c in ekr_entry.get("categories") or []],
             ekr_entry.get("deadline"), ekr_entry.get("fee"), ekr_entry.get("audience")),
            ([c.get("label") for c in hq_entry.get("categories") or []],
             hq_entry.get("deadline"), hq_entry.get("fee"), hq_entry.get("audience")),
        )

    # ── ⑥ cache.json：7 條通告喺東九龍地域組，URL key 同 enrich.json 對得上 ──
    ekr_cache_urls = {
        (it.get("pdf_url") or it.get("url"))
        for it in (cache.get("data", {}).get("東九龍地域") or [])
        if isinstance(it, dict)
    }
    passed += test(
        "cache.json 東九龍地域組有齊 7 條 ?wpdmdl= 通告（key 同 enrich.json 對得上）",
        all(EKR + w in ekr_cache_urls for w, *_ in ekr_expected),
        True,
    )

    total = len(TEST_RESULTS)
    failed = total - passed
    print(f"\n結果：{passed}/{total} 通過")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
