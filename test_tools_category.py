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

    def test_tools_source_covers_all_branches(self):
        meta = extract_subscription_metadata("工具", "", "", source="Scout System")
        branches = set(meta["branch_tags"])
        self.assertTrue({"童軍", "幼童軍", "領袖"} <= branches, branches)

    def test_other_sources_unaffected(self):
        cats = extract_categories("第170屆繩結訓練班", "", "總會")
        self.assertEqual([c["id"] for c in cats], ["training"])


class PushMatchingTests(unittest.TestCase):
    def setUp(self):
        # 模擬冇 enrich 記錄（Scout System 通告唔係 PDF，唔會入 enrich）
        self.meta = notify.notice_metadata(make_item("童軍背包整理器 v2.0"), {})

    def test_tools_subscriber_matches(self):
        sub = {"branch_ids": ["童軍"], "topic_ids": ["branch:童軍:category:tools"]}
        self.assertTrue(notify.subscription_matches(sub, self.meta))

    def test_non_tools_subscriber_not_matched(self):
        sub = {"branch_ids": ["童軍"], "topic_ids": ["branch:童軍:category:activity"]}
        self.assertFalse(notify.subscription_matches(sub, self.meta))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
