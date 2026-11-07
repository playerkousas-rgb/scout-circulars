#!/usr/bin/env python3
"""2026-11-07 用戶規則：上架日＝「公開」日，唔係「入庫」日。

三種狀態（用戶原話）：
  * 今天公開             = 今天上架
  * 今天入庫但沒公開     = 未上架
  * 之前入庫，但今天公開 = 今天上架

個案：SCOUT APP STORE「遊戲學習」created_at 2026-11-06、2026-11-07 先公開，
舊規則用 created_at 把它寫成 11-06，所以「今天更新/發布」只見到「緊急救援」。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tools.scrape_appstore import FIRST_PUBLIC_OVERRIDES, hkt_today  # noqa: E402

BASELINE = "2026-09-24"
SOURCE = "Scout System"
GAME_URL = "https://app.astra-ai.co/lab"
RESCUE_URL = "https://apps.apple.com/hk/app/hksos/id1671480993?l=en-GB"


def app(name, url, created_at, visible=True):
    return {
        "name": name,
        "url": url,
        "description": f"{name} 描述",
        "note": None,
        "icon": "",
        "icon_source": "favicon",
        "category": "工具",
        "page": "apps",
        "tags": ["童軍", "小工具"],
        "visible": visible,
        "sort_order": 0,
        "created_at": created_at,
    }


def catalog_entry(a, date):
    return {
        "title": a["name"], "url": a["url"], "pdf_url": a["url"],
        "date": date, "captured_date": date,
        "source_site": SOURCE, "region": SOURCE,
        "source_url": "https://scoutappstore.vercel.app/",
        "tags": list(a.get("tags") or []), "description": a.get("description") or "",
        "icon": "", "store_category": a.get("category") or "",
        "store_page": a.get("page") or "",
    }


def make_cache(tools):
    notices = [{
        "source_site": SOURCE, "region": SOURCE,
        "pdf_url": t["url"], "title": t["title"],
        "captured_date": t["captured_date"], "tags": list(t.get("tags") or []),
    } for t in tools]
    return {
        "last_updated": f"{BASELINE} 00:00:00",
        "meta": {"version": "5.3.0", "total_notices": len(notices)},
        "data": {SOURCE: tools},
        "notices": notices,
        "_meta": {"appstore": {
            "first_sync": BASELINE, "last_sync": BASELINE,
            "known_dates": {t["url"]: t["captured_date"] for t in tools},
        }},
    }


def run_sync(cache, apps, enrich=None, today=None):
    """喺 temp dir 行一次 scrape_appstore.py，回傳 (cache, enrich, stdout)。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "cache.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        (p / "enrich.json").write_text(json.dumps(enrich or {}, ensure_ascii=False), encoding="utf-8")
        (p / "apps.json").write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "tools" / "scrape_appstore.py"),
               "--apps-json", str(p / "apps.json"),
               "--cache", str(p / "cache.json"),
               "--enrich", str(p / "enrich.json")]
        if today:
            cmd += ["--today", today]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=str(ROOT))
        return (json.loads((p / "cache.json").read_text(encoding="utf-8")),
                json.loads((p / "enrich.json").read_text(encoding="utf-8")),
                res.stdout)


def items(cache):
    return {i["url"]: i for i in cache["data"][SOURCE]}


