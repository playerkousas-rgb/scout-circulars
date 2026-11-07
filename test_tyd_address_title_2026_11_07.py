#!/usr/bin/env python3
"""2026-11-07 用戶報告：青衣區「取錄通知」被 PDF 信頭地址抽成標題。

個案：https://tyd.scout-ntr.org.hk/dist_cir/notice_train/sc260901-1.pdf
文字層第一行係「香港青衣長康邨康美樓 C301 室」，舊版 enrich.py：
  extract_pdf_heading 冇擋地址 → reconcile 判 corrected（列表標題「取錄通知」
  只得 4 個字，做唔到 substring 對證）→ --apply-title-fixes 把地址寫返
  cache.json，列表／推播／分享全部變成地址。
三道防線（離線、零下載）：
  1. extract_pdf_heading 跳過中英文信頭地址；
  2. heading_looks_like_title 唔准地址寫返 cache（連舊 snapshot 嘅更正都還原）；
  3. listing_supported_by_pdf 容許 4–5 字嘅文件類型標題做 substring 對證。
另外 tools/apply_notice_corrections.py 嘅 allowlist 清走已被寫壞嘅兩張通告。
"""
import copy
import json
import unittest
from pathlib import Path

from enrich import (
    extract_pdf_heading,
    heading_looks_like_title,
    looks_like_postal_address,
    reapply_stored_title_fixes,
    reconcile_listing_title,
)
from tools.apply_notice_corrections import TITLE_CORRECTIONS, apply_corrections

ROOT = Path(__file__).resolve().parent
LISTING_TITLE = "取錄通知"
ADDR = "香港青衣長康邨康美樓 C301 室"
URL_OLD = "https://tyd.scout-ntr.org.hk/dist_cir/notice_train/d260701-1.pdf"
URL_NEW = "https://tyd.scout-ntr.org.hk/dist_cir/notice_train/sc260901-1.pdf"

# 信頭形狀按真 PDF 文字層重組；刻意唔放取錄名單（有參加者姓名，唔入 repo）。
TYD_PDF_TEXT = "\n".join([
    "Scout Association of Hong Kong – Tsing Yi District",
    ADDR,
    "Flat C301, Hong Mei House, Cheung Hong Estate, Tsing Yi, Hong Kong",
    "http://www.scout.org.hk/tyd",
    "由 ：活動負責人",
    "致 ：各參加者及參加者之家長",
    "知會：各活動職員及青衣區各職員",
    "日期：2026 年 11 月 5 日",
    "取錄通知書",
    "香港童軍 115 周年 – 童聚青衣樂繽紛",
    "（活動日期：15/11/2026）",
    "閣下申請上述活動已被接納，敬希留意下列事項及準時出席為荷。",
    "活動日期 ： 2026 年 11 月 15 日（星期日）",
])


