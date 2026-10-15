#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性補正：2026-10-15 用戶點名嘅 8 張錯標籤＋成個「月度摘要」家族＋鏡像 URL 分歧。

用戶報告（「講番圖書館／錯標簽」，8 張）
--------------------------------------
1. 九龍地域 比賽 → **公布**「九龍地域通告【2026 年 10 月】」（26410/Summary_2026_10.pdf）
   根因：地域每月通告摘要，PDF 內文有「成績公佈」→ 輸咗畀「賽果＝比賽」呢條
   2026-10-01 規則。規則修復：MONTHLY_DIGEST_TITLE_RE（「…通告【YYYY 年 M 月】」
   形狀）入 `is_reference_document()`，參考文件永遠唔睇內文。
2. 九龍灣區 訓練 → **活動**「九灣小漁夫出海記-水上文化親子大冒險」（PT-15-26）
   根因：海報內文有「訓練班」搶走。規則修復：OTHER_ACTIVITY_TERMS 加「出海記／
   大冒險」（標題先決，但喺 title_decisive 之後——所以「森林大冒險…填色比賽」
   照樣係比賽；「親子」全库 69 筆大半係工作坊／比賽，刻意唔收）。
3. 港島地域 服務 → **活動**「探索歷史典藏、清真文化與創新科技之行」（26366）
4. 港島地域 服務 → **公布**「港島地域通告便覽(2026年10月)」（26380）
5. 港島地域 比賽 → **公布**「港島地域羽毛球會-招收2026-2027年度下半年新會員」（26369）
6. 港島地域 公布 → **訓練**「港島童軍生態小組-觀鳥章(興趣組)領袖座談會」（26363）
   3–6 呢四張**規則早就啱**（2026-10-09 兩批已 merge 咗），錯嘅係 `enrich.json`
   入面嘅存量數據（見下面「點解會有一舊一新一」）。
7. 港島地域 比賽 → 唔可以再係比賽：「港島童軍皮藝會-皮革藝術與生活」（26364）
   用戶：「活動訓練都啱，因為佢 1 張通告入面有 2 個內容，但唔係比賽」「中 1 個都係
   啱呀」→ **唔使人手釘類別**，只標記做人工確認過（HUMAN_CONFIRMED）跳過重算；
   而家入面嘅「活動」本身係該通告嘅內容之一。「比賽」呢條路已由
   BODY_UNTRUSTED_TERMS（內文嘅「比賽／錦標」一律唔計）永久堵死。
8. 總會 活動 → **公布**「寰宇童軍章(P109/2026)」（26401）
   標題冇「訓練班／工作坊／研習」等課程字眼 → 跟規則＝兜底公布。用戶只話「活動」係錯，
   冇指定正解，所以呢度只係清走舊數據嘅「活動」，並喺報告列明「章(Pxxx)」家族 9 筆
   等待用戶定政策（一條規則就搞掂，見 README「通告分類」）。

點解會有一舊一新一（根因，2026-10-15 查實）
--------------------------------------------
同一份 PDF 喺 `enrich.json` 有**兩個 key**：`https://scout.org.hk/...`（總會在列表頁
畀嘅 URL）同 `https://www.scout.org.hk/...`（地域站鏡像）。兩條 entry 各自由唔同次數
嘅 enrich run 寫入，所以可以各持唔同標籤——10-09 嗰批用咗新規則（啱），10-15 本機
排程嗰批用緊未 pull 嘅舊代碼（錯）。全库 4,433 條 entry 有 **219 組**呢種鏡像重複，
其中 **7 組兩邊標籤唔同**（用戶見到嘅錯標籤就係嗰 7 個 www 版本）。

`enrich.summarize_cross_source_consistency()` 淨係配「同標題＋同 captured_date」，
10-09 對 10-15 日期唔同 → 睇唔到呢個分歧。所以呢個腳本之後，該函數亦會**按正規化
PDF URL（除走 www.、連同 query string）再比多一輪**，日後本機／雲端邊個用舊規則覆寫
都會喺 run log 報出嚟。

