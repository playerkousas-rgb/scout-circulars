#!/usr/bin/env python3
"""Security-focused pure checks for the public anonymous subscription API."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "api"))

from push_common import ApiError, validate_endpoint, validate_preferences, validate_subscription  # noqa: E402


class PushCommonTests(unittest.TestCase):
    def test_accepts_only_catalog_choices(self):
        branches, topics, version = validate_preferences({
            "branches": ["童軍"],
            "topics": ["category:training", "category:competition", "course:scout-basic-aircrew-badge"],
        })
        self.assertEqual(branches, ["童軍"])
        self.assertEqual(topics, ["category:training", "category:competition", "course:scout-basic-aircrew-badge"])
        self.assertTrue(version)

    def test_rejects_course_for_wrong_branch(self):
        with self.assertRaises(ApiError) as caught:
            validate_preferences({"branches": ["領袖"], "topics": ["course:scout-basic-aircrew-badge"]})
        self.assertEqual(caught.exception.code, "incompatible_choice")

    def test_branch_scoped_preferences_and_parent_options(self):
        for topic in ("training:家長", "category:service", "category:training", "training:童軍", "course:scout-first-aid-badge", "branch:童軍:category:service"):
            with self.subTest(topic=topic), self.assertRaises(ApiError):
                validate_preferences({"branches": ["家長"], "topics": [topic]})
        topics = ["branch:家長:activity:other", "branch:童軍:category:service", "training:童軍"]
        self.assertEqual(validate_preferences({"branches": ["家長", "童軍"], "topics": topics})[1], topics)
        with self.assertRaises(ApiError):
            validate_preferences({"branches": ["家長"], "topics": ["branch:家長:category:service"]})

    def test_all_new_normalizes_to_one_topic_and_database_compatible_branches(self):
        branches, topics, _ = validate_preferences({"branches": [], "topics": ["all:new", "activity:other"]})
        self.assertEqual(topics, ["all:new"])
        self.assertEqual(len(branches), 8)
        with self.assertRaises(ApiError):
            validate_preferences({"branches": [], "topics": ["activity:other"]})
        with self.assertRaises(ApiError):
            validate_preferences({"branches": [], "topics": ["all:new", "forged"]})

    def test_split_select_all_is_branch_agnostic_but_schema_compatible(self):
        """2026-10-01：all:notices／all:tools 唔靠支部配對，但 schema 要 1..8 個支部。"""
        for topic in ("all:notices", "all:tools"):
            with self.subTest(topic=topic):
                branches, topics, _ = validate_preferences({"branches": [], "topics": [topic]})
                self.assertEqual(topics, [topic])
                self.assertEqual(len(branches), 8)
        branches, topics, _ = validate_preferences({"branches": [], "topics": ["all:notices", "all:tools"]})
        self.assertEqual(topics, ["all:notices", "all:tools"])
        self.assertEqual(len(branches), 8)
        # 全選 + 逐項：已揀支部要原樣保留，唔好悄悄擴散到全部支部。
        branches, topics, _ = validate_preferences(
            {"branches": ["家長"], "topics": ["all:tools", "branch:家長:activity:other"]}
        )
        self.assertEqual(branches, ["家長"])
        self.assertEqual(topics, ["all:tools", "branch:家長:activity:other"])
        # 支部／項目唔夾嘅組合照舊拒收。
        with self.assertRaises(ApiError):
            validate_preferences({"branches": [], "topics": ["all:tools", "forged"]})
        with self.assertRaises(ApiError) as caught:
            validate_preferences({"branches": ["家長"], "topics": ["all:tools", "training:童軍"]})
        self.assertEqual(caught.exception.code, "incompatible_choice")

    def test_rejects_free_text_tag(self):
        with self.assertRaises(ApiError) as caught:
            validate_preferences({"branches": ["童軍"], "topics": ["my custom tag"]})
        self.assertEqual(caught.exception.code, "invalid_choice")

    def test_push_endpoint_provider_allowlist_blocks_ssrf(self):
        self.assertEqual(
            validate_endpoint("https://fcm.googleapis.com/fcm/send/example"),
            "https://fcm.googleapis.com/fcm/send/example",
        )
        for endpoint in (
            "https://127.0.0.1/internal",
            "https://example.com/push",
            "http://fcm.googleapis.com/fcm/send/example",
            "https://user@fcm.googleapis.com/fcm/send/example",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ApiError):
                    validate_endpoint(endpoint)

    def test_subscription_requires_endpoint_and_both_encryption_keys(self):
        value = validate_subscription({
            "endpoint": "https://fcm.googleapis.com/fcm/send/example",
            "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
        })
        self.assertEqual(value["auth"], "B" * 22)
        with self.assertRaises(ApiError):
            validate_subscription({"endpoint": "https://fcm.googleapis.com/fcm/send/example", "keys": {}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
