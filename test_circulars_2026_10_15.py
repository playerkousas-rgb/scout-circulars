#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回歸測試：2026-10-15 用戶點名 8 張錯標籤＋「月度摘要」家族＋鏡像 URL 分歧。

用戶報錯嗰 8 張分兩班，成因唔同，所以測試都分兩班釘：

【班 1 — 規則早已啱，錯嘅係存量數據】同一份 PDF 喺 `enrich.json` 有兩個 key
（`scout.org.hk/…` 同地域站鏡像 `www.scout.org.hk/…`），兩條 entry 由唔同次數嘅 run
寫入，10-15 本機排程用緊未 pull 嘅舊代碼 → 鏡像嗰半用舊規則覆寫咗。
  - 探索歷史典藏、清真文化與創新科技之行          → 活動（之行）
  - 港島地域通告便覽(2026年10月)                 → 公布（便覽）
  - 港島地域羽毛球會-招收2026-2027下半年新會員    → 公布（招收）
  - 港島童軍生態小組-觀鳥章(興趣組)領袖座談會      → 訓練（座談會）

【班 2 — 真規則洞，今次補埋】
  - 「九龍地域通告【2026 年 10 月】」被內文「成績公佈」搶去做比賽
    → 新規則：MONTHLY_DIGEST_TITLE_RE（「…通告【YYYY 年 M 月】」）屬參考文件，永遠唔睇內文
  - 「九龍地域N月份通告一覽」系列（全库 45 筆 digest 家族，26 筆錯／未分類）
    → 新規則：REFERENCE_TITLE_TERMS 加「通告一覽」
  - 「九灣小漁夫出海記-水上文化親子大冒險」被海報內文「訓練班」搶去做訓練
    → 新規則：OTHER_ACTIVITY_TERMS 加「出海記／大冒險」（標題先決）
  - 「港島童軍皮藝會-皮革藝術與生活」＝比賽 → 用戶：一張通告兩個內容，「中 1 個都係啱」
    → **唔人手釘類別**，只標記 HUMAN_CONFIRMED 跳過重算；本測試釘住「唔可以再係比賽」
  - 「寰宇童軍章(P109/2026)」＝活動 → 用戶：「公布會好啲，訓練都係啱，但唔係活動」
    → 跟規則兜底公布；「章(Pxxx)」家族要唔要一律歸訓練仍待用戶定政策

第 4 節係 root-cause 守門：`enrich.summarize_mirror_url_divergence()` 必須回傳空清單，
日後任何一個鏡像 key 俾舊規則覆寫，nightly run log 都會大聲報（唔使再用家肉眼對）。

用法：python3 test_circulars_2026_10_15.py
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

import enrich as enrich_mod  # noqa: E402
import story_queue as sq  # noqa: E402
from subscription_tagging import (  # noqa: E402
    MONTHLY_DIGEST_TITLE_RE,
    extract_categories,
    is_reference_document,
    normalize,
)

ENRICH_PATH = BASE_DIR / "enrich.json"
FIX_SCRIPT = BASE_DIR / "fix_circulars_2026_10_15.py"

# 張張都附一個「敵意內文」：成日搶嘢做嘅字眼擺埋一齊，要標題規則頂得住
ADVERSARIAL_BODY = "成績公佈 工作人員 訓練班 探訪 義工招募 比賽 錦標賽 -community service"

# 用戶點名嘅 8 張（標題 → 應有類別）
NAMED = [
    ("九龍地域通告【2026 年 10 月】", "announcement"),
    ("九龍地域9月份通告一覽", "announcement"),
    ("港島地域通告便覽(2026年10月)", "announcement"),
    ("探索歷史典藏、清真文化與創新科技之行", "activity"),
    ("港島地域羽毛球會-招收2026-2027年度下半年新會員", "announcement"),
    ("港島童軍生態小組-觀鳥章(興趣組)領袖座談會", "training"),
    ("九灣小漁夫出海記-水上文化親子大冒險", "activity"),
]

# 呢啲標題本身冇類別字眼（寰宇童軍章）→ 只釘「由標題計係兜底公布」，即係
# **唔可以再係『活動』**。呢類標題係刻意留返俾 PDF 內文補充嘅（用戶原則：
# 「標題分不到先找內文」），所以唔可以同上面一樣用敵意內文一齊驗。
NAMED_TITLE_ONLY = [
    ("寰宇童軍章(P109/2026)", "announcement"),
    ("港島童軍皮藝會-皮革藝術與生活", "announcement"),   # 規則兜底；數據由人手裁決改做活動
]

