#!/usr/bin/env python3
"""story_queue.py 單元測試 — 無網絡、無第三方依賴。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import story_queue as sq  # noqa: E402

TODAY = "2026-09-21"


def _cache(items_by_section: dict, last_updated: str = "2026-09-21 05:00:10") -> dict:
    return {"last_updated": last_updated, "data": items_by_section}


def _item(**kw) -> dict:
    base = {
        "title": "測試通告",
        "url": "https://example.hk/notice/1.pdf",
        "pdf_url": "https://example.hk/notice/1.pdf",
        "region": "",
        "source_site": "筲箕灣區",
        "date": "2026-10-01",
        "captured_date": TODAY,
    }
    base.update(kw)
    return base


class TestPickToday(unittest.TestCase):
    def test_only_todays_captured_date_is_picked(self):
        cache = _cache({"筲箕灣區": [
            _item(title="今日新"),
            _item(title="昨日嘅", captured_date="2026-09-20"),
        ]})
        picked = sq.pick_today(cache, TODAY)
        self.assertEqual([x["title"] for x in picked], ["今日新"])

    def test_sorted_by_deadline_then_missing_date_last(self):
        cache = _cache({"港島西": [
            _item(title="冇日期", date=""),
            _item(title="遲截止", date="2026-12-31"),
            _item(title="早截止", date="2026-09-30"),
        ]})
        picked = sq.pick_today(cache, TODAY)
        self.assertEqual([x["title"] for x in picked], ["早截止", "遲截止", "冇日期"])

    def test_region_falls_back_to_section_name(self):
        cache = _cache({"九龍城區": [_item(region="")]})
        picked = sq.pick_today(cache, TODAY)
        self.assertEqual(picked[0]["region"], "九龍城區")

    def test_tolerates_malformed_entries(self):
        cache = _cache({"總會": [None, "junk", 42, _item()]})
        picked = sq.pick_today(cache, TODAY)
        self.assertEqual(len(picked), 1)


class TestEnrichJoinAndCategory(unittest.TestCase):
    def test_join_by_pdf_url(self):
        cache = _cache({"筲箕灣區": [_item()]})
        enrich = {"https://example.hk/notice/1.pdf":
                  {"deadline": "2026-10-05", "audience": "童軍", "fee": "HK$50"}}
        picked = sq.pick_today(cache, TODAY, enrich)
        self.assertEqual(picked[0]["deadline"], "2026-10-05")
        self.assertEqual(picked[0]["audience"], "童軍")
        self.assertEqual(picked[0]["fee"], "HK$50")

    def test_tools_sources_never_enter_queue(self):
        cache = _cache({"Scout System": [_item(title="即日天氣", source_site="Scout System")]})
        picked = sq.pick_today(cache, TODAY)
        self.assertEqual(picked, [])

    def test_category_from_enrich_categories_with_competition_subtype(self):
        cache = _cache({"筲箕灣區": [_item(title="乜字都冇嘅標題")]})
        enrich = {"https://example.hk/notice/1.pdf":
                  {"categories": [{"id": "activity", "subtype": "competition"}]}}
        picked = sq.pick_today(cache, TODAY, enrich)
        self.assertEqual(picked[0]["category"], "competition")

    def test_category_title_fallback_keywords(self):
        cases = [("全港射擊錦標賽", "competition"), ("領袖訓練工作坊", "training"),
                 ("海灘清潔服務日", "service"), ("秋季遠足活動", "activity"),
                 ("一般通告", "other")]
        for title, want in cases:
            cache = _cache({"筲箕灣區": [_item(title=title)]})
            got = sq.pick_today(cache, TODAY)[0]["category"]
            self.assertEqual(got, want, f"{title} 應該係 {want} 而係 {got}")


class TestBuildQueue(unittest.TestCase):
    def test_limit_and_metadata(self):
        cache = _cache({"總會": [_item(title=f"通告{i:02d}", date="") for i in range(30)]})
        queue = sq.build_queue(cache, TODAY, 20, now=datetime(2026, 9, 21, 12, 0, tzinfo=sq.HKT))
        self.assertEqual(queue["count"], 20)
        self.assertEqual(len(queue["items"]), 20)
        self.assertEqual(queue["today"], TODAY)
        self.assertEqual(queue["cache_last_updated"], "2026-09-21 05:00:10")
        self.assertIn("+0800", queue["generated_at"])

    def test_today_hkt_uses_hong_kong_timezone(self):
        # UTC 2026-09-20 23:30 = HKT 2026-09-21 07:30
        from datetime import timezone as tz
        utc_now = datetime(2026, 9, 20, 23, 30, tzinfo=tz.utc)
        self.assertEqual(sq.today_hkt(utc_now), TODAY)


class TestMainCli(unittest.TestCase):
    def test_writes_output_file(self):
        with tempfile.TemporaryDirectory() as td:
            cache_p = Path(td) / "cache.json"
            out_p = Path(td) / "story-queue.json"
            cache_p.write_text(json.dumps(_cache({"筲箕灣區": [_item()]}), ensure_ascii=False),
                               encoding="utf-8")
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
