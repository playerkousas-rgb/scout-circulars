#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""離線測試：「小工具」分類 + Scout System 來源 + 2026-09-14 詞表擴充。

涵蓋：
  1. TOOLS_SOURCES 來源嘅通告一律分類「小工具」，並視為所有支部；
  2. notify 真實管道（無 enrich 記錄）都配對得到「小工具」訂閱；
  3. 冇訂小工具／訂錯分類嘅訂閱唔會誤中；
  4. 新增關鍵詞（練習賽／體驗賽／考驗／課程／體驗日）命中正確分類，
     行政類標題（選舉／名單／公布）依然保持未分類。

用法：python test_tools_category.py
"""

import sys
import unittest

sys.path.insert(0, ".")

import notify  # noqa: E402
from subscription_tagging import (  # noqa: E402
    extract_categories,
    extract_subscription_metadata,
    load_catalog,
)

# core.py 需要 requests/bs4；本機冇裝依賴嘅環境就跳過隔離測試。
try:
    import core  # noqa: E402
except Exception:  # pragma: no cover
    core = None


def make_item(title, source="Scout System"):
    return {
        "title": title,
        "url": f"https://example.test/{title}",
        "pdf_url": f"https://example.test/{title}",
        "source_site": source,
        "captured_date": "2026-09-15",
        "date": "2026-09-15",
    }


class ToolsSourceTests(unittest.TestCase):
    def test_tools_source_always_classified_tools(self):
        meta = extract_subscription_metadata("任何標題都算小工具", "", "", source="Scout System")
        self.assertEqual([c["id"] for c in meta["categories"]], ["tools"])
        self.assertIn("category:tools", meta["subscription_tags"])

    def test_tools_branch_comes_from_title_not_blanket(self):
        # 每個工具自帶支部標籤：支部由標題抽取，唔係一刀切全支部
        meta = extract_subscription_metadata("幼童軍計時器", "", "", source="Scout System")
        self.assertEqual(meta["branch_tags"], ["幼童軍"])
        meta2 = extract_subscription_metadata("童軍背包整理器", "", "", source="Scout System")
        self.assertEqual(meta2["branch_tags"], ["童軍"])

    def test_tools_without_branch_label_stays_unlabelled(self):
        meta = extract_subscription_metadata("背包整理器", "", "", source="Scout System")
        self.assertEqual(meta["branch_tags"], [])

    def test_branch_comes_from_owner_site_tags_not_title(self):
        # 「密碼旗號」標題冇支部字眼；支部由站方標籤（抓取時帶返嚟嘅 tags）決定
        meta = extract_subscription_metadata(
            "密碼旗號", "", "", source="Scout System",
            tag_hint="幼童軍 童軍 深資童軍 樂行童軍",
        )
        self.assertEqual([c["id"] for c in meta["categories"]], ["tools"])
        self.assertEqual(meta["branch_tags"], sorted(["幼童軍", "童軍", "深資童軍", "樂行童軍"]))

    def test_non_branch_labels_in_tags_are_ignored(self):
        meta = extract_subscription_metadata(
            "密碼旗號", "", "", source="Scout System",
            tag_hint="童軍 實用 最新",
        )
        self.assertEqual(meta["branch_tags"], ["童軍"])

    def test_pdf_audience_still_beats_tag_hint(self):
        meta = extract_subscription_metadata(
            "某訓練班", "", "幼童軍", source="Scout System",
            tag_hint="童軍",
        )
        self.assertEqual(meta["branch_tags"], ["幼童軍"])

    def test_other_sources_unaffected(self):
        cats = extract_categories("第170屆繩結訓練班", "", "總會")
        self.assertEqual([c["id"] for c in cats], ["training"])


class PushMatchingTests(unittest.TestCase):
    def setUp(self):
        # 模擬冇 enrich 記錄（Scout System 通告唔係 PDF，唔會入 enrich）
        self.meta = notify.notice_metadata(make_item("幼童軍計時器"), {})

    def test_tools_subscriber_of_matching_branch_matches(self):
        sub = {"branch_ids": ["幼童軍"], "topic_ids": ["branch:幼童軍:category:tools"]}
        self.assertTrue(notify.subscription_matches(sub, self.meta))

    def test_tools_subscriber_of_other_branch_not_matched(self):
        # 領袖訂閱者唔應該收到幼童軍嘅工具
        sub = {"branch_ids": ["領袖"], "topic_ids": ["branch:領袖:category:tools"]}
        self.assertFalse(notify.subscription_matches(sub, self.meta))

    def test_non_tools_subscriber_not_matched(self):
        sub = {"branch_ids": ["幼童軍"], "topic_ids": ["branch:幼童軍:category:activity"]}
        self.assertFalse(notify.subscription_matches(sub, self.meta))

    def test_tagged_tool_reaches_each_labelled_branch(self):
        # cache 帶住站方標籤嘅工具：每個被標籤嘅支部訂閱者都收到，冇被標籤嘅唔收
        item = make_item("密碼旗號")
        item["tags"] = ["幼童軍", "童軍"]
        meta = notify.notice_metadata(item, {})
        hit = {"branch_ids": ["童軍"], "topic_ids": ["branch:童軍:category:tools"]}
        miss = {"branch_ids": ["領袖"], "topic_ids": ["branch:領袖:category:tools"]}
        self.assertTrue(notify.subscription_matches(hit, meta))
        self.assertFalse(notify.subscription_matches(miss, meta))

    def test_all_new_still_receives_tools(self):
        self.assertTrue(notify.subscription_matches({"branch_ids": [], "topic_ids": ["all:new"]}, self.meta))

    def test_catalog_contains_tools_options(self):
        by_id = load_catalog()["_topic_by_id"]
        self.assertIn("category:tools", by_id)
        entry = by_id["branch:童軍:category:tools"]
        self.assertEqual(entry.get("match_topic"), "category:tools")
        self.assertEqual(entry.get("group"), "小工具")
        # 既有政策：家長只有活動及比賽 → 唔應該有小工具選項
        self.assertNotIn("branch:家長:category:tools", by_id)


class KeywordExpansionTests(unittest.TestCase):
    def test_new_terms_classify_real_titles(self):
        cases = [
            ("童軍野外定向練習賽2026", "competition"),
            ("2026年東九龍地域會長盾體驗賽", "competition"),
            ("港島童軍泳會-童軍游泳章考驗日", "training"),
            ("深資童軍肩章考驗營 2026", "training"),
            ("SOUL Keeper 精神健康守護者課程 (Level 1)", "training"),
            ("寰宇童軍計劃「探索」課程", "training"),
            ("幼童軍水上安全體驗日", "activity"),
        ]
        for title, want in cases:
            with self.subTest(title=title):
                got = [c["id"] for c in extract_categories(title)]
                self.assertIn(want, got, got)

    def test_administrative_titles_stay_unclassified(self):
        for title in [
            "2026年度模範童軍選舉",
            "呈交童軍旅賬目資料",
            "地域總部公布(2026年9月)",
            "2026年傑出旅團獎勵計劃-獲獎名單公布",
        ]:
            with self.subTest(title=title):
                self.assertEqual(extract_categories(title), [])


@unittest.skipUnless(core, "core.py 依賴（requests/bs4）未安裝，跳過隔離測試")
class TagSelectorIsolationTests(unittest.TestCase):
    """保證：冇設定 tag_selector 嘅來源（即其餘全部來源）行為完全唔變。"""

    def test_no_tag_selector_means_no_tag_collection(self):
        # 冇鍵、空字串、甚至冇 anchor 都一樣：直接回空，唔郁任何抓取邏輯
        self.assertEqual(core.extract_item_tag_labels(None, {}), [])
        self.assertEqual(core.extract_item_tag_labels(None, {"tag_selector": ""}), [])
        self.assertEqual(core.extract_item_tag_labels(None, {"tag_selector": "   "}), [])

    def test_normal_sources_cache_shape_unchanged(self):
        recs = [
            {
                "source_site": "總會",
                "region": "總會",
                "pdf_url": "https://scout.org.hk/x.pdf",
                "title": "某訓練班",
                "captured_date": "2026-09-15",
            }
        ]
        out = core.build_grouped_cache(recs, {"總會": {}}, "2026-09-15 18:00:00")
        entry = out["data"]["總會"][0]
        # 冇 tags 欄位 = 同舊格式一模一樣
        self.assertNotIn("tags", entry)
        self.assertEqual(
            sorted(entry.keys()),
            sorted(["title", "url", "pdf_url", "date", "captured_date", "source_site", "region"]),
        )
        self.assertNotIn("tags", out["notices"][0])

    def test_only_sources_with_tags_carry_them(self):
        recs = [
            {
                "source_site": "Scout System",
                "region": "Scout System",
                "pdf_url": "https://tools.example/t1",
                "title": "密碼旗號",
                "captured_date": "2026-09-15",
                "tags": ["幼童軍", "童軍"],
            }
        ]
        out = core.build_grouped_cache(recs, {"Scout System": {}}, "2026-09-15 18:00:00")
        self.assertEqual(out["data"]["Scout System"][0]["tags"], ["幼童軍", "童軍"])
        self.assertEqual(out["notices"][0]["tags"], ["幼童軍", "童軍"])


if __name__ == "__main__":
    unittest.main(verbosity=2)