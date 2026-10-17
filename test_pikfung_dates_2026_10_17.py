"""Offline regressions for the 2026-10-17 壁峰區 re-dating pass.

Synthetic cache fixtures only: no network, no notification, no publishing.
"""
import copy
import json
import unittest
from pathlib import Path

import notify
import story_queue as sq
from fix_pikfung_dates_2026_10_17 import (
    CAPTURE_DATE,
    CORRECTIONS,
    REVIEW_DATE,
    SINK,
    SINK_DATE,
    SOURCE,
    apply_review,
    drive_url,
)

SUNK_IDS = [drive_id for drive_id, date, _label, _evidence in CORRECTIONS if date == SINK]
DATED_IDS = [(drive_id, date, evidence) for drive_id, date, _label, evidence in CORRECTIONS
             if date not in (SINK, "")]


def row(drive_id, date=CAPTURE_DATE, **extra):
    url = drive_url(drive_id)
    return dict(
        title=f"通告{drive_id[:6]}",
        url=url,
        pdf_url=url,
        date=date,
        captured_date=date,
        source_site=SOURCE,
        region="新界東地域",
        **extra,
    )


def notice(drive_id, date=CAPTURE_DATE, **extra):
    return dict(
        source_site=SOURCE,
        region="新界東地域",
        pdf_url=drive_url(drive_id),
        title=f"通告{drive_id[:6]}",
        captured_date=date,
        **extra,
    )


def fixture():
    """One sunk row, one dated row, one already-backfilled row, one old row,
    plus one row from the same batch that the review never listed."""
    cache = {
        "last_updated": "2026-10-17 05:00:11",
        "meta": {"version": "5.3.0", "total_notices": 4},
        "data": {SOURCE: [
            row(SUNK_IDS[0]),
            row(DATED_IDS[0][0]),
            row(SUNK_IDS[1], date="2026-08-15", backfilled_at="2026-10-16",
                suppress_notifications=True, published_date="2026-08-15"),
            row("old-one", date="2026-05-23"),
            row("not-listed"),
        ]},
        "notices": [
            notice(SUNK_IDS[0]),
            notice(DATED_IDS[0][0]),
            notice("old-one", date="2026-05-23"),
        ],
    }
    enrich = {drive_url(drive_id): dict(
        source=SOURCE, title=f"通告{drive_id[:6]}", deadline="", audience="",
        fee="", method="", error="not_pdf",
    ) for drive_id in (SUNK_IDS[0], DATED_IDS[0][0])}
    return cache, enrich


def by_id(rows):
    return {str(x.get("pdf_url", "")).split("/d/")[-1].split("/")[0]: x for x in rows}