# 護欄：新字眼唔可以食走原本啱嘅判斷
GUARDS = [
    # 「大冒險」唔可以食走比賽（同一個字喺填色比賽標題入面）
    ("維多利亞城區森林大冒險小幼童軍填色比賽", "competition"),
    # 「親子」刻意唔收（全库 69 筆，大半係工作坊／比賽）
    ("小童軍親子堆沙工作坊及BBQ", "training"),
    ("親子急救體驗工作坊 - 報名表格", "training"),   # 工作坊係標題強字眼，表格都跟訓練
    # 「服務之旅」仍係服務、「之旅簡介會」仍係訓練（之行/之旅 規則嘅舊護欄）
    ("「童」心建家園-東莞巿石龍鎮服務之旅", "service"),
    ("水務署童軍節-之旅簡介會", "training"),
    # 真·賽果（標題自己就係成績公布）照舊係比賽
    ("香港童軍115周年—新界地域步操及升旗比賽2026 - 成績公布", "competition"),
    ("2026年香港童軍大會操(四)", "activity"),
    ("2026年香港童軍大會操失物認領安排", "announcement"),
]

# 用戶點名嘅 8 張喺 enrich.json 嘅實際 entry（含兩邊鏡像 key 嘅檔名片段）
REPAIRED_FILES = {
    "26410/Summary_2026_10.pdf": "announcement",
    "26401/P109-26.pdf": "announcement",
    # 一張通告兩個內容：用戶話活動／訓練「中 1 個都係啱」，所以接受兩個答案，
    # 唯獨唔可以係比賽（第 1 節有專門測試釘住）。
    "26364/Prog63_26_LeathercraftExhibition2027.pdf": ("activity", "training"),
    "26380/CircularList-2026-10.pdf": "announcement",
    "26369/Prog64_26_BadmintonClubMemberRecruit.pdf": "announcement",
    "26363/Prog62_26_BirdwatcherSeminar.pdf": "training",
    "26366/I_MA04_26_Shenzhen.pdf": "activity",
    "26372/I_MA04a_26_Shenzhen_form.pdf": "activity",
    "26367/I_MA04a_26_Shenzhen_form.pdf": "activity",
    "26370/Prog64a_26_BadmintonClubRecruitForm.pdf": "announcement",
    "web2017/assets/kb_documents/notice/2026/PT-15-26.pdf": "activity",
}


def cat_ids(title: str, body: str = "") -> list:
    return [c.get("id") for c in extract_categories(title, body)]


class RuleTests(unittest.TestCase):
    """規則層：由標題計，敵意內文搶唔走。"""

    def test_named_notices_use_title_rules(self):
        for title, want in NAMED:
            with self.subTest(title=title):
                self.assertEqual(cat_ids(title, ADVERSARIAL_BODY), [want])

    def test_titles_without_category_words_fall_back_to_announcement(self):
        for title, want in NAMED_TITLE_ONLY:
            with self.subTest(title=title):
                self.assertEqual(cat_ids(title), [want])

    def test_guards_keep_stronger_title_terms(self):
        for title, want in GUARDS:
            with self.subTest(title=title):
                self.assertEqual(cat_ids(title, ADVERSARIAL_BODY), [want])

    def test_leathercraft_notice_never_becomes_competition(self):
        """用戶：「活動訓練都岩，因為佢1張通告入面有2個內容 但唔係比賽」。
        呢張舊數據嘅證據就係內文一個裸字「比賽」（另外仲有「成績公佈」），兩個而家
        都喺 BODY_UNTRUSTED_TERMS 入面 → 內文一律唔計，所以呢條路永久堵死，
        **唔使人手釘類別**。（如果份 PDF 真係寫明「XX錦標賽」呢類事件類型專有詞，
        內文 fallback 照樣可以判比賽——呢個係 2026-10-09 定低嘅「只信事件類型專有詞」
        設計，呢張通告實測冇。）"""
        real_body = "本會舉辦皮革藝術與生活展覽，設有作品比賽，成績公佈將於下月刊登"
        self.assertEqual(cat_ids("港島童軍皮藝會-皮革藝術與生活", real_body), ["announcement"])
        # 標題自己有賽事名時照舊比賽（唔會被「兩個內容」呢條規則食走）
        self.assertEqual(cat_ids("港島童軍皮藝會-皮革藝術與生活 – 首屆皮藝錦標賽"), ["competition"])

    def test_monthly_digest_regex_shape(self):
        self.assertTrue(MONTHLY_DIGEST_TITLE_RE.search(normalize("九龍地域通告【2026 年 10 月】")))
        # 「活動通告第21/26號」呢種掛檔號嘅唔會被誤傷（冇「年…月」結構）
        self.assertFalse(MONTHLY_DIGEST_TITLE_RE.search(normalize("划艇訓練班(活動通告第21/26號)")))

    def test_reference_document_covers_digest_family(self):
        for title in ("港島地域通告便覽(2026年10月)", "九龍地域9月份通告一覽",
                      "九龍地域通告【2026 年 10 月】"):
            with self.subTest(title=title):
                self.assertTrue(is_reference_document(title, ADVERSARIAL_BODY))