class AddressIsNotATitleTests(unittest.TestCase):
    def test_chinese_and_english_letterhead_addresses_are_detected(self):
        self.assertTrue(looks_like_postal_address(ADDR))
        self.assertTrue(looks_like_postal_address("青衣長康邨康美樓C301室"))
        self.assertTrue(looks_like_postal_address(
            "Flat C301, Hong Mei House, Cheung Hong Estate, Tsing Yi, Hong Kong"))
        self.assertTrue(looks_like_postal_address("地址：九龍馬頭圍邨芙蓉樓地下 104 室"))

    def test_pdf_heading_skips_address(self):
        heading = extract_pdf_heading(TYD_PDF_TEXT)
        self.assertNotEqual(heading, ADDR)
        self.assertNotIn("康美樓", heading)
        self.assertFalse(looks_like_postal_address(heading))

    def test_short_listing_title_stays_verified(self):
        check = reconcile_listing_title(LISTING_TITLE, TYD_PDF_TEXT)
        self.assertEqual((check["status"], check["title"]), ("verified", LISTING_TITLE))

    def test_final_guard_blocks_address_from_cache(self):
        self.assertFalse(heading_looks_like_title(ADDR))
        self.assertFalse(heading_looks_like_title("青衣長康邨康美樓C301室"))
        self.assertFalse(heading_looks_like_title(
            "Flat C301, Hong Mei House, Cheung Hong Estate, Tsing Yi, Hong Kong"))

    def test_stored_bad_correction_is_reverted(self):
        """下次 run 見到舊 snapshot 嘅「地址更正」會自動還原做列表標題。"""
        cache = {"data": {"青衣區": [
            {"title": ADDR, "pdf_url": URL_NEW, "url": URL_NEW,
             "captured_date": "2026-11-07"},
        ]}, "notices": [
            {"title": ADDR, "pdf_url": URL_NEW, "captured_date": "2026-11-07"},
        ]}
        enrich = {URL_NEW: {
            "title": ADDR, "listing_title": LISTING_TITLE,
            "title_check": "corrected", "source": "青衣區",
        }}
        self.assertEqual(reapply_stored_title_fixes(cache, enrich), 1)
        self.assertEqual(cache["data"]["青衣區"][0]["title"], LISTING_TITLE)
        self.assertEqual(cache["notices"][0]["title"], LISTING_TITLE)
        self.assertEqual(enrich[URL_NEW]["title"], LISTING_TITLE)
        self.assertEqual(enrich[URL_NEW]["title_check"], "reverted")
        # 冪等：再跑一次唔會重複寫
        self.assertEqual(reapply_stored_title_fixes(cache, enrich), 0)

    def test_real_notice_titles_are_not_rejected(self):
        """唔好為咗擋地址而誤殺真標題（尤其帶樓／室／中心嘅活動名）。"""
        titles = [
            "立法會綜合大樓參觀",
            "室內龍舟訓練證書課程(A)",
            "大潭童軍中心-賽馬會優質自然環境及可持續發展童軍大樓-開幕典禮暨嘉年華",
            "香港童軍115周年–青衣區親子原烹燒烤樂悠遊",
            "Project 18-模擬飛行房間開放計劃(青年空間1808室)",
            "港島童軍攀爬會-室內攀石體驗及定期練習",
            "區總部公布",
            "第95屆營藝訓練班",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(looks_like_postal_address(title))
                self.assertTrue(heading_looks_like_title(title))


class DailyRunWiringTests(unittest.TestCase):
    def test_both_scrape_workflows_apply_reviewed_corrections(self):
        """自動＋手動後備兩條 workflow 都要喺 enrich 之後執行修正，
        否則用戶「RUN 一次推上去」會漏咗標題還原，只靠 enrich 唔夠。"""
        for name in ("scrape.yml", "scrape-appstore.yml"):
            with self.subTest(workflow=name):
                text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
                self.assertIn("python enrich.py --verbose --apply-title-fixes", text)
                self.assertIn("python tools/apply_notice_corrections.py", text)
                self.assertLess(
                    text.index("python enrich.py --verbose --apply-title-fixes"),
                    text.index("python tools/apply_notice_corrections.py"),
                )


class ReviewedTitleCorrectionTests(unittest.TestCase):
    def _snapshot(self):
        notices = [
            {"title": ADDR, "pdf_url": URL_NEW, "source_site": "青衣區",
             "captured_date": "2026-11-07"},
            {"title": LISTING_TITLE, "pdf_url": URL_OLD, "source_site": "青衣區",
             "captured_date": "2026-09-16"},
        ]
        cache = {"data": {"青衣區": copy.deepcopy(notices)}, "notices": notices}
        enrich = {
            URL_NEW: {"source": "青衣區", "title": ADDR, "title_check": "corrected",
                      "listing_title": LISTING_TITLE, "categories": []},
            URL_OLD: {"source": "青衣區", "title": ADDR, "title_check": "corrected",
                      "categories": []},
        }
        return cache, enrich

    def test_both_urls_are_in_the_allowlist(self):
        self.assertEqual(TITLE_CORRECTIONS[URL_NEW], LISTING_TITLE)
        self.assertEqual(TITLE_CORRECTIONS[URL_OLD], LISTING_TITLE)

    def test_cache_and_enrich_are_restored_and_idempotent(self):
        cache, enrich = self._snapshot()
        summary = apply_corrections(enrich, cache)
        # 只有新嗰張嘅 cache 標題仲係地址（舊嗰張 cache 一早係列表原名），
        # 所以 cache 實際改動 1 條；enrich 兩條都要還原。
        self.assertEqual(summary.get("restored_titles"), 1)
        for url in (URL_NEW, URL_OLD):
            self.assertEqual(enrich[url]["title"], LISTING_TITLE)
            self.assertEqual(enrich[url]["title_check"], "verified")
        for item in cache["data"]["青衣區"] + cache["notices"]:
            self.assertEqual(item["title"], LISTING_TITLE)

        before = copy.deepcopy((cache, enrich))
        again = apply_corrections(enrich, cache)
        self.assertNotIn("restored_titles", again)
        self.assertEqual((cache, enrich), before)

    def test_checked_in_seed_data_is_clean(self):
        """main 上嘅種子資料唔應該再留低地址標題。"""
        cache = json.loads((ROOT / "cache.json").read_text(encoding="utf-8"))
        enrich = json.loads((ROOT / "enrich.json").read_text(encoding="utf-8"))
        self.assertEqual(enrich[URL_OLD]["title"], LISTING_TITLE)
        self.assertNotIn(ADDR, json.dumps(enrich[URL_OLD], ensure_ascii=False))
        matches = [item for item in cache["data"]["青衣區"]
                   if (item.get("pdf_url") or item.get("url")) == URL_OLD]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["title"], LISTING_TITLE)


if __name__ == "__main__":
    unittest.main()
