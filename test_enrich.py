#!/usr/bin/env python3
"""
test_enrich.py — enrich.py 準確性單元測試
============================================================
重點：驗證「寧願漏抽，絕不亂抽」原則。
運行：python test_enrich.py
"""

import sys
sys.path.insert(0, ".")

from enrich import extract_audience, extract_deadline, extract_fee, normalize_fee, extract_categories
from subscription_tagging import extract_subscription_metadata, load_catalog


# Keep results independently from the arithmetic used by callers.  ``False``
# adds zero to an integer, so the old harness printed a misleading all-pass
# result even after a failed assertion.
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

    # ── 分類：先睇標題，標題唔肯定先至用內文 ──
    passed += test(
        "標題：有「訓練班」直接判 training（內文空都得）",
        [c["id"] for c in extract_categories("童軍繩結訓練班(P88/2026)", "")],
        ["training"],
    )
    passed += test(
        "標題：有「社區服務」直接判 service",
        [c["id"] for c in extract_categories("社區服務隊招募", "")],
        ["service"],
    )
    passed += test(
        "標題：有「公開賽」歸獨立 competition",
        [(c["id"], c.get("subtype")) for c in extract_categories("射箭公開賽2026", "")],
        [("competition", None)],
    )
    passed += test(
        "比賽不會因大露營字眼混入活動",
        [c["id"] for c in extract_categories("童軍大露營比賽", "")],
        ["competition"],
    )
    passed += test(
        "標題：冇強證據（'訓練日'係弱證據）→ 用內文判斷",
        [c["id"] for c in extract_categories("童軍訓練日", "參加資格：童軍\n訓練班：繩結訓練班")],
        ["training"],
    )
    passed += test(
        "標題：出現排除詞『訓練行事曆』→ 唔會因為內文有訓練班而分類",
        [c["id"] for c in extract_categories("活動與訓練行事曆", "訓練班：繩結訓練班")],
        [],
    )

    # 內文判斷（標題空／弱時先使用）
    passed += test(
        "內文：標題空但有訓練班 → training",
        [c["id"] for c in extract_categories("", "參加資格：童軍\n訓練班：繩結訓練班\n費用：HK$50")],
        ["training"],
    )
    passed += test(
        "內文：標題空但有社區服務 → service",
        [c["id"] for c in extract_categories("", "活動性質：社區服務\n服務日：2026-09-20")],
        ["service"],
    )
    passed += test(
        "內文：標題空但有公開賽 → 獨立 competition",
        [(c["id"], c.get("subtype")) for c in extract_categories("", "全港公開賽\n日期：2026-09-20")],
        [("competition", None)],
    )
    passed += test(
        "內文：標題及內文都冇清楚字眼 → 空",
        [c["id"] for c in extract_categories("", "只係一般通告\n下載附件")],
        [],
    )
    passed += test(
        "內文：有「訓練行事曆」唔當訓練班",
        [c["id"] for c in extract_categories("", "活動與訓練行事曆\n一覽表")],
        [],
    )

    # ── 個人化受控 tag：核心名稱／正式變體而非後綴逐字比較 ──
    aircrew_workshop = extract_subscription_metadata("童軍初級空勤章工作坊")
    passed += test(
        "受控課程：初級空勤章工作坊命中初級空勤員章 + 訓練",
        (aircrew_workshop["branch_tags"], aircrew_workshop["subscription_tags"]),
        (["童軍"], ["category:training", "course:scout-basic-aircrew-badge"]),
    )
    aircrew_class = extract_subscription_metadata("童軍初級空勤員章訓練班")
    passed += test(
        "受控課程：初級空勤員章訓練班命中相同核心項目",
        aircrew_class["subscription_tags"],
        ["category:training", "course:scout-basic-aircrew-badge"],
    )
    passed += test(
        "服務不因泛稱活動同時命中其他活動",
        extract_subscription_metadata("童軍社區服務活動")["subscription_tags"],
        ["category:service"],
    )
    passed += test(
        "營火會只命中活動 campfire 子類",
        extract_subscription_metadata("童軍營火會")["subscription_tags"],
        ["activity:campfire"],
    )
    passed += test(
        "比賽只命中獨立比賽 tag，不混入活動",
        extract_subscription_metadata("童軍射箭公開賽")["subscription_tags"],
        ["category:competition"],
    )
    catalog = load_catalog()
    labels = {entry["id"]: entry["label"] for entry in catalog["topics"]}
    passed += test(
        "受控選單只顯示基礎項目名稱",
        (labels["course:leader-map-reading"], labels["course:scout-basic-aircrew-badge"]),
        ("地圖閱讀", "初級空勤章"),
    )
    passed += test(
        "受控課程選項沒有訓練班／工作坊／課程後綴",
        all(not str(entry["label"]).endswith(("訓練班", "工作坊", "課程", "訓練"))
            for entry in catalog["topics"] if entry.get("kind") == "course"),
        True,
    )
    passed += test(
        "地圖閱讀訓練班與工作坊自動命中同一基礎項目",
        (
            extract_subscription_metadata("領袖地圖閱讀訓練班")["subscription_tags"],
            extract_subscription_metadata("領袖地圖閱讀工作坊")["subscription_tags"],
        ),
        (
            ["category:training", "course:leader-map-reading"],
            ["category:training", "course:leader-map-reading"],
        ),
    )
    passed += test(
        "訓練行事曆不產生任何訂閱 tag",
        extract_subscription_metadata("童軍訓練班一覽表")["subscription_tags"],
        [],
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

    total = len(TEST_RESULTS)
    failed = total - passed
    print(f"\n結果：{passed}/{total} 通過")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
