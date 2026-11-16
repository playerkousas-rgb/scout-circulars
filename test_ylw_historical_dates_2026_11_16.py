"""Offline regressions for the 2026-11-16 元朗西區 historical date & title fix.

Covers:
  1. All 14 historical 2024–early-2026 WordPress posts accidentally stamped
     2026-11-16 are restored to their official WP publish dates with
     backfilled_at='2026-11-16' and suppress_notifications=True;
  2. Genuine today circular (activity15-2026.pdf) and existing circulars
     (activity13-2026.pdf, activity12-2026.pdf) keep their dates untouched;
  3. Broken semicolon-clause titles ('舉辦之本地「領袖木章訓練」課程;') on
     special01-2025.pdf & special02-2026.pdf are restored in both cache copies
     and enrich.json, and enrich.py 3.12 rejects semicolon/comma clause tails;
  4. Re-dated historical items never trigger push notifications or Story queue,
     and core.merge_reviewed_backfills preserves them across future runs.
"""
import copy
import unittest

import core
import enrich
import notify
import story_queue as sq
from tools.apply_notice_corrections import (
    HISTORICAL_DATE_CORRECTIONS,
    TITLE_CORRECTIONS,
    apply_corrections,
)


class YuenLongWestHistoricalDateTests(unittest.TestCase):
    TODAY = "2026-11-16"
    REAL_TODAY_URL = "https://www.ylw-scout.org.hk/circular/activity15-2026.pdf"
    OLD_AUG_URL = "https://www.ylw-scout.org.hk/circular/activity12-2026.pdf"

    def _build_fixture(self):
        data_rows = [
            {
                "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
                "url": self.REAL_TODAY_URL,
                "pdf_url": self.REAL_TODAY_URL,
                "date": self.TODAY,
                "captured_date": self.TODAY,
                "source_site": "元朗西區",
                "region": "新界地域",
            },
            {
                "title": "元朗西區50週年紀念填色比賽 - activity12-2026",
                "url": self.OLD_AUG_URL,
                "pdf_url": self.OLD_AUG_URL,
                "date": "2026-08-25",
                "captured_date": "2026-08-25",
                "source_site": "元朗西區",
                "region": "新界地域",
            },
        ]
        enrich_map = {
            self.REAL_TODAY_URL: {
                "source": "元朗西區",
                "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
                "deadline": "2026-11-21",
                "audience": "幼童軍",
                "fee": "HK$200.00",
                "categories": [{"id": "competition", "label": "比賽"}],
                "title_check": "verified",
            },
        }
        for url in HISTORICAL_DATE_CORRECTIONS:
            bad_title = (
                "舉辦之本地「領袖木章訓練」課程;"
                if url in TITLE_CORRECTIONS
                else f"舊通告-{url.rsplit('/', 1)[-1]}"
            )
            data_rows.append(
                {
                    "title": bad_title,
                    "url": url,
                    "pdf_url": url,
                    "date": self.TODAY,
                    "captured_date": self.TODAY,
                    "source_site": "元朗西區",
                    "region": "新界地域",
                }
            )
            entry = {
                "source": "元朗西區",
                "title": bad_title,
                "deadline": "2026-12-31",
                "audience": "童軍",
                "fee": "全免",
                "categories": [{"id": "training", "label": "訓練"}],
                "title_check": "corrected" if url in TITLE_CORRECTIONS else "verified",
            }
            if url in TITLE_CORRECTIONS:
                entry["listing_title"] = TITLE_CORRECTIONS[url]
            enrich_map[url] = entry

        notices = [
            {
                "source_site": r["source_site"],
                "region": r["region"],
                "pdf_url": r["pdf_url"],
                "title": r["title"],
                "captured_date": r["captured_date"],
            }
            for r in data_rows
        ]
        scout_system_rows = [
            {
                "title": "營釘力學",
                "url": "https://campfiretw.com/tarp-guide/#stake",
                "pdf_url": "https://campfiretw.com/tarp-guide/#stake",
                "date": self.TODAY,
                "captured_date": self.TODAY,
                "source_site": "Scout System",
                "region": "Scout System",
            }
        ]
        cache = {
            "last_updated": "2026-11-16 07:59:21",
            "_meta": {
                "last_run": {
                    "updated_at": "2026-11-16 07:59:21",
                    "new": 14,
                    "daily_new": 16,
                }
            },
            "data": {
                "元朗西區": data_rows,
                "Scout System": scout_system_rows,
            },
            "notices": notices,
        }
        return cache, enrich_map

    def test_redates_all_14_historical_ylw_notices_and_preserves_today_notice(self):
        self.assertEqual(len(HISTORICAL_DATE_CORRECTIONS), 14)
        cache, enrich_map = self._build_fixture()
        summary = apply_corrections(enrich_map, cache)
        self.assertEqual(summary.get("redated_notices"), 14)
        self.assertEqual(summary.get("restored_titles"), 2)

        ylw_rows = cache["data"]["元朗西區"]
        # 頂部第一張一定係真正今日新通告 activity15-2026，第二張係 2026-08-25 舊通告
        self.assertEqual(ylw_rows[0]["pdf_url"], self.REAL_TODAY_URL)
        self.assertEqual(ylw_rows[0]["date"], self.TODAY)
        self.assertNotIn("backfilled_at", ylw_rows[0])
        self.assertEqual(ylw_rows[1]["pdf_url"], self.OLD_AUG_URL)
        self.assertEqual(ylw_rows[1]["date"], "2026-08-25")

        by_url = {r["pdf_url"]: r for r in ylw_rows}
        notice_by_url = {r["pdf_url"]: r for r in cache["notices"]}
        for url, (expected_date, backfill_date, evidence) in HISTORICAL_DATE_CORRECTIONS.items():
            self.assertEqual(by_url[url]["date"], expected_date)
            self.assertEqual(by_url[url]["captured_date"], expected_date)
            self.assertEqual(by_url[url]["published_date"], expected_date)
            self.assertEqual(by_url[url]["backfilled_at"], backfill_date)
            self.assertTrue(by_url[url]["suppress_notifications"])

            self.assertEqual(notice_by_url[url]["captured_date"], expected_date)
            self.assertTrue(notice_by_url[url]["suppress_notifications"])
            self.assertEqual(enrich_map[url]["published_date"], expected_date)
            self.assertEqual(enrich_map[url]["date_evidence"], evidence)

        # 兩張木章助學金計劃標題還原＋分類改返公布
        for url in (
            "https://www.ylw-scout.org.hk/circular/special01-2025.pdf",
            "https://www.ylw-scout.org.hk/circular/special02-2026.pdf",
        ):
            expected_title = TITLE_CORRECTIONS[url]
            self.assertEqual(by_url[url]["title"], expected_title)
            self.assertEqual(notice_by_url[url]["title"], expected_title)
            self.assertEqual(enrich_map[url]["title"], expected_title)
            self.assertEqual([c["id"] for c in enrich_map[url]["categories"]], ["announcement"])

        # daily_new 重算後只剩 activity15-2026 + Scout System = 2，new 扣回 0
        self.assertEqual(cache["_meta"]["last_run"]["new"], 0)
        self.assertEqual(cache["_meta"]["last_run"]["daily_new"], 2)

        # 冪等：再跑一次完全唔會改動 cache 或 enrich
        snap_cache = copy.deepcopy(cache)
        snap_enrich = copy.deepcopy(enrich_map)
        second = apply_corrections(enrich_map, cache)
        self.assertNotIn("redated_notices", second)
        self.assertEqual(cache, snap_cache)
        self.assertEqual(enrich_map, snap_enrich)

    def test_no_push_or_story_for_redated_notices_and_preserved_across_core_merge(self):
        cache, enrich_map = self._build_fixture()
        apply_corrections(enrich_map, cache)

        # Push 通知：就算同空 baseline 比，14 張補登舊通告都唔會發出通知
        candidates = notify.find_new_notices(cache, {"data": {}, "notices": []})
        candidate_urls = {c.get("pdf_url") or c.get("url") for c in candidates}
        self.assertIn(self.REAL_TODAY_URL, candidate_urls)
        self.assertTrue(candidate_urls.isdisjoint(HISTORICAL_DATE_CORRECTIONS))

        # Story 清單：只揀真正今日通告 activity15-2026
        q = sq.build_queue(cache, self.TODAY, limit=5, enrich=enrich_map)
        self.assertEqual([it["url"] for it in q["items"]], [self.REAL_TODAY_URL])

        # core.merge_reviewed_backfills：就算遠端 DB 仍帶舊今日日期，都會保留還原後嘅歷史日期
        stale_remote = [
            {
                "source_site": "元朗西區",
                "region": "新界地域",
                "pdf_url": url,
                "title": "舊通告",
                "captured_date": self.TODAY,
            }
            for url in HISTORICAL_DATE_CORRECTIONS
        ]
        merged = core.merge_reviewed_backfills(stale_remote, cache["notices"])
        merged_by_url = {r["pdf_url"]: r for r in merged if r.get("pdf_url") in HISTORICAL_DATE_CORRECTIONS}
        for url, (expected_date, _bf, _ev) in HISTORICAL_DATE_CORRECTIONS.items():
            self.assertEqual(merged_by_url[url]["captured_date"], expected_date)
            self.assertTrue(merged_by_url[url]["suppress_notifications"])

    def test_enrich_rejects_semicolon_clause_as_heading(self):
        clause = "舉辦之本地「領袖木章訓練」課程;"
        self.assertFalse(enrich.heading_looks_like_title(clause))
        pdf_text = (
            f"{clause}\n"
            "鄧永昌主席領袖木章助學金計劃(2026-27年度)\n"
        )
        self.assertEqual(
            enrich.extract_pdf_heading(pdf_text),
            "鄧永昌主席領袖木章助學金計劃(2026-27年度)",
        )


if __name__ == "__main__":
    unittest.main()
