"""Offline regressions for the 壁峰區「Drive, 」title cleanup.

Synthetic fixtures only: no network, no notification, no publishing.
"""
import copy
import json
import unittest
from pathlib import Path

from fix_pikfung_titles_2026_10_17 import SOURCE, apply_review


def row(title, drive_id):
    url = f"https://drive.google.com/file/d/{drive_id}/view"
    return dict(title=title, url=url, pdf_url=url, date="2026-10-15",
                captured_date="2026-10-15", source_site=SOURCE, region="新界東地域")


def notice(title, drive_id):
    return dict(source_site=SOURCE, region="新界東地域",
                pdf_url=f"https://drive.google.com/file/d/{drive_id}/view",
                title=title, captured_date="2026-10-15")


def fixture():
    cache = {
        "last_updated": "2026-10-17 05:00:11",
        "meta": {"total_notices": 3},
        "data": {SOURCE: [
            row("Drive, PFD2627VS004 政制探究及民政訓練班", "Aaa"),
            row("Drive, 2026-27小童軍親子活動—懷舊食物工作坊", "Bbb"),
            row("小童軍領袖手冊", "Ccc"),
        ]},
        "notices": [
            notice("Drive, PFD2627VS004 政制探究及民政訓練班", "Aaa"),
            notice("小童軍領袖手冊", "Ccc"),
        ],
    }
    enrich = {
        "https://drive.google.com/file/d/Aaa/view": dict(source=SOURCE, title="Drive, PFD2627VS004 政制探究及民政訓練班"),
        "https://drive.google.com/file/d/Ccc/view": dict(source=SOURCE, title="小童軍領袖手冊"),
    }
    return cache, enrich


class TitleCleanup(unittest.TestCase):
    def test_drive_prefix_stripped_from_grouped_notices_and_enrich(self):
        cache, enrich = fixture()
        new_cache, new_enrich, counts = apply_review(cache, enrich)
        self.assertEqual(counts["titles_fixed"], 2)
        titles = [x["title"] for x in new_cache["data"][SOURCE]]
        self.assertIn("PFD2627VS004 政制探究及民政訓練班", titles)
        self.assertIn("2026-27小童軍親子活動—懷舊食物工作坊", titles)
        # 區會編號／年度要留，淨係剷「Drive, 」
        self.assertNotIn("Drive,", "".join(titles))
        notice_titles = {x["pdf_url"]: x["title"] for x in new_cache["notices"]}
        self.assertEqual(notice_titles["https://drive.google.com/file/d/Aaa/view"],
                         "PFD2627VS004 政制探究及民政訓練班")
        self.assertEqual(new_enrich["https://drive.google.com/file/d/Aaa/view"]["title"],
                         "PFD2627VS004 政制探究及民政訓練班")

    def test_titles_without_the_prefix_are_untouched(self):
        cache, enrich = fixture()
        new_cache, new_enrich, _counts = apply_review(cache, enrich)
        self.assertIn("小童軍領袖手冊", [x["title"] for x in new_cache["data"][SOURCE]])
        self.assertEqual(new_enrich["https://drive.google.com/file/d/Ccc/view"]["title"], "小童軍領袖手冊")

    def test_second_run_is_a_no_op(self):
        cache, enrich = fixture()
        once, once_enrich, _counts = apply_review(cache, enrich)
        twice, twice_enrich, counts = apply_review(once, once_enrich)
        self.assertEqual(counts["titles_fixed"], 0)
        self.assertEqual(twice, once)
        self.assertEqual(twice_enrich, once_enrich)


class ProductionShape(unittest.TestCase):
    def setUp(self):
        self.cache = json.loads(Path("cache.json").read_text(encoding="utf-8"))
        self.enrich = json.loads(Path("enrich.json").read_text(encoding="utf-8"))

    def test_no_drive_prefix_left_in_pikfung(self):
        for item in self.cache["data"][SOURCE]:
            self.assertFalse(str(item.get("title", "")).startswith("Drive,"), item.get("title"))

    def test_grouped_notices_and_enrich_titles_agree(self):
        # 破折號冇統一（cache 係檔名入面嘅半形 "-"，enrich 係人工覆核嘅全形 "—"），
        # 呢度只對「剷咗 Drive, 之後主體係咪同一句」負責。
        def norm(text):
            for dash in ("—", "–", "－"):
                text = str(text or "").replace(dash, "-")
            return text.strip()

        for item in self.cache["data"][SOURCE]:
            url = str(item.get("pdf_url") or "")
            for notice in self.cache["notices"]:
                if notice.get("source_site") == SOURCE and notice.get("pdf_url") == url:
                    self.assertEqual(norm(notice["title"]), norm(item["title"]))
            entry = self.enrich.get(url)
            if isinstance(entry, dict) and entry.get("title"):
                self.assertEqual(norm(entry["title"]), norm(item["title"]))


if __name__ == "__main__":
    unittest.main()