修法
----
- PASS 1（用戶點名 8 張，兩邊鏡像都改）：用现行規則由**標題**重算。
- PASS 2（月度摘要家族）：標題命中「便覽／通告一覽／…通告【YYYY 年 M 月】」全库 45 筆（2025-10 至 2026-10，九龍地域／港島地域兩個來源）→ 一律公布。
- PASS 3（鏡像收歛）：正規化 URL 相同＋標題相同＋標籤唔同嘅組，全部跟標題規則收歛。
- PASS 4（人工確認過）：HUMAN_CONFIRMED 入面嘅 entry 一律跳過重算。

`cache.json` 冇 `categories` 欄（分類只存喺 `enrich.json`），所以呢個腳本只寫
`enrich.json`，唔郁 bot 每日重寫嘅 `cache.json`。

用法
----
    python fix_circulars_2026_10_15.py --dry-run   # 只睇會改咩
    python fix_circulars_2026_10_15.py             # 實際寫入 enrich.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from fix_rally_categories_2026_10_06 import patch_entry  # noqa: E402
from subscription_tagging import (  # noqa: E402
    MONTHLY_DIGEST_TITLE_RE,
    _term_hits,
    extract_categories,
    load_catalog,
    normalize,
)

ENRICH_PATH = BASE_DIR / "enrich.json"

HQ = "https://scout.org.hk/uploads/tc/circulars"
HQ_WWW = "https://www.scout.org.hk/uploads/tc/circulars"

# PASS 1：用戶點名嘅 8 張（URL 片段 → 期望類別）。兩邊鏡像（www／冇 www）都包括。
NAMED_FRAGMENTS = {
    "26410/Summary_2026_10.pdf": "announcement",          # 九龍地域通告【2026 年 10 月】
    "26401/P109-26.pdf": "announcement",                   # 寰宇童軍章(P109/2026)
    "26380/CircularList-2026-10.pdf": "announcement",      # 港島地域通告便覽(10月)
    "26369/Prog64_26_BadmintonClubMemberRecruit.pdf": "announcement",
    "26363/Prog62_26_BirdwatcherSeminar.pdf": "training",  # 觀鳥章領袖座談會
    "26366/I_MA04_26_Shenzhen.pdf": "activity",            # 探索…之行
    "26372/I_MA04a_26_Shenzhen_form.pdf": "activity",      # 同件嘅報名表格跟主件（總會版）
    # ⚠️ 報名表格呢張兩邊鏡像嘅檔案編號唔同（總會 26372／港島地域 26367），
    # 所以兩個都要列——否則 PASS 3 個「正規化 URL 相同」永遠配唔到，錯嗰半就留低。
    "26367/I_MA04a_26_Shenzhen_form.pdf": "activity",
}
KLB = "https://www.hkscout-klb.org/web2017/assets/kb_documents/notice/2026/PT-15-26.pdf"
NAMED_FRAGMENTS[KLB] = "activity"                           # 九灣小漁夫出海記

# PASS 4（用戶 2026-10-15 澄清）：**唔使人手釘類別**。
# 「港島童軍皮藝會-皮革藝術與生活」一張通告有兩份內容（展覽＋比賽／工作坊），
# 用戶：「中 1 個都係啱呀」→ 所以唔需要 MANUAL_OVERRIDES 呢類硬釘，只要唔好係
# 「比賽」（舊數據俾內文比賽字眼搶咗）就得。而家入面嘅「活動」係該通告自己嘅
# 內容之一，所以呢度只係**標記做人工確認過、跳過重算**（`patch_entry` 淨係用
# 標題計，呢類標題冇類別字眼會俾佢變兜底公布，反而多餘）。日後真正重跑
# `enrich.py`（有 PDF 內文）判到活動定訓練都啱，兩個都唔會再變比賽：
# 「比賽／錦標」早就喺 BODY_UNTRUSTED_TERMS 入面，內文一律唔計。
HUMAN_CONFIRMED = {
    "26364/Prog63_26_LeathercraftExhibition2027.pdf":
        "用戶 2026-10-15 確認：一張通告兩個內容，中其中一個都啱（只要求唔係比賽）",
}

DIGEST_TITLE_TERMS = ["便覽", "通告一覽"]
# 檔名要係「CircularList-2026-10.pdf」／「Summary_2026_10.pdf」呢種**帶年月**嘅形狀，
# 唔可以係「見過 summary 三個字」（「…收支結算表 Summary_IE_2025-26.pdf」都係 Summary
# 開頭，但嗰張係數表，唔係通告摘要）。
DIGEST_FILENAME_RE = re.compile(r"/(?:circularlist|summary)[-_]\d{4}[-_]\d{1,2}\.pdf(?:$|\?)", re.I)


