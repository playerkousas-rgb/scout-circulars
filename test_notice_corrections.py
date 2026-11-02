import unittest

from tools.apply_notice_corrections import apply_corrections


class ApplyNoticeCorrectionsTests(unittest.TestCase):
    def make_data(self):
        bad_url = "https://hkscout-tko.org/notice/?nid=209"
        title_announcement = "童軍訓練班及活動專用特惠菜式"
        title_activity = "新東毅行.越嶺同行"
        cache = {
            "meta": {"total_notices": 3},
            "notices": [
                {"pdf_url": bad_url, "title": "錯誤通告"},
                {"pdf_url": "menu.pdf", "title": title_announcement},
                {"pdf_url": "hike.pdf", "title": title_activity},
            ],
            "data": {
                "將軍澳區": [{"pdf_url": bad_url, "url": bad_url, "title": "錯誤通告"}],
                "總會": [{"pdf_url": "menu.pdf", "title": title_announcement}],
                "新界東地域": [{"pdf_url": "hike.pdf", "title": title_activity}],
            },
        }
        enrich = {
            bad_url: {"title": "錯誤通告"},
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
        }
        return cache, enrich

    def test_removes_invalid_notice_from_all_public_copies_and_enrich(self):
        cache, enrich = self.make_data()
        summary = apply_corrections(cache, enrich)
        bad_url = "https://hkscout-tko.org/notice/?nid=209"
        self.assertNotIn(bad_url, [row["pdf_url"] for row in cache["notices"]])
        self.assertFalse(any(row.get("pdf_url") == bad_url for rows in cache["data"].values() for row in rows))
        self.assertNotIn(bad_url, enrich)
        self.assertEqual(cache["meta"]["total_notices"], 2)
        self.assertEqual(summary["removed_cache_rows"], 2)
        self.assertEqual(summary["removed_enrich_rows"], 1)

    def test_corrects_categories_and_preserves_independent_topic_tags(self):
        cache, enrich = self.make_data()
        apply_corrections(cache, enrich)
        menu = enrich["menu.pdf"]
        hike = enrich["hike.pdf"]
        self.assertEqual(menu["categories"][0]["id"], "announcement")
        self.assertIn("category:announcement", menu["subscription_tags"])
        self.assertNotIn("category:training", menu["subscription_tags"])
        self.assertIn("course:scout-explorer-badge", menu["subscription_tags"])
        self.assertFalse(any(tag.startswith("training:") for tag in menu["subscription_tags"]))
        self.assertFalse(any(detail["id"].startswith("training:") for detail in menu["subscription_tag_details"]))
        self.assertEqual(hike["categories"][0]["id"], "activity")
        self.assertIn("activity:other", hike["subscription_tags"])
        self.assertNotIn("category:announcement", hike["subscription_tags"])
        self.assertIn("course:venture-expedition", hike["subscription_tags"])


if __name__ == "__main__":
    unittest.main()