class ThreeWaySyncTests(unittest.TestCase):
    """三份規則要同步：`subscription_tagging`（權威）／`story_queue`／出圖台。
    出圖台（index.html BATCH_RE）由 `node test_batch_category.js` 釘住。"""

    TITLES = [t for t, _ in NAMED] + [t for t, _ in GUARDS]

    def test_story_queue_matches_subscription_tagging(self):
        """只比較**標題有規則證據**嘅個案。兩邊嘅兜底本來就唔同：訂閱分類兜底
        返「公布」，Story 清單兜底返「other」（＝唔出 Story），呢個係刻意設計。"""
        for title in self.TITLES:
            cats = extract_categories(title, "")
            if not cats or not cats[0].get("evidence"):
                continue
            with self.subTest(title=title):
                self.assertEqual(sq.classify_category({"title": title, "source_site": "x"}, None),
                                 cats[0]["id"])


class RepairedDataTests(unittest.TestCase):
    """數據層：`enrich.json` 入面嗰 8 張（連鏡像 key）要已經啱。"""

    @classmethod
    def setUpClass(cls):
        with ENRICH_PATH.open("r", encoding="utf-8") as fh:
            cls.enrich = json.load(fh)

    def test_named_entries_repaired(self):
        for frag, want in REPAIRED_FILES.items():
            hits = [(u, e) for u, e in self.enrich.items() if frag in u]
            self.assertTrue(hits, f"enrich.json 冇 {frag}")
            for url, entry in hits:
                with self.subTest(url=url):
                    got = [c.get("id") for c in (entry.get("categories") or [])]
                    if isinstance(want, tuple):        # 多個可接受答案
                        self.assertEqual(len(got), 1)
                        self.assertIn(got[0], want)
                    else:
                        self.assertEqual(got, [want])

    def test_whole_digest_family_is_announcement(self):
        checked = 0
        for url, entry in self.enrich.items():
            if not isinstance(entry, dict) or "categories" not in entry:
                continue
            title = str(entry.get("title") or "")
            if not (MONTHLY_DIGEST_TITLE_RE.search(normalize(title))
                    or "便覽" in title or "通告一覽" in title):
                continue
            checked += 1
            self.assertEqual([c.get("id") for c in (entry.get("categories") or [])],
                             ["announcement"], f"{title} @ {url}")
        self.assertGreater(checked, 30, f"digest 家族淨係驗到 {checked} 條，疑似篩選失靈")

    def test_no_mirror_url_divergence(self):
        """root cause 守門：同一份 PDF 嘅 www／冇 www 鏡像 entry 標籤必須一致。"""
        problems = enrich_mod.summarize_mirror_url_divergence(self.enrich)
        self.assertEqual(problems, [], f"有 {len(problems)} 組鏡像 entry 標籤分歧：{problems[:3]}")

    def test_canonical_key_keeps_query_string(self):
        """東九龍 `?wpdmdl=NNNN` 唔可以撞埋一齊（唔同 ID 係唔同檔）。"""
        a = enrich_mod.canonical_pdf_key("https://hkscout-ekr.org/circulars/download/?wpdmdl=5653")
        b = enrich_mod.canonical_pdf_key("https://www.hkscout-ekr.org/circulars/download/?wpdmdl=5654")
        self.assertNotEqual(a, b)
        c = enrich_mod.canonical_pdf_key("https://www.scout.org.hk/uploads/tc/circulars/26380/CircularList-2026-10.pdf")
        d = enrich_mod.canonical_pdf_key("https://scout.org.hk/uploads/tc/circulars/26380/CircularList-2026-10.pdf")
        self.assertEqual(c, d)

    def test_fix_script_is_idempotent(self):
        """第二次行（--dry-run）應該話零待改——否則補正 script 同規則有落差。"""
        out = subprocess.run([sys.executable, str(FIX_SCRIPT), "--dry-run"],
                             capture_output=True, text=True, cwd=str(BASE_DIR))
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        self.assertIn("已經乾淨", out.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
