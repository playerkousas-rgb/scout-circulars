#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich.py — B 補充爬蟲（截止日期 / 對象 / 費用 / 個人化標籤）
====================================================================
設計原則：
  - 只讀 cache.json 篩「captured_date = 今日」的新通告
  - 抽取方式：先用 pdfplumber 文字 + label 定位 regex；
              文字型抽唔到 → 用 OCR (tesseract chi_tra) fallback
  - 結果寫去 enrich.json（獨立檔），key = pdf_url
  - 抽唔到 = 留空（靠固定 label，不亂猜，唔會抽錯）
  - 雙重認證（2026-09-14 改）：主判準係「攞列表標題去 PDF 內文搵」——搵到就
    verified，唔使猜。列表標題好多時帶連結標籤後綴（「 - 點擊下載」等，
    全庫 1500/4795 條），所以會逐層剝後綴再搵，唔好製造假警報。
    真係搵唔到，先至考慮用 PDF 標題改正（corrected）；PDF 太少字／抽唔到標題
    就維持原樣（unverified）。永遠唔改 pdf_url、captured_date，唔當新通告。
    ⚠️ 改正預設**只報告、唔寫入**；要真寫回 cache.json 請加 --apply-title-fixes
    （每日 workflow／本機 run 已經開咗；更正會記住原本列表標題，之後每次 run
    重新套用，唔會被下一次全量抓取蓋走）。
    （舊版 log 無條件印「已改正」，但寫入係死嘅——cache_dirty 設咗從來冇用過——
     所以 cache.json 一個字都冇變。呢類靜默失敗正正係呢個 repo 最怕嘅。）
  - 個人化只使用「支部＋官方課程／服務／活動／比賽」標籤，不按地域或旅團推論。
  - 訓練班及工作坊同屬「訓練」；活動只分大露營、營火會、其他；比賽獨立。

用法：
  python enrich.py                 # 增量：抽今日新通告（預設，最輕量）
  python enrich.py --backfill      # 補歷史欠帳：抽所有未 enrich 的（不限日期，跳過已做）
  python enrich.py --backfill-categories   # 補分類／舊 taxonomy 欠帳（會重新下載）
  python enrich.py --all           # 全量重抽（含已抽過的；重！僅離峰用）
  python enrich.py --date 2026-06-07
  python enrich.py --limit 5 --verbose
  python enrich.py --no-ocr        # 停用 OCR
  python enrich.py --apply-title-fixes   # 把核對過嘅標題真係寫回 cache.json
