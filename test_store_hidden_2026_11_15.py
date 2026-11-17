#!/usr/bin/env python3
"""2026-11-15 用戶確認嘅新規則：APP STORE 收埋 ≠ 刪除。

曾經公開上架過嘅 app，轉做 visible=false 亦要：
  * cache.json 繼續保留 Scout System 條目＋原首次公開日（唔會變今天）；
  * enrich.json 繼續保留條目、notices 繼續保留；
  * 由 tools/scrape_appstore.py 寫入 store-hidden.json —— 前端顯示層收埋；
  * 再放出（visible=true）之後：store-hidden.json 放開嗰項，日期維持原首次公開日。

從未公開過而 visible=false：仍然係「未上架」，唔入 catalog、唔寫入 store-hidden.json。
紀錄喺 store 完全消失（被刪／換 URL）：維持舊規則（delisted；再出現＝今日重新上架）。
store 回應疑似唔完整（一次過大量消失）：保留舊資料、store-hidden.json 維持原狀。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASELINE = "2026-09-24"
SOURCE = "Scout System"
OLD_URL = "https://old-tool.test/"
HIDE_URL = "https://hide-me.test/"
ABSENT_URL = "https://absent.test/"


def app(name, url, created_at, visible=True, sort_order=0):
    return {
        "name": name,
        "url": url,
        "description": f"{name} 描述",
        "note": None,
        "icon": "",
        "icon_source": "favicon",
        "category": "工具",
        "page": "apps",
        "tags": ["童軍"],
        "visible": visible,
        "sort_order": sort_order,
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
        "meta": {"version": "5.11", "total_notices": len(notices)},
        "data": {SOURCE: tools},
        "notices": notices,
        "_meta": {"appstore": {
            "first_sync": BASELINE, "last_sync": BASELINE,
            "known_dates": {t["url"]: t["captured_date"] for t in tools},
        }},
    }


def run_sync(cache, apps, enrich=None, today=None, hidden_seed=None):
    """喺 temp dir 行一次同步，回傳 (cache, enrich, stdout, hidden_list)。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        (p / "cache.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        (p / "enrich.json").write_text(json.dumps(enrich or {}, ensure_ascii=False), encoding="utf-8")
        (p / "apps.json").write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")
        if hidden_seed is not None:
            (p / "store-hidden.json").write_text(
                json.dumps({"hidden": list(hidden_seed)}, ensure_ascii=False) + "\n",
                encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "tools" / "scrape_appstore.py"),
               "--apps-json", str(p / "apps.json"),
               "--cache", str(p / "cache.json"),
               "--enrich", str(p / "enrich.json"),
               "--hidden", str(p / "store-hidden.json")]
        if today:
            cmd += ["--today", today]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=str(ROOT))
        hidden = json.loads((p / "store-hidden.json").read_text(encoding="utf-8"))["hidden"]
        return (json.loads((p / "cache.json").read_text(encoding="utf-8")),
                json.loads((p / "enrich.json").read_text(encoding="utf-8")),
                res.stdout,
                hidden)


def items(cache):
    return {i["url"].rstrip("/"): i for i in cache["data"][SOURCE]}


def norm(u):
    return (u or "").strip().rstrip("/")


