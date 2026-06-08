#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich.py — B 補充爬蟲（截止日期 / 對象 / 費用）
========================================================
設計原則：
  - 完全獨立於主爬蟲 core.py，不讀寫 cache.json 內部結構
  - 只讀 cache.json 篩「captured_date = 今日」的新通告
  - 只抽 .pdf 直鏈（Drive 暫不處理）
  - 抽取方式：先用 pdfplumber 文字 + label 定位 regex；
              文字型抽唔到 → 用 OCR (tesseract chi_tra) fallback
  - 結果寫去 enrich.json（獨立檔），key = pdf_url
  - 抽唔到 = 留空（靠固定 label，不亂猜，唔會抽錯）

用法：
  python enrich.py                 # 抽今日新通告
  python enrich.py --all           # 抽所有未記錄過的 .pdf
  python enrich.py --date 2026-06-07
  python enrich.py --limit 5 --verbose
  python enrich.py --no-ocr        # 停用 OCR
"""

import argparse
import datetime
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import logging
import warnings

# 靜音 pdfminer/pdfplumber 嘈雜的 FontBBox 等警告
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

CACHE_FILE = "cache.json"
ENRICH_FILE = "enrich.json"

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


# ─── 欄位抽取 ─────────────────────────────────────────────
CN_NUM = "零一二三四五六七八九十"

def extract_deadline(text):
    """截止日期：搵所有含『截止』的行，回傳第一個帶有效日期者。
    （報名類通告通常只有一個截止日期；『報名辦法』行雖含截止二字但無日期，會略過。）"""
    lines = text.split("\n")
    candidate_blocks = []
    for i, line in enumerate(lines):
        c = compact(line)
        if "截止" in c:
            block = " ".join(lines[i:i + 2])
            candidate_blocks.append((c, block))
    # 優先：含「截止日期」label 的行
    for c, block in candidate_blocks:
        if "截止日期" in c or "截止報名" in c:
            d = find_date(block)
            if d:
                return d
    # 其次：任何含截止的行
    for c, block in candidate_blocks:
        d = find_date(block)
        if d:
            return d
    # 「已截止」也算明確訊息
    for c, block in candidate_blocks:
        if "已截止" in compact(block):
            return "已截止"
    return ""


def find_date(s):
    c = compact(s)
    # 2026年6月30日 / 2026 年 6 月 30 日
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", c)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # 2026-06-30 / 2026/6/30
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", c)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return ""


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


def extract_audience(text):
    """對象：唔抽整段，而是從『參加資格/對象』附近文字辨識出包含的支部主體。
    主體離不開：小童軍/幼童軍/童軍/深資童軍/樂行童軍/領袖/家長/成年成員/公眾。"""
    # 先鎖定 label 後面一段範圍（資格段通常在 label 後 1-3 行）
    scope = locate_label_scope(
        text,
        label_keys=["參加資格", "參加對象", "對象", "資格"],
        lines_after=2,
        stop_keys=["費用", "收費", "名額", "報名", "截止", "日期", "辦法"],
    )
    if not scope:
        return ""
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


def locate_label_scope(text, label_keys, lines_after=3, stop_keys=None):
    """回傳 label 那行（冒號後）+ 之後 N 行的合併文字。
    若提供 stop_keys：合併後續行時，一遇到含 stop 詞的行就停，
    避免把下一個欄位（如『報名辦法』）的內容撈進來。"""
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
            return head + " " + " ".join(tail_parts)
    return ""


# 金額樣式：$123 / HK$123 / 港幣123元 / 123元 / 全免 / 免費
FEE_PATTERNS = [
    r"全免",
    r"免費",
    r"(?:HK\$|HKD|港幣|\$)\s*[\d,]+(?:\.\d+)?\s*元?(?:正)?",
    r"[\d,]+\s*元(?:正)?",
]

def extract_fee(text):
    """費用：抽『費用 label』附近的金額。
    規則（依實際觀察）：
      - 抽到兩個金額且一個剛好是另一個的一半 → 用細嗰個
        （童軍通告的『原價 / 半費資助後實價』必為 2 倍關係；
         未見過 0.7、0.8 折，故 2 倍即可判定為資助原價，取實價）
      - 否則保留兩個（應付『領袖 $100 / 成員 $50』這類真．身份差價，
        但身份差價甚少剛好 2 倍，故不會誤殺）
    """
    scope = locate_label_scope(
        text,
        label_keys=["費用", "收費", "報名費", "餐費", "團費", "班費", "活動費用"],
        lines_after=1,
    )
    if not scope:
        return ""
    c = compact(scope)
    if re.search(r"全免|免費", c):
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
        return raw[0]

    # 取前兩個判斷：剛好 2 倍 → 資助原價，用細嗰個
    a_raw, b_raw = raw[0], raw[1]
    a_num, b_num = nums[0], nums[1]
    big, small = (a_raw, b_raw) if a_num >= b_num else (b_raw, a_raw)
    big_n, small_n = max(a_num, b_num), min(a_num, b_num)
    if small_n > 0 and big_n == small_n * 2:
        return small        # 半費資助，取實價
    return f"{a_raw} / {b_raw}"   # 真．身份差價，兩個都保留


def clean_value(v, max_len):
    v = re.sub(r"\s+", " ", v).strip()
    # 去掉開頭的編號殘留 如 "： " / "1. "
    v = re.sub(r"^[:：\d\.\)）、\s]+", "", v)
    if len(v) > max_len:
        v = v[:max_len].rstrip() + "…"
    return v


def extract_fields(text):
    return {
        "deadline": extract_deadline(text),
        "audience": extract_audience(text),
        "fee": extract_fee(text),
    }


# ─── 下載 ─────────────────────────────────────────────────
def download(url, timeout=25):
    # URL 含中文 → 需 percent-encode（保留已 encode 的部分）
    safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    req = urllib.request.Request(safe_url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def enrich_one(url, use_ocr=True, verbose=False):
    """回傳 dict：{deadline, audience, fee, _method}"""
    try:
        data = download(url)
    except Exception as e:
        return {"_error": f"download: {type(e).__name__}", "deadline": "", "audience": "", "fee": ""}

    # magic bytes 檢查是否真 PDF
    if not data[:5].startswith(b"%PDF"):
        return {"_error": "not_pdf", "deadline": "", "audience": "", "fee": ""}

    text = pdf_text_via_pdfplumber(data)
    method = "text"
    fields = extract_fields(text)

    # 文字抽唔到任何欄位 + 文字本身太少 → 可能圖片型 → OCR
    has_any = any(fields.values())
    if (not has_any and len(compact(text)) < 40) and use_ocr:
        if verbose:
            print("    → 文字型抽唔到，改用 OCR")
        ocr_text = pdf_text_via_ocr(data)
        if ocr_text.strip():
            method = "ocr"
            fields = extract_fields(ocr_text)

    fields["_method"] = method
    return fields


# ─── 主流程 ───────────────────────────────────────────────
def collect_targets(cache, target_date, do_all):
    """回傳要處理的 [(source, title, pdf_url)]"""
    out = []
    data = cache.get("data", {})
    for source, arr in data.items():
        for it in arr:
            url = it.get("pdf_url") or it.get("url") or ""
            if not url.lower().endswith(".pdf"):
                continue
            if "drive.google" in url:
                continue
            if not do_all:
                cap = it.get("captured_date", "")
                if cap != target_date:
                    continue
            out.append((source, it.get("title", ""), url))
    return out


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
    ap.add_argument("--all", action="store_true", help="抽所有未記錄過的 .pdf")
    ap.add_argument("--limit", type=int, default=0, help="最多處理幾條（0=不限）")
    ap.add_argument("--no-ocr", action="store_true", help="停用 OCR")
    ap.add_argument("--report", action="store_true", help="行完輸出 enrich_review.md 方便人手核對")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # ── 環境自檢（避免靜靜地全部抽空）──
    check_environment(args)

    today = args.date or datetime.date.today().isoformat()

    if not os.path.exists(CACHE_FILE):
        print(f"❌ 找唔到 {CACHE_FILE}")
        sys.exit(1)
    cache = json.load(open(CACHE_FILE, encoding="utf-8"))

    enrich = {}
    if os.path.exists(ENRICH_FILE):
        enrich = json.load(open(ENRICH_FILE, encoding="utf-8"))

    targets = collect_targets(cache, today, args.all)
    # 跳過已抽過（除非 --all 強制重抽）
    if not args.all:
        targets = [t for t in targets if t[2] not in enrich]

    if args.limit:
        targets = targets[:args.limit]

    print(f"🔎 目標：{len(targets)} 條 .pdf 通告"
          + (f"（captured_date={today}）" if not args.all else "（全部未記錄）"))
    print(f"   OCR：{'停用' if args.no_ocr else '啟用'}\n")

    done = ok = 0
    for source, title, url in targets:
        print(f"[{source}] {title[:36]}")
        res = enrich_one(url, use_ocr=not args.no_ocr, verbose=args.verbose)
        enrich[url] = {
            "source": source,
            "title": title,
            "deadline": res.get("deadline", ""),
            "audience": res.get("audience", ""),
            "fee": res.get("fee", ""),
            "method": res.get("_method", ""),
            "error": res.get("_error", ""),
            "enriched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        tag = res.get("_error") or res.get("_method")
        got = [k for k in ("deadline", "audience", "fee") if res.get(k)]
        print(f"   [{tag}] 截止={res.get('deadline') or '—'} | "
              f"對象={(res.get('audience') or '—')[:20]} | 費用={(res.get('fee') or '—')[:20]}")
        done += 1
        if got:
            ok += 1

    json.dump(enrich, open(ENRICH_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n✅ 完成：處理 {done} 條，抽到內容 {ok} 條 → {ENRICH_FILE}")

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