class ReDating(unittest.TestCase):
    def test_2025_documents_sink_below_every_window(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, counts = apply_review(cache, enrich)
        rows = by_id(new_cache["data"][SOURCE])
        self.assertEqual(counts["re_dated"], 2)   # sunk + dated rows in the fixture
        for drive_id in SUNK_IDS[:1]:
            self.assertEqual(rows[drive_id]["date"], SINK_DATE)
            self.assertEqual(rows[drive_id]["captured_date"], SINK_DATE)
            self.assertEqual(rows[drive_id]["published_date"], SINK_DATE)
            self.assertEqual(rows[drive_id]["backfilled_at"], REVIEW_DATE)
            self.assertTrue(rows[drive_id]["suppress_notifications"])

    def test_verified_issue_date_replaces_the_capture_date(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, _counts = apply_review(cache, enrich)
        rows = by_id(new_cache["data"][SOURCE])
        for drive_id, date, _evidence in DATED_IDS[:1]:
            self.assertEqual(rows[drive_id]["date"], date)
            self.assertEqual(rows[drive_id]["captured_date"], date)
            self.assertEqual(rows[drive_id]["published_date"], date)
            self.assertEqual(rows[drive_id]["backfilled_at"], REVIEW_DATE)
            self.assertTrue(rows[drive_id]["suppress_notifications"])

    def test_rows_outside_the_review_are_never_touched(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, _counts = apply_review(cache, enrich)
        rows = by_id(new_cache["data"][SOURCE])
        # 上一輪（2026-10-16）已經補登過嘅：唔會被改寫
        self.assertEqual(rows[SUNK_IDS[1]]["captured_date"], "2026-08-15")
        self.assertEqual(rows[SUNK_IDS[1]]["backfilled_at"], "2026-10-16")
        # 舊通告：原封不動
        self.assertEqual(rows["old-one"]["captured_date"], "2026-05-23")
        # 同一批但對照表冇列嘅：照留今日，等人手核實
        self.assertEqual(rows["not-listed"]["captured_date"], CAPTURE_DATE)
        self.assertNotIn("backfilled_at", rows["not-listed"])

    def test_notices_mirror_grouped_rows_and_stay_sorted(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, _counts = apply_review(cache, enrich)
        for drive_id, expected in ((SUNK_IDS[0], SINK_DATE), (DATED_IDS[0][0], DATED_IDS[0][1])):
            mirrored = [x for x in new_cache["notices"] if x["pdf_url"] == drive_url(drive_id)]
            self.assertEqual(len(mirrored), 1)
            self.assertEqual(mirrored[0]["captured_date"], expected)
            self.assertTrue(mirrored[0]["suppress_notifications"])
            self.assertEqual(mirrored[0]["backfilled_at"], REVIEW_DATE)
        dates = [x["captured_date"] for x in new_cache["notices"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(new_cache["meta"]["total_notices"], len(new_cache["notices"]))

    def test_enrich_records_why_the_date_changed(self):
        cache, enrich = fixture()
        _new_cache, new_enrich, _counts = apply_review(cache, enrich)
        sunk = new_enrich[drive_url(SUNK_IDS[0])]
        self.assertEqual(sunk["reviewed_at"], REVIEW_DATE)
        self.assertEqual(sunk["method"], "manual-reviewed-original")
        self.assertIn(SINK_DATE, sunk["date_evidence"])
        dated = new_enrich[drive_url(DATED_IDS[0][0])]
        self.assertEqual(dated["date_evidence"], DATED_IDS[0][2])
        self.assertEqual(dated["evidence_url"], drive_url(DATED_IDS[0][0]))

    def test_second_run_is_a_no_op(self):
        cache, enrich = fixture()
        once, once_enrich, _counts = apply_review(cache, enrich)
        twice, twice_enrich, counts = apply_review(once, once_enrich)
        self.assertEqual(counts["re_dated"], 0)
        self.assertEqual(twice, once)
        self.assertEqual(twice_enrich, once_enrich)


class NoNotificationNoStory(unittest.TestCase):
    def setUp(self):
        self.cache, self.enrich = fixture()
        self.updated, self.updated_enrich, _counts = apply_review(self.cache, self.enrich)

    def test_no_push_notification_for_re_dated_rows(self):
        empty = {"data": {}, "notices": []}
        # 未核實（對照表冇列）同舊通告照舊可以出通知；搬咗位嗰啲一定唔出。
        pushed = [x.get("pdf_url") for x in notify.find_new_notices(self.updated, empty)]
        caught = [x.get("pdf_url") for x in notify.find_catchup_notices(self.updated, [], CAPTURE_DATE)]
        for url in (pushed, caught):
            self.assertNotIn(drive_url(SUNK_IDS[0]), url)
            self.assertNotIn(drive_url(DATED_IDS[0][0]), url)

    def test_re_dated_rows_never_enter_the_story_queue(self):
        queue = sq.build_queue(self.updated, CAPTURE_DATE, enrich=self.updated_enrich)
        queued = {str(x.get("pdf_url", "")) for x in queue.get("items", [])}
        self.assertNotIn(drive_url(SUNK_IDS[0]), queued)
        self.assertNotIn(drive_url(DATED_IDS[0][0]), queued)


class ProductionShape(unittest.TestCase):
    """The committed cache must keep the review flags the merge logic looks for."""

    def setUp(self):
        self.cache = json.loads(Path("cache.json").read_text(encoding="utf-8"))

    def test_every_listed_notice_carries_both_flags(self):
        touched = [x for x in self.cache["data"][SOURCE] if x.get("backfilled_at") == REVIEW_DATE]
        self.assertEqual(len(touched), len(CORRECTIONS))
        for item in self.cache["notices"]:
            if item.get("backfilled_at") == REVIEW_DATE:
                self.assertTrue(item["suppress_notifications"])

    def test_pikfung_no_longer_owns_today(self):
        today = [x["title"] for x in self.cache["data"][SOURCE]
                 if str(x.get("captured_date"))[:10] == CAPTURE_DATE]
        self.assertEqual(today, [])

    def test_grouped_rows_and_notices_agree(self):
        grouped = {x["pdf_url"]: x["captured_date"] for x in self.cache["data"][SOURCE]}
        for item in self.cache["notices"]:
            if item.get("source_site") == SOURCE:
                self.assertEqual(grouped.get(item["pdf_url"]), item["captured_date"])


if __name__ == "__main__":
    unittest.main()
