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
    """確保 Scout System 唔會日日變「今日更新」：改動標籤唔算新 APP，全新上架先算。"""

    def test_nine_existing_apps_are_in_previously_published(self):
        import json
        from pathlib import Path

        cache = json.loads(Path("cache.json").read_text(encoding="utf-8"))
        ss = cache.get("data", {}).get("Scout System", [])
        self.assertEqual(len(ss), 9)
        for item in ss:
            self.assertEqual(item.get("date"), "2026-09-24", item.get("title"))
            self.assertEqual(item.get("captured_date"), "2026-09-24", item.get("title"))

    def test_tag_or_name_changes_with_same_url_do_not_make_app_new_today(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        store = json.loads(Path("appstore.json").read_text(encoding="utf-8"))
        apps = [dict(a) for a in store["apps"]]
        # 修改現有 APP「遠足路程表」嘅名稱、支部標籤同分類（但 URL 不變）
        for a in apps:
            if a.get("url") == "https://drawtheroute-yd8p.vercel.app/":
                a["name"] = "遠足路程規劃表 2.0"
                a["tags"] = ["幼童軍", "童軍", "深資童軍", "樂行童軍"]
                a["category"] = "集會助手及指南"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_copy = tmp_path / "cache.json"
            enrich_copy = tmp_path / "enrich.json"
            apps_json = tmp_path / "apps.json"

            orig_cache = json.loads(Path("cache.json").read_text(encoding="utf-8"))
            cache_copy.write_text(json.dumps(orig_cache, ensure_ascii=False), encoding="utf-8")
            enrich_copy.write_text(Path("enrich.json").read_text(encoding="utf-8"), encoding="utf-8")
            apps_json.write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")

            res = subprocess.run(
                [
                    sys.executable,
                    "tools/scrape_appstore.py",
                    "--apps-json", str(apps_json),
                    "--cache", str(cache_copy),
                    "--enrich", str(enrich_copy),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("新 APP 0 個", res.stdout)

            updated_cache = json.loads(cache_copy.read_text(encoding="utf-8"))
            updated_enrich = json.loads(enrich_copy.read_text(encoding="utf-8"))
            ss = updated_cache["data"]["Scout System"]
            self.assertEqual(len(ss), 9)
            for item in ss:
                # 同一 URL 改名或改標籤：全部 9 個仍然留喺「之前發布」(2026-09-24)，唔會變今日
                self.assertEqual(item["date"], "2026-09-24", item["title"])
                self.assertEqual(item["captured_date"], "2026-09-24", item["title"])
                if item["url"] == "https://drawtheroute-yd8p.vercel.app/":
                    self.assertEqual(item["title"], "遠足路程規劃表 2.0")
                    self.assertIn("幼童軍", item["tags"])
                    self.assertEqual(item["store_category"], "集會助手及指南")

            e = updated_enrich["https://drawtheroute-yd8p.vercel.app/"]
            self.assertEqual(e["title"], "遠足路程規劃表 2.0")
            self.assertIn("幼童軍", e["branch_tags"])
            self.assertEqual(e["ss_kind"], "assistant")

    def test_major_rewrite_with_new_url_or_brand_new_app_counts_as_new_today(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        from tools.scrape_appstore import hkt_today

        today = hkt_today()
        store = json.loads(Path("appstore.json").read_text(encoding="utf-8"))
        apps = [dict(a) for a in store["apps"]]
        # 超大型改版：同一個 ID 但換咗全新 URL → 以 URL 為準，應該當成今日重新上架
        for a in apps:
            if a.get("url") == "https://drawtheroute-yd8p.vercel.app/":
                a["url"] = "https://drawtheroute-v3-major.vercel.app/"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_copy = tmp_path / "cache.json"
            enrich_copy = tmp_path / "enrich.json"
            apps_json = tmp_path / "apps.json"

            cache_copy.write_text(Path("cache.json").read_text(encoding="utf-8"), encoding="utf-8")
            enrich_copy.write_text(Path("enrich.json").read_text(encoding="utf-8"), encoding="utf-8")
            apps_json.write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")

            res1 = subprocess.run(
                [
                    sys.executable,
                    "tools/scrape_appstore.py",
                    "--apps-json", str(apps_json),
                    "--cache", str(cache_copy),
                    "--enrich", str(enrich_copy),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("新 APP 1 個", res1.stdout)
            c1 = json.loads(cache_copy.read_text(encoding="utf-8"))
            by_url = {x["url"]: x for x in c1["data"]["Scout System"]}
            self.assertEqual(by_url["https://drawtheroute-v3-major.vercel.app/"]["captured_date"], today)
            self.assertEqual(by_url["https://scoutbadge.vercel.app/"]["captured_date"], "2026-09-24")

            # 同日再跑一次（例如改名／改標籤，但 URL 唔再變）：唔會重複當新 APP
            for a in apps:
                if a.get("url") == "https://drawtheroute-v3-major.vercel.app/":
                    a["name"] = "遠足路程表 V3"
                    a["tags"] = ["幼童軍", "童軍"]
            apps_json.write_text(json.dumps(apps, ensure_ascii=False), encoding="utf-8")
            res2 = subprocess.run(
                [
                    sys.executable,
                    "tools/scrape_appstore.py",
                    "--apps-json", str(apps_json),
                    "--cache", str(cache_copy),
                    "--enrich", str(enrich_copy),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("新 APP 0 個", res2.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)