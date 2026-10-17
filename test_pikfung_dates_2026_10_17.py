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

SUNK_IDS = [drive_id for drive_id, date, _note in CORRECTIONS if date == SINK]
PENDING_IDS = [drive_id for drive_id, date, _note in CORRECTIONS if date == ""]


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
    """One sunk row, one pending row, one already-backfilled row, one old row."""
    cache = {
        "last_updated": "2026-10-17 05:00:11",
        "meta": {"version": "5.3.0", "total_notices": 4},
        "data": {SOURCE: [
            row(SUNK_IDS[0]),
            row(PENDING_IDS[0]),
            row(SUNK_IDS[1], date="2026-08-15", backfilled_at="2026-10-16",
                suppress_notifications=True, published_date="2026-08-15"),
            row("old-one", date="2026-05-23"),
        ]},
        "notices": [
            notice(SUNK_IDS[0]),
            notice(PENDING_IDS[0]),
            notice("old-one", date="2026-05-23"),
        ],
    }
    enrich = {drive_url(drive_id): dict(
        source=SOURCE, title=f"通告{drive_id[:6]}", deadline="", audience="",
        fee="", method="", error="not_pdf",
    ) for drive_id in (SUNK_IDS[0], PENDING_IDS[0])}
    return cache, enrich


def by_id(rows):
    return {str(x.get("pdf_url", "")).split("/d/")[-1].split("/")[0]: x for x in rows}


class ReDating(unittest.TestCase):
    def test_2025_documents_sink_below_every_window(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, counts = apply_review(cache, enrich)
        rows = by_id(new_cache["data"][SOURCE])
        self.assertEqual(counts["re_dated"], 1)
        for drive_id in SUNK_IDS[:1]:
            self.assertEqual(rows[drive_id]["date"], SINK_DATE)
            self.assertEqual(rows[drive_id]["captured_date"], SINK_DATE)
            self.assertEqual(rows[drive_id]["published_date"], SINK_DATE)
            self.assertEqual(rows[drive_id]["backfilled_at"], REVIEW_DATE)
            self.assertTrue(rows[drive_id]["suppress_notifications"])

    def test_pending_rows_keep_the_capture_date(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, counts = apply_review(cache, enrich)
        self.assertTrue(counts["pending"])
        rows = by_id(new_cache["data"][SOURCE])
        self.assertEqual(rows[PENDING_IDS[0]]["captured_date"], CAPTURE_DATE)
        self.assertNotIn("backfilled_at", rows[PENDING_IDS[0]])

    def test_existing_backfills_and_older_rows_are_never_touched(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, _counts = apply_review(cache, enrich)
        rows = by_id(new_cache["data"][SOURCE])
        self.assertEqual(rows[SUNK_IDS[1]]["captured_date"], "2026-08-15")
        self.assertEqual(rows[SUNK_IDS[1]]["backfilled_at"], "2026-10-16")
        self.assertEqual(rows["old-one"]["captured_date"], "2026-05-23")

    def test_notices_mirror_grouped_rows_and_stay_sorted(self):
        cache, enrich = fixture()
        new_cache, _new_enrich, _counts = apply_review(cache, enrich)
        mirrored = [x for x in new_cache["notices"] if x["pdf_url"] == drive_url(SUNK_IDS[0])]
        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored[0]["captured_date"], SINK_DATE)
        self.assertTrue(mirrored[0]["suppress_notifications"])
        self.assertEqual(mirrored[0]["backfilled_at"], REVIEW_DATE)
        dates = [x["captured_date"] for x in new_cache["notices"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(new_cache["meta"]["total_notices"], len(new_cache["notices"]))

    def test_enrich_records_why_the_date_changed(self):
        cache, enrich = fixture()
        _new_cache, new_enrich, _counts = apply_review(cache, enrich)
        entry = new_enrich[drive_url(SUNK_IDS[0])]
        self.assertEqual(entry["reviewed_at"], REVIEW_DATE)
        self.assertEqual(entry["method"], "manual-reviewed-original")
        self.assertIn(SINK_DATE, entry["date_evidence"])
        self.assertEqual(new_enrich[drive_url(PENDING_IDS[0])], enrich[drive_url(PENDING_IDS[0])])

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

    def test_no_push_notification_for_sunk_rows(self):
        empty = {"data": {}, "notices": []}
        # 未核實（pending）同舊通告照舊可以出通知；沉底嗰啲一定唔出。
        pushed = [x.get("pdf_url") for x in notify.find_new_notices(self.updated, empty)]
        caught = [x.get("pdf_url") for x in notify.find_catchup_notices(self.updated, [], CAPTURE_DATE)]
        for url in (pushed, caught):
            self.assertNotIn(drive_url(SUNK_IDS[0]), url)

    def test_sunk_rows_never_enter_the_story_queue(self):
        queue = sq.build_queue(self.updated, CAPTURE_DATE, enrich=self.updated_enrich)
        queued = {str(x.get("pdf_url", "")) for x in queue.get("items", [])}
        for drive_id in SUNK_IDS[:1]:
            self.assertNotIn(drive_url(drive_id), queued)


class ProductionShape(unittest.TestCase):
    """The committed cache must keep the review flags the merge logic looks for."""

    def test_committed_backfills_carry_both_flags(self):
        cache = json.loads(Path("cache.json").read_text(encoding="utf-8"))
        touched = [x for x in cache["data"][SOURCE] if x.get("backfilled_at") == REVIEW_DATE]
        self.assertEqual(len(touched), len(SUNK_IDS))
        for item in cache["notices"]:
            if item.get("backfilled_at") == REVIEW_DATE:
                self.assertTrue(item["suppress_notifications"])


if __name__ == "__main__":
    unittest.main()
