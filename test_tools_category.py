#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""離線測試：「小工具」分類 + Scout System 來源 + 2026-09-14 詞表擴充。

涵蓋：
  1. TOOLS_SOURCES 來源嘅通告一律分類「小工具」，並視為所有支部；
  2. notify 真實管道（無 enrich 記錄）都配對得到「小工具」訂閱；
  3. 冇訂小工具／訂錯分類嘅訂閱唔會誤中；
  4. 新增關鍵詞（練習賽／體驗賽／考驗／課程／體驗日）命中正確分類，
     行政類標題（選舉／名單／公布）依然保持未分類。

用法：python test_tools_category.py
"""

import sys
import unittest

sys.path.insert(0, ".")

import notify  # noqa: E402
from subscription_tagging import (  # noqa: E402
    extract_categories,
    extract_subscription_metadata,
    load_catalog,
)

# core.py 需要 requests/bs4；本機冇裝依賴嘅環境就跳過隔離測試。
try:
    import core  # noqa: E402
except Exception:  # pragma: no cover
    core = None


def make_item(title, source="Scout System"):
    return {
        "title": title,
        "url": f"https://example.test/{title}",
        "pdf_url": f"https://example.test/{title}",
        "source_site": source,
        "captured_date": "2026-09-15",
        "date": "2026-09-15",
    }


class ToolsSourceTests(unittest.TestCase):
    def test_tools_source_always_classified_tools(self):
        meta = extract_subscription_metadata("任何標題都算小工具", "", "", source="Scout System")
        self.assertEqual([c["id"] for c in meta["categories"]], ["tools"])
        self.assertIn("category:tools", meta["subscription_tags"])

    def test_tools_branch_comes_from_title_not_blanket(self):
        # 每個工具自帶支部標籤：支部由標題抽取，唔係一刀切全支部
        meta = extract_subscription_metadata("幼童軍計時器", "", "", source="Scout System")
        self.assertEqual(meta["branch_tags"], ["幼童軍"])
        meta2 = extract_subscription_metadata("童軍背包整理器", "", "", source="Scout System")
        self.assertEqual(meta2["branch_tags"], ["童軍"])

    def test_tools_without_branch_label_stays_unlabelled(self):
        meta = extract_subscription_metadata("背包整理器", "", "", source="Scout System")
        self.assertEqual(meta["branch_tags"], [])

    def test_branch_comes_from_owner_site_tags_not_title(self):
        # 「密碼旗號」標題冇支部字眼；支部由站方標籤（抓取時帶返嚟嘅 tags）決定
        meta = extract_subscription_metadata(
            "密碼旗號", "", "", source="Scout System",
            tag_hint="幼童軍 童軍 深資童軍 樂行童軍",
        )
        self.assertEqual([c["id"] for c in meta["categories"]], ["tools"])
        self.assertEqual(meta["branch_tags"], sorted(["幼童軍", "童軍", "深資童軍", "樂行童軍"]))

    def test_non_branch_labels_in_tags_are_ignored(self):
        meta = extract_subscription_metadata(
            "密碼旗號", "", "", source="Scout System",
            tag_hint="童軍 實用 最新",
        )
        self.assertEqual(meta["branch_tags"], ["童軍"])

    def test_pdf_audience_still_beats_tag_hint(self):
        meta = extract_subscription_metadata(
            "某訓練班", "", "幼童軍", source="Scout System",
            tag_hint="童軍",
        )
        self.assertEqual(meta["branch_tags"], ["幼童軍"])

    def test_other_sources_unaffected(self):
        cats = extract_categories("第170屆繩結訓練班", "", "總會")
        self.assertEqual([c["id"] for c in cats], ["training"])


class PushMatchingTests(unittest.TestCase):
    def setUp(self):
        # 模擬冇 enrich 記錄（Scout System 通告唔係 PDF，唔會入 enrich）
        self.meta = notify.notice_metadata(make_item("幼童軍計時器"), {})

    def test_tools_subscriber_of_matching_branch_matches(self):
        sub = {"branch_ids": ["幼童軍"], "topic_ids": ["branch:幼童軍:category:tools"]}
        self.assertTrue(notify.subscription_matches(sub, self.meta))

    def test_tools_subscriber_of_other_branch_not_matched(self):
        # 領袖訂閱者唔應該收到幼童軍嘅工具
        sub = {"branch_ids": ["領袖"], "topic_ids": ["branch:領袖:category:tools"]}
        self.assertFalse(notify.subscription_matches(sub, self.meta))

    def test_non_tools_subscriber_not_matched(self):
        sub = {"branch_ids": ["幼童軍"], "topic_ids": ["branch:幼童軍:category:activity"]}
        self.assertFalse(notify.subscription_matches(sub, self.meta))

    def test_tagged_tool_reaches_each_labelled_branch(self):
        # cache 帶住站方標籤嘅工具：每個被標籤嘅支部訂閱者都收到，冇被標籤嘅唔收
        item = make_item("密碼旗號")
        item["tags"] = ["幼童軍", "童軍"]
        meta = notify.notice_metadata(item, {})
        hit = {"branch_ids": ["童軍"], "topic_ids": ["branch:童軍:category:tools"]}
        miss = {"branch_ids": ["領袖"], "topic_ids": ["branch:領袖:category:tools"]}
        self.assertTrue(notify.subscription_matches(hit, meta))
        self.assertFalse(notify.subscription_matches(miss, meta))

    def test_all_new_still_receives_tools(self):
        self.assertTrue(notify.subscription_matches({"branch_ids": [], "topic_ids": ["all:new"]}, self.meta))

    def test_select_all_tools_is_separate_from_select_all_notices(self):
        """2026-10-01：訂閱推送分開「全選所有通告」同「全選小工具」。"""
        tools_only = {"branch_ids": [], "topic_ids": ["all:tools"]}
        notices_only = {"branch_ids": [], "topic_ids": ["all:notices"]}
        self.assertTrue(notify.subscription_matches(tools_only, self.meta))
        self.assertFalse(notify.subscription_matches(notices_only, self.meta))
        notice_meta = notify.notice_metadata(make_item("童軍繩結訓練班", source="總會"), {})
        self.assertTrue(notify.subscription_matches(notices_only, notice_meta))
        self.assertFalse(notify.subscription_matches(tools_only, notice_meta))

    def test_catalog_contains_tools_options(self):
        by_id = load_catalog()["_topic_by_id"]
        self.assertIn("category:tools", by_id)
        entry = by_id["branch:童軍:category:tools"]
        self.assertEqual(entry.get("match_topic"), "category:tools")
        self.assertEqual(entry.get("group"), "小工具")
        # 既有政策：家長只有活動及比賽 → 唔應該有小工具選項
        self.assertNotIn("branch:家長:category:tools", by_id)
        # 全選掣：通告同小工具各有一個受控 ID，舊版 all:new 保留相容。
        for topic_id, kind in (("all:notices", "all-notices"), ("all:tools", "all-tools"), ("all:new", "all")):
            self.assertIn(topic_id, by_id)
            self.assertEqual(by_id[topic_id].get("kind"), kind)
            self.assertEqual(by_id[topic_id].get("branches"), ["*"])
        self.assertTrue(by_id["all:new"].get("legacy"), "舊版全選唔應該再出現喺新選單")


class KeywordExpansionTests(unittest.TestCase):
    def test_new_terms_classify_real_titles(self):
        cases = [
            ("童軍野外定向練習賽2026", "competition"),
            ("2026年東九龍地域會長盾體驗賽", "competition"),
            ("港島童軍泳會-童軍游泳章考驗日", "training"),
            ("深資童軍肩章考驗營 2026", "training"),
            ("SOUL Keeper 精神健康守護者課程 (Level 1)", "training"),
            ("寰宇童軍計劃「探索」課程", "training"),
            ("幼童軍水上安全體驗日", "activity"),
        ]
        for title, want in cases:
            with self.subTest(title=title):
                got = [c["id"] for c in extract_categories(title)]
                self.assertIn(want, got, got)

    def test_announcement_keyword_in_title_beats_pdf_body(self):
        """2026-10-03 用戶規則：標題有「公告／公布／公佈」＝公布（明確字眼以標題為準）。

        個案：總會「總部公告」（內文有「社會服務」）同紅磡區「D-26-05 區會公布」
        （內文有「考驗」）被 PDF 內文字眼搶去服務／訓練。標題公布字眼要贏。
        「成績公布／結果公布」係賽果＝比賽，唔可以變公布。
        """
        cases = [
            ("總部公告", "訓練署\n余永健先生獲委任，童軍知友社總監（社會服務及內部協調）。", "announcement"),
            ("D-26-05 - 26年10月區會公布 【New】", "區總部公布\n所屬支部成員考驗及相關事務", "announcement"),
            ("地域總部公佈(2026年9月)", "", "announcement"),
            ("香港童軍115周年—新界地域步操及升旗比賽2026 - 成績公布", "", "competition"),
            ("成績公佈", "", "competition"),
        ]
        for title, text, want in cases:
            with self.subTest(title=title):
                got = [c["id"] for c in extract_categories(title, text)]
                self.assertEqual(got, [want], got)
        meta = extract_subscription_metadata("總部公告", "社會服務", "")
        self.assertEqual(meta["subscription_tags"], ["category:announcement"])
        self.assertNotIn("category:service", meta["subscription_tags"])

    def test_title_keywords_beat_pdf_body_keywords(self):
        """標題有明確字眼（訓練／服務／比賽）就以標題為準，內文唔可以搶走。"""
        cases = [
            ("第95屆營藝訓練班", "社會服務：本區服務日", "training"),
            ("社區服務隊招募", "訓練班：繩結訓練班", "service"),
        ]
        for title, text, want in cases:
            with self.subTest(title=title):
                self.assertEqual([c["id"] for c in extract_categories(title, text)], [want])

    def test_administrative_titles_become_announcement(self):
        """2026-10-01：新增「公佈」分類做行政類通告嘅兜底，唔再係空分類——
        等成員訂閱設定時可以揀唔要呢類佢哋最唔想睇嘅一次性行政通告。"""
        for title in [
            "2026年度模範童軍選舉",
            "呈交童軍旅賬目資料",
            "地域總部公布(2026年9月)",
            "地域總部公佈(2026年9月)",
            "2026年傑出旅團獎勵計劃-獲獎名單公布",
        ]:
            with self.subTest(title=title):
                categories = extract_categories(title)
                self.assertEqual([c["id"] for c in categories], ["announcement"])
                self.assertEqual(categories[0]["label"], "公布")


@unittest.skipUnless(core, "core.py 依賴（requests/bs4）未安裝，跳過隔離測試")
class TagSelectorIsolationTests(unittest.TestCase):
    """保證：冇設定 tag_selector 嘅來源（即其餘全部來源）行為完全唔變。"""

    def test_no_tag_selector_means_no_tag_collection(self):
        # 冇鍵、空字串、甚至冇 anchor 都一樣：直接回空，唔郁任何抓取邏輯
        self.assertEqual(core.extract_item_tag_labels(None, {}), [])
        self.assertEqual(core.extract_item_tag_labels(None, {"tag_selector": ""}), [])
        self.assertEqual(core.extract_item_tag_labels(None, {"tag_selector": "   "}), [])

    def test_normal_sources_cache_shape_unchanged(self):
        recs = [
            {
                "source_site": "總會",
                "region": "總會",
                "pdf_url": "https://scout.org.hk/x.pdf",
                "title": "某訓練班",
                "captured_date": "2026-09-15",
            }
        ]
        out = core.build_grouped_cache(recs, {"總會": {}}, "2026-09-15 18:00:00")
        entry = out["data"]["總會"][0]
        # 冇 tags 欄位 = 同舊格式一模一樣
        self.assertNotIn("tags", entry)
        self.assertEqual(
            sorted(entry.keys()),
            sorted(["title", "url", "pdf_url", "date", "captured_date", "source_site", "region"]),
        )
        self.assertNotIn("tags", out["notices"][0])

    def test_only_sources_with_tags_carry_them(self):
        recs = [
            {
                "source_site": "Scout System",
                "region": "Scout System",
                "pdf_url": "https://tools.example/t1",
                "title": "密碼旗號",
                "captured_date": "2026-09-15",
                "tags": ["幼童軍", "童軍"],
            }
        ]
        out = core.build_grouped_cache(recs, {"Scout System": {}}, "2026-09-15 18:00:00")
        self.assertEqual(out["data"]["Scout System"][0]["tags"], ["幼童軍", "童軍"])
        self.assertEqual(out["notices"][0]["tags"], ["幼童軍", "童軍"])


class AppStoreSyncTests(unittest.TestCase):
    """Scout System 上架日規則（2026-11-07 用戶規則，取代 2026-11-06）。

    「今天更新/發布」＝ **今日公開**，唔係今日入庫，亦唔係圖書館第一次見到 URL：
      * 一直喺架上 → 保留首次公開日，留在「之前發布」；
      * 之前入庫（created_at 舊）但今日首次公開 → 今日上架；
      * 今日入庫但未公開（visible=false）→ 未上架，唔入 catalog；
      * 下架後重新上架 → 今日；
      * 冇 baseline／一次過太多未見過 URL → 防呆介入，唔會全版變今日。
    同時保證：每個已上架 app 都有一條 notice（唔重複）＋ 一條 enrich。
    """

    BASELINE = "2026-09-24"

    # ── fixture helpers ───────────────────────────────────────────
    def _app(self, name, url, created_at, tags=None, category="工具", page="apps"):
        return {
            "id": name,
            "name": name,
            "url": url,
            "description": f"{name} 描述",
            "note": None,
            "icon": "",
            "icon_source": "favicon",
            "category": category,
            "page": page,
            "tags": tags if tags is not None else ["童軍", "小工具"],
            "visible": True,
            "sort_order": 0,
            "created_at": created_at,
        }

    def _catalog_entry(self, app, date):
        return {
            "title": app["name"],
            "url": app["url"],
            "pdf_url": app["url"],
            "date": date,
            "captured_date": date,
            "source_site": "Scout System",
            "region": "Scout System",
            "source_url": "https://scoutappstore.vercel.app/",
            "tags": list(app.get("tags") or []),
            "description": app.get("description") or "",
            "icon": "",
            "store_category": app.get("category") or "",
            "store_page": app.get("page") or "",
        }

    def _cache(self, tools, extra_notices=None):
        notices = []
        for item in tools:
            notices.append({
                "source_site": "Scout System",
                "region": "Scout System",
                "pdf_url": item["url"],
                "title": item["title"],
                "captured_date": item["captured_date"],
                "tags": list(item.get("tags") or []),
            })
        notices.extend(extra_notices or [])
        return {
            "last_updated": f"{self.BASELINE} 00:00:00",
            "meta": {"version": "5.3.0", "total_sources": 1, "total_notices": len(notices)},
            "data": {"Scout System": tools},
            "notices": notices,
            "_meta": {
                "appstore": {
                    "first_sync": self.BASELINE,
                    "last_sync": self.BASELINE,
                    "known_dates": {i["url"]: i["captured_date"] for i in tools},
                }
            },
        }

    def _run(self, cache, apps, enrich=None):
        """喺 temp dir 跑一次同步，回傳 (cache, enrich, stdout)。"""
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_path = tmp_path / "cache.json"
            enrich_path = tmp_path / "enrich.json"
            apps_path = tmp_path / "apps.json"
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            enrich_path.write_text(json.dumps(enrich or {}, ensure_ascii=False), encoding="utf-8")
            apps_path.write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")
            res = subprocess.run(
                [
                    sys.executable,
                    "tools/scrape_appstore.py",
                    "--apps-json", str(apps_path),
                    "--cache", str(cache_path),
                    "--enrich", str(enrich_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return (
                json.loads(cache_path.read_text(encoding="utf-8")),
                json.loads(enrich_path.read_text(encoding="utf-8")),
                res.stdout,
            )

    def _items(self, cache):
        return {i["url"]: i for i in cache["data"]["Scout System"]}

    def _notices(self, cache):
        return [n for n in cache["notices"] if n.get("source_site") == "Scout System"]

    # ── 測試 ─────────────────────────────────────────────────────
    def test_existing_apps_keep_published_dates_when_they_change(self):
        old_a = self._app("遠足路程表", "https://drawtheroute.test/", "2026-09-03T10:00:00+00:00")
        old_b = self._app("童軍進度紀錄", "https://scoutbadge.test/", "2026-09-04T10:00:00+00:00")
        cache = self._cache([self._catalog_entry(old_a, self.BASELINE),
                             self._catalog_entry(old_b, self.BASELINE)])

        # 改名、改標籤、改分類，但 URL 唔變
        apps = [dict(old_a, name="遠足路程規劃表 2.0", tags=["幼童軍", "童軍"], category="集會助手及指南"),
                dict(old_b)]

        updated, enrich, out = self._run(cache, apps)
        self.assertIn("今日新上架 0 個", out)
        items = self._items(updated)
        for item in items.values():
            self.assertEqual(item["date"], self.BASELINE)
            self.assertEqual(item["captured_date"], self.BASELINE)
        self.assertEqual(items["https://drawtheroute.test/"]["title"], "遠足路程規劃表 2.0")
        self.assertIn("幼童軍", items["https://drawtheroute.test/"]["tags"])
        self.assertEqual(enrich["https://drawtheroute.test/"]["ss_kind"], "assistant")
        self.assertEqual(len(self._notices(updated)), 2, "改名唔應該多一條 notice")

    def test_brand_new_app_created_today_counts_as_today(self):
        from tools.scrape_appstore import hkt_today

        today = hkt_today()
        old = self._app("遠足路程表", "https://drawtheroute.test/", "2026-09-03T10:00:00+00:00")
        fresh = self._app("新出小工具", "https://brandnew.test/", f"{today}T01:00:00+00:00")
        cache = self._cache([self._catalog_entry(old, self.BASELINE)])

        updated, enrich, out = self._run(cache, [old, fresh])
        self.assertIn("今日新上架 1 個", out)
        items = self._items(updated)
        self.assertEqual(items["https://brandnew.test/"]["captured_date"], today)
        self.assertEqual(items["https://drawtheroute.test/"]["captured_date"], self.BASELINE)
        self.assertEqual(len(self._notices(updated)), 2)
        self.assertEqual(self._notices(updated)[1]["captured_date"] if self._notices(updated)[1]["pdf_url"] == "https://brandnew.test/" else self._notices(updated)[0]["captured_date"], today)
        self.assertIn("https://brandnew.test/", enrich)
        self.assertEqual(enrich["https://brandnew.test/"]["categories"][0]["id"], "tools")

    def test_old_created_at_published_today_counts_as_today(self):
        """2026-11-07 用戶規則：之前入庫、今日先公開 → 今日上架。

        舊規則（2026-11-06）用 created_at 壓住新 URL，令「遊戲學習」
        （created 11-06、11-07 公開）被寫成 11-06；呢個測試鎖住新規則。
        """
        from tools.scrape_appstore import hkt_today

        today = hkt_today()
        old = self._app("遠足路程表", "https://drawtheroute.test/", "2026-09-03T10:00:00+00:00")
        moved = dict(old, url="https://drawtheroute-v3.test/", name="遠足路程表 V3")
        cache = self._cache([self._catalog_entry(old, self.BASELINE)])

        updated, _enrich, out = self._run(cache, [moved])
        self.assertIn("今日新上架 1 個", out)
        items = self._items(updated)
        # 新 URL 今日首次公開；created_at 2026-09-03 只係入庫日，唔可以蓋走
        self.assertEqual(items["https://drawtheroute-v3.test/"]["captured_date"], today)
        self.assertEqual(
            updated["_meta"]["appstore"]["first_public"]["https://drawtheroute-v3.test"], today
        )
        # delisted 用 normalize 咗嘅 key（去尾斜線）
        self.assertIn("https://drawtheroute.test", updated["_meta"]["appstore"]["delisted"])

    def test_baseline_loss_uses_store_dates_not_today(self):
        apps = [
            self._app("工具一", "https://t1.test/", "2026-09-03T10:00:00+00:00"),
            self._app("工具二", "https://t2.test/", "2026-09-05T10:00:00+00:00"),
        ]
        # 完全冇歷史：冇 data["Scout System"]、冇 known_dates、冇 enrich
        cache = {"last_updated": "", "meta": {}, "data": {}, "notices": [], "_meta": {}}

        updated, enrich, out = self._run(cache, apps)
        self.assertIn("今日新上架 0 個", out)
        items = self._items(updated)
        self.assertEqual(items["https://t1.test/"]["captured_date"], "2026-09-03")
        self.assertEqual(items["https://t2.test/"]["captured_date"], "2026-09-05")
        self.assertEqual(len(self._notices(updated)), 2)
        self.assertEqual(len(enrich), 2)

    def test_mass_unknown_urls_are_defused_instead_of_flooding_today(self):
        keep = [self._app(f"舊工具{i}", f"https://old{i}.test/", "2026-09-03T10:00:00+00:00") for i in range(10)]
        cache = self._cache([self._catalog_entry(a, self.BASELINE) for a in keep])
        # 8 個從未見過、又冇 created_at 嘅 URL（模擬 baseline 斷咗／store 換 key）
        unknown = [{"name": f"神秘工具{i}", "url": f"https://mystery{i}.test/", "visible": True,
                    "tags": ["小工具"], "category": "工具", "page": "apps", "sort_order": 0}
                   for i in range(8)]

        updated, _enrich, out = self._run(cache, keep + unknown)
        self.assertIn("當 baseline 斷咗", out)
        self.assertIn("今日新上架 0 個", out)
        items = self._items(updated)
        for i in range(8):
            self.assertEqual(items[f"https://mystery{i}.test/"]["captured_date"], self.BASELINE)
        for i in range(10):
            self.assertEqual(items[f"https://old{i}.test/"]["captured_date"], self.BASELINE)

    def test_delisted_app_that_comes_back_counts_as_today(self):
        from tools.scrape_appstore import hkt_today

        today = hkt_today()
        a = self._app("工具甲", "https://a.test/", "2026-09-03T10:00:00+00:00")
        b = self._app("工具乙", "https://b.test/", "2026-09-04T10:00:00+00:00")
        cache = self._cache([self._catalog_entry(a, self.BASELINE), self._catalog_entry(b, self.BASELINE)])

        # 第一日：乙下架
        step1, _enrich, out1 = self._run(cache, [a])
        self.assertIn("今日新上架 0 個", out1)
        self.assertIn("https://b.test", step1["_meta"]["appstore"]["delisted"])
        self.assertEqual(self._items(step1)["https://a.test/"]["captured_date"], self.BASELINE)

        # 第二日：乙重新上架 → 今日
        step2, _enrich2, out2 = self._run(step1, [a, b])
        self.assertIn("今日新上架 1 個", out2)
        items = self._items(step2)
        self.assertEqual(items["https://b.test/"]["captured_date"], today)
        self.assertEqual(items["https://a.test/"]["captured_date"], self.BASELINE)
        self.assertNotIn("https://b.test", step2["_meta"]["appstore"]["delisted"])
        b_notices = [n for n in self._notices(step2) if (n.get("url") or n.get("pdf_url")) == "https://b.test/"]
        self.assertEqual(len(b_notices), 1, "重新上架唔可以疊多一條重複 notice")
        self.assertEqual(b_notices[0]["captured_date"], today)

    def test_missing_notices_are_backfilled_without_becoming_today(self):
        a = self._app("工具甲", "https://a.test/", "2026-09-03T10:00:00+00:00")
        b = self._app("工具乙", "https://b.test/", "2026-09-04T10:00:00+00:00")
        cache = self._cache([self._catalog_entry(a, self.BASELINE), self._catalog_entry(b, self.BASELINE)])
        cache["notices"] = [n for n in cache["notices"] if n["pdf_url"] != "https://b.test/"]

        updated, _enrich, out = self._run(cache, [a, b])
        self.assertIn("補 notices 1 條", out)
        self.assertIn("今日新上架 0 個", out)
        b_notices = [n for n in self._notices(updated) if (n.get("url") or n.get("pdf_url")) == "https://b.test/"]
        self.assertEqual(len(b_notices), 1)
        self.assertEqual(b_notices[0]["captured_date"], self.BASELINE)


class ScoutSystemGroupTests(unittest.TestCase):
    """2026-11-12 用戶規則：Scout System 只分兩大類。

    * 小工具＝自家出品（store page apps／cards／ppt），再按原分類細分；
    * 連結＝他人網站／APP（store page links），全部直接歸連結，唔再細分。
    store page 最權威，唔可以再因為原分類叫「課堂學習工具」而把他人網站當工具。
    """

    def _app(self, page, category):
        return {
            "name": "測試項目", "url": "https://x.test/", "tags": ["童軍"],
            "category": category, "page": page, "visible": True,
        }

    def test_links_page_is_always_link(self):
        from tools.scrape_appstore import store_app_kind
        for category in ("其他", "課堂學習工具", "工具", "遊戲", "系統", "助手", "連結"):
            self.assertEqual(store_app_kind(self._app("links", category)), "link",
                             f"links page 嘅「{category}」都要歸連結")

    def test_own_pages_are_subdivided_by_category(self):
        from tools.scrape_appstore import store_app_kind
        for page in ("apps", "cards", "ppt"):
            self.assertEqual(store_app_kind(self._app(page, "課堂學習工具")), "tool")
            self.assertEqual(store_app_kind(self._app(page, "遊戲")), "game")
            self.assertEqual(store_app_kind(self._app(page, "電子紀錄冊")), "assistant")
            self.assertEqual(store_app_kind(self._app(page, "其他")), "other")

    def test_group_tag_follows_page(self):
        from tools.scrape_appstore import category_to_tags
        link_tags = category_to_tags(self._app("links", "課堂學習工具"))
        self.assertIn("連結", link_tags)
        self.assertNotIn("小工具", link_tags)

        own_tags = category_to_tags(self._app("apps", "工具"))
        self.assertIn("小工具", own_tags)
        self.assertNotIn("連結", own_tags)

    def test_enrich_entry_marks_links_as_link(self):
        from tools.scrape_appstore import build_enrich_entry
        entry = build_enrich_entry(
            {"name": "海外單車遊資料", "url": "https://veloplanner.com/",
             "page": "links", "category": "其他", "tags": ["深資童軍", "樂行童軍"]},
            "2026-09-24",
        )
        self.assertEqual(entry["ss_kind"], "link")
        self.assertEqual(entry["categories"][0]["subtype"], "link")
        self.assertEqual(entry["subscription_tags"], ["scout_kind:link"])
        self.assertEqual(entry["store_page"], "links")


if __name__ == "__main__":
    unittest.main(verbosity=2)