class HideShowTests(unittest.TestCase):
    def test_hidden_published_app_keeps_record_date_and_is_listed(self):
        from tools.scrape_appstore import hkt_today  # noqa: F401
        old = app("舊工具", OLD_URL, "2026-09-03T10:00:00+00:00")
        victim = app("將被收埋嘅工具", HIDE_URL, "2026-09-05T10:00:00+00:00")
        cache = make_cache([catalog_entry(old, BASELINE),
                            catalog_entry(victim, "2026-10-01")])
        enrich = {
            HIDE_URL: {"source": SOURCE, "title": "將被收埋嘅工具",
                       "captured_date": "2026-10-01"},
        }
        updated, updated_enrich, out, hidden = run_sync(
            cache, [old, dict(victim, visible=False)], enrich, today="2026-11-15")

        # cache.json：條目仲喺度，日期唔變
        got = items(updated)
        self.assertIn(norm(HIDE_URL), got)
        self.assertEqual(got[norm(HIDE_URL)]["captured_date"], "2026-10-01")
        self.assertEqual(got[norm(HIDE_URL)]["date"], "2026-10-01")
        self.assertEqual(got[norm(OLD_URL)]["captured_date"], BASELINE)
        # notices 保留
        notice = [n for n in updated["notices"]
                  if norm(n.get("pdf_url") or n.get("url")) == norm(HIDE_URL)]
        self.assertEqual(len(notice), 1)
        self.assertEqual(notice[0]["captured_date"], "2026-10-01")
        # enrich 保留
        self.assertIn(HIDE_URL, updated_enrich)
        self.assertEqual(updated_enrich[HIDE_URL]["captured_date"], "2026-10-01")
        # store-hidden.json 點名收埋
        self.assertEqual(hidden, [norm(HIDE_URL)])
        # 唔當今天新上架
        self.assertIn("今日新上架 0 個", out)
        self.assertIn("store-hidden 1 項", out)
        # 首次公開日唔受影響
        self.assertEqual(updated["_meta"]["appstore"]["first_public"][norm(HIDE_URL)], "2026-10-01")

    def test_reshown_app_keeps_original_date_not_today(self):
        old = app("舊工具", OLD_URL, "2026-09-03T10:00:00+00:00")
        victim = app("將被收埋嘅工具", HIDE_URL, "2026-09-05T10:00:00+00:00")
        cache = make_cache([catalog_entry(old, BASELINE),
                            catalog_entry(victim, "2026-10-01")])
        step1, _e1, _o1, hidden1 = run_sync(
            cache, [old, dict(victim, visible=False)], today="2026-11-15")
        self.assertEqual(hidden1, [norm(HIDE_URL)])

        step2, e2, out2, hidden2 = run_sync(
            step1, [old, dict(victim, visible=True)], _e1, today="2026-11-16")
        got = items(step2)
        self.assertEqual(hidden2, [])
        self.assertEqual(got[norm(HIDE_URL)]["captured_date"], "2026-10-01")
        self.assertEqual(got[norm(HIDE_URL)]["date"], "2026-10-01")
        self.assertNotIn("今日新上架 1", out2)
        self.assertIn("今日新上架 0 個", out2)
        self.assertEqual(step2["_meta"]["appstore"]["first_public"][norm(HIDE_URL)], "2026-10-01")
        self.assertIn(HIDE_URL, e2)

    def test_never_published_hidden_stays_pending_and_not_listed(self):
        old = app("舊工具", OLD_URL, "2026-09-03T10:00:00+00:00")
        fresh_hidden = app("未公開過", "https://never-public.test/", "2026-11-10T10:00:00+00:00",
                           visible=False)
        cache = make_cache([catalog_entry(old, BASELINE)])
        updated, _e, out, hidden = run_sync(cache, [old, fresh_hidden], today="2026-11-15")
        got = items(updated)
        self.assertNotIn(norm("https://never-public.test/"), got)
        self.assertEqual(hidden, [])
        self.assertIn("https://never-public.test", updated["_meta"]["appstore"]["pending"])
        self.assertIn("未上架 1 個", out)

    def test_absent_app_is_dropped_and_relisted_as_today(self):
        """紀錄喺 store 完全消失（被刪／換 URL）＝舊規則：再出現＝今日重新上架。"""
        a = app("工具甲", OLD_URL, "2026-09-03T10:00:00+00:00")
        b = app("工具乙", ABSENT_URL, "2026-09-04T10:00:00+00:00")
        cache = make_cache([catalog_entry(a, BASELINE),
                            catalog_entry(b, BASELINE)])
        step1, _e1, _o1, hidden1 = run_sync(cache, [a], today="2026-11-15")
        self.assertNotIn(norm(ABSENT_URL), items(step1))
        self.assertIn(norm(ABSENT_URL), step1["_meta"]["appstore"]["delisted"])
        self.assertEqual(hidden1, [], "消失咗嘅 app 唔寫入 store-hidden.json，前端以「唔再有呢條記錄」處理")

        step2, _e2, out2, hidden2 = run_sync(step1, [a, b], today="2026-11-16")
        self.assertEqual(items(step2)[norm(ABSENT_URL)]["captured_date"], "2026-11-16")
        self.assertIn("今日新上架 1 個", out2)
        self.assertEqual(hidden2, [])

    def test_suspicious_shrink_carries_and_freezes_hidden_list(self):
        """一次過少咁多 = store 抓唔齊：保留舊資料、store-hidden.json 維持原狀。"""
        base_apps = [app(f"工具{i}", f"https://keep{i}.test/", "2026-09-03T10:00:00+00:00")
                     for i in range(4)]
        cache = make_cache([catalog_entry(a, BASELINE) for a in base_apps])
        # 4 個入面今次只見到 1 個 → 3 個消失 > max(2, 4//3=1) → suspicious
        step, _e, out, hidden = run_sync(
            cache, base_apps[:1], today="2026-11-15",
            hidden_seed=["https://sentinel.test"])
        got = items(step)
        self.assertEqual(len(got), 4, "抓唔齊唔可以縮水 catalog")
        self.assertEqual(hidden, ["https://sentinel.test"],
                         "抓唔齊時 store-hidden.json 維持原狀，唔會全館收埋")
        self.assertNotIn(norm("https://keep1.test/"), step["_meta"]["appstore"]["delisted"])
        self.assertNotIn(norm("https://keep1.test/"), step["_meta"]["appstore"]["pending"])

    def test_mixed_hidden_and_absent(self):
        """1 visible + 1 收埋（曾經公開）+ 2 消失（未到 suspicious 線）。"""
        four = [app(f"工具{i}", f"https://mix{i}.test/", "2026-09-03T10:00:00+00:00")
                for i in range(4)]
        cache = make_cache([catalog_entry(a, BASELINE) for a in four])
        apps = [dict(four[0], visible=True),
                dict(four[1], visible=False)]
        # four[2]、four[3] 完全消失
        updated, _e, _out, hidden = run_sync(cache, apps, today="2026-11-15")
        got = items(updated)
        self.assertIn(norm("https://mix0.test/"), got)
        self.assertIn(norm("https://mix1.test/"), got, "收埋但曾經公開 → 保留")
        self.assertEqual(got[norm("https://mix1.test/")]["captured_date"], BASELINE)
        self.assertNotIn(norm("https://mix2.test/"), got, "消失 → 舊規則掉出 catalog")
        self.assertNotIn(norm("https://mix3.test/"), got)
        self.assertEqual(hidden, [norm("https://mix1.test/")])
        self.assertIn(norm("https://mix2.test/"), updated["_meta"]["appstore"]["delisted"])
        self.assertIn(norm("https://mix3.test/"), updated["_meta"]["appstore"]["delisted"])

    def test_first_public_evidence_restores_record_when_hidden(self):
        """舊紀錄（catalog 之前已經被舊規則掉走）但 first_public 仲喺度：
        而家再見到 visible=false，要連原首次公開日一齊救返。"""
        old = app("舊工具", OLD_URL, "2026-09-03T10:00:00+00:00")
        cache = make_cache([catalog_entry(old, BASELINE)])
        # 模擬舊規則掉走後嘅狀態：catalog 冇 HIDE_URL，但 first_public 仲記住佢
        cache["_meta"]["appstore"]["first_public"] = {norm(HIDE_URL): "2026-10-01"}
        victim = app("舊收埋", HIDE_URL, "2026-09-05T10:00:00+00:00", visible=False)

        updated, _e, out, hidden = run_sync(cache, [old, victim], today="2026-11-15")
        got = items(updated)
        self.assertIn(norm(HIDE_URL), got)
        self.assertEqual(got[norm(HIDE_URL)]["captured_date"], "2026-10-01")
        self.assertEqual(hidden, [norm(HIDE_URL)])

    def test_hidden_url_trailing_slash_normalized_in_store_hidden(self):
        old = app("舊工具", OLD_URL, "2026-09-03T10:00:00+00:00")
        victim = app("收埋工具", "https://x.test/", "2026-09-05T10:00:00+00:00")
        cache = make_cache([catalog_entry(old, BASELINE),
                            catalog_entry(victim, BASELINE)])
        _u, _e, _o, hidden = run_sync(
            cache, [old, dict(victim, url="https://x.test/", visible=False)],
            today="2026-11-15")
        self.assertEqual(hidden, ["https://x.test"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
