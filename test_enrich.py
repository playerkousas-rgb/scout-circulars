#!/usr/bin/env python3
"""
test_enrich.py — enrich.py 準確性單元測試
============================================================
重點：驗證「寧願漏抽，絕不亂抽」原則。
運行：python test_enrich.py
"""

import sys
sys.path.insert(0, ".")

from enrich import (
    extract_audience, extract_deadline, extract_fee, normalize_fee, extract_categories,
    compact_title, title_similarity, extract_pdf_heading, reconcile_listing_title,
    apply_title_to_cache, title_variants, listing_supported_by_pdf,
    heading_looks_like_title, reapply_stored_title_fixes,
    looks_like_table_row, deadline_from_tables, fee_from_tables,
    is_enrichable_url, skip_reason, summarize_skipped_links, collect_targets,
    TITLE_SIMILARITY_THRESHOLD, INCREMENTAL_CATCHUP_DAYS,
)
from subscription_tagging import extract_subscription_metadata, load_catalog


# Keep results independently from the arithmetic used by callers.  ``False``
# adds zero to an integer, so the old harness printed a misleading all-pass
# result even after a failed assertion.
TEST_RESULTS = []


def test(name, got, want):
    ok = got == want
    TEST_RESULTS.append(ok)
    tag = "✅" if ok else "❌"
    print(f"{tag} {name}")
    if not ok:
        print(f"   期望: {want!r}")
        print(f"   實際: {got!r}")
    return int(ok)


