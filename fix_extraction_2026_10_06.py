#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性修復：2026-10-06 東九龍地域批次嘅標題／標籤／截止日污染。

背景（用戶報告：「這些通告的抽取都這麼奇怪，標簽也有問題」）
--------------------------------------------------------------
當日 05:07 嘅 enrich run 對 4 條通告做咗「標題更正」，其中 3 條改錯咗，
1 條改咗但改得唔夠準：

1. `26243/Sea-Activities_Calendar_26-27-Oct-Jan_se.pdf`
   列表標題：香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月)活動與訓練行事曆
   被改成：  2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰
   原因：呢份行事曆嘅大標題係圖，pdfplumber 抽到嘅第一批文字係表格列；
        表格列含「訓練班」而喺 hint 加分贏咗，再被寫返 cache.json。
   連帶後果：行事曆唔再被 is_reference_document() 認出 → 分類變「訓練」，
        內文（表格列出成個季度活動）嘅課程全部變成訂閱標籤。

2. `26244/SING-Activities_Calendar_26-27_Oct---Jan__se.pdf`
   列表標題：香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月) 賽馬會童「SING」匯航計劃 - 活動與訓練行事曆
   被改成：  13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰
   原因同上（表格列）；連帶後果同上（錯分類＋亂標籤）。

3. `26242/SA71.pdf`（東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班）
   列表標題被縮短成 PDF 標題「地質生態導賞員訓練班」，唔見咗計劃名。
   原因：舊版 reconcile 要求相似度 ≥90%，10/31 字嘅子字串只有 0.32 → 當「列表標題錯」。
   （新版 heading_contained_in_listing() 已經唔會再縮短。）

4. `26239/SA69.pdf`（三級童軍標準艇訓練班）／26242 嘅截止日抽錯：
   兩個都會期表都係表格，舊版 3 行窗口攞第一個日期＝第一堂日期：
     26239 → 抽到 2027-01-02，真截止日 2026-12-11（表格「截止日期」欄／東九龍地域
             網頁「截止報名」欄都係 2026-12-11）
     26242 → 抽到 2027-01-13，真截止日 2026-12-19（同上）
   26239 嘅費用喺表格「費用($)」欄（160），內文冇「費用：」label，舊版抽唔到。

程式碼修復（enrich.py 3.4／subscription_tagging.py）
----------------------------------------------------
    - looks_like_table_row()：表格列唔可以當標題（亦寫入 heading_looks_like_title）
    - reconcile_listing_title()：PDF metadata 標題確認 + 列表標題係 PDF 標題超集時維持
    - deadline_from_tables() / fee_from_tables()：直接讀表格欄
    - collect_targets()：接受 ?wpdmdl= 下載連結（東九龍地域一直冇 enrich）
    - 分類：標題有明確活動字眼時以標題為準（獎券籌募活動唔再被內文「比賽」搶走）
    - 課程標籤：唔再由「持有…資歷／由…擔任」呢類資格句抽出

第二批（同日，以今日通告為例）程式碼修復
----------------------------------------
    - extract_deadline()：「（日期）…或之前（交回／遞交／提交／電郵…）」冇「截止」
      兩個字都抽得到（26228 獎券活動 → 2026-11-30）；日期同動作唔可以跨句號／分號，
      所以「每年 6 月 30 日前提交」＋下一段「2026 年 10 月 31 日呈交」唔會亂抽（26227）。
    - extract_fee()：加「售價」標籤（盲盒訂購 → HK$50）。
    - extract_audience()：參加資格係（1）（2）（3）多行清單時全部讀（26241 唔會漏
      「持有有效委任狀之會務委員」）。
    - 分類：標題有「嘉許計劃」＝公布（26232 唔會再被內文「服務記錄」搶去服務）；
      標題只有參考文件字眼（名單／行事曆／章程／指引）＝公布（26231 唔會再被內文
      「服務精神」搶去服務）；「成績公布」等賽果仍然係比賽。

呢支 script 只負責清走／補返已經寫入 cache.json / enrich.json 嘅資料，零下載。

用法
----
    python fix_extraction_2026_10_06.py --dry-run   # 只睇會改咩
    python fix_extraction_2026_10_06.py             # 實際寫入

（可重複執行：第二次 run 會顯示「已經乾淨」。）

