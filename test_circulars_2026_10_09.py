#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回歸測試：2026-10-09 用戶點名通告嘅分類標籤、欄位表式標題清理同 'view' 殘留。

涵蓋：
1. 五張點名標錯標籤嘅通告由標題重算已歸位（+ 同場「之行-報名表格」跟活動）：
   - 總會 26366 探索歷史典藏、清真文化與創新科技之行       服務 → 活動
   - 總會 26370 港島地域羽毛球會-入會表格                   訓練 → 公布
   - 總會 26369 港島地域羽毛球會-招收2026-2027年度下半年新會員 比賽 → 公布
   - 總會 26380 港島地域通告便覽(2026年10月)                服務 → 公布
   - 總會 26363 港島童軍生態小組-觀鳥章(興趣組)領袖座談會   公布 → 訓練
   仲有護欄：「服務之旅」＝服務、「工作人員招募」＝服務、
   「XX邀請賽-隊員招募」＝比賽、「XX訓練班-學員招募」＝訓練。
2. 港島南區欄位表式連結文字（「…活動名稱: 靜觀品茶工作坊 活動日期:… 通告下載」）
   喺 cache.json（data + notices）同 enrich.json 已抽成「靜觀品茶工作坊」，
   並由 core.clean_title／extract_activity_name_title 守住。
3. 港島南區 24 筆殘留 'view' 標題（data + notices）已清走。
4. 同類存量（過去通告便覽／羽毛球會入會系列／座談會／靜觀品茶地域版）
   已按新規則補返分類。
5. `fix_circulars_2026_10_09.py --dry-run` 確認存量數據零待改項。
6. 用戶再報（同日）：「跨支部海洋公園研習日(P105/2026)」公布→訓練，規則層
   TRAINING_TERMS 收裸詞「研習」（涵蓋研習班／坊／日，同 story_queue／出圖台
   對齊）；同場重申「標題分不到才找內文，內文範圍太廣很易亂的」——內文
   fallback 收窄（BODY_SCAN_LIMIT 只掃開首 600 字＋BODY_UNTRUSTED_TERMS
   附帶字眼唔計），有專屬測試組守住。

用法：python3 test_circulars_2026_10_09.py
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

import fix_circulars_2026_10_09 as fix_mod  # noqa: E402
import story_queue as sq  # noqa: E402
from subscription_tagging import (  # noqa: E402
    extract_categories,
    extract_subscription_metadata,
)

try:
    import core  # noqa: E402
except Exception:  # pragma: no cover
    core = None

CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

HQ = "https://scout.org.hk/uploads/tc/circulars"

# 用戶點名嘅 5 張（＋同場報名表格）：URL →（修好後類別 id、類別標籤）
NAMED_CATEGORY_URLS = {
    f"{HQ}/26366/I_MA04_26_Shenzhen.pdf": ("activity", "活動"),
    f"{HQ}/26372/I_MA04a_26_Shenzhen_form.pdf": ("activity", "活動"),
    f"{HQ}/26370/Prog64a_26_BadmintonClubRecruitForm.pdf": ("announcement", "公布"),
    f"{HQ}/26369/Prog64_26_BadmintonClubMemberRecruit.pdf": ("announcement", "公布"),
    f"{HQ}/26380/CircularList-2026-10.pdf": ("announcement", "公布"),
    f"{HQ}/26363/Prog62_26_BirdwatcherSeminar.pdf": ("training", "訓練"),
    # 用戶再報（2026-10-09）：海洋公園研習日（研習＝訓練）
    f"{HQ}/26358/P105-26.pdf": ("training", "訓練"),
}

SQ_LABEL = {
    "活動": "activity",
    "公布": "announcement",
    "訓練": "training",
    "服務": "service",
    "比賽": "competition",
}


