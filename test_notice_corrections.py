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


class NoticeCorrections2026_11_04Tests(unittest.TestCase):
    """2026-11-04 用戶確認嘅三張通告：改名、標籤、網頁型通告補分類。"""

    GRANTHAM = "https://scout.org.hk/uploads/tc/circulars/26576/CPA202607_Grantham_Chi_2026.pdf"
    WINTER = "https://scout.org.hk/uploads/tc/circulars/26582/Cir23_2026_冬日弦音-•-聖誕燒烤派對.pdf"
    TKO = "https://hkscout-tko.org/notice/?nid=209"

    def make_snapshot(self):
        listing_title = "葛量洪青少年制服團隊傑出服務奬2026-2027"
        bad_title = "2.1 11至26歲(以本通告發出日為準)的童軍、深資童軍或樂行童軍支部成員;"
        winter_title = "冬日弦音 • 聖誕燒烤派對"
        tko_title = "11-2026 小童軍支部 - 「小草」賀新春—小童軍親子利是封設計比賽 (截止: 2026-12-26)"
        notices = [
            {"title": bad_title, "pdf_url": self.GRANTHAM, "source_site": "總會"},
            {"title": winter_title, "pdf_url": self.WINTER, "source_site": "總會"},
            {"title": tko_title, "pdf_url": self.TKO, "source_site": "將軍澳區"},
        ]
        cache = {
            "data": {"總會": notices[:2], "將軍澳區": notices[2:]},
            "notices": notices,
        }
        enrich = {
            self.GRANTHAM: {
                "title": bad_title, "source": "總會", "audience": "",
                "categories": [{"id": "service", "label": "服務", "score": 3.0, "evidence": ["社會服務"]}],
                "branch_tags": ["童軍", "深資童軍", "樂行童軍"],
                "subscription_tags": ["category:service"],
                "subscription_tag_details": [],
                "title_check": "corrected", "listing_title": listing_title,
            },
            self.WINTER: {
                "title": winter_title, "source": "總會", "audience": "",
                "categories": [{"id": "announcement", "label": "公布", "score": 3.0, "evidence": []}],
                "subscription_tags": ["category:announcement"],
                "subscription_tag_details": [], "branch_tags": [],
            },
        }
        return cache, enrich, listing_title, tko_title

    def test_today_notices_are_corrected_and_idempotent(self):
        cache, enrich, listing_title, tko_title = self.make_snapshot()
        summary = apply_corrections(enrich, cache)
        self.assertEqual(summary["corrected_categories"], 2)
        self.assertEqual(summary["restored_titles"], 1)
        self.assertEqual(summary["injected_entries"], 1)

        grantham = enrich[self.GRANTHAM]
        self.assertEqual(grantham["title"], listing_title)
        self.assertEqual(grantham["title_check"], "verified")
        self.assertEqual([c["id"] for c in grantham["categories"]], ["announcement"])
        self.assertEqual(grantham["audience"], "童軍、深資童軍、樂行童軍")
        self.assertEqual(sorted(grantham["branch_tags"]), ["樂行童軍", "深資童軍", "童軍"])
        self.assertEqual(grantham["subscription_tags"], ["category:announcement"])
        # cache 兩份副本（data + notices）都要還原
        self.assertEqual(cache["data"]["總會"][0]["title"], listing_title)
        self.assertEqual(cache["notices"][0]["title"], listing_title)

        winter = enrich[self.WINTER]
        self.assertEqual([c["id"] for c in winter["categories"]], ["activity"])
        self.assertIn("activity:other", winter["subscription_tags"])

        tko = enrich[self.TKO]
        self.assertEqual(tko["title"], tko_title)
        self.assertEqual([c["id"] for c in tko["categories"]], ["competition"])
        self.assertEqual(tko["branch_tags"], ["小童軍"])
        self.assertEqual(tko["deadline"], "2026-12-26")
        self.assertEqual(tko["method"], "site-listing")

        second = apply_corrections(enrich, cache)
        self.assertNotIn("restored_titles", second)
        self.assertNotIn("injected_entries", second)

    def test_no_cache_means_no_title_or_inventory_changes(self):
        """舊測試（只傳 enrich）唔應該被新功能影響。"""
        cache, enrich, _listing, _tko = self.make_snapshot()
        bad_title = cache["notices"][0]["title"]
        summary = apply_corrections(enrich)
        self.assertEqual(summary, {"corrected_categories": 1})
        self.assertNotIn(self.TKO, enrich)
        # 冇 cache 就唔改名、唔補 entry；兩份資料維持原狀。
        self.assertEqual(enrich[self.GRANTHAM]["title"], bad_title)
        self.assertEqual(cache["notices"][0]["title"], bad_title)


if __name__ == "__main__":
    unittest.main()