第二批（今日通告）會做三件事：
    6. 按新規則重算分類／標籤：26232 → 公布、26231 → 公布
    7. 補 26228／26229 嘅截止日 2026-11-30（人手核對 PDF 全文）
    8. 補 26241 對象（會務委員）
另外會【撤回】之前版本由「孖生」通告搬過去嘅 15 條東九龍地域 entry：
每條通告要如實反映自己嘅來源，唔可以借用另一個來源嘅抽取結果；
（2026-10-06 用戶指正：「這不對，是從那來就如實反映」）
正確做法係 enrich.py 自己下載（?wpdmdl= 已經支援，增量有 7 日補漏窗）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from subscription_tagging import extract_subscription_metadata, load_catalog

BASE_DIR = Path(__file__).parent
CACHE_PATH = BASE_DIR / "cache.json"
ENRICH_PATH = BASE_DIR / "enrich.json"

HQ = "https://scout.org.hk/uploads/tc/circulars"
SEA_CALENDAR = f"{HQ}/26243/Sea-Activities_Calendar_26-27-Oct-Jan_se.pdf"
SING_CALENDAR = f"{HQ}/26244/SING-Activities_Calendar_26-27_Oct---Jan__se.pdf"
GEO_TOUR = f"{HQ}/26242/SA71.pdf"
BOAT_LEVEL3 = f"{HQ}/26239/SA69.pdf"

# url → 由列表頁（即用戶應該見到嘅名）還原嘅標題
TITLE_BY_URL = {
    SEA_CALENDAR: "香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月)活動與訓練行事曆",
    SING_CALENDAR: "香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月) 賽馬會童「SING」匯航計劃 - 活動與訓練行事曆",
    GEO_TOUR: "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
}

# url → (截止日, 費用)；由 PDF 表格「截止日期」／「費用($)」欄核實
TABLE_FIELDS = {
    BOAT_LEVEL3: {"deadline": "2026-12-11", "fee": "HK$160"},
    GEO_TOUR: {"deadline": "2026-12-19", "fee": ""},
}

# url → 唔應該存在嘅課程標籤（只喺「資格／工作人員」句出現，唔係通告主題）
NOISE_COURSES = {
    GEO_TOUR: "course:leader-canoe-instructor",
    BOAT_LEVEL3: "course:leader-standard-boat-instructor",
}

# 5. 2027年童軍獎券籌募活動（Adm25）被 PDF 內文「獎券銷售獎勵比賽」搶去「比賽」，
#    但同一個活動嘅回條（Adm25-app）一直係「活動」——同一件事兩個標籤。
#    新版分類規則以標題為準，呢度按新規則重算兩個 copy（標題已有齊資料，毋須下載）。
RAFFLE_URLS = {
    f"{HQ}/26228/Adm25.pdf": "2027年童軍獎券籌募活動",
    f"{HQ}/26229/Adm25-app.pdf": "2027年童軍獎券籌募活動 - 回條",
}

# ── 第二批（同日）：今日通告本身 ─────────────────────────────────
# 6. 分類重算（標題已足夠，毋須內文）：兩條「同一類文件唔同標籤」個案
#    （2026-10-06 最新規則：標題有『嘉許計劃』／參考文件字眼（名單…）＝公布）
TODAY_TITLE_RECOMPUTE = {
    # 內文「前線領袖在童軍旅的服務記錄」搶去「服務」→ 公布
    # （同一計劃嘅附錄 26233 同 2026 年獲嘉許名單 26230 都係公布）
    f"{HQ}/26232/Adm28.pdf": "卓越領袖嘉許計劃2027",
    # 內文「無私奉獻的服務精神」搶去「服務」→ 公布（同 26230 一致）
    f"{HQ}/26231/Adm27.pdf": "傑出表現成員地域總監嘉許2026 - 獲嘉許名單",
}

# 7. 人手核實欄位（PDF 全文已逐字核對）：Adm25／Adm25-app 內文寫「必須於
#    2026 年 11 月 30 日（星期一）或之前填妥夾附回條，交回東九龍地域總部辦事處」，
#    舊版因為冇「截止」兩個字而抽唔到。新版 extract_deadline 已經認得呢種寫法
#    （見 test_enrich.py），呢度係幫今日已入庫嘅記錄補返。
TODAY_CURATED_FIELDS = {
    f"{HQ}/26228/Adm25.pdf": {"deadline": "2026-11-30"},
    f"{HQ}/26229/Adm25-app.pdf": {"deadline": "2026-11-30"},
}