"""

import argparse
import datetime
from datetime import timezone, timedelta
from difflib import SequenceMatcher
import io
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import logging
import warnings

from subscription_tagging import extract_categories as classify_subscription_categories
from subscription_tagging import extract_subscription_metadata, load_catalog

# 靜音 pdfminer/pdfplumber 嘈雜的 FontBBox 等警告
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

CACHE_FILE = "cache.json"
ENRICH_FILE = "enrich.json"
ENRICH_VERSION = "3.4"  # 列表標題 vs PDF 雙重認證；只改錯名，唔改連結
# 3.3（2026-10-03）：標題抽出避開公函欄位（由／致／知會／編號）同檔號行
# （「行政通告第 13/2026號」），並把「公告／公布／公佈」加入標題 hint；
# 更正確更正會記錄 listing_title，之後每次 run 重新套用（見
# reapply_stored_title_fixes），令 cache 重建都唔會失去正確名稱。
# 3.4（2026-10-06）：三個修正（用戶報告：東九龍地域批次「抽取好奇怪、標籤有問題」）：
#   1. 表格列（「13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰」）同內文指示句
#      唔可以當 PDF 標題（looks_like_table_row / _BODY_INSTRUCTION_RE）；
#   2. PDF metadata 標題用嚟確認列表標題，列表標題係 PDF 標題超集時維持列表
#      （見 reconcile_listing_title）；
#   3. 表格通告直接讀「截止日期」「費用」欄（deadline_from_tables /
#      fee_from_tables），唔再由 3 行窗口攞第一個日期（＝第一堂日期）。
#   另外 collect_targets 而家接受 WordPress Download Manager 連結
#   （?wpdmdl=…），東九龍地域等來源終於會被 enrich。

# 香港時區：core.py 的 captured_date 是用 HKT 寫的，
# 這裡的「今日」必須同樣用 HKT，否則在 UTC runner 上跨日時會對不上、抓 0 條。
HKT = timezone(timedelta(hours=8))

# ─── PDF 文字抽取 ─────────────────────────────────────────
def nfkc(text):
    """Unicode NFKC 正規化：把 PDF 常見的兼容區/異體字（如 0xF98E 年、0xF9D1 截）
    轉回正常字元，否則 regex 會配對失敗。"""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text)


def pdf_text_via_pdfplumber(pdf_bytes):
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = pdf.pages[:3]  # 通告重點通常在頭 1-2 頁
            return nfkc("\n".join((p.extract_text() or "") for p in pages))
    except Exception:
        return ""


def pdf_meta_title_via_pdfplumber(pdf_bytes):
    """PDF metadata 標題（發通告嗰個人入嘅通告名）。

    2026-10-06：行事曆類 PDF 嘅大標題可能係圖（唔喺文字層），但 metadata 標題
    通常就係通告全名。呢個值只會用嚟「確認」列表標題（見 reconcile_listing_title），
    永遠唔會覆蓋——fix_hks_titles.py 記錄過有來源會沿用舊檔 metadata 名。
    """
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            info = pdf.metadata or {}
            return nfkc(str(info.get("Title") or "")).strip()
    except Exception:
        return ""


def pdf_tables_via_pdfplumber(pdf_bytes, max_pages=3):
    """頭幾頁嘅表格（pdfplumber 預設 lattice：有框線先當表格）。

    2026-10-06：通告正文好多時係「日期／時間／費用／名額／截止日期」表格，
    純文字流抽欄位會將表頭同資料列連成一串，於是把第一堂日期當成截止日期。
    有表格結構就唔使猜。
    """
    try:
        import pdfplumber
        tables = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:max_pages]:
                for table in page.extract_tables() or []:
                    rows = [
                        [nfkc(str(cell or "")).replace("\n", " ").strip() for cell in row]
                        for row in table
                        if row
                    ]
                    if any(any(cell for cell in row) for row in rows):
                        tables.append(rows)
        return tables
    except Exception:
        return []


def pdf_text_via_ocr(pdf_bytes, lang="chi_tra+eng"):
    """圖片型 PDF fallback：轉圖片 → tesseract OCR"""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=2)
        out = []
        for img in images:
            out.append(pytesseract.image_to_string(img, lang=lang))
        return nfkc("\n".join(out))
    except Exception as e:
        print(f"    [OCR 失敗] {type(e).__name__}: {str(e)[:60]}")
        return ""


# ─── 文字正規化 ───────────────────────────────────────────
def normalize_for_label(text):
    """去掉 label 內常見空格，方便配對「參 加 資 格」這類間隔字"""
    return text


def compact(s):
    return re.sub(r"[ \u3000\t]", "", s or "")


# ─── 列表標題 vs PDF 雙重認證 ─────────────────────────────────
# 主爬蟲只信列表頁；列表標題一空就可能抄鄰居個名。
# enrich 本來就要下載 PDF，喺呢度核對一次：對得上就維持，對唔上先改名。

_TITLE_PUNCT_RE = re.compile(r"[「」『』\"“”'（）()\[\]【】\-–—/／:：,.。、·•*＊]")
_LETTERHEAD_RE = re.compile(
    r"香港童軍總會|Scout Association|電話|傳真|\bTel\b|\bFax\b|\bE-?mail\b|電郵|"
    r"www\.|https?://|檔號|發文者|受文者|內部傳閱"
)
_HEADING_SKIP_RE = re.compile(
    r"參加資格|參加對象|報名辦法|報名日期|查詢|備註|^附件|費用[:：]|收費[:：]|"
    # 2026-09-14 加：呢啲係「欄位名」，永遠唔可能係通告標題。之前冇擋住，
    # 於是「截止日期：2026年11月20日(星期五)」会被當成 PDF 標題，
    # 再被 reconcile 当成「正確標題」写回列表（柴灣區深資童軍原野烹飪個案）。
    # ⚠️ 一定要錨定做「欄位名形態」（後面跟冒號或數字），唔可以用裸字「截止日期」：
    #    真標題入面會出現呢四個字，例如「區會提名截止日期」通告。
    r"截止日期[:：\d]|截止[:：]|^日期[:：]|^時間[:：]|^地點[:：]|^對象[:：]|^名額[:：]|"
    # 2026-10-03 加：區會通告嘅「由／致／知會／編號」係公函欄位名，唔係標題。
    # 紅磡區「區總部公布」個案：PDF 開頭係信頭「由：區總監／致：各旅長／旅負責
    # 領袖／知會：…／編號：HHD-D-26-05」，舊版因為「致：各旅長／旅負責領袖」
    # 長度過關而揀咗佢做 PDF 標題，令核對誤判「corrected」，差啲改錯名。
    r"^(?:由|致|知會|副本|受文者|發文者|檔號|編號|日期|時間|地點|對象|名額)"
    r"\s*(?:E-?mail|Email)?\s*[:：]|"
    # 通訊欄位（地址／電話／傳真／網址／電郵）都唔係標題
    r"^(?:地址|地址及網址|電話|傳真|網址|電郵|辦事處地址)\s*[:：]"
)
# 「總部公告」「區總部公布」呢類真標題短過 6 個字，唔可以當雜訊濾走。
# 只有含「公告／公布／公佈」嘅短行先獲豁免（3 字起，避免單字雜訊）——「通告」
# 兩個字本身成日係分類標籤（「行政通告」），維持原本 6 字下限。
_HEADING_SHORT_OK_RE = re.compile(r"公告|公布|公佈")
# 2026-10-03：通告檔號行（「行政通告第 13/2026號」「訓練署 第 64/2026 號通告」
# 「通告第 19/2026 號」）。佢係編號，唔係標題；舊版好多時揀咗佢，於是核對把
# 好標題（飛鏢同樂日、第10屆海童軍工作坊、總部公告…）誤判成「要改正」。
_CIRCULAR_NUMBER_RE = re.compile(
    r"^.{0,10}第\s*\d{1,4}\s*[/\-–—]\s*\d{1,4}\s*[號号]?\s*(?:通告)?$"
)
# 「截止日期」以前喺呢度做 hint，令一條欄位行贏過真標題，已移除。
# 2026-10-01 擴充：舊版淨係識「比賽」兩個字做埋，「XX挑戰賽」「XX錦標賽」呢類
# 長詞嘅真標題完全冇 hint 撞中，於是會輸俾另一行啱啱好撞中「招募」嘅內文句子
# （見「油尖區百年童行-童軍115追蹤挑戰賽(服務邀請)」錯判成通告標題個案）。
# 詞表同 subscription_tagging.COMPETITION_TERMS／SERVICE_INVITATION_TERMS 對齊。
# 2026-10-03 加公告／公布／公佈：呢啲係最典型嘅通告標題字眼（用戶：明確字眼
# 以標題為準），偏偏舊版冇佢哋，令「區總部公布」「總部公告」等真標題輸畀欄位行。
_HEADING_HINT_RE = re.compile(
    r"通告|公告|公布|公佈|訓練班|工作坊|提名|比賽|競賽|公開賽|錦標賽|邀請賽|挑戰賽|會操|練習賽|體驗賽|"
    r"感謝狀|招募|課程|服務邀請|義工邀請"
)
# 列表頁 scrape 落嚟嘅連結標籤後綴：呢啲字永遠唔會出現喺 PDF 內文，
# 所以直接攞成個列表標題去 PDF 搵 substring 一定搵唔到（全庫 1500/4795 條中招）。
_LINK_SUFFIX_RE = re.compile(r"\s*[-–—]\s*[^-–—]{1,12}$")
_CIRCULAR_CODE_RE = re.compile(
    r"^[A-Za-z]{2,5}[/\-_\s]+(?:[A-Za-z]{1,4}[/\-_\s]+)*\d{2,4}[/\-_\s]+\d{2,4}[A-Za-z]?$"
)
# ── 2026-10-06：表格列／內文指示句唔係標題 ────────────────────────────
# 用戶個案（東九龍地域 2026-10-06 批次）：總會兩個「活動與訓練行事曆」PDF 嘅
# 大標題係圖（唔喺文字層），pdfplumber 抽到嘅第一批文字就係表格列，於是
#   「2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰」
#   「13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰」
# 因為含「訓練班」而喺 _HEADING_HINT_RE 加分，贏過其他候選行，再被當成
# 「PDF 真標題」寫返 cache.json —— 結果：一個行事曆嘅標題變成一行表格，
# 分類跟住錯（行事曆被當成「訓練」）、內文全部課程標籤都抽埋落一個通告度。
# 呢啲行有共同形狀：開頭係日期清單／英文月份／表頭字眼，一律唔可以當標題。
_TABLE_ROW_LEAD_RE = re.compile(
    r"^(?:20\d{2})?(?:"                                                   # 年份可以痴住月份（compact 咗嘅文字）
    r"(?:\d{1,2}\s*[,，、]\s*)+\d{1,2}"                                   # 13, 17, 20, 23, 31
    r"|\d{1,2}[-–—]\d{1,2}(?:[/／]\d{1,2})?"                              # 24-25、16-17/1
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"           # 2026 Oct …（英文行事曆）
    r"|(?:YEAR|MONTH|DATE|EVENT|C\.L\.)"                                   # 表頭英文字
    r")",
    re.I,
)
# 行首係一個獨立日數（後面有空格）：「17 風帆賽事先修研習班（A） 曾昭溢」。
# 注意：中文標題嘅數字通常痴住後面（「50周年」），所以唔會誤殺。
_TABLE_ROW_BARE_DAY_RE = re.compile(r"^\s*(?:20\d{2}\s+)?\d{1,2}\s+\S")
# 完整日期開頭而且同一行仲有兩個以上數字格（「2027年1月24日 日 待定 160 14
# 2026年12月11日」）＝表格列。單純以「2026年10月…」開頭嘅真標題唔會被殺。
_TABLE_ROW_DATE_LEAD_RE = re.compile(r"^(?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日")
_NUMBER_TOKEN_RE = re.compile(r"\d+")
# 內文指示句（繳費、交表、注意事項）同理唔係標題。
_BODY_INSTRUCTION_RE = re.compile(r"^(?:請|敬希|敬請|填妥|連同|如有|如欲)")
TITLE_SIMILARITY_THRESHOLD = 0.90


def looks_like_table_row(line: str) -> bool:
    """呢行係咪表格列（日期清單／英文月份表頭）——永遠唔可以當通告標題。"""
    text = compact(line)
    if not text:
        return False
    if _TABLE_ROW_LEAD_RE.match(text):
        return True
    if _TABLE_ROW_BARE_DAY_RE.match(line or ""):
        return True
    return bool(_TABLE_ROW_DATE_LEAD_RE.match(text) and len(_NUMBER_TOKEN_RE.findall(text)) >= 3)


def compact_title(value: str) -> str:
    """比較用：去掉引號、空白、標點同句尾「通告」。"""
    text = nfkc(value or "")
    text = _TITLE_PUNCT_RE.sub("", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"通告$", "", text)
    return text.casefold()


def title_similarity(left: str, right: str) -> float:
    a, b = compact_title(left), compact_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 6 and shorter in longer and len(shorter) / len(longer) >= 0.5:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def extract_pdf_heading(text: str) -> str:
    """從 PDF 頭幾行抽出通告標題。寧願空，唔好把信頭／欄位名當成標題。"""
    if not text:
        return ""
    lines = []
    for raw in text.splitlines():
        line = nfkc(raw).strip()
        if line:
            lines.append(line)
        if len(lines) >= 16:
            break

    candidates = []
    for line in lines:
        compact_line = compact(line)
        short_ok = len(compact_line) >= 3 and bool(_HEADING_SHORT_OK_RE.search(compact_line))
        if (len(compact_line) < 6 and not short_ok) or len(line) > 80:
            continue
        if not re.search(r"[\u4e00-\u9fff]", line):
            continue
        if _LETTERHEAD_RE.search(line):
            continue
        if _HEADING_SKIP_RE.search(compact_line):
            continue
        # 2026-10-06：表格列（「13, 17, 20, 23, 31 …」「2026 Oct 10, 11 …」）同
        # 內文指示句（「請以劃線支票支付…」）唔係標題。
        if looks_like_table_row(line) or _BODY_INSTRUCTION_RE.match(compact_line):
            continue
        if re.fullmatch(r"20\d{2}年\d{1,2}月\d{1,2}日", compact_line):
            continue
        if _CIRCULAR_CODE_RE.match(line.strip()):
            continue
        # 2026-10-03：檔號行（「行政通告第 13/2026號」）唔係標題
        if _CIRCULAR_NUMBER_RE.match(compact_line):
            continue
        candidates.append(line)

    if not candidates:
        return ""
    hinted = [line for line in candidates if _HEADING_HINT_RE.search(line)]
    return (hinted or candidates)[0]


def heading_looks_like_title(text: str) -> bool:
    """寫回 cache 前嘅最後防線：似通告標題嘅先至夠膽寫。

    抽取器已經避開大部分欄位／檔號行，但舊版 enrich.json 仲留住一堆亂抽嘅
    「更正」（地址、表格行、節目時間表），所以寫入前再檢查一次形狀：
    長度合理、唔係欄位／檔號／信頭、冇日期時間同表格符號。
    """
    line = compact(nfkc(text or "")).strip()
    if not line or len(line) > 40:
        return False
    # 2026-10-06：表格列（用戶個案嘅「13, 17, 20, 23, 31 地質生態導賞員訓練班
    # 楊劍聰」）同內文指示句都唔可以寫返 cache.json 當標題。
    if looks_like_table_row(line) or _BODY_INSTRUCTION_RE.match(line):
        return False
    if _HEADING_SKIP_RE.search(line) or _CIRCULAR_NUMBER_RE.match(line) or _CIRCULAR_CODE_RE.match(line):
        return False
    if _LETTERHEAD_RE.search(line):
        return False
    if re.search(r"[|>»«\u3008\u3009]|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}:\d{2}|\d{3,4}\s*[-–—]\s*\d{3,4}", line):
        return False
    return True


def title_variants(listing: str) -> list:
    """由完整列表標題開始，逐層剝走尾段連結標籤。

    列表頁 scrape 落嚟嘅標題好多時帶「 - 點擊下載」「 - 通告下載」「 - 報名表格」
    呢類連結文字，佢哋唔屬於通告本身，PDF 內文當然搵唔到。全庫 4795 條有
    1500 條（31%）係咁，所以唔剝就核對嘅話會製造大量假警報。
    回傳由最完整到最精簡，叫嘅人由頭試到尾，第一個命中就算對得上。
    """
    out = []
    cur = nfkc(listing or "").strip()
    while cur:
        out.append(cur)
        m = _LINK_SUFFIX_RE.search(cur)
        if not m:
            break
        nxt = cur[: m.start()].strip()
        if not nxt or nxt == cur:
            break
        cur = nxt
    return out


def listing_supported_by_pdf(listing: str, pdf_text: str, heading: str = "") -> bool:
    """列表標題可唔可以由 PDF 內文支持。

    主判準（2026-09-14 起）：攞標題（連剝咗連結標籤後綴嘅各個變體）去 PDF
    內文搵 substring —— 搵到就代表 PDF 真係嗰份通告，唔使再猜。
    搵唔到先至退而用「同 PDF 標題 ≥90% 相似」。
    """
    hay = compact_title(pdf_text)
    for variant in title_variants(listing):
        needle = compact_title(variant)
        if len(needle) >= 6 and needle in hay:
            return True
    if heading and title_similarity(listing, heading) >= TITLE_SIMILARITY_THRESHOLD:
        return True
    return False


def heading_contained_in_listing(listing: str, heading: str) -> bool:
    """PDF 標題係列表標題嘅一部分？

    2026-10-06 個案：「東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員
    訓練班」（列表）vs「地質生態導賞員訓練班」（PDF 標題）。舊版因為相似度
    0.5 < 0.9 就當列表標題錯，縮短成 PDF 標題——但列表標題只係多咗計劃名，
    更完整。呢類「PDF 標題係列表標題子字串」嘅情況一律維持列表標題。
    """
    hay = compact_title(listing)
    needle = compact_title(heading)
    return bool(needle) and len(needle) >= 6 and needle in hay


def reconcile_listing_title(listing: str, pdf_text: str, pdf_meta_title: str = "") -> dict:
    """列表標題 vs PDF。回傳 {title, status, pdf_heading, similarity}。

    status:
      verified   — 列表標題出現喺 PDF、同 PDF 標題 ≥90% 相似、或者係 PDF 標題嘅
                   超集（列表標題更完整）；亦包括 PDF metadata 標題同列表標題一致
      corrected  — 對唔上，而且 PDF 標題夠清楚，改用 PDF
      unverified — PDF 太少字／抽唔到標題，維持列表（寧願唔改）

    2026-10-06：只用 PDF 自帶嘅 metadata 標題做「確認」（metadata 可能係舊檔
    另存時留下嘅錯名——見 fix_hks_titles.py，所以永遠唔會攞佢做更正內容）；
    行事曆類 PDF 嘅大標題有時係圖，文字層只剩表格，靠 metadata 先認得返。
    """
    listing = nfkc(listing or "").strip()
    heading = extract_pdf_heading(pdf_text)
    similarity = title_similarity(listing, heading) if heading else 0.0
    meta = nfkc(pdf_meta_title or "").strip()
    if meta and len(compact(meta)) >= 6 and title_similarity(listing, meta) >= TITLE_SIMILARITY_THRESHOLD:
        return {"title": listing, "status": "verified", "pdf_heading": heading,
                "similarity": similarity, "pdf_meta_title": meta}
    if not pdf_text or len(compact(pdf_text)) < 20:
        return {"title": listing, "status": "unverified", "pdf_heading": heading, "similarity": similarity}
    if listing_supported_by_pdf(listing, pdf_text, heading):
        return {"title": listing, "status": "verified", "pdf_heading": heading, "similarity": similarity}
    if heading_contained_in_listing(listing, heading):
        return {"title": listing, "status": "verified", "pdf_heading": heading, "similarity": similarity}
    if heading and similarity < TITLE_SIMILARITY_THRESHOLD:
        return {"title": heading, "status": "corrected", "pdf_heading": heading, "similarity": similarity}
    return {"title": listing, "status": "unverified", "pdf_heading": heading, "similarity": similarity}


def _cache_title_for(cache: dict, url: str) -> str:
    """cache 入面呢個 url 而家顯示緊嘅標題（搵唔到就空字串）。"""
    if not url or not isinstance(cache, dict):
        return ""
    for arr in (cache.get("data") or {}).values():
        if not isinstance(arr, list):
            continue
        for item in arr:
            if isinstance(item, dict) and (item.get("pdf_url") or item.get("url") or "") == url:
                return str(item.get("title") or "")
    return ""


def reapply_stored_title_fixes(cache: dict, enrich: dict) -> int:
    """把已核實嘅 PDF 標題重新寫返 cache.json（零下載）。

    core.py 每次抓取都會用列表頁標題重建 cache.json（連 --force），所以之前
    寫入嘅標題更正會被蓋走。呢度趁每次 enrich run 重新套用一次，令 PDF 真標題
    長期有效——2026-10-03 用戶要求：「名字應該是區總部公布」。

    安全閘（唔想再有靜默失敗）：
      1. 只處理有記錄 `listing_title`（即係新版核對過）嘅更正——舊版 enrich.json
         留住嘅欄位／檔號亂抽更正冇呢個欄位，永遠唔會套用；
      2. 更正標題要通過 heading_looks_like_title()；
      3. 只有當 cache 標題仍然係原本嘅列表標題（即係未被其他嘢改過）先寫——
         列表標題日後改咗就唔會覆蓋。
    回傳今次實際寫入幾多條。
    """
    fixed = 0
    for url, entry in (enrich or {}).items():
        if not isinstance(entry, dict) or entry.get("title_check") != "corrected":
            continue
        listing_title = str(entry.get("listing_title") or "")
        corrected = str(entry.get("title") or "")
        if not listing_title or not corrected or listing_title == corrected:
            continue
        if not heading_looks_like_title(corrected):
            continue
        if _cache_title_for(cache, url) != listing_title:
            continue
        if apply_title_to_cache(cache, url, corrected):
            fixed += 1
            print(f"   📝 重新套用已核實標題：{listing_title[:28]} → {corrected[:28]}")
    return fixed


def apply_title_to_cache(cache: dict, url: str, new_title: str) -> bool:
    """只改 title，唔改 pdf_url / captured_date。"""
    if not url or not new_title or not isinstance(cache, dict):
        return False
    changed = False
    for arr in (cache.get("data") or {}).values():
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            item_url = item.get("pdf_url") or item.get("url") or ""
            if item_url == url and item.get("title") != new_title:
                item["title"] = new_title
                changed = True
    for item in cache.get("notices") or []:
        if not isinstance(item, dict):
            continue
        if item.get("pdf_url") == url and item.get("title") != new_title:
            item["title"] = new_title
            changed = True
    return changed


# ─── 欄位抽取 ─────────────────────────────────────────────
CN_NUM = "零一二三四五六七八九十"


# ─── 個人化分類（訓練 / 服務 / 活動 / 比賽）──────────────────────
# 這個網站的推播分類刻意只有四大類：
#   1. 訓練：訓練班和工作坊都算入；
#   2. 服務；
#   3. 活動：只細分大露營、營火會、其他；
#   4. 比賽：獨立，絕不混入其他活動。
# 詳細的受控課程／徽章別名放在 subscription_catalog.json，由
# subscription_tagging.py 和前端共用，不讓臨時或難辨識課程進入訂閱選項。
CATE_VER = "3.0"
CURRENT_SUBSCRIPTION_CATALOG_VERSION = str(load_catalog().get("version", ""))


def extract_categories(title, text):
    """Compatibility wrapper for the shared personal-subscription taxonomy."""
    return classify_subscription_categories(title, text)


def extract_deadline(text, tables=None):
    """截止日期：搵含『截止』的行，回傳第一個帶有效日期者。

    設計原則（非常重要）：
      - **寧願漏抽，絕不亂抽**
      - 只認「截止」相關 label，不認「報名日期」等可能係開始日期的字樣
      - 優先匹配明確 label（截止日期 / 截止報名日期 / 報名截止日期），
        再 fallback 到任何含截止的行
      - 2026-10-06：表格有『截止日期』欄就先用表格嗰個（見 deadline_from_tables）
    """
    table_value = deadline_from_tables(tables) if tables else ""
    if table_value:
        return table_value
    lines = text.split("\n")
    candidate_blocks = []
    for i, line in enumerate(lines):
        c = compact(line)
        if "截止" in c:
            block = " ".join(lines[i:i + 3])
            candidate_blocks.append((c, block))

    # 優先：含明確截止 label 的行
    priority_labels = ["截止日期", "截止報名日期", "報名截止日期", "截止報名"]
    for c, block in candidate_blocks:
        if any(k in c for k in priority_labels):
            d = find_date(block)
            if d:
                return d
    # 其次：任何含截止的行
    for c, block in candidate_blocks:
        if "截止" in c:
            d = find_date(block)
            if d:
                return d
    # 2026-10-06：冇「截止」字眼，但寫住「…日或之前（交回／遞交／提交）」
    # 逐行試；同一行搵唔到就先後拼埋隔籬一行（PDF 換行會將日期同「或之前」分開），
    # 但日期同動作之間唔可以跨句號／分號（見 _DEADLINE_DATE_BEFORE_RE）。
    for i, line in enumerate(lines):
        if not _DEADLINE_BEFORE_PHRASE_RE.search(compact(line)):
            continue
        windows = [line]
        if i:
            windows.append(lines[i - 1] + line)
        if i + 1 < len(lines):
            windows.append(line + lines[i + 1])
        for window in windows:
            m = _DEADLINE_DATE_BEFORE_RE.search(compact(window))
            if not m:
                continue
            d = find_date(m.group(1))
            if d:
                return d
    # 「已截止」也算明確訊息
    for c, block in candidate_blocks:
        if "已截止" in compact(block):
            return "已截止"
    return ""


def _valid_date(y, mo, d):
    """驗證日期是否真實存在（避免 2026-12-34 等無效日期）"""
    try:
        from datetime import date as _date
        _date(y, mo, d)
        return True
    except (ValueError, OverflowError):
        return False


def find_date(s):
    c = compact(s)
    # 2026年6月30日 / 2026 年 6 月 30 日
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", c)
    if m:
        y, mo, d = m.groups()
        if _valid_date(int(y), int(mo), int(d)):
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    # 2026年6月30日（沒有「日」字也接受）
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})(?:日)?", c)
    if m:
        y, mo, d = m.groups()
        if _valid_date(int(y), int(mo), int(d)):
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    # 2026-06-30 / 2026/6/30
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", c)
    if m:
        y, mo, d = m.groups()
        if _valid_date(int(y), int(mo), int(d)):
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    # 30/06/2026 或 30-06-2026
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", c)
    if m:
        d, mo, y = m.groups()
        if _valid_date(int(y), int(mo), int(d)):
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


# ─── 表格欄位（2026-10-06）──────────────────────────────────
# 通告正文係表格時，表頭同資料列會被 pdfplumber 排成相連文字，於是
# 「日期 星期 時間 費用 名額 截止日期」之後就跟住「2027年1月2日 六 … 2026年12月11日」。
# 舊版 extract_deadline 喺呢個 3 行窗口攞第一個日期＝第一堂日期（唔係截止日）。
# 有表格結構就直接讀「截止日期」欄，唔使猜。
_TABLE_DEADLINE_HEADER_RE = re.compile(r"截止")
_TABLE_FEE_HEADER_RE = re.compile(r"^(?:費用|班費|收費|報名費|活動費用|團費)")
# 2026-10-06：好多通告唔寫「截止」兩個字，而係「必須於 2026 年 11 月 30 日
# （星期一）或之前填妥回條，交回…」。個案：東九龍地域 26228「2027年童軍獎券
# 籌募活動」——舊版完全抽唔到截止日（前端顯示空白，但內文白紙黑字寫住 11 月 30 日）。
# 只認「（日期）…或之前」同時有交回／遞交／提交／寄回／電郵／傳真等動作嘅行，
# 而且要行內（或緊接一行）有完整年份日期，唔會亂認「每年的 6 月 30 日前提交」。
_DEADLINE_BEFORE_PHRASE_RE = re.compile(r"或之前|之前|前(?:交回|遞交|提交|呈交|寄回|寄交|回覆|電郵|傳真)")
# 「（完整日期）…（最多 16 個字，例如『（星期一）』）…或之前／前交回」
# 中間唔可以跨句號／分號——防止「每年 6 月 30 日前提交。…2026 年 10 月 31 日呈交」
# 呢種前後兩句被當成一句。
_DEADLINE_DATE_BEFORE_RE = re.compile(
    r"(20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)[^。；\n]{0,16}?"
    r"(?:或之前|之前|前(?:交回|遞交|提交|呈交|寄回|寄交|回覆|電郵|傳真))"
)


def _table_column_first_value(tables, header_re, max_header_rows=4):
    """喺表格搵表頭含指定字眼嘅欄，回傳該欄第一個非空值。"""
    for rows in tables or []:
        column = None
        start = 0
        for i, row in enumerate(rows[:max_header_rows]):
            for j, cell in enumerate(row):
                if header_re.search(compact(cell)):
                    column, start = j, i + 1
                    break
            if column is not None:
                break
        if column is None:
            continue
        for row in rows[start:]:
            if column < len(row):
                value = str(row[column] or "").strip()
                if value:
                    return value
    return ""


def deadline_from_tables(tables):
    """表格『截止日期』欄嘅第一個日期（抽唔到就回空字串，唔猜）。"""
    value = _table_column_first_value(tables, _TABLE_DEADLINE_HEADER_RE)
    return find_date(value) if value else ""


def fee_from_tables(tables):
    """表格『費用／班費／收費』欄嘅第一個金額。

    只認個欄名，唔會攞「按金」（可退）或者「名額」；純數字欄位（例如 160）
    喺童軍通告一律當港幣。
    """
    value = _table_column_first_value(tables, _TABLE_FEE_HEADER_RE)
    if not value:
        return ""
    bare = compact(value)
    if re.fullmatch(r"[\d,]+(?:\.\d+)?", bare):
        return f"HK${bare}"
    return normalize_fee(value)


def extract_after_label(text, label_keys, stop_keys, max_len=120):
    """通用：搵到 label 行 → 抽 label 後面的內容（到冒號後），跨行接到遇上 stop_key 為止。"""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        c = compact(line)
        if any(k in c for k in label_keys):
            # 抽冒號之後
            m = re.search(r"[:：]\s*(.+)$", line)
            val = (m.group(1).strip() if m else "")
            # 若同行冒號後為空，往下接一行
            j = i + 1
            while not val and j < len(lines) and j <= i + 1:
                val = lines[j].strip()
                j += 1
            val = val.strip()
            if val:
                return clean_value(val, max_len)
    return ""


def _recipient_scope(text):
    """公函式通告嘅收件人欄（「致：各旅長／旅負責領袖」）。

    2026-10-03：區會通告成日冇「參加資格／對象」label，但開頭「致：」就係收件人
    （紅磡區「區總部公布」個案）。只認行首嘅「致／受文者」＋冒號，而且只睇頭 15 行，
    避免內文「致謝」等字眼誤中；「知會：」係副本，刻意唔當對象。
    """
    for line in (text or "").split("\n")[:15]:
        match = re.match(r"^(?:致|受文者)\s*[:：]\s*(.+)$", compact(line))
        if match:
            return match.group(1)
    return ""


def extract_audience(text):
    """對象：只從明確『參加資格/對象』label 附近辨識支部主體。
    主體離不開：小童軍/幼童軍/童軍/深資童軍/樂行童軍/領袖/家長/成年成員/公眾。

    設計原則（非常重要）：
      - **寧願漏抽，絕不亂抽**
      - 無明確 label 時寧願回傳空字串，也不用全段文字 fallback
      - 因為全段文字可能出現「本活動不適合深資童軍」或附件中引用其他支部，
        亂抽會導致用戶錯過報名或報錯對象

    v2.2 改動 (2026-08): find_date 日曆驗證，拒絕無效日期

    v2.1 改動：
      - label 後掃描範圍維持 2 行（平衡覆蓋率與準確率）
      - 無 label 時不回傳任何結果
      - 維持「由窄到闊」匹配，避免「童軍」吃掉「幼童軍/深資童軍」
    """
    # 先鎖定 label 後面一段範圍（資格段通常在 label 後 1-2 行）
    scope = locate_label_scope(
        text,
        label_keys=["參加資格", "參加對象", "對象", "資格"],
        lines_after=2,
        stop_keys=["費用", "收費", "名額", "報名", "截止", "日期", "辦法"],
        follow_list=True,   # 2026-10-06：資格通常係（1）（2）（3）多行清單
    )
    if not scope:
        # 冇「參加資格／對象」label 時，先睇公函收件人欄（「致：…」）；
        # 都冇就寧願漏抽。
        scope = _recipient_scope(text)
    if not scope:
        return ""  # 無明確 label，寧願漏抽

    c = compact(scope)
    # 主體辨識（次序由窄到闊，避免「童軍」吃掉「幼童軍/深資童軍」）
    found = []
    rules = [
        ("小童軍", "小童軍"),
        ("幼童軍", "幼童軍"),
        ("深資童軍", "深資童軍"),
        ("樂行童軍", "樂行童軍"),
        ("童軍", "童軍"),
        ("領袖", "領袖"),
        ("家長", "家長"),
        ("成年成員", "成年成員"),
        ("會務委員", "會務委員"),
        ("公眾", "公眾"),
    ]
    tmp = c
    for needle, label in rules:
        if needle in tmp:
            found.append(label)
            # 移走已配對的較長詞，避免「童軍」重覆命中「幼童軍」殘留
            tmp = tmp.replace(needle, "")
    # 去重保序
    seen = set(); ordered = []
    for x in found:
        if x not in seen:
            seen.add(x); ordered.append(x)
    return "、".join(ordered)


# 2026-10-06：「參加資格」呢類欄位後面通常係（1）（2）（3）… 編號清單，
# 每項一行，全部加埋先知有邊幾個支部／身分（個案：26241「一個石籃的故事」
# 舊版只抽到前 2 行，漏咗「持有有效委任狀之會務委員」）。
_LIST_ITEM_RE = re.compile(r"^(?:（\d{1,2}）|\(\d{1,2}\)|\d{1,2}[.、)）]|[•·])")


def locate_label_scope(text, label_keys, lines_after=3, stop_keys=None,
                       follow_list=False, max_follow=6):
    """回傳 label 那行（冒號後）+ 之後 N 行的合併文字。
    若提供 stop_keys：合併後續行時，一遇到含 stop 詞的行就停，
    避免把下一個欄位（如『報名辦法』）的內容撈進來。
    follow_list=True（只係「參加資格／對象」用）：之後嘅行如果係
    （1）（2）… 編號清單就繼續讀，最多多讀 max_follow 行。"""
    stop_keys = stop_keys or []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        c = compact(line)
        if any(k in c for k in label_keys):
            m = re.search(r"[:：]\s*(.+)$", line)
            head = (m.group(1) if m else line)
            tail_parts = []
            for nl in lines[i + 1:i + 1 + lines_after]:
                if any(k in compact(nl) for k in stop_keys):
                    break
                tail_parts.append(nl)
            if follow_list:
                n = i + 1 + lines_after
                extra = 0
                while n < len(lines) and extra < max_follow:
                    nxt = lines[n]
                    c2 = compact(nxt)
                    if not c2:
                        n += 1
                        continue
                    if any(k in c2 for k in stop_keys):
                        break
                    if not _LIST_ITEM_RE.match(c2):
                        break
                    tail_parts.append(nxt)
                    extra += 1
                    n += 1
            return head + " " + " ".join(tail_parts)
    return ""


# 金額樣式：$123 / HK$123 / 港幣123元 / 123元 / 全免 / 免費
FEE_PATTERNS = [
    r"全免",
    r"免費",
    r"(?:HK\$|HKD|港幣|\$)\s*[\d,]+(?:\.\d+)?\s*元?(?:正)?",
    r"[\d,]+\s*元(?:正)?",
]

def extract_fee(text, tables=None):
    """費用：抽『費用 label』附近的金額。
    v2 改動：
      - 擴大 label 關鍵詞，包括「費用」「收費」「報名費」「活動費用」「費用全免」等
      - 優先判斷全免 / 豁免
      - 抽到兩個金額且一個剛好是另一個的一半 → 用細嗰個（半費資助）
      - 否則保留兩個（應付身份差價）
    2026-10-06：內文抽唔到（例如費用只出現喺表格嘅「費用($)」欄）→ 讀表格欄。
    """
    scope = locate_label_scope(
        text,
        # 2026-10-06：加「售價」——紀念品／盲盒訂購類通告寫「售價：每個港幣 50 元」
        # （個案：東九龍地域「東九50時間錦囊」盲盒訂購），舊版會漏咗費用。
        label_keys=["費用", "收費", "報名費", "餐費", "團費", "班費", "活動費用", "報名費用", "售價"],
        lines_after=2,
    )
    value = _fee_from_scope(scope)
    if value:
        return value
    return fee_from_tables(tables) if tables else ""


def _fee_from_scope(scope: str) -> str:
    """由『費用』label 附近嘅文字抽金額（scope 空＝抽唔到）。"""
    if not scope:
        return ""
    c = compact(scope)
    if re.search(r"費用全免|全免|免費", c):
        return "全免"
    # 只看第一句，避免撈到後段代購費／按金
    first_sentence = re.split(r"[。;；]", c, maxsplit=1)[0]

    combined = r"(?:HK\$|HKD|港幣|\$)\s*[\d,]+(?:\.\d+)?\s*元?(?:正)?|[\d,]+\s*元(?:正)?"
    spans = []
    raw = []          # 保留原字串（含「港幣…元正」格式）
    nums = []         # 對應數值
    for m in re.finditer(combined, first_sentence):
        if any(not (m.end() <= s or m.start() >= e) for s, e in spans):
            continue
        spans.append((m.start(), m.end()))
        a = m.group(0).strip(" ,，.。、")
        digits = re.search(r"[\d,]+", a)
        if not digits:
            continue
        val = int(digits.group(0).replace(",", ""))
        if val <= 0:
            continue
        if a not in raw:
            raw.append(a)
            nums.append(val)

    if not raw:
        return ""
    if len(raw) == 1:
        return normalize_fee(raw[0])

    # 取前兩個判斷：
    # 只有在附近文字明確提到「資助 / 半費 / 資助後」且剛好 2 倍時，先至取細價。
    # 否則寧願顯示兩個金額，避免把真．身份差價誤判為資助。
    a_raw, b_raw = raw[0], raw[1]
    a_num, b_num = nums[0], nums[1]
    big, small_raw = (a_raw, b_raw) if a_num >= b_num else (b_raw, a_raw)
    big_n, small_n = max(a_num, b_num), min(a_num, b_num)
    has_subsidy_hint = re.search(r"資助|半費|資助後|減半|資助計劃", compact(scope))
    if has_subsidy_hint and small_n > 0 and big_n == small_n * 2:
        return normalize_fee(small_raw)        # 半費資助，取實價
    return f"{normalize_fee(a_raw)} / {normalize_fee(b_raw)}"   # 真．身份差價，兩個都保留


def normalize_fee(fee_str: str) -> str:
    """統一費用格式：
      - 全免 / 免費 / 費用全免 → "全免"
      - 港幣$10 / HK$10 / $10 / 港幣10元 / 10元正 → "HK$10"
      - 美元 USD$10 / US$10 → "US$10"（國際活動）
      - 保留小數點（如 HK$12.5）

    注意：此處假設無特別標示貨幣的金額均為港幣，符合香港童軍通告絕大多數情況。
    """
    if not fee_str:
        return ""
    s = compact(fee_str)
    if re.search(r"費用全免|全免|免費", s):
        return "全免"
    # 美元優先
    m = re.search(r"(?:USD\$|US\$|美元)\s*([\d,]+(?:\.\d+)?)", s)
    if m:
        return f"US${m.group(1)}"
    m = re.search(r"(?:HK\$|HKD|港幣|\$)\s*([\d,]+(?:\.\d+)?)\s*元?(?:正)?", s)
    if m:
        return f"HK${m.group(1)}"
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*元(?:正)?", s)
    if m:
        return f"HK${m.group(1)}"
    return fee_str.strip()


def clean_value(v, max_len):
    v = re.sub(r"\s+", " ", v).strip()
    # 去掉開頭的編號殘留 如 "： " / "1. "
    v = re.sub(r"^[:：\d\.\)）、\s]+", "", v)
    if len(v) > max_len:
        v = v[:max_len].rstrip() + "…"
    return v


def extract_fields(text, title="", source="", tables=None):
    """Extract display fields and the stable IDs used for personalised push.

    ``tables`` 係 pdf_tables_via_pdfplumber() 嘅輸出（可選）：表格通告嘅
    截止／費用準好多（見 deadline_from_tables / fee_from_tables）。
    """
    audience = extract_audience(text)
    subscription = extract_subscription_metadata(title, text, audience, source=source)
    return {
        "deadline": extract_deadline(text, tables=tables),
        "audience": audience,
        "fee": extract_fee(text, tables=tables),
        "categories": subscription["categories"],
        "branch_tags": subscription["branch_tags"],
        "subscription_tags": subscription["subscription_tags"],
        "subscription_tag_details": subscription["subscription_tag_details"],
        "subscription_catalog_version": subscription["catalog_version"],
    }


# ─── 下載 ─────────────────────────────────────────────────
def drive_direct_url(url):
    """Google Drive 分享連結 → 直接下載連結；認唔出就回 None。

    /file/d/<id>/view 係一個 HTML 檢視頁，直接下載會攞到 HTML 而唔係 PDF。
    要轉成 uc?export=download&id=<id> 先攞到檔案本身。

    設計原則：**寧願唔抽，都唔好抽錯**。
    - 認唔出格式 → 回 None（唔猜、唔亂砌 URL）
    - 就算轉換成功，下載返嚟仍然要過 magic bytes（%PDF）先當數；
      Drive 有時會回權限頁／病毒掃描中介頁，嗰啲一律當 not_pdf 丟棄，
      唔會塞半頁 HTML 落去當通告內容。
    """
    m = re.search(r"/file/d/([\w-]+)", url)
    if not m:
        m = re.search(r"[?&]id=([\w-]+)", url)
    if not m:
        return None
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}"


def download(url, timeout=25):
    # URL 含中文 → 需 percent-encode（保留已 encode 的部分）
    safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    req = urllib.request.Request(safe_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _empty_enrichment(title, error, source=""):
    """Retain title-based subscription tags even when the PDF is unavailable."""
    fields = extract_fields("", title, source=source)
    fields["_error"] = error
    fields["_verified_title"] = title
    fields["_title_check"] = "unverified"
    return fields


def enrich_one(url, title="", use_ocr=True, verbose=False, source=""):
    """回傳 dict：截止／對象／費用／分類／個人化標籤。"""
    fetch_url = url
    if "drive.google" in url or "docs.google" in url:
        direct = drive_direct_url(url)
        if not direct:
            # 認唔出格式就唔猜，直接放棄 —— 寧願冇資料，好過抽錯資料
            return _empty_enrichment(title, "drive_unrecognized", source=source)
        fetch_url = direct

    try:
        data = download(fetch_url)
    except Exception as e:
        return _empty_enrichment(title, f"download: {type(e).__name__}", source=source)

    # magic bytes 檢查是否真 PDF。
    # Drive 回權限頁／病毒掃描中介頁／登入頁時都係 HTML，會喺呢度被擋落嚟，
    # 唔會當成通告內容抽欄位。
    if not data[:5].startswith(b"%PDF"):
        return _empty_enrichment(title, "not_pdf", source=source)

    text = pdf_text_via_pdfplumber(data)
    # 2026-10-06：PDF metadata 標題（用嚟確認列表標題）+ 表格（截止／費用欄）。
    meta_title = pdf_meta_title_via_pdfplumber(data)
    tables = pdf_tables_via_pdfplumber(data)
    method = "text"
    probe = extract_fields(text, title, source=source, tables=tables)

    # 文字抽唔到任何欄位 + 文字本身太少 → 可能圖片型 → OCR
    has_any = any(probe[k] for k in ("deadline", "audience", "fee"))
    if (not has_any and len(compact(text)) < 40) and use_ocr:
        if verbose:
            print("    → 文字型抽唔到，改用 OCR")
        ocr_text = pdf_text_via_ocr(data)
        if ocr_text.strip():
            method = "ocr"
            text = ocr_text

    check = reconcile_listing_title(title, text, pdf_meta_title=meta_title)
    verified_title = check["title"]
    fields = extract_fields(text, verified_title, source=source, tables=tables)
    fields["_method"] = method
    fields["_verified_title"] = verified_title
    fields["_title_check"] = check["status"]
    fields["_pdf_heading"] = check.get("pdf_heading") or ""
    fields["_title_similarity"] = check.get("similarity") or 0.0
    if check.get("pdf_meta_title"):
        fields["_pdf_meta_title"] = check["pdf_meta_title"]
    return fields


# ─── 主流程 ───────────────────────────────────────────────
# 除咗 .pdf 之外仲可以直接攞到 PDF bytes 嘅下載端點。
# 2026-10-06：東九龍地域（140 條，全部）用 WordPress Download Manager
# （/circulars/download/?wpdmdl=NNNN）發通告，URL 唔會以 .pdf 結尾，所以
# collect_targets 一直跳過佢哋 —— 結果該來源全部通告冇截止／對象／費用／分類，
# 前端於是把每一張都顯示成「公布」。下載返嚟照樣要過 %PDF magic bytes，
# 唔係 PDF 就當 not_pdf（唔會亂塞內容）。
_ENRICHABLE_URL_RE = re.compile(r"[?&]wpdmdl=\d+", re.I)


def url_path_lower(url: str) -> str:
    return (url or "").split("#")[0].split("?")[0].lower()


def is_enrichable_url(url: str) -> bool:
    """呢個 URL 值唔值得下載去抽 PDF 內文。"""
    url = url or ""
    if url_path_lower(url).endswith(".pdf"):
        return True
    return bool(_ENRICHABLE_URL_RE.search(url))


# 2026-10-06：預設（增量）模式嘅補漏窗（日）。每日 workflow 只跑增量，一旦某個
# 來源／URL 形狀之前被 collect_targets 靜靜跳過（例如東九龍地域嘅 ?wpdmdl= 下載
# 連結，140 條全部冇 enrich），佢哋永遠唔會補做。有咗呢個窗口，最近 N 日入庫而
# enrich.json 仍然冇紀錄嘅通告會自動執返；已經有當前版本標籤嘅唔會重抽。
# 實測成本：最近 7 日只有 0–2 條係仍然唔 enrichable（.docx／.xlsx 報名表）。
INCREMENTAL_CATCHUP_DAYS = 7


def collect_targets(cache, target_date, do_all, do_backfill, do_backfill_categories=False,
                    catchup_days=INCREMENTAL_CATCHUP_DAYS):
    """回傳要處理的 [(source, title, pdf_url)]

    四種模式：
      - 預設（增量）：抓 captured_date == target_date 的當天新通告，
        另外補做最近 catchup_days 日仍然冇 enrich 紀錄嘅通告（見上）
      - --backfill：  抓「所有日期」但稍後跳過已 enrich 的，用來補歷史欠帳（如 5/23 批次匯入的舊通告）
      - --backfill-categories：抓「所有日期」但只處理缺 categories 或舊 taxonomy 嘅
      - --all：       強制全量重抽（連已 enrich 的也重抽；重！極少用）
    """
    out = []
    data = cache.get("data", {})
    for source, arr in data.items():
        for it in arr:
            url = it.get("pdf_url") or it.get("url") or ""
            # Google Drive 連結唔會以 .pdf 結尾，但可以轉成直接下載連結，
            # 下載返嚟仍要過 magic bytes 檢查先當數（見 enrich_one）。
            is_drive = ("drive.google" in url or "docs.google" in url)
            if is_drive:
                if not drive_direct_url(url):
                    continue          # 認唔出格式就唔猜
            elif not is_enrichable_url(url):
                continue
            # 預設模式：今日 + 最近 catchup_days 日嘅補漏窗；
            # --all / --backfill / --backfill-categories 則不分日期全收
            if not do_all and not do_backfill and not do_backfill_categories:
                cap = str(it.get("captured_date", ""))[:10]
                if catchup_days > 0:
                    try:
                        lower = (
                            datetime.date.fromisoformat(target_date) - datetime.timedelta(days=catchup_days)
                        ).isoformat()
                    except ValueError:
                        lower = target_date
                    if not (lower <= cap <= target_date):
                        continue
                elif cap != target_date:
                    continue
            out.append((source, it.get("title", ""), url))
    return out


def skip_reason(url: str) -> str:
    """未支援連結嘅原因（用嚟喺警號入面分類，方便判斷係設定問題定係真係冇 PDF）。"""
    name = url_path_lower(url).rsplit("/", 1)[-1]
    if "." in name:
        ext = name.rsplit(".", 1)[-1]
        if ext and all(ch.isalnum() for ch in ext) and len(ext) <= 5:
            return f".{ext}"
    return "網頁／無檔案尾綴"


def summarize_skipped_links(cache, target_date, do_all, do_backfill, do_backfill_categories,
                            catchup_days=INCREMENTAL_CATCHUP_DAYS):
    """回傳「連結形狀未支援所以唔會 enrich」嘅統計：[(來源, 條數, 例子URL)]。

    2026-10-06（用戶個案）：東九龍地域 140 條全部用 WordPress Download Manager
    （?wpdmdl=），collect_targets 以前只認 `.pdf` 尾，靜靜跳過——個來源就永遠
    冇截止／對象／費用／分類，而且冇任何訊息提示。呢個函數將「靜默跳過」變成
    每次 run 都印出嚟嘅警號，等下一次有新來源／新連結形狀時即刻見到。
    """
    counts = {}
    for source, arr in (cache.get("data") or {}).items():
        if not isinstance(arr, list):
            continue
        for it in arr:
            if not isinstance(it, dict):
                continue
            url = it.get("pdf_url") or it.get("url") or ""
            if "drive.google" in url or "docs.google" in url:
                if drive_direct_url(url):
                    continue            # Drive 支援，唔算跳過
            elif is_enrichable_url(url):
                continue
            if not do_all and not do_backfill and not do_backfill_categories:
                cap = str(it.get("captured_date", ""))[:10]
                if catchup_days > 0:
                    try:
                        lower = (datetime.date.fromisoformat(target_date)
                                 - datetime.timedelta(days=catchup_days)).isoformat()
                    except ValueError:
                        lower = target_date
                    if not (lower <= cap <= target_date):
                        continue
                elif cap != target_date:
                    continue
            entry = counts.setdefault(source, [0, url])
            entry[0] += 1
    return sorted(((s, c, u) for s, (c, u) in counts.items()), key=lambda x: -x[1])


def check_environment(args):
    """啟動自檢：缺 pdfplumber 直接停；缺 OCR 元件只警告。"""
    print("🔧 環境自檢…")
    ok = True
    # pdfplumber 是必須
    try:
        import pdfplumber  # noqa
        print("  ✅ pdfplumber")
    except Exception:
        print("  ❌ pdfplumber 未安裝 —— 冇佢咩都抽唔到！")
        print("     請執行：  pip install pdfplumber")
        ok = False

    # OCR 元件（可選；除非 --no-ocr）
    if not args.no_ocr:
        try:
            import pytesseract  # noqa
            import pdf2image    # noqa
            print("  ✅ pytesseract / pdf2image")
        except Exception:
            print("  ⚠️ pytesseract / pdf2image 未安裝 —— 圖片型 PDF 將無法 OCR")
            print("     pip install pytesseract pdf2image pillow")
        # tesseract 執行檔
        import shutil
        if shutil.which("tesseract"):
            print("  ✅ tesseract 執行檔")
            try:
                import subprocess
                langs = subprocess.run(["tesseract", "--list-langs"],
                                       capture_output=True, text=True, timeout=10).stdout
                if "chi_tra" in langs:
                    print("  ✅ 中文語言包 chi_tra")
                else:
                    print("  ⚠️ 缺中文語言包 chi_tra（圖片型 PDF 中文會抽唔到）")
                    print("     安裝：sudo apt install tesseract-ocr-chi-tra")
            except Exception:
                pass
        else:
            print("  ⚠️ 系統未安裝 tesseract（圖片型 PDF 將無法 OCR）")
            print("     安裝：sudo apt install tesseract-ocr tesseract-ocr-chi-tra poppler-utils")

    if not ok:
        print("\n❌ 缺少必要元件，已停止。請先安裝上面標 ❌ 的套件。")
        sys.exit(1)
    print()


def main():
    ap = argparse.ArgumentParser(description="B 補充爬蟲：抽 PDF 截止/對象/費用")
    ap.add_argument("--date", default=None, help="目標 captured_date（預設今日）")
    ap.add_argument("--all", action="store_true", help="全量重抽所有 .pdf（含已抽過的；重！會大量重下載，僅離峰/補歷史欠帳用）")
    ap.add_argument("--backfill", action="store_true", help="補歷史欠帳：抽所有未 enrich 的 .pdf（不限日期，但跳過已做的）")
    ap.add_argument("--backfill-categories", action="store_true", help="補分類／舊 taxonomy 欠帳的 .pdf（會重新下載，量較大）")
    ap.add_argument("--limit", type=int, default=0, help="最多處理幾條（0=不限）")
    ap.add_argument("--no-ocr", action="store_true", help="停用 OCR")
    ap.add_argument("--report", action="store_true", help="行完輸出 enrich_review.md 方便人手核對")
    ap.add_argument("--apply-title-fixes", action="store_true",
                    help="真係把核對出嘅標題写回 cache.json（預設只報告、唔改 cache）。"
                         "注意：之前呢個寫入係死嘅（cache_dirty 設咗從來冇用過），"
                         "所以 log 講「已改正」但 cache.json 一個字都冇變。")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # ── 環境自檢（避免靜靜地全部抽空）──
    check_environment(args)

    today = args.date or datetime.datetime.now(HKT).date().isoformat()

    if not os.path.exists(CACHE_FILE):
        print(f"❌ 找唔到 {CACHE_FILE}")
        sys.exit(1)
    cache = json.load(open(CACHE_FILE, encoding="utf-8"))

    enrich = {}
    if os.path.exists(ENRICH_FILE):
        enrich = json.load(open(ENRICH_FILE, encoding="utf-8"))

    targets = collect_targets(cache, today, args.all, args.backfill, args.backfill_categories)
    # 跳過已抽過：--all 強制重抽（不跳過）
    # - 預設增量：新通告或仍未有個人化標籤的今日通告才處理；
    # - --backfill：跳過已 enrich，但重試暫時性下載失敗；
    # - --backfill-categories：保留舊旗標，補 categories／subscription_tags 欠帳；
    # - 永久性錯誤（如 not_pdf）唔重試，避免白白重下載。
    if not args.all:
        def _entry(u):
            value = enrich.get(u)
            return value if isinstance(value, dict) else {}

        def _retryable_error(u):
            err = (_entry(u).get("error") or "")
            return args.backfill and err.startswith("download")

        def _has_current_tags(u):
            entry = _entry(u)
            # 空 array 也是已判斷結果；以欄位存在＋目前 catalog version 為準，
            # 否則一張不屬四類的通告會被每天重下載。升級 taxonomy（例如新增
            # 獨立比賽）時，--backfill-categories 也會重建舊版本 metadata。
            # 2026-10-06：再加 `enrich_version`——抽 PDF 嘅規則（標題、表格
            # 截止／費用、課程標籤過濾）一升級，最近 7 日窗口內用舊版抽出嘅
            # 結果就會自動重抽一次。冇呢個檢查，改完規則都只會影響將來嘅新
            # 通告，舊 entry 因為 catalog version 冇變而永遠唔會重算。
            return (
                "categories" in entry
                and "branch_tags" in entry
                and "subscription_tags" in entry
                and entry.get("subscription_catalog_version") == CURRENT_SUBSCRIPTION_CATALOG_VERSION
                and entry.get("enrich_version") == ENRICH_VERSION
            )

        if args.backfill_categories:
            targets = [t for t in targets if not _has_current_tags(t[2])]
        elif args.backfill:
            targets = [t for t in targets if t[2] not in enrich or _retryable_error(t[2])]
        else:
            targets = [t for t in targets if t[2] not in enrich or not _has_current_tags(t[2])]

    if args.limit:
        targets = targets[:args.limit]

    mode = "全量重抽" if args.all else ("補分類／舊 taxonomy 欠帳" if args.backfill_categories else ("補歷史欠帳" if args.backfill else "增量"))
    print(f"🔎 目標：{len(targets)} 條 .pdf 通告（模式={mode}"
          + (f"，captured_date={today}" if not args.all and not args.backfill else "") + "）")
    print(f"   OCR：{'停用' if args.no_ocr else '啟用'}\n")

    # 「靜默跳過」警號：連結形狀未支援嘅通告（今次唔會 enrich、亦唔會有人知）。
    # 東九龍地域 140 條 ?wpdmdl= 就係咁樣整整一個來源冇數據；而家每次 run 都印。
    skipped = summarize_skipped_links(cache, today, args.all, args.backfill, args.backfill_categories)
    if skipped:
        total_skipped = sum(c for _, c, _ in skipped)
        reasons = {}
        for _, count, url in skipped:
            key = skip_reason(url)
            reasons[key] = reasons.get(key, 0) + count
        reason_text = "、".join(f"{k} {v} 條" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
        top = "、".join(f"{s} {c} 條" for s, c, _ in skipped[:6])
        print(f"⏭  連結形狀未支援（唔會 enrich）：{total_skipped} 條（{reason_text}）")
        print(f"    來源：{top}")
        print(f"    例：{skipped[0][2][:96]}")
        print("    如果某個來源整批落喺呢度，檢查 sources.json 嘅 selector（攞到嘅係")
        print("    檔案連結定係文章頁），再喺 enrich.py is_enrichable_url() 加新形狀")
        print("    ＋補 test_enrich.py 回歸測試。\n")

    done = ok = 0
    cache_dirty = False
    title_corrections = 0
    error_counts = {}   # (來源, 錯誤) → 條數；收尾一次過報，唔會再靜默失敗
    for idx, (source, title, url) in enumerate(targets):
        if idx > 0:
            # v2.4: 下載之間加隨機延遲（同 core.py 標準）——
            # 5/23 教訓：同一 session 連環下載最易觸發站點封鎖
            time.sleep(random.uniform(1.5, 4.0))
        print(f"[{source}] {title[:36]}")
        listing_title = title  # 核對前嘅列表標題：更正一旦寫入，要用嚟記住原貌
        res = enrich_one(url, title=title, use_ocr=not args.no_ocr, verbose=args.verbose, source=source)
        verified_title = res.get("_verified_title") or title
        title_check = res.get("_title_check") or "unverified"
        if title_check == "corrected" and verified_title != title and not heading_looks_like_title(verified_title):
            # 抽出嚟嘅嘢唔似標題（欄位／檔號／表格行）→ 寧願唔改，當未核實
            title_check = "unverified"
            verified_title = title
            res["_title_check"] = title_check
        if title_check == "corrected" and verified_title != title:
            sim = res.get("_title_similarity", 0)
            if args.apply_title_fixes:
                if apply_title_to_cache(cache, url, verified_title):
                    cache_dirty = True
                    title_corrections += 1
                    print(f"   ⚠️ 標題與 PDF 不符（相似 {sim:.0%}），"
                          f"已寫回 cache.json：{title[:28]} → {verified_title[:28]}")
                else:
                    # cache 入面根本搵唔到呢個 url：講明冇改到，唔好扮改咗
                    print(f"   ⚠️ 標題與 PDF 不符（相似 {sim:.0%}），但 cache 入面搵唔到呢個 url，未改："
                          f"{title[:28]} → {verified_title[:28]}")
            else:
                # 預設：只報告。舊版呢句无条件印「已改正」，但個寫入係死嘅
                # （cache_dirty 設咗從來冇用過），所以 cache.json 一個字都冇變 ——
                # 呢個 repo 最怕嘅就係呢類靜默失敗，而家講真話。
                print(f"   ⚠️ 標題與 PDF 對唔上（相似 {sim:.0%}），建議改："
                      f"{title[:28]} → {verified_title[:28]}"
                      f"（未寫入；要真改加 --apply-title-fixes）")
            title = verified_title
        enrich[url] = {
            "source": source,
            "title": title,
            "deadline": res.get("deadline", ""),
            "audience": res.get("audience", ""),
            "fee": normalize_fee(res.get("fee", "")),
            "categories": res.get("categories") or [],
            "branch_tags": res.get("branch_tags") or [],
            "subscription_tags": res.get("subscription_tags") or [],
            "subscription_tag_details": res.get("subscription_tag_details") or [],
            "subscription_catalog_version": res.get("subscription_catalog_version", ""),
            "method": res.get("_method", ""),
            "error": res.get("_error", ""),
            "title_check": title_check,
            "enriched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "enrich_version": ENRICH_VERSION,
        }
        if title_check == "corrected" and title != listing_title:
            # 記住原本列表標題：cache 每次重建都會用返列表標題，靠呢個欄位
            # 之後先可以安全地重新套用更正（見 reapply_stored_title_fixes）。
            enrich[url]["listing_title"] = listing_title
        tag = res.get("_error") or res.get("_method")
        got = [k for k in ("deadline", "audience", "fee", "categories", "subscription_tags") if res.get(k)]
        cats = "、".join(c.get("label", "") for c in (res.get("categories") or []))
        sub_tags = "、".join(res.get("subscription_tags") or [])
        print(f"   [{tag}] 截止={res.get('deadline') or '—'} | "
              f"對象={(res.get('audience') or '—')[:20]} | 費用={(res.get('fee') or '—')[:20]} | "
              f"分類={cats or '—'} | 訂閱={sub_tags or '—'}")
        if res.get("_error"):
            error_counts[(source, res["_error"])] = error_counts.get((source, res["_error"]), 0) + 1
        done += 1
        if got:
            ok += 1

    json.dump(enrich, open(ENRICH_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n✅ 完成：處理 {done} 條，抽到內容 {ok} 條 → {ENRICH_FILE}")

    # 收尾報告：失敗原因要一眼睇到（唔好再出現「某個來源永遠冇數據但冇人知」）。
    # not_pdf 尤其重要——多數係 WPDM／Drive 之類要 cookie 或改 headers 嘅下載端點。
    if error_counts:
        summary = "、".join(f"{src} {err} {n} 條" for (src, err), n in
                            sorted(error_counts.items(), key=lambda kv: -kv[1]))
        print(f"⚠️  今次有 {sum(error_counts.values())} 條抽唔到：{summary}")

    # 2026-10-03：core.py 每次抓取（包括 --force）都會用列表頁標題重建
    # cache.json，之前寫入嘅更正會被蓋走。呢度零下載重新套用已核實嘅更正，
    # 令「區總部公布」等 PDF 真標題長期有效。
    if args.apply_title_fixes:
        reapplied = reapply_stored_title_fixes(cache, enrich)
        if reapplied:
            cache_dirty = True
            print(f"📝 重新套用 {reapplied} 個已核實嘅 PDF 標題（cache 之前被列表標題蓋走）")

    # 2026-09-14：呢個寫入之前完全冇接上（cache_dirty 設咗從來冇讀過），
    # 所以 PR #19 個「標題雙重認證」實際上從未改過 cache.json。
    # 而家明確接上，但只喺 --apply-title-fixes 先至會觸發，預設仍然淨係報告。
    if cache_dirty:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"📝 已更新 {CACHE_FILE}（今次新寫入 {title_corrections} 個核對過嘅標題）")

    if args.report:
        write_report(enrich)
        print(f"📄 已輸出可讀報告 → enrich_review.md")


def write_report(enrich):
    rows = list(enrich.values())
    got = sum(1 for r in rows if r.get("deadline") or r.get("fee") or r.get("audience"))
    out = ["# enrich.py 抽取結果 — 人手核對", "",
           f"> 共 {len(rows)} 條 ｜ 抽到內容 {got} 條", "",
           "| 來源 | 標題 | 截止 | 對象 | 費用 | 方式 |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| {} | {} | {} | {} | {} | {} |".format(
            r.get("source", ""), (r.get("title", "")[:26]).replace("|", "/"),
            r.get("deadline") or "—", (r.get("audience") or "—")[:30],
            (r.get("fee") or "—")[:20], r.get("method") or r.get("error") or ""))
    open("enrich_review.md", "w", encoding="utf-8").write("\n".join(out))


if __name__ == "__main__":
    main()