class Circulars20261009RuleTests(unittest.TestCase):
    """分類器同標題清理規則測試。"""

    def test_named_titles_reclassify_under_new_rules(self):
        cases = [
            ("探索歷史典藏、清真文化與創新科技之行", "活動"),
            ("探索歷史典藏、清真文化與創新科技之行-報名表格", "活動"),
            ("港島地域羽毛球會-入會表格", "公布"),
            ("港島地域羽毛球會-招收2026-2027年度下半年新會員", "公布"),
            ("港島地域通告便覽(2026年10月)", "公布"),
            ("港島童軍生態小組-觀鳥章(興趣組)領袖座談會", "訓練"),
        ]
        for title, label in cases:
            with self.subTest(title=title):
                cats = extract_categories(title, "", "總會")
                self.assertEqual(cats[0]["label"], label)
                meta = extract_subscription_metadata(title, "", "")
                topic = {
                    "活動": "activity:other",
                    "公布": "category:announcement",
                    "訓練": "category:training",
                }[label]
                self.assertIn(topic, meta["subscription_tags"])
                self.assertEqual(sq.classify_category({"title": title, "source_site": "總會"}, None),
                                 SQ_LABEL[label])

    def test_body_text_cannot_steal_category_anymore(self):
        # 舊版俾 PDF 內文搶走嘅三個個案：內文有「探訪／訓練班／比賽」都好，
        # 標題字眼行先。
        cases = [
            ("探索歷史典藏、清真文化與創新科技之行", "安排探訪當地清真寺", "活動"),
            ("港島地域羽毛球會-入會表格", "本會設有羽毛球訓練班", "公布"),
            ("港島地域羽毛球會-招收2026-2027年度下半年新會員", "本會每年舉辦羽毛球比賽", "公布"),
            ("港島地域通告便覽(2026年10月)", "工作人員招募 訓練班 比賽", "公布"),
        ]
        for title, text, label in cases:
            with self.subTest(title=title):
                self.assertEqual(extract_categories(title, text, "總會")[0]["label"], label)

    def test_stronger_title_signals_still_win(self):
        # 汲取經驗：新規則唔可以反噬既有優先序。
        cases = [
            ("「童」心建家園-東莞巿石龍鎮服務之旅", "服務"),      # 服務之旅仍係服務
            ("跨越疆界:港台童軍泰北服務之旅2026", "服務"),
            ("渣打香港馬拉松2027 - 工作人員大招募(歡迎全港童軍參與)", "服務"),
            ("香港童軍龍舟邀請賽2026 – 沙田西區龍舟隊成員招募", "比賽"),  # 賽事名行先
            ("童軍露營訓練班-學員招募", "訓練"),                  # 訓練班行先
            ("東九50樂悠遊之與你「童」行(步行籌款活動)", "活動"),  # 「童」行唔係「之行」
            ("社會服務隊 ─ 隊員招募", "服務"),                    # 服務隊招募仍係服務
        ]
        for title, label in cases:
            with self.subTest(title=title):
                self.assertEqual(extract_categories(title, "", "總會")[0]["label"], label)
                self.assertEqual(sq.classify_category({"title": title, "source_site": "總會"}, None),
                                 SQ_LABEL[label])

    def test_yanyi_family_is_training_from_title(self):
        # 2026-10-09 用戶點名「跨支部海洋公園研習日」：研習日／坊／班一律由
        # 標題「研習」認到係訓練（同「第5屆公園定向研習班」＝訓練一致），
        # 三份規則（訂閱分類／story_queue／出圖台）都對齊。
        cases = [
            ("「環境保育與生態安全」— 跨支部海洋公園研習日(P105/2026)", "訓練"),
            ("童軍單車研習坊 (第20/26號)", "訓練"),
            ("第5屆公園定向研習班(P100/2026)", "訓練"),
            ("港島童軍章會-幼童軍搜集章研習班-報名表格", "訓練"),  # 表格跟返主件
            ("深資童軍會議程序研習班 - 接納通知書", "訓練"),        # 通知書跟返主件
            ("立划板競賽研習班", "比賽"),                          # 競賽字眼行先
        ]
        for title, label in cases:
            with self.subTest(title=title):
                self.assertEqual(extract_categories(title, "", "總會")[0]["label"], label)
                self.assertEqual(sq.classify_category({"title": title, "source_site": "總會"}, None),
                                 SQ_LABEL[label])

    def test_body_scope_narrowed_per_user_rule(self):
        # 2026-10-09 用戶重申：「標題分不到才找內文，內文範圍太廣很易亂的」。
        # 內文 fallback 兩點收窄：
        # (a) 附帶字眼（工作人員／探訪／服務／義工／比賽／錦標）喺內文唔計；
        # (b) 淨係掃開首 BODY_SCAN_LIMIT 字，尾段字眼唔好亂。
        # 但事件類型專有詞（訓練班／社區服務／公開賽）照樣信。
        noise = [
            ("某某表格", "本會每年舉辦羽毛球比賽"),          # 內文「比賽」唔搶
            ("", "招募工作人員"),                            # 內文「工作人員」唔搶
            ("", "行程包括探訪古蹟"),                        # 內文「探訪」唔搶
            ("特別通告", "內文提及服務同義工"),              # 內文裸字「服務／義工」唔搶
        ]
        for title, text in noise:
            with self.subTest(title=title, text=text):
                self.assertEqual(extract_categories(title, text, "總會")[0]["label"], "公布")

        keep = [
            ("", "參加資格：童軍\n訓練班：繩結訓練班", "訓練"),   # 事件類型詞照信
            ("", "活動性質：社區服務", "服務"),
            ("", "服務日：2026-09-20", "服務"),
            ("", "全港公開賽", "比賽"),
        ]
        for title, text, label in keep:
            with self.subTest(title=title, text=text):
                self.assertEqual(extract_categories(title, text, "總會")[0]["label"], label)

        # 範圍收窄：600 字之後嘅字眼唔計（內文範圍太廣好易亂）
        self.assertEqual(
            extract_categories("特別通告", "前言前言前言" + "x" * 700 + "訓練班", "總會")[0]["label"],
            "公布",
        )
        self.assertEqual(
            extract_categories("特別通告", "訓練班" + "x" * 700, "總會")[0]["label"],
            "訓練",
        )

    def test_clean_title_extracts_activity_name_field(self):
        if core is None:
            self.skipTest("core.py 依賴未安裝")
        dump = fix_mod.TEA_WORKSHOP_DUMP_TITLE
        self.assertEqual(core.clean_title(dump, {}), "靜觀品茶工作坊")
        self.assertEqual(
            core.clean_title("小童軍支部 活動名稱:中秋晚會 活動日期:2026年10月6日 截止日期:2026年10月1日", {}),
            "中秋晚會",
        )
        # 護欄：冇欄位結構／冇下一個欄位標籤就唔好斬
        self.assertEqual(core.clean_title("請填寫活動名稱：（見表格）", {}),
                         "請填寫活動名稱:(見表格)")
        self.assertEqual(core.clean_title("童軍精神健康(服務組)專章訓練班", {}),
                         "童軍精神健康(服務組)專章訓練班")
        self.assertIsNone(core.extract_activity_name_title("活動名稱: 靜觀品茶工作坊"))