# 8. 人手核實對象（PDF 全文已核對）：26241「一個石籃的故事」嘅「參加資格」係
#    （1）幼童軍、童軍、深資童軍及樂行童軍支部成員（2）各級領袖（3）會務委員
#    （4）親友（5）各界人士；舊版只讀 label 之後 2 行，漏咗會務委員。
#    新版 extract_audience 會讀埋（1）（2）（3）… 清單（見 test_enrich.py），
#    呢度係幫今日已入庫嘅記錄補返，並同時重算支部標籤。
TODAY_CURATED_AUDIENCE = {
    f"{HQ}/26241/SA70.pdf": "幼童軍、深資童軍、樂行童軍、童軍、領袖、會務委員",
}

# 8. 【撤回】唔可以由「孖生」通告搬欄位。
#    2026-10-06 傍晚曾經咁樣做過（東九龍地域 14 條 ?wpdmdl= 由總會站同一份通告
#    抄 deadline／fee／標籤，並記低 derived_from）——用戶指正：每條通告要如實
#    反映自己嘅來源，唔可以借用另一個來源嘅抽取結果。正確做法係修好管線，
#    令兩份都由自己嘅 PDF 抽（見 enrich.py is_enrichable_url / 7 日補漏窗）。
#    所以：凡係有 `derived_from` 嘅 entry（＝由呢支 script 之前版本製造）一律刪除，
#    等下一次 enrich run 自己下載返。
DERIVED_KEY = "derived_from"


def find_cache_items(cache, url):
    """cache.json 有兩份通告：分組嘅 `data`（前端主用）同扁平嘅 `notices`
    （notify.py／check_local_gain.py／fix_tko_notice_urls.py 等工具用），
    兩份都要改——core.py 每次重建都會寫齊兩份（見 apply_title_to_cache）。"""
    out = []
    for arr in (cache.get("data") or {}).values():
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, dict) and (item.get("pdf_url") or item.get("url")) == url:
                    out.append(item)
    for item in cache.get("notices") or []:
        if isinstance(item, dict) and (item.get("pdf_url") or item.get("url")) == url:
            out.append(item)
    return out


def recompute_reference_tags(title):
    """行事曆類（參考文件）嘅標籤：只有 category:announcement，唔會有內文課程標籤。

    呢批通告嘅 PDF 文字層只有表格，冇必要為咗重算而重新下載；
    is_reference_document() 係靠標題「行事曆」判定，所以標題就夠。
    """
    meta = extract_subscription_metadata(title, "")
    return meta["categories"], meta["branch_tags"], meta["subscription_tags"], meta["subscription_tag_details"]


def drop_noise_tag(entry, topic_id):
    tags = list(entry.get("subscription_tags") or [])
    if topic_id not in tags:
        return False
    entry["subscription_tags"] = [tag for tag in tags if tag != topic_id]
    entry["subscription_tag_details"] = [
        d for d in (entry.get("subscription_tag_details") or []) if str(d.get("id")) != topic_id
    ]
    return True