def canonical_pdf_key(url: str) -> str:
    """鏡像 URL 正規化：除走 host 嘅 `www.`、host＋path 細階化，**保留 query**
    （東九龍地域嘅 `?wpdmdl=NNNN` 係唔同檔，唔可以撞埋一齊）。"""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return str(url or "")
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = parts.query.lower()
    return f"{host}{parts.path.lower()}{'?' + query if query else ''}"


def is_digest_title(title: str) -> bool:
    return bool(_term_hits(title, DIGEST_TITLE_TERMS)
                or MONTHLY_DIGEST_TITLE_RE.search(normalize(title)))


def collect_targets(enrich: dict) -> list[tuple[str, str, str]]:
    """回傳 [(url, 原因, 期望類別 or ''（由規則決定）)]。"""
    targets: dict[str, str] = {}

    def is_human_confirmed(url: str) -> bool:
        return any(frag in url for frag in HUMAN_CONFIRMED)

    # PASS 1：用戶點名（人工確認過嘅跳過，見上面 HUMAN_CONFIRMED）
    for url, entry in enrich.items():
        if not isinstance(entry, dict) or is_human_confirmed(url):
            continue
        for frag, want in NAMED_FRAGMENTS.items():
            if frag in url:
                targets[url] = f"用戶點名（{want}）"
    # 出海記嗰張唔係 scout.org.hk 格式，逐條再捉一次（萬一 URL 有變）
    for url, entry in enrich.items():
        title = str((entry or {}).get("title") or "") if isinstance(entry, dict) else ""
        if "小漁夫出海記" in title and not is_human_confirmed(url):
            targets[url] = "用戶點名（活動）"

    # PASS 2：月度摘要家族
    for url, entry in enrich.items():
        if not isinstance(entry, dict) or url in targets or is_human_confirmed(url):
            continue
        title = str(entry.get("title") or "")
        if not title:
            continue
        if is_digest_title(title) or DIGEST_FILENAME_RE.search(url):
            if [c.get("id") for c in (entry.get("categories") or [])] != ["announcement"]:
                targets[url] = "月度摘要家族（便覽／通告一覽／…通告【年月】＝公布）"

    # PASS 3：鏡像收歛
    groups: dict[str, list[str]] = defaultdict(list)
    for url, entry in enrich.items():
        if isinstance(entry, dict):
            groups[canonical_pdf_key(url)].append(url)
    # 註：HUMAN_CONFIRMED 嘅兩邊鏡像都已經唔會俾收歛改（下面逐條再 filter 一次）
    for _, urls in groups.items():
        if len(urls) < 2:
            continue
        sigs = {tuple(sorted(c.get("id", "") for c in (enrich[u].get("categories") or [])))
                for u in urls}
        if len(sigs) < 2:
            continue
        titles = {str(enrich[u].get("title") or "") for u in urls}
        if len(titles) != 1:
            continue                              # 唔係同一份內容，唔好亂撞
        title = titles.pop()
        if not title_is_decisive(title):
            continue
        for u in urls:
            targets.setdefault(u, f"鏡像分歧收歛（{title[:20]}…）")
    return [(u, why, "") for u, why in targets.items()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只報告，唔寫檔")
    args = ap.parse_args(argv)

    catalog = load_catalog()
    with ENRICH_PATH.open("r", encoding="utf-8") as fh:
        enrich = json.load(fh)

    targets = collect_targets(enrich)
    changed = 0
    for url, why, _want in targets:
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            continue
        patched, note = patch_entry(entry, catalog)
        if not note:
            continue
        changed += 1
        print(f"  [{why}] {entry.get('source', '?')}｜{title}\n     {note}\n     {url}")
        if not args.dry_run:
            enrich[url] = patched

    if not changed:
        print("✅ 已經乾淨：點名嘅 8 張、月度摘要家族同鏡像 entry 全部同現行規則一致。")
        return 0

    if args.dry_run:
        print(f"\n（dry-run：以上 {changed} 條未寫入；要真改請去掉 --dry-run）")
        return 0

    with ENRICH_PATH.open("w", encoding="utf-8") as fh:
        json.dump(enrich, fh, ensure_ascii=False, indent=2)
    print(f"\n✅ 已更新 {changed} 條 → {ENRICH_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