class Circulars20261009DataTests(unittest.TestCase):
    """鎖定 cache.json 同 enrich.json 入面點名通告嘅實際狀態。"""

    @classmethod
    def setUpClass(cls):
        cls.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        cls.enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))

    def test_named_circulars_have_fixed_categories(self):
        for url, (cat_id, label) in NAMED_CATEGORY_URLS.items():
            with self.subTest(url=url):
                entry = self.enrich[url]
                self.assertEqual([c["id"] for c in entry["categories"]], [cat_id])
                self.assertEqual([c["label"] for c in entry["categories"]], [label])
                topic = {
                    "activity": "activity:other",
                    "announcement": "category:announcement",
                    "training": "category:training",
                }[cat_id]
                self.assertIn(topic, entry["subscription_tags"])

    def test_stock_series_follow_new_rules(self):
        for url in fix_mod.CATEGORY_URLS:
            with self.subTest(url=url):
                entry = self.enrich[url]
                self.assertTrue(entry.get("categories"), f"{url} 應已補分類")
                expected = extract_categories(entry.get("title", ""), "", entry.get("source", ""))
                self.assertEqual([c["id"] for c in entry["categories"]],
                                 [c["id"] for c in expected])

    def test_teaworkshop_title_extracted_in_cache_and_enrich(self):
        for url, (clean_title, listing_title) in fix_mod.TITLE_FIXES.items():
            with self.subTest(url=url):
                items = fix_mod.find_cache_items(self.cache, url)
                self.assertGreaterEqual(len(items), 2)  # data + notices
                for item in items:
                    self.assertEqual(item["title"], clean_title)
                entry = self.enrich[url]
                self.assertEqual(entry["title"], clean_title)
                self.assertEqual(entry.get("title_check"), "corrected")
                self.assertEqual(entry.get("listing_title"), listing_title)
        if core is not None:
            for url, (clean_title, listing_title) in fix_mod.TITLE_FIXES.items():
                self.assertEqual(core.clean_title(listing_title, {}), clean_title)

    def test_no_view_titles_left_in_cache(self):
        bad = [x for arr in (self.cache.get("data") or {}).values() if isinstance(arr, list)
               for x in arr if str(x.get("title", "")).strip().lower() in {"view", "preview"}]
        bad += [x for x in self.cache.get("notices") or []
                if str(x.get("title", "")).strip().lower() in {"view", "preview"}]
        self.assertEqual(bad, [])

    def test_fix_script_dry_run_is_clean(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fix_mod.main(["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("已經乾淨", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
