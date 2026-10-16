"""Offline regressions for the October 16 review (synthetic layout fixtures).

Eligibility excerpts are manually reviewed cases, not exact production PDF
line dumps. No external network, database, notification or publishing calls.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
import core
import enrich
import notify
import story_queue as sq
from fix_logbook_2026_10_16 import apply_review, AUDIENCE_FIXES, VERIFIED, PIKFUNG
from subscription_tagging import extract_subscription_metadata, extract_branch_ids

SOURCES = json.loads(Path("sources.json").read_text())["sources"]


def card(i, category="training", **extra):
    return dict(title=f"通告{i}", category=category,
                pdf_url=f"https://example.hk/{i}.pdf", **extra)


class StorySelection(unittest.TestCase):
    def test_four_categories_before_any_fill(self):
        rows = [card(i) for i in range(20)]
        rows += [card(20, "activity"), card(21, "service"), card(22, "competition")]
        got = sq.select_story_items(rows)
        self.assertEqual([x["category"] for x in got], ["training", "activity", "service", "competition", "training"])
        self.assertEqual(got[-1]["title"], "通告1")
        self.assertEqual(got, sq.select_story_items(rows))

    def test_missing_categories_filled_with_different_notices(self):
        rows = [card(i, "activity") for i in range(8)]
        self.assertEqual(sq.select_story_items(rows), rows[:5])
        self.assertEqual(sq.select_story_items(rows[:2]), rows[:2])
        self.assertEqual(sq.select_story_items([]), [])

    def test_all_limit_bypasses_hard_capped(self):
        rows = [card(i) for i in range(30)]
        for limit, expected in [(None, 5), (0, 5), (-1, 5), (999, 5), (3, 3), (1, 1)]:
            with self.subTest(limit=limit):
                self.assertEqual(len(sq.select_story_items(rows, limit)), expected)

    def test_dedup_urls_drive_aliases_mirrors_and_normalized_titles(self):
        rows = [
            dict(card(0), title="同 一通告", pdf_url="https://scout.org.hk/uploads/X.pdf"),
            dict(card(1), title="鏡像", pdf_url="https://www.scout.org.hk/uploads/x.pdf"),
            dict(card(2), title="同一通告", pdf_url="https://example.hk/copy.pdf"),
            dict(card(3), title="Drive通告", pdf_url="https://drive.google.com/file/d/AbC-123/view"),
            dict(card(4), title="Drive別名", pdf_url="https://drive.google.com/open?id=AbC-123"),
        ]
        self.assertEqual([x["title"] for x in sq.select_story_items(rows)], ["同 一通告", "Drive通告"])

    def test_archived_today_never_enters_story(self):
        item = dict(card(0), date="2026-10-16", captured_date="2026-10-16", suppress_notifications=True)
        self.assertEqual(sq.build_queue({"data": {"總會": [item]}}, "2026-10-16")["count"], 0)


class SourceExtraction(unittest.TestCase):
    def test_official_endpoint_not_shared_sidebar_pdf(self):
        cfg = SOURCES["沙田南區"]
        html = '''<body><aside><a href="/media/resources/shared.pdf">船鐘報時</a></aside>
        <table><tr><td>急救證書課程</td><td>2026-09-15</td><td><a href="/programme/view_notice/175"><img></a></td></tr>
        <tr><td>幼童軍歷史章訓練班</td><td>2026-09-13</td><td><a href="/programme/view_notice/174">下載</a></td></tr>
        <tr><td>急救證書課程</td><td>2026-09-15</td><td><a href="/programme/view_notice/175">下載</a></td></tr>
        <tr><td>外站</td><td><a href="https://evil.example/programme/view_notice/175">下載</a></td></tr></table></body>'''
        with patch.object(core, "fetch_page", side_effect=AssertionError("endpoint is the asset")):
            got = core.extract_assets_from_listing("沙田南區", BeautifulSoup(html, "html.parser"), cfg["url"], cfg, 50)
        self.assertEqual([x["title"] for x in got], ["急救證書課程", "幼童軍歷史章訓練班"])
        self.assertEqual([x["pdf_url"].rsplit("/", 1)[-1] for x in got], ["175", "174"])

    def test_endpoint_supported_only_on_official_host_and_shape(self):
        for url, expected in [
            ("https://www.stsd-scout.org/programme/view_notice/175", True),
            ("https://stsd-scout.org/programme/view_notice/155?x=1", True),
            ("https://evil.example/programme/view_notice/175", False),
            ("https://www.stsd-scout.org/programme/view_notice/nope", False),
        ]:
            with self.subTest(url=url):
                self.assertEqual(enrich.is_enrichable_url(url), expected)

    def test_endpoint_still_requires_pdf_magic_bytes(self):
        with patch.object(enrich, "download", return_value=b"<html>not a pdf</html>"):
            result = enrich.enrich_one("https://www.stsd-scout.org/programme/view_notice/175", use_ocr=False)
        self.assertEqual(result["_error"], "not_pdf")

    def test_embeds_keep_adjacent_titles(self):
        cfg = SOURCES["壁峰區"]
        html = '''<body><h2>訓練及活動通告</h2><p>第7屆原野烹飪訓練班—技能組</p>
        <iframe src="https://drive.google.com/file/d/first-file/preview"></iframe>
        <p>第7屆原野烹飪訓練班—教導組</p><iframe src="https://drive.google.com/file/d/second-file/preview"></iframe>
        <iframe src="https://evil.example/file/d/nope/preview"></iframe></body>'''
        got = core.extract_assets_from_listing("壁峰區", BeautifulSoup(html, "html.parser"), cfg["url"], cfg, 0)
        self.assertEqual([x["title"] for x in got], ["第7屆原野烹飪訓練班—技能組", "第7屆原野烹飪訓練班—教導組"])
        self.assertTrue(all(x["pdf_url"].endswith("/view") for x in got))

    def test_lazy_embed_can_use_following_specific_heading(self):
        cfg = SOURCES["壁峰區"]
        html = '<body><h2>訓練及活動通告</h2><iframe title="Embedded Files" data-src="https://drive.google.com/file/d/child-id/preview"></iframe><h1>小童軍親子活動—懷舊食物工作坊</h1></body>'
        got = core.extract_assets_from_listing("壁峰區", BeautifulSoup(html, "html.parser"), cfg["url"], cfg, 0)
        self.assertEqual(got[0]["title"], "小童軍親子活動—懷舊食物工作坊")

    def test_unchanged_parent_does_not_hide_changed_child(self):
        cfg = SOURCES["壁峰區"]
        main = core.FetchResult(cfg["url"], "<body>區會通訊</body>", "requests")
        fingerprint = core.compute_fingerprint(BeautifulSoup(main.html, "html.parser"), "body")
        def child(url, *_args, **_kwargs):
            return core.FetchResult(url, '<body><p>新童軍訓練班通告</p><iframe src="https://drive.google.com/file/d/changed-child/preview"></iframe></body>', "requests")
        with patch.object(core, "fetch_main_page", return_value=main), patch.object(core, "fetch_page", side_effect=child) as fetch:
            new, updates, _fp, skipped, _engine, error = core.process_source("壁峰區", cfg, {"壁峰區": fingerprint}, set(), "2026-10-16")
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(len(new), 1)
        self.assertFalse(skipped)
        self.assertFalse(error)

    def test_child_fetch_failure_preserves_fingerprint_and_reports_error(self):
        cfg = SOURCES["壁峰區"]
        main = core.FetchResult(cfg["url"], "<body>區會通訊</body>", "requests")
        with patch.object(core, "fetch_main_page", return_value=main), patch.object(core, "fetch_page", side_effect=RuntimeError("offline")):
            result = core.process_source("壁峰區", cfg, {"壁峰區": "old-fingerprint"}, set(), "2026-10-16")
        self.assertEqual(result[2], "old-fingerprint")
        self.assertTrue(result[-1])
        self.assertEqual(result[:2], ([], []))

    def test_no_official_notice_links_fails_closed(self):
        cfg = SOURCES["沙田南區"]
        main = core.FetchResult(cfg["url"], '<body><a href="/media/shared.pdf">船鐘報時</a></body>', "requests")
        with patch.object(core, "fetch_main_page", return_value=main):
            result = core.process_source("沙田南區", cfg, {}, set(), "2026-10-16")
        self.assertTrue(result[-1])
        self.assertFalse(result[0])


class AudienceExtraction(unittest.TestCase):
    def test_seven_reviewed_errors(self):
        for path, (text, expected) in AUDIENCE_FIXES.items():
            with self.subTest(path=path):
                self.assertEqual(enrich.extract_audience(text), expected)

    def test_preserve_real_parent_and_leader_participants(self):
        for text, expected in [
            ("參加資格：小童軍及其家長、領袖\n費用：免費", "小童軍、領袖、家長"),
            ("參加資格：每隊1名領袖及10至12名小童軍\n報名：交表", "小童軍、領袖"),
            ("參加資格：領袖及會務委員\n費用：港幣50元", "領袖、會務委員"),
            ("參加資格：幼童軍\n備註：領袖須簽署，家長同意書", "幼童軍"),
            ("參加資格：非童軍成員及公眾\n費用：免費", "公眾"),
        ]:
            with self.subTest(text=text):
                self.assertEqual(enrich.extract_audience(text), expected)

    def test_age_qualified_all_sections_not_expanded(self):
        for age in (12, 18):
            text = f"參加對象：年滿{age}歲之各支部成員及領袖\n費用：免費"
            audience = enrich.extract_audience(text)
            self.assertEqual(audience, f"各支部成員（年滿{age}歲）、領袖")
            self.assertEqual(extract_branch_ids("有蓋訊號台工作坊", audience), {"領袖"})

    def test_all_sections_with_real_parent_roles(self):
        audience = enrich.extract_audience("參加對象：本區各支部成員、領袖及家長\n費用：免費")
        self.assertEqual(audience, "各支部成員、領袖、家長")
        self.assertEqual(extract_branch_ids("設計比賽", audience), {"小童軍", "幼童軍", "童軍", "深資童軍", "樂行童軍", "領袖", "家長"})

    def test_prerequisite_course_does_not_create_youth_or_wood_subscriptions(self):
        evidence, _expected = next(iter(AUDIENCE_FIXES.values()))
        audience = enrich.extract_audience(evidence)
        meta = extract_subscription_metadata("第8屆森林舞蹈訓練班（領袖技能訓練班）", evidence, audience)
        self.assertNotIn("童軍", meta["branch_tags"])
        self.assertNotIn("training:童軍", meta["subscription_tags"])
        self.assertNotIn("training:領袖:木章", meta["subscription_tags"])
        self.assertFalse(any(x.startswith("course:wood-") for x in meta["subscription_tags"]))
        self.assertIn("領袖", meta["branch_tags"])

    def test_explicit_restricted_audience_blocks_course_scope_fallback(self):
        meta = extract_subscription_metadata("急救章訓練班", "", "各支部成員（年滿18歲）")
        self.assertEqual(meta["branch_tags"], [])


class BackfillSafety(unittest.TestCase):
    def setUp(self):
        self.cache = {"last_updated": "2026-10-16 05:00:07", "data": {}, "notices": [], "meta": {"total_notices": 0}, "_meta": {"last_run": {"has_errors": False}}}

    def test_verified_dates_and_idempotence_no_metadata_run_changes(self):
        before = copy.deepcopy(self.cache)
        cache, data, counts = apply_review(self.cache, {})
        self.assertEqual(self.cache, before)
        self.assertEqual(counts["backfilled"], 25)
        self.assertEqual(cache["last_updated"], before["last_updated"])
        self.assertEqual(cache["_meta"], before["_meta"])
        expected = {str(row[0]): row[1] for row in VERIFIED}
        self.assertEqual({x["pdf_url"].rsplit("/", 1)[-1]: x["captured_date"] for x in cache["data"]["沙田南區"]}, expected)
        for row in cache["notices"]:
            self.assertEqual(row["captured_date"], row["published_date"])
            self.assertTrue(row["suppress_notifications"])
        again, again_data, stats = apply_review(cache, data)
        self.assertEqual((again, again_data), (cache, data))
        self.assertEqual(stats, {"backfilled": 0, "audiences_corrected": 0})

    def test_existing_records_and_captured_dates_preserved(self):
        existing = dict(title="已收通告", pdf_url="https://www.stsd-scout.org/programme/view_notice/175", captured_date="2026-09-03")
        self.cache["data"]["沙田南區"] = [existing]
        self.cache["notices"] = [existing]
        cache, _data, counts = apply_review(self.cache, {})
        self.assertEqual(counts["backfilled"], 24)
        self.assertIn(existing, cache["data"]["沙田南區"])
        self.assertIn(existing, cache["notices"])

    def test_admissions_and_subsidy_not_fabricated_as_open_enrollment(self):
        _cache, data, _counts = apply_review(self.cache, {})
        for notice in (166, 167, 148):
            row = data[f"https://www.stsd-scout.org/programme/view_notice/{notice}"]
            self.assertEqual(row["fee"], "")
            self.assertEqual(row["audience"], "")
            if notice != 148:
                self.assertEqual(row["deadline"], "")
                self.assertEqual(row["categories"][0]["id"], "announcement")

    def test_no_new_push_no_catchup_or_story_even_for_today_publication(self):
        cache, data, _counts = apply_review(self.cache, {})
        self.assertEqual(notify.find_new_notices(cache, self.cache), [])
        self.assertEqual(notify.find_catchup_notices(cache, [], "2026-10-16"), [])
        self.assertEqual(sq.build_queue(cache, "2026-10-16", enrich=data)["count"], 0)

    def test_rebuild_retains_archive_suppression(self):
        cache, data, _counts = apply_review(self.cache, {})
        rebuilt = core.build_grouped_cache(cache["notices"], SOURCES, cache["last_updated"])
        self.assertTrue(all(x["suppress_notifications"] for x in rebuilt["notices"]))
        self.assertEqual(notify.find_new_notices(rebuilt, self.cache), [])
        self.assertEqual(sq.build_queue(rebuilt, "2026-10-16", enrich=data)["count"], 0)

    def test_targeted_review_recomputes_branch_and_subscription_tags_and_mirrors(self):
        evidence, expected = AUDIENCE_FIXES["/uploads/tc/circulars/26401/p109-26.pdf"]
        urls = [f"https://{host}/uploads/tc/circulars/26401/P109-26.pdf" for host in ("scout.org.hk", "www.scout.org.hk")]
        entries = {url: dict(title="寰宇童軍章(P109/2026)", source="總會", audience="童軍", deadline="", fee="") for url in urls}
        _cache, data, counts = apply_review(self.cache, entries)
        self.assertEqual(counts["audiences_corrected"], 2)
        for url in urls:
            self.assertEqual(data[url]["audience"], expected)
            self.assertEqual(set(data[url]["branch_tags"]), {"深資童軍", "樂行童軍"})


class RendererAndRefreshSafety(unittest.TestCase):
    def test_remote_refresh_retains_offline_backfills_and_suppression(self):
        local = [dict(source_site="壁峰區", pdf_url="https://drive.google.com/file/d/ABC/view",
                      captured_date="2026-08-15", published_date="2026-08-15",
                      backfilled_at="2026-10-16", suppress_notifications=True)]
        remote = [dict(source_site="壁峰區", pdf_url=local[0]["pdf_url"], captured_date="2026-10-17")]
        merged = core.merge_reviewed_backfills(remote, local)
        self.assertEqual(merged[0]["captured_date"], "2026-08-15")
        self.assertTrue(merged[0]["suppress_notifications"])
        self.assertEqual(core.merge_reviewed_backfills([], local), local)
        self.assertEqual(core.merge_reviewed_backfills(remote, [dict(source_site="其他", pdf_url="ordinary")]), remote)

    def test_renderer_caps_a_stale_thirty_item_queue_and_removes_duplicates(self):
        from tools import render_story_templates as renderer
        rows = [card(i) for i in range(30)]
        rows.insert(0, card(0))  # stale/manually generated duplicate
        rows += [card(31, "service"), card(32, "competition"), card(33, "activity")]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            queue = root / "queue.json"
            queue.write_text(json.dumps({"today": "2026-10-16", "items": rows}))
            with patch.object(renderer, "load_orgs", return_value={}), \
                 patch.object(renderer, "pick_daily_templates", side_effect=lambda items: [(x["category"], "test", lambda *args: None) for x in items]), \
                 patch.object(renderer.Image, "new"), patch.object(renderer.ImageDraw, "Draw"), \
                 patch.object(renderer, "badge_for", return_value=None):
                code = renderer.main(["--queue", str(queue), "--out", str(root), "--limit", "999"])
            self.assertEqual(code, 0)
            items = json.loads((root / "2026-10-16" / "manifest.json").read_text())["items"]
            self.assertEqual(len(items), 5)
            self.assertEqual(len({x["pdf_url"] for x in items}), 5)
            self.assertEqual({x["category"] for x in items}, set(sq.STORY_CATEGORY_ORDER))


if __name__ == "__main__":
    unittest.main()
