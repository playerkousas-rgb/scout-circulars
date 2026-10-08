#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回歸測試：2026-10-08 用戶點名通告嘅分類標籤、標題清理同課程標籤雜訊。

涵蓋：
1. 三張點名標錯標籤嘅通告喺 enrich.json 已歸「活動」（activity:other）：
   - 總會      26238/SP16-.pdf  東九50樂悠遊之與你「童」行(步行籌款活動)
   - 東九龍地域 wpdmdl=5659     東九50樂悠遊之與你「童」行(步行籌款活動)
   - 總會      26338/P102-26.pdf 探尋宗教足跡-參訪寶蓮禪寺(P102/2026)
2. 旺角區「深資及樂行童軍支部比賽2026 - 通告07.10」及大埔北區「… - 連結」
   喺 cache.json（data + notices）同 enrich.json 已清走尾綴，並由 core.clean_title 守住。
3. 總會 26342（戶外壁畫設計比賽）及 26343（嘉年華）唔再帶有誤抽嘅
   `course:leader-adventure-instructor`（歷奇活動教練員）課程標籤。
4. `fix_circulars_2026_10_08.py --dry-run` 確認存量數據零待改項。

用法：python3 test_circulars_2026_10_08.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

import fix_circulars_2026_10_08 as fix_mod  # noqa: E402
import story_queue as sq  # noqa: E402
from subscription_tagging import (  # noqa: E402
    extract_categories,
    extract_subscription_metadata,
)

try:
    import core  # noqa: E402
except Exception:  # pragma: no cover
    core = None

CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

HQ = "https://scout.org.hk/uploads/tc/circulars"
EKR = "https://hkscout-ekr.org/circulars/download/?wpdmdl="


class Circulars20261008RuleTests(unittest.TestCase):
    """分類器、標題清理同課程標籤規則測試。"""

    def test_fundraising_walk_and_temple_visit_are_activity(self):
        for title in (
            "東九50樂悠遊之與你「童」行(步行籌款活動)",
            "探尋宗教足跡-參訪寶蓮禪寺(P102/2026)",
        ):
            with self.subTest(title=title):
                cats = extract_categories(title, "")
                self.assertEqual([(c["id"], c["label"], c.get("subtype")) for c in cats],
                                 [("activity", "活動", "other")])
                meta = extract_subscription_metadata(title, "", "")
                self.assertIn("activity:other", meta["subscription_tags"])
                self.assertNotIn("category:service", meta["subscription_tags"])
                self.assertNotIn("category:announcement", meta["subscription_tags"])
                self.assertEqual(sq.classify_category({"title": title}, None), "activity")

    def test_clean_title_strips_filename_date_and_link_suffix(self):
        if core is None:
            self.skipTest("core.py 依賴未安裝")
        self.assertEqual(
            core.clean_title("深資及樂行童軍支部比賽2026 - 通告07.10.pdf", {}),
            "深資及樂行童軍支部比賽2026",
        )
        self.assertEqual(
            core.clean_title("深資及樂行童軍支部比賽2026 - 通告(07/10).pdf", {}),
            "深資及樂行童軍支部比賽2026",
        )
        self.assertEqual(
            core.clean_title("香港童軍115周年 – 幼童軍度假營2026 大埔北區資助計劃 - 連結", {}),
            "香港童軍115周年 – 幼童軍度假營2026 大埔北區資助計劃",
        )
        self.assertEqual(
            core.clean_title("幼童軍金紫荊考驗日 - >>連結<<", {}),
            "幼童軍金紫荊考驗日",
        )
        self.assertEqual(
            core.clean_title("幼童軍讀圖章訓練班 - 通告連結", {}),
            "幼童軍讀圖章訓練班",
        )
        self.assertEqual(
            core.clean_title("2026-27 年度區會長盾童軍技能錦標賽 - https://tpnscout.org/wp-content/uploads/2026/06/test.pdf", {}),
            "2026-27 年度區會長盾童軍技能錦標賽",
        )
        for generic in ("連結", ">>連結<<", "通告連結", "通告下載", "點擊下載", "https://tpnscout.org/a.pdf"):
            self.assertTrue(core.is_generic_download_title(generic), generic)


class Circulars20261008DataTests(unittest.TestCase):
    """鎖定 cache.json 同 enrich.json 入面點名通告嘅實際狀態。"""

    @classmethod
    def setUpClass(cls):
        cls.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        cls.enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))

    def test_three_named_circulars_are_activity_in_enrich(self):
        for url in fix_mod.CATEGORY_URLS:
            with self.subTest(url=url):
                entry = self.enrich[url]
                self.assertEqual([c["label"] for c in entry["categories"]], ["活動"])
                self.assertIn("activity:other", entry["subscription_tags"])
                self.assertNotIn("category:service", entry["subscription_tags"])
                self.assertNotIn("category:announcement", entry["subscription_tags"])

    def test_titles_are_cleaned_in_cache_and_enrich(self):
        for url, (clean_title, listing_title) in fix_mod.TITLE_FIXES.items():
            with self.subTest(url=url):
                items = fix_mod.find_cache_items(self.cache, url)
                self.assertGreaterEqual(len(items), 1)
                for item in items:
                    self.assertEqual(item["title"], clean_title)
                entry = self.enrich[url]
                self.assertEqual(entry["title"], clean_title)
                self.assertEqual(entry.get("title_check"), "corrected")
                self.assertEqual(entry.get("listing_title"), listing_title)

    def test_noise_course_tags_removed(self):
        for url, topic_id in fix_mod.NOISE_COURSES.items():
            with self.subTest(url=url):
                entry = self.enrich[url]
                self.assertNotIn(topic_id, entry.get("subscription_tags") or [])
                detail_ids = [d.get("id") for d in (entry.get("subscription_tag_details") or [])]
                self.assertNotIn(topic_id, detail_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
