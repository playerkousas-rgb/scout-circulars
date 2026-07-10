#!/usr/bin/env python3
"""
test_enrich.py — enrich.py 準確性單元測試
============================================================
重點：驗證「寧願漏抽，絕不亂抽」原則。
運行：python test_enrich.py
"""

import sys
sys.path.insert(0, ".")

from enrich import extract_audience, extract_deadline, extract_fee, normalize_fee


def test(name, got, want):
    ok = got == want
    tag = "✅" if ok else "❌"
    print(f"{tag} {name}")
    if not ok:
        print(f"   期望: {want!r}")
        print(f"   實際: {got!r}")
    return ok


def main():
    passed = 0
    failed = 0

    # ── 對象：必須有明確 label，否則寧願空 ──
    passed += test(
        "對象：無 label 時不亂抽",
        extract_audience("本活動不適合深資童軍及樂行童軍參加。"),
        "",
    )
    passed += test(
        "對象：有 label 時正確抽取",
        extract_audience("參加資格：深資童軍及樂行童軍\n費用：HK$50"),
        "深資童軍、樂行童軍",
    )
    passed += test(
        "對象：由窄到闊，避免童軍吃掉幼童軍",
        extract_audience("參加對象：幼童軍、童軍"),
        "幼童軍、童軍",
    )

    # ── 截止日期：必須有『截止』，否則寧願空 ──
    passed += test(
        "截止：無截止字樣時不抽",
        extract_deadline("報名日期：2026-08-01\n活動日期：2026-08-15"),
        "",
    )
    passed += test(
        "截止：有截止日期 label",
        extract_deadline("截止日期：2026年8月1日"),
        "2026-08-01",
    )
    passed += test(
        "截止：有截止報名日期 label",
        extract_deadline("截止報名日期：2026/8/1"),
        "2026-08-01",
    )

    # ── 費用：全免要明確，雙金額不亂判資助 ──
    passed += test(
        "費用：全免",
        extract_fee("費用：全免"),
        "全免",
    )
    passed += test(
        "費用：免費",
        extract_fee("費用：免費"),
        "全免",
    )
    passed += test(
        "費用：兩個金額但無資助提示，顯示兩個",
        extract_fee("費用：領袖 HK$200 / 童軍 HK$100"),
        "HK$200 / HK$100",
    )
    passed += test(
        "費用：兩個金額且有資助提示，取細價",
        extract_fee("費用：原價 HK$200，半費資助後 HK$100"),
        "HK$100",
    )
    passed += test(
        "費用：豁免唔等於全免，寧願空",
        extract_fee("費用：可向主辦單位申請豁免"),
        "",
    )

    # ── 格式正規化 ──
    passed += test(
        "normalize_fee：港幣$10 → HK$10",
        normalize_fee("港幣$10"),
        "HK$10",
    )
    passed += test(
        "normalize_fee：10元正 → HK$10",
        normalize_fee("10元正"),
        "HK$10",
    )
    passed += test(
        "normalize_fee：USD$50 → US$50",
        normalize_fee("USD$50"),
        "US$50",
    )

    total = passed + failed
    print(f"\n結果：{passed}/{total} 通過")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
