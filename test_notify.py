#!/usr/bin/env python3
"""Pure-unit checks for the anonymous Web Push dispatcher (no network needed)."""

import unittest

from notify import build_push_payload, find_new_notices, matching_groups, notice_id, notice_key


class NotifyMatchingTests(unittest.TestCase):
    def setUp(self):
        self.training_one = {
            "source_site": "總會",
            "pdf_url": "https://example.test/one.pdf",
            "title": "童軍繩結訓練班",
            "captured_date": "2026-09-07",
        }
        self.training_two = {
            "source_site": "總會",
            "pdf_url": "https://example.test/two.pdf",
            "title": "童軍初級空勤員章工作坊",
            "captured_date": "2026-09-07",
        }
        self.service = {
            "source_site": "總會",
            "pdf_url": "https://example.test/service.pdf",
            "title": "童軍社區服務日",
            "captured_date": "2026-09-07",
        }
        self.enrich = {
            self.training_one["pdf_url"]: {"branch_tags": ["童軍"], "subscription_tags": ["category:training"], "deadline": "2026-09-10", "fee": "HK$50"},
            self.training_two["pdf_url"]: {"branch_tags": ["童軍"], "subscription_tags": ["category:training", "course:scout-basic-aircrew-badge"]},
            self.service["pdf_url"]: {"branch_tags": ["童軍"], "subscription_tags": ["category:service"]},
        }
        self.subscription = {
            "id": "00000000-0000-0000-0000-000000000001",
            "branch_ids": ["童軍", "深資童軍"],
            "topic_ids": ["category:training", "activity:campfire"],
        }

    def test_source_qualified_cache_comparison(self):
        same_url = "https://example.test/shared.pdf"
        baseline = {"data": {"甲區": [{"source_site": "甲區", "pdf_url": same_url}]}}
        current = {"data": {"甲區": [{"source_site": "甲區", "pdf_url": same_url}], "乙區": [{"source_site": "乙區", "pdf_url": same_url}]}}
        found = find_new_notices(current, baseline)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source_site"], "乙區")
        self.assertNotEqual(notice_key(found[0]), notice_key(baseline["data"]["甲區"][0]))

    def test_branch_and_topic_intersection_then_aggregate(self):
        groups = matching_groups(
            [self.subscription],
            [self.training_one, self.training_two, self.service],
            [self.training_one, self.training_two, self.service],
            self.enrich,
            set(),
        )
        self.assertEqual(list(groups), [self.subscription["id"]])
        _sub, newly, summary = groups[self.subscription["id"]]
        self.assertEqual([item["pdf_url"] for item in newly], [self.training_one["pdf_url"], self.training_two["pdf_url"]])
        self.assertEqual(len(summary), 2)

    def test_already_delivered_notice_does_not_resend_but_stays_in_updated_summary(self):
        groups = matching_groups(
            [self.subscription],
            [self.training_one, self.training_two],
            [self.training_one, self.training_two],
            self.enrich,
            {(self.subscription["id"], notice_key(self.training_one))},
        )
        _sub, newly, summary = groups[self.subscription["id"]]
        self.assertEqual(newly, [self.training_two])
        self.assertEqual(summary, [self.training_one, self.training_two])

    def test_one_item_payload_is_minimal_and_opens_exact_library_result(self):
        payload = build_push_payload([self.training_one], self.enrich, "https://site.example/", "2026-09-07")
        expected_id = notice_id(self.training_one)
        self.assertEqual(payload["title"], "🔔 童軍繩結訓練班")
        self.assertEqual(payload["body"], "點擊查看通告")
        self.assertEqual(payload["url"], f"https://site.example/?n={expected_id}")
        self.assertNotIn(self.training_one["pdf_url"], payload["url"])
        self.assertEqual(payload["noticeIds"], [expected_id])
        self.assertEqual(payload["tag"], "scout-circulars-personal-2026-09-07")
        self.assertFalse(payload["silent"])

    def test_multi_item_payload_is_minimal_and_opens_exact_library_results(self):
        payload = build_push_payload([self.training_one, self.training_two], self.enrich, "https://site.example/", "2026-09-07")
        expected_ids = [notice_id(self.training_one), notice_id(self.training_two)]
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["title"], "🔔 你關注的項目有 2 項新通告")
        self.assertEqual(payload["body"], "按此查看全部")
        self.assertEqual(payload["url"], f"https://site.example/?n={','.join(expected_ids)}")
        self.assertNotIn("personal=1", payload["url"])
        self.assertEqual(payload["noticeIds"], expected_ids)
        self.assertEqual(payload["tag"], "scout-circulars-personal-2026-09-07")
        update = build_push_payload([self.training_one, self.training_two], self.enrich, "https://site.example/", "2026-09-07", silent=True)
        self.assertTrue(update["silent"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
