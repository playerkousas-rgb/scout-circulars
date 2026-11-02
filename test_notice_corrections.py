import unittest

from tools.apply_notice_corrections import apply_corrections


class ApplyNoticeCorrectionsTests(unittest.TestCase):
    def make_enrich(self):
        title_announcement = "童軍訓練班及活動專用特惠菜式"
        title_activity = "新東毅行.越嶺同行"
        return {
            "menu.pdf": {
                "title": title_announcement,
                "source": "總會",
                "categories": [{"id": "training", "label": "訓練"}],
                "subscription_tags": ["category:training", "training:童軍", "course:scout-explorer-badge"],
                "subscription_tag_details": [
                    {"id": "category:training", "label": "訓練", "kind": "category"},
                    {"id": "training:童軍", "label": "所有童軍訓練", "kind": "training"},
                    {"id": "course:scout-explorer-badge", "label": "探險章", "kind": "course"},
                ],
            },
            "hike.pdf": {
                "title": title_activity,
                "source": "總會",
                "categories": [{"id": "announcement", "label": "公布"}],
                "subscription_tags": ["category:announcement", "course:venture-expedition"],
                "subscription_tag_details": [
                    {"id": "category:announcement", "label": "公布", "kind": "category"},
                    {"id": "course:venture-expedition", "label": "遠足", "kind": "course"},
                ],
            },
            "hike-mirror.pdf": {
                "title": title_activity,
                "source": "新界東地域",
                "categories": [{"id": "announcement", "label": "公布"}],
                "subscription_tags": ["category:announcement"],
                "subscription_tag_details": [
                    {"id": "category:announcement", "label": "公布", "kind": "category"},
                ],
            },
            "unrelated.pdf": {
                "title": "一般通告",
                "categories": [{"id": "announcement", "label": "公布"}],
                "subscription_tags": ["category:announcement"],
            },
        }

    def test_corrects_categories_and_preserves_independent_topic_tags(self):
        enrich = self.make_enrich()
        summary = apply_corrections(enrich)
        menu = enrich["menu.pdf"]
        hike = enrich["hike.pdf"]
        self.assertEqual(summary, {"corrected_categories": 3})
        self.assertEqual(menu["categories"][0]["id"], "announcement")
        self.assertIn("category:announcement", menu["subscription_tags"])
        self.assertNotIn("category:training", menu["subscription_tags"])
        self.assertFalse(any(tag.startswith("training:") for tag in menu["subscription_tags"]))
        self.assertFalse(any(detail["id"].startswith("training:") for detail in menu["subscription_tag_details"]))
        self.assertIn("course:scout-explorer-badge", menu["subscription_tags"])
        self.assertEqual(hike["categories"][0]["id"], "activity")
        self.assertIn("activity:other", hike["subscription_tags"])
        self.assertNotIn("category:announcement", hike["subscription_tags"])
        self.assertIn("course:venture-expedition", hike["subscription_tags"])
        self.assertEqual(enrich["hike-mirror.pdf"]["categories"][0]["id"], "activity")
        self.assertEqual(enrich["unrelated.pdf"]["categories"][0]["id"], "announcement")

    def test_rule_is_repeatable(self):
        enrich = self.make_enrich()
        apply_corrections(enrich)
        corrected = {key: value.copy() for key, value in enrich.items()}
        apply_corrections(enrich)
        self.assertEqual(enrich, corrected)


if __name__ == "__main__":
    unittest.main()