def main():
    passed = 0

    # ── 對象：必須有明確 label，否則寧願空 ──
    passed += test(
        "對象：無 label 時不亂抽",
        extract_audience("本活動不適合深資童軍及樂行童軍參加。"),
        "",
    )
    passed += test(
        "對象：有 label 時正確抽取",
        extract_audience("參加資格：深資童軍及樂行童軍\n費用：HK$50"),
        "深資童軍、樂行童軍",
    )
    passed += test(
        "對象：由窄到闊，避免童軍吃掉幼童軍",
        extract_audience("參加對象：幼童軍、童軍"),
        "幼童軍、童軍",
    )

    # ── 截止日期：必須有『截止』，否則寧願空 ──
    passed += test(
        "截止：無截止字樣時不抽",
        extract_deadline("報名日期：2026-08-01\n活動日期：2026-08-15"),
        "",
    )
    passed += test(
        "截止：有截止日期 label",
        extract_deadline("截止日期：2026年8月1日"),
        "2026-08-01",
    )
    passed += test(
        "截止：有截止報名日期 label",
        extract_deadline("截止報名日期：2026/8/1"),
        "2026-08-01",
    )

    # ── 費用：全免要明確，雙金額不亂判資助 ──
    passed += test(
        "費用：全免",
        extract_fee("費用：全免"),
        "全免",
    )
    passed += test(
        "費用：免費",
        extract_fee("費用：免費"),
        "全免",
    )
    passed += test(
        "費用：兩個金額但無資助提示，顯示兩個",
        extract_fee("費用：領袖 HK$200 / 童軍 HK$100"),
        "HK$200 / HK$100",
    )
    passed += test(
        "費用：兩個金額且有資助提示，取細價",
        extract_fee("費用：原價 HK$200，半費資助後 HK$100"),
        "HK$100",
    )
    passed += test(
        "費用：豁免唔等於全免，寧願空",
        extract_fee("費用：可向主辦單位申請豁免"),
        "",
    )

    # ── 分類：先睇標題，標題唔肯定先至用內文 ──
    passed += test(
        "標題：有「訓練班」直接判 training（內文空都得）",
        [c["id"] for c in extract_categories("童軍繩結訓練班(P88/2026)", "")],
        ["training"],
    )
    passed += test(
        "標題：有「社區服務」直接判 service",
        [c["id"] for c in extract_categories("社區服務隊招募", "")],
        ["service"],
    )
    passed += test(
        "標題：有「公開賽」歸獨立 competition",
        [(c["id"], c.get("subtype")) for c in extract_categories("射箭公開賽2026", "")],
        [("competition", None)],
    )
    passed += test(
        "比賽不會因大露營字眼混入活動",
        [c["id"] for c in extract_categories("童軍大露營比賽", "")],
        ["competition"],
    )
    passed += test(
        "標題：冇強證據（'訓練日'係弱證據）→ 用內文判斷",
        [c["id"] for c in extract_categories("童軍訓練日", "參加資格：童軍\n訓練班：繩結訓練班")],
        ["training"],
    )
    passed += test(
        "標題：出現排除詞『訓練行事曆』→ 唔會因為內文有訓練班而分類，歸公佈",
        [c["id"] for c in extract_categories("活動與訓練行事曆", "訓練班：繩結訓練班")],
        ["announcement"],
    )

    # 內文判斷（標題空／弱時先使用）
    passed += test(
        "內文：標題空但有訓練班 → training",
        [c["id"] for c in extract_categories("", "參加資格：童軍\n訓練班：繩結訓練班\n費用：HK$50")],
        ["training"],
    )
    passed += test(
        "內文：標題空但有社區服務 → service",
        [c["id"] for c in extract_categories("", "活動性質：社區服務\n服務日：2026-09-20")],
        ["service"],
    )
    passed += test(
        "內文：標題空但有公開賽 → 獨立 competition",
        [(c["id"], c.get("subtype")) for c in extract_categories("", "全港公開賽\n日期：2026-09-20")],
        [("competition", None)],
    )
    passed += test(
        "內文：標題及內文都冇清楚字眼 → 兜底歸公佈",
        [c["id"] for c in extract_categories("", "只係一般通告\n下載附件")],
        ["announcement"],
    )
    passed += test(
        "內文：有「訓練行事曆」唔當訓練班，歸公佈",
        [c["id"] for c in extract_categories("", "活動與訓練行事曆\n一覽表")],
        ["announcement"],
    )

    # ── 個人化受控 tag：核心名稱／正式變體而非後綴逐字比較 ──
    aircrew_workshop = extract_subscription_metadata("童軍初級空勤章工作坊")
    passed += test(
        "受控課程：初級空勤章工作坊命中初級空勤員章 + 訓練",
        (aircrew_workshop["branch_tags"], aircrew_workshop["subscription_tags"]),
        (["童軍"], ["category:training", "course:scout-basic-aircrew-badge", "training:童軍"]),
    )
    aircrew_class = extract_subscription_metadata("童軍初級空勤員章訓練班")
    passed += test(
        "受控課程：初級空勤員章訓練班命中相同核心項目",
        aircrew_class["subscription_tags"],
        ["category:training", "course:scout-basic-aircrew-badge", "training:童軍"],
    )
    venture_aircrew = extract_subscription_metadata("第1屆初級空勤員章訓練班", "", "深資童軍")
    passed += test(
        "同名徽章按對象支部分流：深資空勤員章不會標成童軍所有訓練",
        (venture_aircrew["branch_tags"], venture_aircrew["subscription_tags"]),
        (["深資童軍"], ["category:training", "course:scout-basic-aircrew-badge", "training:深資童軍"]),
    )
    cub_first_aid = extract_subscription_metadata("幼童軍急救章訓練班")
    passed += test(
        "同名徽章只命中該支部版本（幼童軍急救章≠童軍急救章）",
        cub_first_aid["subscription_tags"],
        ["category:training", "course:cub-first-aid-badge", "training:幼童軍"],
    )
    passed += test(
        "較長官方名稱不誤中較短徽章（滑浪風帆章≠風帆章、教練員班≠青少年徽章）",
        (
            extract_subscription_metadata("童軍滑浪風帆章訓練班")["subscription_tags"],
            extract_subscription_metadata("第16屆中級航空活動章教練員訓練班", "", "領袖")["subscription_tags"],
        ),
        (
            ["category:training", "course:scout-windsurfing-badge", "training:童軍"],
            ["category:training", "course:leader-air-activity-instructor", "training:領袖:非木章"],
        ),
    )
    wood = extract_subscription_metadata("第109屆童軍運動基本原則訓練班(單元 1A 及 單元1B)", "", "童軍、領袖")
    passed += test(
        "木章單元命中木章訓練班，而非非木章",
        wood["subscription_tags"],
        ["category:training", "course:wood-module-1", "training:童軍", "training:領袖:木章"],
    )
    passed += test(
        "支部訓練方法只命中該支部單元",
        extract_subscription_metadata("第8屆幼童軍支部訓練方法訓練班(單元2A及單元2B)", "", "領袖")["subscription_tags"],
        ["category:training", "course:wood-module-2-cub", "training:領袖:木章"],
    )
    passed += test(
        "領袖技能訓練班命中非木章，不命中木章",
        extract_subscription_metadata("第48屆行動主導領導才訓練班", "", "領袖")["subscription_tags"],
        ["category:training", "course:leader-action-centred-leadership", "training:領袖:非木章"],
    )
    passed += test(
        "童軍領導才訓練班是童軍特別項目",
        extract_subscription_metadata("沙田西區 - 第590屆童軍領導才訓練班", "", "童軍")["subscription_tags"],
        ["category:training", "course:scout-leadership", "training:童軍"],
    )
    passed += test(
        "服務不因泛稱活動同時命中其他活動",
        extract_subscription_metadata("童軍社區服務活動")["subscription_tags"],
        ["category:service"],
    )
    passed += test(
        "營火會只命中活動 campfire 子類",
        extract_subscription_metadata("童軍營火會")["subscription_tags"],
        ["activity:campfire"],
    )
    passed += test(
        "比賽只命中獨立比賽 tag，不混入活動",
        extract_subscription_metadata("童軍射箭公開賽")["subscription_tags"],
        ["category:competition"],
    )
    catalog = load_catalog()
    labels = {entry["id"]: entry["label"] for entry in catalog["topics"]}
    passed += test(
        "受控選單只顯示基礎項目名稱",
        (labels["course:leader-map-reading"], labels["course:scout-basic-aircrew-badge"]),
        ("地圖閱讀", "初級空勤員章"),
    )
    passed += test(
        "受控課程選項沒有訓練班／工作坊／課程後綴",
        all(not str(entry["label"]).endswith(("訓練班", "工作坊", "課程", "訓練"))
            for entry in catalog["topics"] if entry.get("kind") == "course"),
        True,
    )
    passed += test(
        "地圖閱讀訓練班與工作坊自動命中同一基礎項目",
        (
            extract_subscription_metadata("領袖地圖閱讀訓練班")["subscription_tags"],
            extract_subscription_metadata("領袖地圖閱讀工作坊")["subscription_tags"],
        ),
        (
            ["category:training", "course:leader-map-reading", "training:領袖:非木章"],
            ["category:training", "course:leader-map-reading", "training:領袖:非木章"],
        ),
    )
    passed += test(
        "訓練行事曆唔會當訓練班，變成可剔走嘅公佈 tag",
        extract_subscription_metadata("童軍訓練班一覽表")["subscription_tags"],
        ["category:announcement"],
    )

    # ── 列表標題 vs PDF 雙重認證（寧願不改，不要亂改）──
    merit = "「2027年功績獎勵及感謝狀提名 - 區會提名截止日期」通告"
    fire = "「深資童軍消防訓練班」通告"
    merit_pdf = (
        "香港童軍總會\n"
        "屯門東區\n"
        "2026年9月14日\n"
        "「2027年功績獎勵及感謝狀提名 - 區會提名截止日期」通告\n"
        "參加資格：本區各旅旅長\n"
        "截止日期：2026年10月9日\n"
    )
    fire_pdf = (
        "香港童軍總會\n"
        "「深資童軍消防訓練班」通告\n"
        "參加資格：已完成深資童軍肩章之深資童軍成員\n"
        "截止日期：2026年10月14日\n"
    )
    passed += test(
        "標題正規化：引號／通告後綴唔影響比較",
        compact_title(merit) == compact_title("2027年功績獎勵及感謝狀提名區會提名截止日期"),
        True,
    )
    passed += test(
        "相似：同一通告加引號 ≥ 90%",
        title_similarity(merit, "2027年功績獎勵及感謝狀提名 - 區會提名截止日期") >= TITLE_SIMILARITY_THRESHOLD,
        True,
    )
    passed += test(
        "相似：功績 vs 消防遠低於 90%",
        title_similarity(merit, fire) < 0.5,
        True,
    )
    passed += test(
        "PDF 標題：跳過信頭，取通告名",
        extract_pdf_heading(merit_pdf),
        merit,
    )
    passed += test(
        "對證：列表正確 → 維持",
        reconcile_listing_title(merit, merit_pdf)["status"],
        "verified",
    )
    stolen = reconcile_listing_title(fire, merit_pdf)
    passed += test(
        "對證：列表抄咗消防班、PDF 係功績 → 改正",
        (stolen["status"], stolen["title"]),
        ("corrected", merit),
    )
    passed += test(
        "對證：PDF 太少字 → 唔改",
        reconcile_listing_title(fire, "abc")["status"],
        "unverified",
    )
    cache = {
        "data": {"屯門東區": [
            {"title": fire, "pdf_url": "https://example/TME_A_26_03.pdf", "captured_date": "2026-09-13"},
        ]},
        "notices": [
            {"title": fire, "pdf_url": "https://example/TME_A_26_03.pdf", "captured_date": "2026-09-13"},
        ],
    }
    passed += test(
        "寫回 cache：只改 title，唔改 url／日期",
        (
            apply_title_to_cache(cache, "https://example/TME_A_26_03.pdf", merit),
            cache["data"]["屯門東區"][0]["title"],
            cache["data"]["屯門東區"][0]["pdf_url"],
            cache["data"]["屯門東區"][0]["captured_date"],
            cache["notices"][0]["title"],
        ),
        (True, merit, "https://example/TME_A_26_03.pdf", "2026-09-13", merit),
    )

    # ── 2026-09-14 回歸：連結標籤後綴 + 欄位行唔可以當成標題 ──
    # 柴灣區個案：列表標題正確但帶「 - 點擊下載」，舊版因為
    #   (1) substring 用成個標題（含連結標籤）→ 喺 PDF 一定搵唔到
    #   (2) extract_pdf_heading 把「截止日期: ...」當成 PDF 標題
    # 於是判定 corrected，把正確標題改成「截止日期: 2026年11月20日(星期五)」。
    chw_pdf = (
        "香港童軍總會 柴灣區\n"
        "CHW/26-27/13\n"
        "深資童軍原野烹飪暨營藝考驗\n"
        "日期: 2026年11月21日至22日\n"
        "截止日期: 2026年11月20日(星期五)\n"
        "對象: 深資童軍\n"
        "費用: HK$60\n"
    )
    passed += test(
        "剝後綴：title_variants 由完整到精簡",
        title_variants("深資童軍原野烹飪暨營藝考驗 - 點擊下載"),
        ["深資童軍原野烹飪暨營藝考驗 - 點擊下載", "深資童軍原野烹飪暨營藝考驗"],
    )
    passed += test(
        "剝後綴：冇後綴就只得一個變體",
        title_variants("深資童軍原野烹飪暨營藝考驗"),
        ["深資童軍原野烹飪暨營藝考驗"],
    )
    passed += test(
        "對證：列表帶「 - 點擊下載」都算對得上（唔好假警報）",
        listing_supported_by_pdf("深資童軍原野烹飪暨營藝考驗 - 點擊下載", chw_pdf),
        True,
    )
    passed += test(
        "PDF 標題：唔可以揀「截止日期」欄位行",
        extract_pdf_heading(chw_pdf),
        "深資童軍原野烹飪暨營藝考驗",
    )
    for chw_listing in ("深資童軍原野烹飪暨營藝考驗 - 點擊下載",
                        "深資童軍原野烹飪暨營藝考驗 - 總會"):
        chw_res = reconcile_listing_title(chw_listing, chw_pdf)
        passed += test(
            f"對證：{chw_listing[-5:]} → 維持原標題，唔好改成欄位行",
            (chw_res["status"], chw_res["title"]),
            ("verified", chw_listing),
        )
    # 錨定檢查：裸字「截止日期」唔可以擋走真標題
    passed += test(
        "欄位過濾唔好誤殺：標題含「截止日期」四字仍然抽到",
        extract_pdf_heading(merit_pdf),
        merit,
    )

    # ── 2026-10-03 用戶個案：總會「總部公告」＋紅磡區「區總部公布」 ──
    # 兩個都係公布類通告，但舊版標題抽出揀咗檔號／公函欄位，令 (1) 分類被
    # PDF 內文搶走、(2) 核對誤判「corrected」。呢度釘死修正後嘅行為。
    acr_pdf = (
        "行政署 第 21/2026 號通告\n"
        "總部公告\n"
        "訓練署\n"
        "﹙一﹚ 余永健先生由 2026 年 10 月 1 日起，獲委任為總部總監。\n"
        "童軍知友社\n"
        "﹙二﹚ 鄺志立先生獲委任為助理總部總監（項目）。\n"
    )
    passed += test(
        "PDF 標題：檔號行（行政署 第 21/2026 號通告）唔可以當標題",
        extract_pdf_heading(acr_pdf),
        "總部公告",
    )
    passed += test(
        "對證：列表標題「總部公告」＝PDF 標題 → 維持，唔好改成檔號",
        (reconcile_listing_title("總部公告", acr_pdf)["status"],
         reconcile_listing_title("總部公告", acr_pdf)["title"]),
        ("verified", "總部公告"),
    )
    hhd_pdf = (
        "香港童軍總會紅磡區\n"
        "Scout Association of Hong Kong – Hung Hom District\n"
        "網址 Web Site：https://www.scout.org.hk/hhd\n"
        "電話 Tel.：2712 3841\n"
        "地址：九龍馬頭圍邨芙蓉樓地下 104 室\n"
        "由 ：區總監\n"
        "致 ：各旅長／旅負責領袖\n"
        "知會：區各級總監及領袖\n"
        "日期：2026 年 10 月 1 日\n"
        "編號：HHD-D-26-05\n"
        "區總部公布\n"
        "（一） 區總部更改開放時間\n"
    )
    passed += test(
        "PDF 標題：公函欄位（由／致／知會／編號）唔可以當標題",
        extract_pdf_heading(hhd_pdf),
        "區總部公布",
    )
    hhd = reconcile_listing_title("D-26-05 - 26年10月區會公布 【New】", hhd_pdf)
    passed += test(
        "對證：區會公布 → 用 PDF 真標題「區總部公布」",
        (hhd["status"], hhd["title"]),
        ("corrected", "區總部公布"),
    )
    for noise in ("致 :各旅長/旅負責領袖", "行政通告第 13/2026號", "通告第 19/2026 號",
                  "截止日期: 2026年11月20日(星期五)", "遊戲節目 / 招募配對 11 月28日 六 1115-1230"):
        passed += test(
            f"寫入前防線：唔似標題嘅「{noise[:12]}…」唔會寫回 cache",
            heading_looks_like_title(noise),
            False,
        )
    passed += test(
        "寫入前防線：正常標題可以寫回 cache",
        heading_looks_like_title("區總部公布") and heading_looks_like_title("第95屆營藝訓練班"),
        True,
    )

    # ── 已核實更正會喺 cache 被列表標題蓋走之後重新套用 ──
    fix_cache = {"data": {"紅磡區": [
        {"title": "D-26-05 - 26年10月區會公布 【New】", "pdf_url": "https://example/hhd.pdf",
         "url": "https://example/hhd.pdf", "captured_date": "2026-10-03"},
    ]}}
    fix_enrich = {"https://example/hhd.pdf": {
        "title": "區總部公布", "listing_title": "D-26-05 - 26年10月區會公布 【New】",
        "title_check": "corrected",
    }}
    passed += test(
        "重新套用：cache 被列表標題蓋走 → 寫返已核實標題",
        (reapply_stored_title_fixes(fix_cache, fix_enrich),
         fix_cache["data"]["紅磡區"][0]["title"]),
        (1, "區總部公布"),
    )
    passed += test(
        "重新套用：已經係正確標題 → 唔會重複寫",
        reapply_stored_title_fixes(fix_cache, fix_enrich),
        0,
    )
    legacy_enrich = {"https://example/old.pdf": {
        "title": "截止日期: 2026年11月20日(星期五)", "title_check": "corrected",
    }}
    legacy_cache = {"data": {"柴灣區": [
        {"title": "深資童軍原野烹飪暨營藝考驗", "pdf_url": "https://example/old.pdf",
         "url": "https://example/old.pdf", "captured_date": "2026-09-13"},
    ]}}
    passed += test(
        "重新套用：舊版冇 listing_title 嘅亂抽更正永遠唔會套用",
        (reapply_stored_title_fixes(legacy_cache, legacy_enrich),
         legacy_cache["data"]["柴灣區"][0]["title"]),
        (0, "深資童軍原野烹飪暨營藝考驗"),
    )

    # ── 2026-10-06 用戶個案：行事曆 PDF 嘅表格列被當成標題 ──
    # 實測文字（總會 26243 Sea-Activities_Calendar，標題係圖，文字層只剩表格）
    sea_calendar_text = "\n".join([
        "Calendar of Events - 2026/2027 YEAR MONTH DATE EVENT C.L.",
        "2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰",
        "17 風帆賽事先修研習班（A） 曾昭溢",
        "19, 25 立划板一段章及二段章訓練班 徐嘉苓",
        "請以劃線支票支付訓練班／活動費用，抬頭請書",
    ])
    passed += test(
        "表格列唔可以當 PDF 標題（英文月份行）",
        looks_like_table_row("2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰"),
        True,
    )
    passed += test(
        "表格列唔可以當 PDF 標題（日期清單行）",
        looks_like_table_row("13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰"),
        True,
    )
    passed += test(
        "表格列唔可以當 PDF 標題（完整日期＋多個數字格）",
        looks_like_table_row("2027年1月24日 (後備日) 日 待定 160 14 2026年12月11日"),
        True,
    )
    passed += test(
        "真標題（含「訓練班」但開頭唔係日期）唔會被誤殺",
        looks_like_table_row("三級童軍標準艇訓練班"),
        False,
    )
    passed += test(
        "行事曆文字層只剩表格 → 抽唔到 PDF 標題（寧願空）",
        extract_pdf_heading(sea_calendar_text),
        "",
    )
    passed += test(
        "寫入前防線：『13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰』唔會寫返 cache",
        heading_looks_like_title("13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰"),
        False,
    )
    passed += test(
        "寫入前防線：『2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰』唔會寫返 cache",
        heading_looks_like_title("2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰"),
        False,
    )
    passed += test(
        "寫入前防線：內文指示句（請以劃線支票…）唔會寫返 cache",
        heading_looks_like_title("請以劃線支票支付訓練班／活動費用，抬頭請書"),
        False,
    )

    # 真標題存在時，表格列唔應該搶走佢（即使表格列有「訓練班」hint）
    titled_calendar = "\n".join([
        "二○二六／二○二七年度（二零二六年十月至二零二七年一月）賽馬會童「SING」匯航計劃 活動與訓練行事曆",
        "Calendar of Events - 2026/2027",
        "13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰",
    ])
    passed += test(
        "行事曆有真標題時，揀真標題（唔係表格列）",
        extract_pdf_heading(titled_calendar),
        "二○二六/二○二七年度(二零二六年十月至二零二七年一月)賽馬會童「SING」匯航計劃 活動與訓練行事曆",
    )

    # ── 2026-10-06：PDF metadata 標題確認 + 列表標題係 PDF 標題超集 ──
    passed += test(
        "對證：列表標題係 PDF 標題嘅超集（多咗計劃名）→ 維持列表標題",
        reconcile_listing_title(
            "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
            "地質生態導賞員訓練班\n（一）日期：\n2027年1月13日 三 香港童軍中心",
        )["status"],
        "verified",
    )
    passed += test(
        "對證：列表標題係 PDF 標題嘅超集 → 唔會縮短標題",
        reconcile_listing_title(
            "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
            "地質生態導賞員訓練班\n（一）日期：\n2027年1月13日 三 香港童軍中心",
        )["title"],
        "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
    )
    passed += test(
        "對證：行事曆文字層只剩表格，但 PDF metadata 標題同列表標題一致 → verified（維持列表標題）",
        reconcile_listing_title(
            "香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月)活動與訓練行事曆",
            sea_calendar_text,
            pdf_meta_title="香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月)活動與訓練行事曆",
        )["status"],
        "verified",
    )
    passed += test(
        "對證：metadata 標題亂嚟（同列表標題唔同）唔會影響結果",
        reconcile_listing_title(
            "D-26-05 - 26年10月區會公布 【New】",
            "由：區總監\n致：各旅長／旅負責領袖\n區總部公布\n本區活動如常舉行。",
            pdf_meta_title="港島南區幼童軍支部比賽2023",
        )["status"],
        "corrected",
    )

    # ── 2026-10-06：表格通告嘅截止／費用（SA69／SA71 個案）──
    # pdfplumber 對「日期／時間／費用／名額／截止日期」表格嘅文字流，表頭同行連成一串；
    # 舊版 3 行窗口攞第一個日期＝第一堂日期（2027-01-02），真截止日係 2026-12-11。
    sa69_table = [
        ["（一）日期", "", "", "", "", ""],
        ["日期", "星期", "時間", "費用($)", "名額", "截止日期"],
        ["2027年1月2日", "六", "0900至1700", "160", "14", "2026年12月11日"],
        ["2027年1月3日", "日", "0900至1700", "160", "14", "2026年12月11日"],
    ]
    passed += test(
        "表格：截止日期取自『截止日期』欄（唔係第一堂日期）",
        deadline_from_tables([sa69_table]),
        "2026-12-11",
    )
    passed += test(
        "表格：費用取自『費用』欄（按金欄唔算）",
        fee_from_tables([sa69_table]),
        "HK$160",
    )
    passed += test(
        "表格：按金欄唔會被當成費用",
        fee_from_tables([[["日期", "按金", "名額"], ["2027年1月13日", "$300", "10"]]]),
        "",
    )
    sa69_text = "\n".join([
        "（一）日期：",
        "日期 星期 時間 費用($) 名額 截止日期",
        "2027年1月2日 六 0900至1700 160 14 2026年12月11日",
        "2027年1月3日 日 0900至1700 160 14 2026年12月11日",
    ])
    passed += test(
        "表格通告：有表格就用表格（截止 2026-12-11）",
        extract_deadline(sa69_text, tables=[sa69_table]),
        "2026-12-11",
    )
    passed += test(
        "（記錄）純文字流仍然會攞到第一堂日期 → 所以表格一定要讀",
        extract_deadline(sa69_text),
        "2027-01-02",
    )
    passed += test(
        "表格通告：費用只喺表格欄出現都抽得到",
        extract_fee("（一）日期：\n日期 星期 時間 費用($) 名額 截止日期", tables=[sa69_table]),
        "HK$160",
    )

    # ── 2026-10-06：分類／標籤唔可以由內文搶走標題嘅明確字眼 ──
    raffle_body = (
        "為鼓勵童軍旅積極參與，2027年童軍獎券籌募活動繼續設銷售獎及進步獎，"
        "有意參與獎券銷售獎勵比賽的童軍旅請留意總會稍後發出之獎券籌募通告。"
    )
    passed += test(
        "分類：標題有『活動』但內文有『比賽』→ 以標題為準（獎券籌募活動＝活動）",
        [c["id"] for c in extract_categories("2027年童軍獎券籌募活動", raffle_body)],
        ["activity"],
    )
    passed += test(
        "分類：同一個活動嘅回條（標題有『活動』）都歸活動，兩個 copy 一致",
        [c["id"] for c in extract_categories("2027年童軍獎券籌募活動 - 回條", raffle_body)],
        ["activity"],
    )
    passed += test(
        "分類：標題同時有『訓練班』同『活動通告第N號』→ 仍然係訓練",
        [c["id"] for c in extract_categories("幼童軍射箭章（三級制）訓練班 (活動通告第21/26號)", "參加資格：幼童軍")],
        ["training"],
    )
    passed += test(
        "分類：行事曆（參考文件）＝公布，內文提及課程都唔會變訓練",
        [c["id"] for c in extract_categories(
            "香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月)活動與訓練行事曆",
            "2027年1月2日 六 三級童軍標準艇訓練班 楊劍聰",
        )],
        ["announcement"],
    )
    passed += test(
        "標籤：行事曆唔會抽內文所有課程做訂閱標籤",
        extract_subscription_metadata(
            "香港童軍總會白沙灣譚華正海上活動中心2026-2027年度(10-1月)活動與訓練行事曆",
            "2027年1月2日 六 三級童軍標準艇訓練班 楊劍聰 獨木舟教練",
        )["subscription_tags"],
        ["category:announcement"],
    )
    passed += test(
        "標籤：內文『持有獨木舟教練資歷…優先考慮』唔會變『獨木舟教練』課程標籤",
        "course:leader-canoe-instructor" in extract_subscription_metadata(
            "東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班",
            "（5）持有獨木舟教練資歷、遊樂船隻二級操作人證書或同等資歷將獲優先考慮。",
            "領袖、會務委員",
        )["subscription_tags"],
        False,
    )
    passed += test(
        "標籤：內文『由…童軍標準艇教練員…擔任班領導人』唔會變課程標籤",
        "course:leader-standard-boat-instructor" in extract_subscription_metadata(
            "三級童軍標準艇訓練班",
            "由香港童軍總會註冊中級童軍標準艇教練員楊劍聰先生擔任班領導人。",
            "童軍、領袖",
        )["subscription_tags"],
        False,
    )
    passed += test(
        "標籤：標題自己講明嘅課程永遠保留（唔會被資格過濾誤殺）",
        "course:leader-standard-boat-instructor" in extract_subscription_metadata(
            "童軍標準艇教練員訓練班",
            "由香港童軍總會註冊中級童軍標準艇教練員擔任導師。",
            "領袖",
        )["subscription_tags"],
        True,
    )
    passed += test(
        "標籤：目標獎章（『考獲本訓練班證書等同完成水手長章的要求』）仍然保留",
        "course:scout-boatswain-badge" in extract_subscription_metadata(
            "三級童軍標準艇訓練班",
            "考獲本訓練班證書等同完成「童軍／深資童軍支部海上活動徽章—水手長章」的要求。",
            "童軍、領袖",
        )["subscription_tags"],
        True,
    )

    # ── 2026-10-06（第二批）：今日通告嘅真實文字 ──────────────────────
    # 全部 text 由當日 PDF 直接抄出（東九龍地域 26227／26228、盲盒訂購、26241）。
    passed += test(
        "截止：冇『截止』字樣，但『必須於…或之前…交回』（26228 獎券活動）",
        extract_deadline(
            "為統計領取獎券數量，各旅長／負責領袖必須於 2026 年 11 月 30 日（星期一）\n"
            "或之前 填妥夾附回條，交回東九龍地域總部辦事處。"
        ),
        "2026-11-30",
    )
    passed += test(
        "截止：『每年 6 月 30 日前提交』＋下一段『2026 年 10 月 31 日呈交』都唔算截止（26227）",
        extract_deadline(
            "電話：2957 6466 傳真：2302 1168 2026年10月1日\n"
            "香港童軍總會「政策、組織及規條」規條 2.11.2 列明，所有童軍旅必須於每年的 6 月 30 日前提交"
            "一份經審核的周年財務報告及所有銀行戶口結算表副本予區總監。\n"
            "倘銷售童軍旅於2026年10月31日，仍未根據規定呈交經審核之2025／2026年度周年賬目結算表及設有銀行戶口，"
            "有關獎券收益即撥歸總會「童軍發展資助計劃」。"
        ),
        "",
    )
    passed += test(
        "費用：『售價』標籤（盲盒訂購）→ HK$50",
        extract_fee("（一） 售 價 ： 每個港幣 50 元，內含 15 款東九龍地域歷年紀念品\n（二） 截止訂購日期 ： 2027 年 3 月 15 日（星期一）"),
        "HK$50",
    )
    passed += test(
        "截止：『截止訂購日期』（盲盒訂購）→ 2027-03-15",
        extract_deadline("（二） 截止訂購日期 ： 2027 年 3 月 15 日（星期一）"),
        "2027-03-15",
    )
    passed += test(
        "對象：（1）（2）（3）… 編號清單全部讀（26241 一個石籃的故事，唔可以漏會務委員）",
        extract_audience(
            "（五） 參加資格 ： （1） 6 歲或以上持有有效紀錄冊之幼童軍、童軍、深資童軍及樂行童軍支部成員；\n"
            "（2） 持有有效領袖委任書或教練員委任證之各級領袖；\n"
            "（3） 持有有效委任狀之會務委員；\n"
            "（4） 以上各合資格童軍人士的 6 歲或以上親友；或\n"
            "（5） 6 歲或以上各界人士。\n"
            "（六） 費 用 ： 全免\n"
        ),
        "幼童軍、深資童軍、樂行童軍、童軍、領袖、會務委員",
    )
    passed += test(
        "分類：標題『嘉許計劃』＝公布（26232，內文有『服務記錄』都唔可以搶）",
        extract_categories("卓越領袖嘉許計劃2027", "前線領袖在童軍旅的服務記錄及參與服務或事工")[0]["label"],
        "公布",
    )
    passed += test(
        "分類：標題『名單』＝公布（26231，內文有『服務精神』都唔可以搶）",
        extract_categories("傑出表現成員地域總監嘉許2026 - 獲嘉許名單", "其無私奉獻的服務精神深獲讚賞")[0]["label"],
        "公布",
    )
    passed += test(
        "分類：『成績公布』仍然係比賽（唔可以被上面名單／參考文件規則拉走）",
        extract_categories("東九龍地域步操、團呼及快樂傘比賽2026 - 成績公布", "比賽")[0]["label"],
        "比賽",
    )
    passed += test(
        "分類：紀念品訂購（冇任何類別字眼）＝公布兜底，唔會亂入活動",
        extract_categories("「東九50時間錦囊」盲盒訂購", "內含 15 款東九龍地域歷年紀念品")[0]["label"],
        "公布",
    )

    # ── 2026-10-06：連結形狀（唔可以再有來源靜默跳過）────────────────
    passed += test(
        "連結：東九龍地域 ?wpdmdl= 下載連結＝可 enrich",
        is_enrichable_url("https://hkscout-ekr.org/circulars/download/?wpdmdl=5653"),
        True,
    )
    passed += test(
        "連結：.pdf 帶 query string 都算",
        is_enrichable_url("https://example.org/a/b.pdf?ver=2"),
        True,
    )
    passed += test(
        "連結：Office 附件（.xlsx）唔算（唔會白下載）",
        is_enrichable_url("https://group.scout.org.hk/…/SMD2606_報名表.xlsx"),
        False,
    )
    passed += test(
        "連結：HTML 文章頁唔算",
        is_enrichable_url("https://hkscout-tko.org/notice/?nid=207"),
        False,
    )
    passed += test(
        "跳過原因分類：Office／HTML 分得開",
        (skip_reason("https://x/a/b.docx"), skip_reason("https://hkscout-tko.org/notice/?nid=207")),
        (".docx", "網頁／無檔案尾綴"),
    )

    # 東九龍地域個案：wpdmdl 通告要入目標；7 日補漏窗要 cover 舊一兩日
    link_cache = {
        "data": {"東九龍地域": [
            {"title": "三級童軍標準艇訓練班",
             "pdf_url": "https://hkscout-ekr.org/circulars/download/?wpdmdl=5653",
             "captured_date": "2026-10-06"},
            {"title": "舊通告（2 日前）",
             "pdf_url": "https://hkscout-ekr.org/circulars/download/?wpdmdl=5500",
             "captured_date": "2026-10-04"},
            {"title": "報名表",
             "pdf_url": "https://x/a/報名表.xlsx",
             "captured_date": "2026-10-06"},
        ]},
    }
    passed += test(
        "目標：今日嘅 wpdmdl 通告會入 enrich 名單",
        [u for _, _, u in collect_targets(link_cache, "2026-10-06", False, False)],
        ["https://hkscout-ekr.org/circulars/download/?wpdmdl=5653",
         "https://hkscout-ekr.org/circulars/download/?wpdmdl=5500"],
    )
    passed += test(
        "目標：catchup_days=0 時只做今日（舊通告唔會被拉入）",
        len(collect_targets(link_cache, "2026-10-06", False, False, catchup_days=0)),
        1,
    )
    passed += test(
        "目標：預設補漏窗＝INCREMENTAL_CATCHUP_DAYS 日",
        INCREMENTAL_CATCHUP_DAYS >= 7,
        True,
    )
    passed += test(
        "警號：未支援連結會計入 summarize_skipped_links（唔會靜默）",
        summarize_skipped_links(link_cache, "2026-10-06", False, False, False),
        [("東九龍地域", 1, "https://x/a/報名表.xlsx")],
    )

    # ── 格式正規化 ──
    passed += test(
        "normalize_fee：港幣$10 → HK$10",
        normalize_fee("港幣$10"),
        "HK$10",
    )
    passed += test(
        "normalize_fee：10元正 → HK$10",
        normalize_fee("10元正"),
        "HK$10",
    )
    passed += test(
        "normalize_fee：USD$50 → US$50",
        normalize_fee("USD$50"),
        "US$50",
    )

    total = len(TEST_RESULTS)
    failed = total - passed
    print(f"\n結果：{passed}/{total} 通過")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