def main():
    ap = argparse.ArgumentParser(description="修復 2026-10-06 東九龍批次嘅標題／標籤／截止日")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會改咩，唔寫檔")
    args = ap.parse_args()

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    catalog = load_catalog()
    changes = []

    for url, title in TITLE_BY_URL.items():
        for item in find_cache_items(cache, url):
            if item.get("title") != title:
                changes.append(f"cache.json 標題：{item.get('title')} → {title}")
                item["title"] = title

        entry = enrich.get(url)
        if isinstance(entry, dict):
            if entry.get("title") != title:
                changes.append(f"enrich.json 標題：{entry.get('title')} → {title}")
                entry["title"] = title
            if entry.get("title_check") != "verified":
                changes.append(f"enrich.json title_check：{entry.get('title_check')} → verified")
                entry["title_check"] = "verified"

        if url in (SEA_CALENDAR, SING_CALENDAR) and isinstance(entry, dict):
            cats, branches, tags, details = recompute_reference_tags(title)
            if entry.get("subscription_tags") != tags:
                changes.append(
                    f"enrich.json 訂閱標籤（行事曆＝參考文件）：{entry.get('subscription_tags')} → {tags}"
                )
            entry["categories"] = cats
            entry["branch_tags"] = branches
            entry["subscription_tags"] = tags
            entry["subscription_tag_details"] = details
            entry["subscription_catalog_version"] = str(catalog.get("version", ""))

    for url, fields in TABLE_FIELDS.items():
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            continue
        for key, value in fields.items():
            if value and entry.get(key) != value:
                changes.append(f"enrich.json {key}（表格欄）：{entry.get(key) or '—'} → {value}")
                entry[key] = value

    for url, topic_id in NOISE_COURSES.items():
        entry = enrich.get(url)
        if isinstance(entry, dict) and drop_noise_tag(entry, topic_id):
            changes.append(f"enrich.json 移除課程標籤（只喺資格／工作人員句出現）：{topic_id}")

    def apply_title_categories(url, title):
        """按標題重算分類／訂閱標籤（保留原有支部標籤，因為標題＋對象先抽得出）。"""
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            return
        meta = extract_subscription_metadata(title, "", entry.get("audience", ""))
        if entry.get("categories") != meta["categories"]:
            before = [c.get("label") for c in (entry.get("categories") or [])] or ["—"]
            after = [c.get("label") for c in meta["categories"]] or ["—"]
            changes.append(f"enrich.json 分類（標題為準）：{'／'.join(before)} → {'／'.join(after)} | {title}")
        entry["categories"] = meta["categories"]
        entry["branch_tags"] = sorted(set(entry.get("branch_tags") or []) | set(meta["branch_tags"]))
        entry["subscription_tags"] = meta["subscription_tags"]
        entry["subscription_tag_details"] = meta["subscription_tag_details"]
        entry["subscription_catalog_version"] = str(catalog.get("version", ""))

    for url, title in RAFFLE_URLS.items():
        apply_title_categories(url, title)

    # ── 第二批（同日）：今日通告 ──
    for url, title in TODAY_TITLE_RECOMPUTE.items():
        apply_title_categories(url, title)

    for url, fields in TODAY_CURATED_FIELDS.items():
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            continue
        for key, value in fields.items():
            if value and entry.get(key) != value:
                changes.append(f"enrich.json {key}（『…或之前交回』句，人手核實）：{entry.get(key) or '—'} → {value}")
                entry[key] = value

    for url, audience in TODAY_CURATED_AUDIENCE.items():
        entry = enrich.get(url)
        if not isinstance(entry, dict):
            continue
        if entry.get("audience") != audience:
            changes.append(f"enrich.json 對象（附件資格清單第 (3) 項，人手核實）：{entry.get('audience') or '—'} → {audience}")
            entry["audience"] = audience
        meta = extract_subscription_metadata(entry.get("title") or "", "", audience)
        if entry.get("branch_tags") != sorted(set(entry.get("branch_tags") or []) | set(meta["branch_tags"])):
            entry["branch_tags"] = sorted(set(entry.get("branch_tags") or []) | set(meta["branch_tags"]))
            changes.append(f"  ↳ 重算支部標籤：{entry['branch_tags']}")

    # 【撤回】刪除之前由「孖生」搬過去嘅 entry（見上面第 8 點）：
    # 每份通告要如實反映自己嘅來源，等 enrich（已支援 ?wpdmdl=）自己抽。
    for url in [u for u, v in enrich.items()
                if isinstance(v, dict) and DERIVED_KEY in v]:
        title = (enrich.get(url) or {}).get("title") or ""
        del enrich[url]
        changes.append(f"enrich.json 刪除搬字過紙 entry（等自己做 enrich）：{title[:34]}")

    # 東九龍地域（?wpdmdl=）：唔會再由總會站搬欄位——正確做法係 enrich.py
    # 自己下載（is_enrichable_url 接受 ?wpdmdl=，增量模式有 7 日補漏窗）。

    if not changes:
        print("✅ 已經乾淨，冇嘢要改。")
        return

    for line in changes:
        print(" •", line)
    print(f"\n合共 {len(changes)} 項修改。")

    if args.dry_run:
        print("（--dry-run：未寫入任何檔案）")
        return

    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ENRICH_PATH.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"📝 已更新 {CACHE_PATH.name} + {ENRICH_PATH.name}")


if __name__ == "__main__":
    main()