class PublicationRuleTests(unittest.TestCase):
    def test_three_states(self):
        today = hkt_today()
        old = app("舊工具", "https://old.test/", "2026-09-03T10:00:00+00:00")
        created_today = app("今日入庫兼公開", "https://fresh.test/", f"{today}T01:00:00+00:00")
        old_created_public_today = app("之前入庫今日公開", "https://oldcreated.test/", "2026-11-06T02:32:00+00:00")
        hidden_today = app("未公開工具", "https://hidden.test/", f"{today}T02:00:00+00:00",
                           visible=False)

        cache = make_cache([catalog_entry(old, BASELINE)])
        updated, enrich, out = run_sync(
            cache, [old, created_today, old_created_public_today, hidden_today])

        self.assertIn("今日新上架 2 個", out)
        self.assertIn("未上架 1 個", out)
        got = items(updated)
        # 1) 一直喺架上 → 保留首次公開日
        self.assertEqual(got["https://old.test/"]["captured_date"], BASELINE)
        # 2) 今天公開（今日入庫）= 今天上架
        self.assertEqual(got["https://fresh.test/"]["captured_date"], today)
        # 3) 之前入庫，但今天公開 = 今天上架（created_at 舊過今日都唔可以壓住）
        self.assertEqual(got["https://oldcreated.test/"]["captured_date"], today)
        # 4) 今天入庫但沒公開 = 未上架：唔入 catalog、唔計今日
        self.assertNotIn("https://hidden.test/", got)
        self.assertNotIn("https://hidden.test/", enrich)

        sync = updated["_meta"]["appstore"]
        self.assertEqual(sync["first_public"]["https://fresh.test"], today)
        self.assertEqual(sync["first_public"]["https://oldcreated.test"], today)
        self.assertEqual(sync["pending"]["https://hidden.test"]["state"], "未上架")
        self.assertEqual(sync["pending"]["https://hidden.test"]["created_at"], today)
        self.assertEqual(len([n for n in updated["notices"]
                              if n.get("source_site") == SOURCE]), 3)

    def test_hidden_app_that_later_becomes_public_is_today(self):
        """未上架 → 公開：由 pending 轉去今日上架。"""
        today = hkt_today()
        hidden = app("待公開", "https://later.test/", "2026-11-06T02:32:00+00:00", visible=False)
        cache = make_cache([catalog_entry(
            app("舊工具", "https://old.test/", "2026-09-03T10:00:00+00:00"), BASELINE)])

        keep = app("舊工具", "https://old.test/", "2026-09-03T10:00:00+00:00")
        step1, _e1, out1 = run_sync(cache, [keep, hidden])
        self.assertIn("未上架 1 個", out1)
        self.assertIn("https://later.test", step1["_meta"]["appstore"]["pending"])
        self.assertNotIn("https://later.test/", items(step1))

        visible = dict(hidden, visible=True)
        step2, _e2, out2 = run_sync(step1, [keep, visible])
        self.assertIn("今日新上架 1 個", out2)
        self.assertEqual(items(step2)["https://later.test/"]["captured_date"], today)
        self.assertNotIn("https://later.test", step2["_meta"]["appstore"]["pending"])

    def test_override_repairs_2026_11_07_misdated_run(self):
        """11-07 嗰次 RUN 把「遊戲學習」寫咗做 11-06（抄 created_at），要修正。"""
        game = app("遊戲學習", GAME_URL, "2026-11-06T02:32:00+00:00")
        rescue = app("緊急救援", RESCUE_URL, "2026-11-07T05:19:04+00:00")
        cache = make_cache([catalog_entry(game, "2026-11-06"),
                            catalog_entry(rescue, "2026-11-07")])
        enrich = {
            GAME_URL: {"source": SOURCE, "title": "遊戲學習",
                       "captured_date": "2026-11-06"},
        }
        self.assertEqual(FIRST_PUBLIC_OVERRIDES[GAME_URL], "2026-11-07")

        updated, updated_enrich, out = run_sync(cache, [game, rescue], enrich,
                                               today="2026-11-07")
        got = items(updated)
        self.assertEqual(got[GAME_URL]["date"], "2026-11-07")
        self.assertEqual(got[GAME_URL]["captured_date"], "2026-11-07")
        self.assertEqual(updated_enrich[GAME_URL]["captured_date"], "2026-11-07")
        notices = {n["pdf_url"]: n for n in updated["notices"]}
        self.assertEqual(notices[GAME_URL]["captured_date"], "2026-11-07")
        sync = updated["_meta"]["appstore"]
        self.assertEqual(sync["known_dates"][GAME_URL], "2026-11-07")
        self.assertEqual(sync["first_public"][GAME_URL.rstrip("/")], "2026-11-07")
        # 緊急救援本身已係今日公開，唔受影響
        self.assertEqual(got[RESCUE_URL]["captured_date"], "2026-11-07")
        self.assertIn("+ 遊戲學習", out)
        self.assertIn("今日新上架 2 個", out)

    def test_repaired_date_is_stable_on_later_days(self):
        """修正只做一次：之後每日 keep 返 2026-11-07，唔會再彈做今日。"""
        game = app("遊戲學習", GAME_URL, "2026-11-06T02:32:00+00:00")
        keep = app("舊工具", "https://old.test/", "2026-09-03T10:00:00+00:00")
        cache = make_cache([catalog_entry(game, "2026-11-06"),
                            catalog_entry(keep, BASELINE)])
        fixed, e1, _ = run_sync(cache, [game, keep], today="2026-11-07")
        later, e2, out = run_sync(fixed, [game, keep], e1, today="2026-11-20")
        self.assertEqual(items(later)[GAME_URL]["captured_date"], "2026-11-07")
        self.assertEqual(later["_meta"]["appstore"]["first_public"][GAME_URL], "2026-11-07")
        self.assertIn("今日新上架 0 個", out)

    def test_relist_after_repair_does_not_reuse_old_override_date(self):
        """下架再上架優先過一次性修正：會用重新公開嗰日，唔會被 11-07 蓋返。"""
        game = app("遊戲學習", GAME_URL, "2026-11-06T02:32:00+00:00")
        keep = app("舊工具", "https://old.test/", "2026-09-03T10:00:00+00:00")
        cache = make_cache([catalog_entry(game, "2026-11-06"),
                            catalog_entry(keep, BASELINE)])
        cache["_meta"]["appstore"]["delisted"] = {GAME_URL: "2026-11-08"}
        updated, _e, out = run_sync(cache, [game, keep], today="2026-11-20")
        self.assertEqual(items(updated)[GAME_URL]["captured_date"], "2026-11-20")
        self.assertEqual(updated["_meta"]["appstore"]["first_public"][GAME_URL], "2026-11-20")
        self.assertNotIn(GAME_URL, updated["_meta"]["appstore"]["delisted"])
        self.assertIn("今日新上架 1 個", out)

    def test_rule_is_idempotent_within_the_same_day(self):
        today = hkt_today()
        old = app("舊工具", "https://old.test/", "2026-09-03T10:00:00+00:00")
        fresh = app("今日公開", "https://fresh2.test/", "2026-11-06T02:32:00+00:00")
        cache = make_cache([catalog_entry(old, BASELINE)])
        first, e1, _ = run_sync(cache, [old, fresh])
        second, e2, _ = run_sync(first, [old, fresh], e1)
        self.assertEqual(items(first)["https://fresh2.test/"]["captured_date"], today)
        self.assertEqual(items(second)["https://fresh2.test/"]["captured_date"], today)
        self.assertEqual(first["_meta"]["appstore"]["first_public"],
                         second["_meta"]["appstore"]["first_public"])
        self.assertEqual(first["_meta"]["appstore"]["pending"],
                         second["_meta"]["appstore"]["pending"])
        self.assertEqual(e1["https://fresh2.test/"]["captured_date"],
                         e2["https://fresh2.test/"]["captured_date"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
