#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""離線測試：2026-09-18「工作人員招募 → 一定係服務」規則。

背景（馬拉松事件）：
  渣打香港馬拉松2027「工作人員大招募」——站方 listing 標題寫得好清楚，
  但 PDF 標題只係「特別通告第18/26號」，內文又滿係「比賽」（馬拉松本身係
  賽事），結果被分類做「比賽」推咗出去。規則：標題（listing 標題都計）
  有工作人員／義工／籌委會招募字眼 → 只回「服務」，壓住內文嘅比賽 fallback。

涵蓋：
  1. listing 標題帶「工作人員大招募」＋內文比賽字眼 → 只有服務；
  2. 標題本身帶「工作人員招募／招募義工／工作人員報名」→ 只有服務；
  3. 參與者招募（隊員／成員＋邀請賽）唔受影響，照樣係比賽；
  4. 正常比賽通告（冇招募字眼）唔會被誤壓；
  5. 參考文件（名單）優先過招募規則；
  6. notify 真實管道（無 enrich 記錄）都配對得到「服務」、配對唔到「比賽」；
  7. enrich.extract_fields 連 listing_title 一齊分類（pipeline 整合點）。

用法：python test_staff_recruit_category.py
"""

import sys
import unittest

sys.path.insert(0, ".")

import notify  # noqa: E402
from enrich import extract_fields  # noqa: E402
from subscription_tagging import (  # noqa: E402
    CLASSIFIER_VERSION,
    extract_categories,
    extract_subscription_metadata,
)

MARATHON_LISTING_TITLE = "渣打香港馬拉松2027 - 工作人員大招募(歡迎全港童軍參與)"
GENERIC_HKS_PDF_TITLE = "特別通告第18/26號"
RACE_TEXT = "渣打香港馬拉松2027 比賽詳情 競賽路程 邀請賽起跑時間 參加比賽嘅隊伍請留意"


def cat_ids(categories):
    return [c.get("id") for c in categories]


def make_item(title, source="總會"):
    return {
        "title": title,
        "url": f"https://example.test/{title}",
        "pdf_url": f"https://example.test/{title}",
        "source_site": source,
        "captured_date": "2026-09-18",
    }


class StaffRecruitRule(unittest.TestCase):
    def test_listing_title_with_race_body_text(self):
        """馬拉松事件回歸：listing 標題有工作人員大招募，內文滿係比賽。"""
        cats = extract_categories(
            GENERIC_HKS_PDF_TITLE, RACE_TEXT, "總會",
            listing_title=MARATHON_LISTING_TITLE,
        )
        self.assertEqual(cat_ids(cats), ["service"])
        self.assertEqual(cats[0].get("evidence"), ["工作人員大招募"])

    def test_subscription_tags_service_only(self):
        meta = extract_subscription_metadata(
            GENERIC_HKS_PDF_TITLE, RACE_TEXT, "", source="總會",
            listing_title=MARATHON_LISTING_TITLE,
        )
        self.assertEqual(meta["subscription_tags"], ["category:service"])
        self.assertNotIn("category:competition", meta["subscription_tags"])

    def test_title_only_recruitment_variants(self):
        for title in (
            "「樂施毅行者2026」工作人員招募(P73/2026)",
            "嘉年華 招募工作人員",
            "活動 工作人員報名表格",
            "招募義工 – 長者探訪",
        ):
            cats = extract_categories(title, RACE_TEXT)
            self.assertEqual(cat_ids(cats), ["service"], msg=title)

    def test_participant_recruitment_stays_competition(self):
        """隊員／成員招募係參與者，唔係工作人員——照走原本詞表。"""
        cats = extract_categories(
            "香港童軍龍舟邀請賽2026 – 沙田西區龍舟隊成員招募", "")
        self.assertEqual(cat_ids(cats), ["competition"])

    def test_plain_competition_unaffected(self):
        cats = extract_categories("全港童軍海上競賽2026", RACE_TEXT)
        self.assertEqual(cat_ids(cats), ["competition"])

    def test_reference_document_wins_over_recruit(self):
        """名單係參考文件：優先過招募規則，保持未分類。"""
        cats = extract_categories("工作人員招募義工名單", "")
        self.assertEqual(cat_ids(cats), [])

    def test_text_only_mention_does_not_fire(self):
        """內文提一句招募義工唔會中招——規則只認標題。"""
        cats = extract_categories("全港童軍海上競賽2026", "比賽期間請招募義工幫手")
        self.assertEqual(cat_ids(cats), ["competition"])

    def test_classifier_version_bumped(self):
        """規則改動要 bump CLASSIFIER_VERSION，enrich 先識得重分類舊記錄。"""
        self.assertEqual(CLASSIFIER_VERSION, "3.1")


class PipelineIntegration(unittest.TestCase):
    def test_extract_fields_uses_listing_title(self):
        fields = extract_fields(
            RACE_TEXT, GENERIC_HKS_PDF_TITLE, source="總會",
            listing_title=MARATHON_LISTING_TITLE,
        )
        self.assertEqual(
            [c.get("id") for c in fields["categories"]], ["service"])
        self.assertEqual(fields["subscription_tags"], ["category:service"])

    def test_notify_fallback_matches_service_not_competition(self):
        """無 enrich 記錄時，notify 用標題 fallback：服務訂閱中、比賽訂閱唔中。"""
        item = make_item(MARATHON_LISTING_TITLE)
        meta = notify.notice_metadata(item, {})
        self.assertIn("category:service", meta["topic_tags"])
        self.assertNotIn("category:competition", meta["topic_tags"])

    def test_notify_fallback_ignores_participant_recruitment(self):
        item = make_item("香港童軍龍舟邀請賽2026 – 沙田西區龍舟隊成員招募")
        meta = notify.notice_metadata(item, {})
        self.assertIn("category:competition", meta["topic_tags"])
        self.assertNotIn("category:service", meta["topic_tags"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
