#!/usr/bin/env python3
"""story_queue.py unit tests — offline and stdlib-only."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_queue as sq  # noqa: E402

TODAY = "2026-09-21"
READY_META = {"deadline": "2026-10-05", "audience": "童軍", "fee": "HK$50"}


def _cache(items_by_section: dict, last_updated: str = "2026-09-21 05:00:10") -> dict:
    return {"last_updated": last_updated, "data": items_by_section}


def _item(**kw) -> dict:
    base = {
        "title": "測試訓練班",
        "url": "https://example.hk/notice/1.pdf",
        "pdf_url": "https://example.hk/notice/1.pdf",
        "region": "",
        "source_site": "筲箕灣區",
        "date": "2026-10-01",
        "captured_date": TODAY,
    }
    base.update(kw)
    return base


def _enrich(items: list[dict], by_url: dict[str, dict] | None = None) -> dict:
    result = {}
    for item in items:
        key = item.get("pdf_url") or item.get("url")
        meta = dict(READY_META)
        meta.update((by_url or {}).get(key, {}))
        result[key] = meta
    return result


class TestPickToday(unittest.TestCase):
    def test_only_todays_captured_date_is_picked(self):
        current = _item(title="今日新訓練")
        yesterday = _item(title="昨日嘅", captured_date="2026-09-20")
        cache = _cache({"筲箕灣區": [current, yesterday]})
        picked = sq.pick_today(cache, TODAY, _enrich([current, yesterday]))
        self.assertEqual([x["title"] for x in picked], ["今日新訓練"])

    def test_sorted_by_notice_date_then_source_and_title(self):
        items = [
            _item(title="後發布訓練", date="2026-12-31"),
            _item(title="同日乙訓練", date="2026-09-30", source_site="B 區"),
            _item(title="先發布訓練", date="2026-09-01"),
            _item(title="同日甲訓練", date="2026-09-30", source_site="A 區"),
        ]
        cache = _cache({"港島西": items})
        picked = sq.pick_today(cache, TODAY, _enrich(items))
        self.assertEqual([x["title"] for x in picked], ["先發布訓練", "同日甲訓練", "同日乙訓練", "後發布訓練"])

    def test_region_falls_back_to_section_name(self):
        item = _item(region="")
        cache = _cache({"九龍城區": [item]})
        picked = sq.pick_today(cache, TODAY, _enrich([item]))
        self.assertEqual(picked[0]["region"], "九龍城區")

    def test_tolerates_malformed_entries(self):
        valid = _item()
        cache = _cache({"總會": [None, "junk", 42, valid]})
        picked = sq.pick_today(cache, TODAY, _enrich([valid]))
        self.assertEqual(len(picked), 1)

    def test_incomplete_display_fields_are_excluded(self):
        complete = _item(title="齊料訓練班")
        missing_fee = _item(title="欠費用資料訓練班", url="https://example.hk/2.pdf",
                            pdf_url="https://example.hk/2.pdf")
        missing_date = _item(title="欠頒佈日期訓練班", date="", url="https://example.hk/3.pdf",
                             pdf_url="https://example.hk/3.pdf")
        cache = _cache({"筲箕灣區": [complete, missing_fee, missing_date]})
        enrich = _enrich(
            [complete, missing_fee, missing_date],
            {
                missing_fee["pdf_url"]: {"fee": ""},
                missing_date["pdf_url"]: READY_META,
            },
        )
        picked = sq.pick_today(cache, TODAY, enrich)
        self.assertEqual([item["title"] for item in picked], ["齊料訓練班"])

    def test_missing_category_is_excluded(self):
        item = _item(title="待分類通告")
        with mock.patch.object(sq, "classify_category", return_value=""):
            picked = sq.pick_today(_cache({"筲箕灣區": [item]}), TODAY, _enrich([item]))
        self.assertEqual(picked, [])

    def test_empty_title_and_missing_link_are_excluded(self):
        blank_title = _item(title="")
        no_link = _item(title="冇連結", url="", pdf_url="")
        cache = _cache({"筲箕灣區": [blank_title, no_link]})
        picked = sq.pick_today(cache, TODAY, _enrich([blank_title, no_link]))
        self.assertEqual(picked, [])


class TestStoryAttachmentAndCopy(unittest.TestCase):
    def test_qr_url_is_the_original_attachment_not_the_library(self):
        item = {"pdf_url": "https://source.example.hk/original.pdf",
                "url": "https://source.example.hk/notice-page"}
        self.assertEqual(sq.story_attachment_url(item), item["pdf_url"])
        self.assertEqual(sq.story_attachment_url({"pdf_url": " ", "url": item["url"]}), item["url"])
        self.assertEqual(sq.story_attachment_url({"pdf_url": "", "url": ""}), "")

    def test_each_category_has_eight_distinct_cantonese_lines(self):
        for category in ("training", "activity", "service", "competition"):
            with self.subTest(category=category):
                slogans = sq.STORY_SLOGANS[category]
                self.assertEqual(len(slogans), 8)
                self.assertEqual(len(set(slogans)), 8)
        self.assertEqual(sq.STORY_SLOGANS["training"][0], "解鎖新技能")
        self.assertEqual(sq.STORY_SLOGANS["activity"][0], "一齊玩，一齊記住")
        self.assertEqual(sq.STORY_SLOGANS["service"][0], "一齊做好事")
        self.assertEqual(sq.STORY_SLOGANS["competition"][0], "挑戰一下自己")

    def test_same_day_stories_take_turns_in_fixed_order(self):
        items = [{"title": f"訓練通告 {i}", "category": "training",
                  "captured_date": TODAY,
                  "url": f"https://source.example.hk/{i}.pdf"}
                 for i in range(10)]
        assigned = [item["slogan"] for item in sq.assign_story_slogans(items)]
        self.assertEqual(assigned, list(sq.STORY_SLOGANS["training"]) + ["解鎖新技能", "Skill Up!"])
        self.assertEqual(assigned, [item["slogan"] for item in sq.assign_story_slogans(items)])
        self.assertEqual(assigned, [sq.story_slogan(item) for item in items])

    def test_copy_stays_within_the_fixed_lines_without_extra_signup_claims(self):
        # 就算是徽章考章班又趕得上報名，都只會用返固定文案，唔會另外作報名宣傳。
        signup_badge = {"title": "幼童軍徽章考章班接受報名", "category": "training",
                        "deadline": "2026-10-05", "captured_date": TODAY,
                        "source_site": "測試區", "slogan": "",
                        "url": "https://source.example.hk/badge.pdf"}
        self.assertEqual(sq.story_slogan(signup_badge), "解鎖新技能")
        for category in ("training", "activity", "service", "competition"):
            for slot in range(8):
                self.assertIn(sq.story_slogan_for_slot(category, slot),
                              sq.STORY_SLOGANS[category])


class TestEnrichJoinAndCategory(unittest.TestCase):
    def test_join_by_pdf_url(self):
        item = _item()
        cache = _cache({"筲箕灣區": [item]})
        enrich = {"https://example.hk/notice/1.pdf": READY_META}
        picked = sq.pick_today(cache, TODAY, enrich)
        self.assertEqual(picked[0]["deadline"], "2026-10-05")
        self.assertEqual(picked[0]["audience"], "童軍")
        self.assertEqual(picked[0]["fee"], "HK$50")

    def test_tools_sources_never_enter_queue(self):
        item = _item(title="即日天氣", source_site="Scout System")
        cache = _cache({"Scout System": [item]})
        picked = sq.pick_today(cache, TODAY)
        self.assertEqual(picked, [])

    def test_category_from_enrich_categories_with_competition_subtype(self):
        item = _item(title="乜字都冇嘅標題")
        cache = _cache({"筲箕灣區": [item]})
        enrich = {item["pdf_url"]: {**READY_META, "categories": [{"id": "activity", "subtype": "competition"}]}}
        picked = sq.pick_today(cache, TODAY, enrich)
        self.assertEqual(picked[0]["category"], "competition")

    def test_category_title_fallback_keywords(self):
        cases = [("全港射擊錦標賽", "competition"), ("領袖訓練工作坊", "training"),
                 ("海灘清潔服務日", "service"), ("秋季遠足活動", "activity")]
        for title, want in cases:
            item = _item(title=title)
            cache = _cache({"筲箕灣區": [item]})
            got = sq.pick_today(cache, TODAY, _enrich([item]))[0]["category"]
            self.assertEqual(got, want, f"{title} 應該係 {want} 而係 {got}")

        unclassified = _item(title="一般通告")
        self.assertEqual(sq.pick_today(_cache({"筲箕灣區": [unclassified]}), TODAY,
                                       _enrich([unclassified])), [])


class TestBuildQueue(unittest.TestCase):
    def test_default_has_no_count_limit_and_reports_skipped_items(self):
        items = [_item(title=f"訓練通告{i:02d}", date="2026-10-01",
                       url=f"https://example.hk/{i}.pdf", pdf_url=f"https://example.hk/{i}.pdf")
                 for i in range(30)]
        items.append(_item(title="資料不齊訓練班", url="https://example.hk/incomplete.pdf",
                           pdf_url="https://example.hk/incomplete.pdf"))
        enrich = _enrich(items, {"https://example.hk/incomplete.pdf": {"fee": ""}})
        cache = _cache({"總會": items})
        queue = sq.build_queue(cache, TODAY, now=datetime(2026, 9, 21, 12, 0, tzinfo=sq.HKT), enrich=enrich)
        self.assertEqual(queue["count"], 30)
        self.assertEqual(len(queue["items"]), 30)
        self.assertEqual(queue["candidate_count"], 31)
        self.assertEqual(queue["skipped_incomplete"], 1)
        self.assertEqual(queue["today"], TODAY)
        self.assertEqual(queue["cache_last_updated"], "2026-09-21 05:00:10")
        self.assertIn("+0800", queue["generated_at"])

    def test_explicit_positive_limit_is_only_a_manual_override(self):
        items = [_item(title=f"訓練通告{i:02d}", url=f"https://example.hk/{i}.pdf",
                       pdf_url=f"https://example.hk/{i}.pdf") for i in range(30)]
        queue = sq.build_queue(_cache({"總會": items}), TODAY, 5, enrich=_enrich(items))
        self.assertEqual(queue["count"], 5)
        self.assertEqual(queue["candidate_count"], 30)

    def test_today_hkt_uses_hong_kong_timezone(self):
        # UTC 2026-09-20 23:30 = HKT 2026-09-21 07:30
        from datetime import timezone as tz
        utc_now = datetime(2026, 9, 20, 23, 30, tzinfo=tz.utc)
        self.assertEqual(sq.today_hkt(utc_now), TODAY)


class TestMainCli(unittest.TestCase):
    def test_writes_output_file(self):
        with tempfile.TemporaryDirectory() as td:
            cache_p = Path(td) / "cache.json"
            enrich_p = Path(td) / "enrich.json"
            out_p = Path(td) / "story-queue.json"
            item = _item()
            cache_p.write_text(json.dumps(_cache({"筲箕灣區": [item]}), ensure_ascii=False), encoding="utf-8")
            enrich_p.write_text(json.dumps(_enrich([item]), ensure_ascii=False), encoding="utf-8")
            rc = sq.main(["--cache", str(cache_p), "--out", str(out_p), "--today", TODAY])
            self.assertEqual(rc, 0)
            data = json.loads(out_p.read_text(encoding="utf-8"))
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["items"][0]["source_site"], "筲箕灣區")

    def test_missing_cache_returns_1(self):
        with tempfile.TemporaryDirectory() as td:
            rc = sq.main(["--cache", str(Path(td) / "nope.json"),
                          "--out", str(Path(td) / "o.json"), "--today", TODAY])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
