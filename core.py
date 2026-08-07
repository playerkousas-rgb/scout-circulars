#!/usr/bin/env python3
"""
全港童軍通告自動化圖書館 v5.6.17 — 核心爬蟲引擎 (core.py)
========================================================
目標只有一個：未來總會 / 地域 / 區會一有新更新，就能穩定抓回來給成員看到。


  1. 極度嚴格的錯誤通報機制：任何連線異常、403、404 皆會觸發 has_errors=true
  2. 確保爬蟲只增不減，徹底隔離舊資料覆寫風險

v5.6.15 核心修復 (2026-08):
  1. 部分特殊 type 失敗時 fall through 而非 return None
  2. expected_empty 指紋保留空白 hash
  3. pw_used 計數修正
  4. 來源間延遲增至 random 1.5~4.0s
  5. enrich.py find_date 日曆驗證
  6. sources.json 補回青衣區

v5.6.14 核心修復 (2026-06):
  1. 更新 sources.json 針對多個改版網站:
     - 九龍城區 (klcscout.hk/circular): .datagrid 容器 + 強制PW + 更好標題選擇器
     - 旺角區: 更新至正確通告及表格下載子頁 + 強制PW + 廣義選擇器
     - 秀茂坪區: 更新url至首頁最新消息 (含實際PDF)
     - 港島西區: 更新至 circular2026/ 直接抓最新PDF表格
     - 大嶼山區 (Wix): 加大超時至90s + fingerprint + 滾動等待
  2. Playwright 增強: 自動滾動 + 針對Google/Wix/klcscout 額外等待時間，幫助動態載入
  3. 保留原有所有穩定邏輯

v5.6.13-fix 核心修復:
  1. Playwright 增加超時到 60 秒
  2. 模擬真實瀏覽器頭和行為
  3. 添加隨機等待降低風控
  1. 無條件在 HTTP 錯誤/異常時自動降級 Playwright
  2. 解決 GitHub Actions IP 被屏蔽問題:
  1. 恢復 HTTP 錯誤/異常時自動降級 Playwright 的邏輯:
  1. 強化 WP API 分頁參數相容性
  2. 更新 GENERIC_DOWNLOAD_TITLES 以支援更多免篩選字詞 (如 pdf格式)
  3. 修復 WP API 的通告名稱合併與覆寫邏輯

v5.4 核心升級:
  1. 不再只抓 PDF，改抓「可下載資產」(downloadable assets)
  2. 列表頁 + 內頁兩階段作業
  3. 指紋比對仍然保留，用來極速跳過沒變動頁面
  4. 來源隔離：唯一鍵改為 (source_site, pdf_url)
  5. cache.json 改為按來源分組 data[source]，並保留 notices 扁平輸出作兼容
  6. 前端 / GitHub Raw / 本地 cache 都可以讀同一份 cache.json

注意:
  - 為兼容你現有 Supabase schema 與欄位名，資產網址欄位仍叫 pdf_url
  - 但語義上它已經代表「downloadable asset url」，不再只限 PDF
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

# HKT
HKT = ZoneInfo("Asia/Hong_Kong")

def hkt_now():
    return datetime.now(HKT)

def hkt_today_str():
    return datetime.now(HKT).strftime("%Y-%m-%d")

def hkt_now_str():
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

# ─── Playwright (optional, lazy import) ───────────────────
_playwright_available = False
try:
    from playwright.sync_api import sync_playwright
    _playwright_available = True
except ImportError:
    pass

# ─── 路徑配置 ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
SOURCES_PATH = BASE_DIR / "sources.json"
CACHE_PATH = BASE_DIR / "cache.json"
FINGERPRINTS_PATH = BASE_DIR / "fingerprints.json"

# ─── Supabase 配置 ────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_TABLE = "scout_notices"
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

# ─── HTTP Session ─────────────────────────────────────────
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
})

DOWNLOAD_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".rtf", ".csv"
}
IGNORE_FILE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp",
    ".mp4", ".mp3", ".mov", ".avi", ".webm"
}
BAD_TITLE_FRAGMENTS = {"é", "ś", "ă", "æ", "°", "â", "ã"}
NAV_TEXT_PATTERNS = [
    "首頁", "主頁", "home", "更多", "read more", "詳情", "詳閱", "查看",
    "上一頁", "下一頁", "prev", "next", "facebook", "instagram", "youtube",
    "whatsapp", "分享", "share", "聯絡", "contact", "登入", "login",
    "register", "訂閱", "搜尋", "search", "menu", "download", "下載附件"
]
SOCIAL_HOST_PATTERNS = [
    "facebook.com", "instagram.com", "youtube.com", "wa.me", "twitter.com",
    "x.com", "linkedin.com", "t.me"
]
GENERIC_DOWNLOAD_TITLES = {
    "下載", "download", "檔案下載", "file download", "附件", "attachment",
    "按此下載", "download here", "here", "click here", "pdf格式", "(pdf格式)", "doc格式", "(doc格式)",
    "通告", "表格", "[通告]", "[表格]", "下載通告", "查看", "詳情", "更多資訊", "read more", "詳閱"
}
ARTICLE_SOURCE_TYPES = {
    "home_news", "wordpress", "wordpress_archive", "wordpress_category",
    "wordpress_dynamic", "wordpress_elementor", "wordpress_post",
    "joomla_category", "joomla_archive", "modern_cms"
}

# ─── Playwright browser singleton ────────────────────────
_pw_browser = None
_pw_controller = None


@dataclass
class FetchResult:
    url: str
    html: str
    engine: str
    status_code: int = 200


def get_browser():
    global _pw_browser, _pw_controller
    if _pw_browser is not None:
        return _pw_browser
    if not _playwright_available:
        return None
    _pw_controller = sync_playwright().start()
    _pw_browser = _pw_controller.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )
    return _pw_browser


def close_browser():
    global _pw_browser, _pw_controller
    if _pw_browser:
        try:
            _pw_browser.close()
        except Exception:
            pass
        _pw_browser = None
    if _pw_controller:
        try:
            _pw_controller.stop()
        except Exception:
            pass
        _pw_controller = None


# ─── 文字 / URL 工具 ──────────────────────────────────────
def normalize_text(value: str) -> str:
    value = html_lib.unescape(value or "")
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[\u200b-\u200f\ufeff]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def is_generic_download_title(title: Optional[str]) -> bool:
    title = normalize_text(title or "").lower()
    return title in GENERIC_DOWNLOAD_TITLES


def clean_title(raw_title: str, config: Dict[str, Any]) -> Optional[str]:
    title = normalize_text(raw_title)
    if not title:
        return None

    # strip common brackets from link texts like [通告]
    title = re.sub(r'^\[|\]$', '', title).strip()

    # URL 解碼
    title = unquote(title)
    
    # 移除句尾的副檔名
    title = re.sub(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|rtf|csv)$", "", title, flags=re.I).strip()
    
    # 移除 Apache index 常見的截斷後綴
    title = re.sub(r"\.\.>$", "", title)
    title = re.sub(r"\.\.&gt;$", "", title)
    title = re.sub(r"\.\.$", "", title)
    
    # 將底線替換為空白
    title = title.replace("_", " ")
    title = re.sub(r"\s+", " ", title).strip()

    # 智能移除童軍通告編號前綴 (例如 TPN/CIR/VS/2627/003 或 TPN CIR S 2526 006)
    # 匹配: 2-5個英文字母 + (可選的英文部門代號) + 2-4位數字年份 + 2-3位數字序號
    prefix_pattern = r"^[A-Za-z]{2,5}[/\-_\s]+(?:[A-Za-z]{1,4}[/\-_\s]+)*\d{2,4}[/\-_\s]+\d{2,3}[a-zA-Z]?\s*[/\-_\s]*"
    cleaned_title = re.sub(prefix_pattern, "", title).strip()
    
    # 如果移除前綴後還有剩下真正的文字，就使用乾淨的標題；否則保留原樣(以免完全沒有標題)
    if len(cleaned_title) > 2:
        title = cleaned_title

    regex = config.get("title_filter_regex")
    if regex:
        try:
            title = re.sub(regex, "", title).strip()
        except re.error:
            pass

    for pattern in (config.get("exclude_patterns") or []):
        if pattern and pattern.lower() in title.lower():
            return None

    for bad in BAD_TITLE_FRAGMENTS:
        if bad in title:
            return None

    if is_generic_download_title(title):
        return None

    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", title):
        return None
    if re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}", title):
        return None
    if any(flag in title for flag in ["通告日期", "截止日期", "活動/訓練班名稱"]):
        return None

    min_len = int(config.get("min_title_length") or 4)
    if len(title) < min_len:
        return None

    return title


def fallback_title_from_url(url: str, config: Dict[str, Any]) -> Optional[str]:
    path = unquote(urlparse(url).path)
    filename = path.rsplit("/", 1)[-1]
    filename = re.sub(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|rtf|csv)$", "", filename, flags=re.I)
    filename = filename.replace("_", " ").replace("-", " ")
    return clean_title(filename, config)




def salvage_title_from_text(text: str, config: Dict[str, Any]) -> Optional[str]:
    text = normalize_text(text)
    if not text:
        return None

    # 移除常見日期前綴
    patterns = [
        r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+',
        r'^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\s+',
        r'^\d{4}年\d{1,2}月\d{1,2}日\s*',
        r'^\d{4}-\d{1,2}-\d{1,2}\s*',
    ]
    for pat in patterns:
        text = re.sub(pat, '', text).strip()

    # 移除常見分類 / 編號 / 狀態 / 操作字樣
    text = re.sub(r'[A-Z]{2,8}/\d{2}-\d{2}/[A-Z]{1,4}', ' ', text)
    text = re.sub(r'[A-Z]{2,8}\d{2,4}[A-Z-]*', ' ', text)
    text = re.sub(r'(活動與訓練通告|行政通告|特別通告)第\s*\d+[/-]\d+\s*號', ' ', text)
    text = re.sub(r'(已經結束|接受報名|即將進行|檢視|開啟|下載)', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # 單欄位表格的支部標籤常在標題前面
    text = re.sub(r'^(區會|區|地域總部|小童軍|幼童軍|童軍|深資童軍|樂行童軍)\s+', '', text).strip()
    if text in {'行政通告', '特別通告', '公布', '地域總部', '刊物', '通告', '區會', '小童軍', '幼童軍', '童軍', '深資童軍', '樂行童軍'}:
        return None
    if re.fullmatch(r'[A-Za-z]{2,10}(?:[/-][A-Za-z0-9]{1,10}){1,6}', text):
        return None
    if re.fullmatch(r'[A-Za-z]{2,12}\d{2,8}[A-Za-z-]*', text):
        return None
    text = re.sub(r'^(小|幼|童|深|樂)\s+', '', text).strip()

    # 遇到分類/受眾/百分比編碼等長尾噪音就截斷
    cut_tokens = [
        ' 所有成員', ' 小童軍,', ' 幼童軍,', ' 童軍,', ' 深資童軍,', ' 樂行童軍,',
        ' 行政通告', ' 特別通告', ' 活動/訓練', ' 地域總部 / 刊物',
        ' 九龍地域最新消息', ' announcement ', ' 活動與訓練 ', ' 活動／課程之報名須知 '
    ]
    for token in cut_tokens:
        if token in text:
            left = text.split(token, 1)[0].strip()
            if left:
                text = left
                break

    if '%e' in text.lower():
        text = re.split(r'\s+%[0-9a-fA-F]{2}', text, maxsplit=1)[0].strip()

    text = re.sub(r'\s+', ' ', text).strip(' -–—|/：:')
    cleaned = clean_title(text, config)
    return cleaned or None


def nearest_container(anchor: Any) -> Optional[Any]:
    node = anchor
    while node is not None:
        name = getattr(node, 'name', None)
        if name in {'tr', 'li', 'article', 'section'}:
            return node
        if name == 'div':
            txt = normalize_text(node.get_text(' ', strip=True))
            classes = ' '.join(node.get('class', [])) if hasattr(node, 'get') else ''
            if txt and txt not in {'下載', 'download'}:
                if any(key in classes for key in ['media', 'well', 'entry', 'post', 'content', 'item', 'card']):
                    return node
                if len(txt) > 20:
                    return node
        node = node.parent
    return None


def infer_listing_title(anchor: Any, page_soup: BeautifulSoup, config: Dict[str, Any]) -> Optional[str]:
    raw_candidates: List[str] = []

    # 1. anchor 自身文字
    raw_candidates.append(anchor.get_text(' ', strip=True) or '')
    if anchor.get('title'):
        raw_candidates.append(anchor.get('title'))
    if anchor.get('aria-label'):
        raw_candidates.append(anchor.get('aria-label'))

    container = nearest_container(anchor)
    title_selector = config.get('title_selector')

    # 2. 先處理表格列，因為很多來源真正標題在相鄰 td
    if container is not None and getattr(container, 'name', None) == 'tr':
        for cell in container.find_all(['td', 'th']):
            raw_candidates.append(cell.get_text(' ', strip=True) or '')

    # 3. 再看鄰近容器內 title_selector
    if container is not None and title_selector:
        try:
            nodes = container.select(title_selector)
        except Exception:
            nodes = []
        for node in nodes:
            raw_candidates.append(node.get_text(' ', strip=True) or '')

    # 4. 容器全文
    if container is not None:
        raw_candidates.append(container.get_text(' ', strip=True) or '')

    # 5. page level title_selector 最後補救
    if title_selector:
        try:
            nodes = page_soup.select(title_selector)
        except Exception:
            nodes = []
        for node in nodes[:5]:
            raw_candidates.append(node.get_text(' ', strip=True) or '')

    seen = set()
    for cand in raw_candidates:
        cand = normalize_text(cand)
        if not cand or cand in seen:
            continue
        seen.add(cand)
        fixed = salvage_title_from_text(cand, config)
        if fixed:
            return fixed

    return None

def resolve_url(base_url: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base_url, href)


def sanitize_url(url: str, sanitize_params: Optional[List[str]] = None) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    strip_keys = {
        "v", "t", "ver", "timestamp", "authuser", "usp",
        "_", "nocache", "rand", "random"
    }
    for p in sanitize_params or []:
        p = (p or "").strip()
        if p.startswith("?"):
            strip_keys.add(p[1:].split("=", 1)[0].strip())

    path_lower = parsed.path.lower()
    if 'wpdmdl' in parsed.query and '/download/' not in path_lower and not path_lower.endswith(tuple(ext for ext in DOWNLOAD_EXTENSIONS)):
        strip_keys.add('wpdmdl')

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    cleaned_items = []
    for k, v in query_items:
        if k in strip_keys or k.startswith("utm_"):
            continue
        cleaned_items.append((k, v))

    query = urlencode(cleaned_items, doseq=True)
    cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))
    return cleaned.rstrip("?&")


def url_path_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    if "." not in path:
        return ""
    return "." + path.rsplit(".", 1)[-1]


def is_download_url(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    host = urlparse(lowered).netloc
    path = urlparse(lowered).path

    ext = url_path_ext(lowered)
    if ext in DOWNLOAD_EXTENSIONS:
        return True
    if ext in IGNORE_FILE_EXTENSIONS:
        return False

    if "drive.google.com" in host:
        if "/file/d/" in path or "/uc" in path or "export=download" in lowered:
            return True
    if "dropbox.com" in host and ("dl=1" in lowered or path.endswith(tuple(DOWNLOAD_EXTENSIONS))):
        return True
    if any(k in lowered for k in ["download=1", "download=", "/download/", "attachment_id="]):
        return True
    return False


def is_article_candidate(url: str, root_url: str, text: str) -> bool:
    if not url or is_download_url(url):
        return False

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    if url_path_ext(url) in IGNORE_FILE_EXTENSIONS:
        return False

    root_host = urlparse(root_url).netloc.lower()
    host = parsed.netloc.lower()
    if host != root_host:
        return False

    if any(social in host for social in SOCIAL_HOST_PATTERNS):
        return False

    lowered_text = normalize_text(text).lower()
    if lowered_text and any(pattern in lowered_text for pattern in NAV_TEXT_PATTERNS):
        return False

    path = parsed.path.lower().strip()
    if path in {"", "/"}:
        return False

    return True


def broaden_selector(selector: Optional[str]) -> Optional[str]:
    if not selector:
        return selector
    replacements = [
        ("[href$='.pdf']", "[href]"),
        ('[href$=".pdf"]', "[href]"),
        ("[href*='.pdf']", "[href]"),
        ('[href*=".pdf"]', "[href]"),
        ("[href*='drive.google.com']", "[href]"),
        ('[href*="drive.google.com"]', "[href]"),
    ]
    out = selector
    for old, new in replacements:
        out = out.replace(old, new)
    return out


def encoding_shield_response(resp: requests.Response, config: Dict[str, Any]) -> None:
    forced = (config.get("encoding") or '').strip().lower()
    apparent = (resp.apparent_encoding or '').strip().lower()
    if forced in {'big5', 'cp950'} and apparent and apparent not in {'big5', 'cp950'}:
        resp.encoding = resp.apparent_encoding
    elif forced in {'big5', 'cp950'}:
        resp.encoding = 'cp950'
    else:
        resp.encoding = resp.apparent_encoding or forced or 'utf-8'


# ─── 指紋引擎 ──────────────────────────────────────────────
def compute_fingerprint(soup: BeautifulSoup, selector: str) -> str:
    try:
        elements = soup.select(selector)
        if not elements:
            body = soup.select_one("body")
            elements = [body] if body else []

        parts: List[str] = []
        for el in elements:
            anchors = el.select("a[href]")
            if anchors:
                for a in anchors:
                    href = normalize_text(a.get("href", ""))
                    text = normalize_text(a.get_text(" ", strip=True))
                    if href or text:
                        parts.append(f"{href}|{text}")
            else:
                parts.append(normalize_text(el.get_text(" ", strip=True)))

        combined = "|".join(parts)
        return hashlib.md5(combined.encode("utf-8", errors="ignore")).hexdigest()
    except Exception:
        return ""


# ─── 抓頁引擎 ──────────────────────────────────────────────
def fetch_requests(url: str, config: Dict[str, Any], timeout: int = 20) -> FetchResult:
    try:
        resp = SESSION.get(url, timeout=timeout, verify=config.get("verify_ssl", True))
    except requests.exceptions.SSLError:
        resp = SESSION.get(url, timeout=timeout, verify=False)
    except Exception as e:
        raise e
    encoding_shield_response(resp, config)
    return FetchResult(url=resp.url, html=resp.text, engine="requests", status_code=resp.status_code)


def fetch_with_playwright(name: str, config: Dict[str, Any], url: Optional[str] = None) -> Optional[FetchResult]:
    if not _playwright_available:
        print(f"  [{name}] ⚠️ Playwright 未安裝 (pip install playwright && playwright install chromium)")
        return None

    browser = get_browser()
    if not browser:
        return None

    target_url = url or config["url"]
    wait_strategy = config.get("wait_strategy", "networkidle")
    wait_selector = config.get("wait_selector", "")
    wait_timeout = int(config.get("wait_timeout", 60000))  # 增加超時到 60 秒

    page = None
    try:
        # 使用更真實的瀏覽器上下文
        context = browser.contexts[0] if browser.contexts else browser.new_context(
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
            }
        )
        
        # 隨機化 viewport（像真實用戶）
        viewport_width = 1920
        viewport_height = 1080
        
        page = context.new_page()
        page.set_default_timeout(60000)  # 增加到 60 秒超時
        
        # 模擬真實瀏覽器頭
        page.set_extra_http_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
        
        print(f"  [{name}] 🎭 嘗試 Playwright ({target_url[:60]}...)")
        
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        
        # 隨機等待（像真實用戶）
        import random
        page.wait_for_timeout(random.uniform(1000, 3000))
        
        if wait_strategy == "selector" and wait_selector:
            page.wait_for_selector(wait_selector, state="attached", timeout=wait_timeout)
            page.wait_for_timeout(random.uniform(500, 1500))
        else:
            page.wait_for_load_state("networkidle", timeout=wait_timeout)
            # 再等待一下（像真實用戶在看頁面）
            page.wait_for_timeout(random.uniform(1000, 2000))

        # 額外處理動態/重JS網站 (Google Sites, Wix, klcscout 等)：滾動載入更多內容 + 額外等待
        try:
            import random
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(random.uniform(1000, 2500))
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(random.uniform(500, 1500))
            lowered = target_url.lower()
            if "google" in lowered or "sites.google" in lowered or "wix" in lowered or "klcscout" in lowered:
                page.wait_for_timeout(random.uniform(2000, 6000))  # heavy sites extra time
                # 嘗試再滾一次
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
                page.wait_for_timeout(random.uniform(800, 2000))
        except Exception:
            pass

        html = page.content()
        print(f"  [{name}] 🎭 Playwright 成功，HTML 長度: {len(html)}")

        return FetchResult(url=page.url, html=html, engine="playwright", status_code=200)
    except Exception as e:
        print(f"  [{name}] ⚠️ Playwright: {type(e).__name__}: {e}")
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def has_useful_candidates(soup: BeautifulSoup, config: Dict[str, Any]) -> bool:
    selectors = [
        broaden_selector(config.get("link_selector")),
        broaden_selector(config.get("title_selector")),
        config.get("fingerprint_selector"),
    ]
    for sel in selectors:
        if not sel:
            continue
        try:
            if soup.select(sel):
                return True
        except Exception:
            continue
    return bool(soup.select("a[href]"))


def fetch_page(url: str, config: Dict[str, Any], force_playwright: bool = False) -> Optional[FetchResult]:
    use_playwright = force_playwright or config.get('use_playwright', False)
    result = None
    try:
        result = fetch_requests(url, config, timeout=30)
        if result.status_code == 200:
            soup = BeautifulSoup(result.html, 'html.parser')
            if has_useful_candidates(soup, config):
                return result
        else:
            result = None
    except Exception:
        result = None

    if use_playwright:
        pw_result = fetch_with_playwright('subpage', config, url=url)
        if pw_result is None:
            return None
        return pw_result
    return result

def fetch_main_page(name: str, config: Dict[str, Any]) -> Optional[FetchResult]:
    url = config.get("url", "")
    use_playwright = config.get("use_playwright", False)
    result: Optional[FetchResult] = None

    # --- Google Sites + Drive folderview Injection (旺角區等：通告放喺 Drive 資料夾) ---
    if config.get("type") == "gsites_folders":
        import requests as _rq, re as _re
        print(f"[{name}] === 抓取 Google Sites Drive 資料夾 ===")
        try:
            r = _rq.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            page_html = r.text
        except Exception as e:
            print(f"[{name}] ⚠️ gsites_folders 失敗: {e}，fall through")
        # v5.6.15: 成功已在上面 return，失敗 fall through 到通用路徑

        # 從主頁抽出所有 Drive 資料夾 id
        folder_ids = set(_re.findall(
            r"(?:drive|docs)\.google\.com/(?:embedded)?folderview\?id=([\w-]+)", page_html))
        folder_ids |= set(_re.findall(r"drive\.google\.com/drive/folders/([\w-]+)", page_html))
        print(f"[{name}] 發現 {len(folder_ids)} 個 Drive 資料夾")

        mock_html = "<html><body>"
        count = 0
        seen = set()
        for fid in folder_ids:
            try:
                fr = _rq.get(f"https://drive.google.com/embeddedfolderview?id={fid}#list",
                             timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                fsoup = BeautifulSoup(fr.text, "html.parser")
            except Exception:
                continue
            for entry in fsoup.select(".flip-entry"):
                a = entry.find("a", href=True)
                if not a:
                    continue
                m = _re.search(r"/file/d/([\w-]+)", a.get("href", ""))
                href = f"https://drive.google.com/file/d/{m.group(1)}/view" if m else a["href"]
                if href in seen:
                    continue
                seen.add(href)
                tnode = entry.select_one(".flip-entry-title")
                title = (tnode.get_text(strip=True) if tnode else a.get_text(strip=True)) or f"{name}通告"
                mock_html += f'<a href="{href}">{title}</a><br/>'
                count += 1
                print(f"[{name}] 找到通告 → {title} → {href}")
        mock_html += "</body></html>"
        print(f"[{name}] 完成！共 {count} 個 Drive 通告")
        return FetchResult(url=url, html=mock_html, engine="requests", status_code=200)
    # ---------------------------------

    # --- iframe Drive Injection (雙魚區等：通告以 Google Drive iframe 嵌入) ---
    # 注意：必須在通用 use_playwright 早退之前處理，否則會被攔截。
    if config.get("type") == "iframe_drive":
        import re
        print(f"[{name}] === 抓取 iframe Drive 嵌入頁 (Playwright render) ===")
        pw_result = fetch_with_playwright(name, config, url=url)
        if pw_result is None:
            print(f"[{name}] ⚠️ Playwright render 失敗，fall through")
            # v5.6.15: 成功在上面 return，失敗 fall through
        soup = BeautifulSoup(pw_result.html, "html.parser")
        BAD = ("日期", "費用", "集合", "報名", "截止", "下載", "申請",
               "地點", "時間", "資助", "名額", "備註", "查詢", "內容")
        iframes = [
            i for i in soup.find_all("iframe", src=True)
            if "drive.google" in i.get("src", "") or "docs.google" in i.get("src", "")
        ]
        mock_html = "<html><body>"
        count = 0
        seen = set()
        for i in iframes:
            src = i.get("src", "").strip()
            # iframe preview 連結 → 還原成可開啟的 Drive 檔案連結
            m = re.search(r"/file/d/([\w-]+)", src)
            href = f"https://drive.google.com/file/d/{m.group(1)}/view" if m else src
            if href in seen:
                continue
            seen.add(href)
            # 標題：向上找最近、長度合理、非欄位標籤開頭的文字
            title = None
            node = i
            for _ in range(60):
                node = node.find_previous()
                if node is None:
                    break
                if not getattr(node, "name", None):
                    continue
                t = node.get_text(" ", strip=True)
                if t and 5 <= len(t) <= 40 and not t.startswith(BAD) \
                        and "：" not in t and ":" not in t:
                    title = t
                    break
            if not title:
                title = f"{name}通告 {count + 1}"
            mock_html += f'<a href="{href}">{title}</a><br/>'
            count += 1
            print(f"[{name}] 找到通告 → {title} → {href}")
        mock_html += "</body></html>"
        print(f"[{name}] 完成！共 {count} 個 Drive 通告")
        # 用 render 後嘅完整頁做指紋，頁面一改即觸發更新
        return FetchResult(url=pw_result.url, html=mock_html, engine="playwright", status_code=200)
    # ---------------------------------

    # 如果來源明確要求 Playwright，則直接使用（避免 requests 靜態 shell 誤判有內容導致跳過PW）
    if use_playwright:
        pw_result = fetch_with_playwright(name, config, url=url)
        if pw_result is None:
            return None
        return pw_result

    # --- Next.js RSC payload Injection (維多利亞城區 Firebase Hosting) ---
    if config.get("type") == "nextjs_rsc":
        import requests, json, re

        base = config.get("base_url") or re.match(r"https?://[^/]+", url).group(0)
        rsc_url = config.get("rsc_url") or url
        print(f"[{name}] === 抓取 Next.js RSC payload: {rsc_url} ===")
        try:
            r = requests.get(
                rsc_url,
                verify=config.get("verify_ssl", True),
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "RSC": "1",
                },
            )
            print(f"[{name}] Status Code: {r.status_code}")
            if r.status_code != 200:
                return None
            t = r.text
        except Exception as e:
            print(f"[{name}] ⚠️ RSC 抓取失敗: {e}")
            return None

        # 逐個 "event":{...} 物件用括號配對切出，再 json.loads
        def _slice_objects(text: str):
            for m in re.finditer(r'"event":\s*\{', text):
                bstart = text.find("{", m.start() + len('"event":'))
                depth = 0
                i = bstart
                while i < len(text):
                    c = text[i]
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    elif c == '"':
                        i += 1
                        while i < len(text) and text[i] != '"':
                            if text[i] == "\\":
                                i += 1
                            i += 1
                    i += 1
                yield text[bstart:i + 1]

        def _localized(v):
            if isinstance(v, dict):
                return v.get("zh") or v.get("en") or next(iter(v.values()), "")
            return v or ""

        mock_html = "<html><body>"
        count = 0
        seen = set()
        for raw in _slice_objects(t):
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            title = (_localized(obj.get("title")) or "Unknown").strip()

            # 收集候選連結：actions[].href 內的 PDF 優先，其次 registrationUrl
            pdf_href = None
            other_href = None
            for a in (obj.get("actions") or []):
                h = (a.get("href") or "").strip()
                if not h:
                    continue
                full = h if h.startswith("http") else base + h
                if h.lower().endswith(".pdf"):
                    pdf_href = full
                elif other_href is None:
                    other_href = full
            reg = (obj.get("registrationUrl") or "").strip()
            if reg and not reg.startswith("http"):
                reg = base + reg

            href = pdf_href or other_href or reg
            if not href:
                # 無附件 fallback：指向該活動內頁
                slug = obj.get("slug", "")
                href = f"{base}/zh/events#{slug}" if slug else f"{base}/zh/events"

            if href in seen:
                continue
            seen.add(href)
            mock_html += f'<a href="{href}">{title}</a><br/>'
            count += 1
            print(f"[{name}] 找到通告 → {title} → {href}")

        mock_html += "</body></html>"
        print(f"[{name}] 完成！共 {count} 個通告")
        return FetchResult(url=url, html=mock_html, engine="requests", status_code=200)
    # ---------------------------------

    # --- WP API Injection ---
    if config.get("type") == "wordpress_api":
        import requests, json
        
        all_posts = []
        page = 1
        max_pages = 10
        
        print(f"[{name}] === 開始抓取 WordPress API ===")

        while page <= max_pages:
            paged_url = f"{url}&per_page=100&page={page}" if "?" in url else f"{url}?per_page=100&page={page}"
            try:
                r = requests.get(
                    paged_url,
                    verify=config.get("verify_ssl", True),
                    timeout=30,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                
                print(f"[{name}] 第 {page} 頁 Status Code: {r.status_code}")
                
                if r.status_code != 200:
                    if page == 1:
                        return None # Trigger error if first page fails
                    break
                    
                posts = r.json()
                print(f"[{name}] 第 {page} 頁 返回類型: {type(posts)}, 數量: {len(posts) if isinstance(posts, list) else '非 list'}")  # ← 重要診斷
                
                if not isinstance(posts, list) or len(posts) == 0:
                    print(f"[{name}] 第 {page} 頁沒有文章，停止")
                    break
                    
                all_posts.extend(posts)
                print(f"[{name}] ✅ 第 {page} 頁成功 | 本頁 {len(posts)} 筆 | 累計 {len(all_posts)} 筆")
                page += 1
                
            except Exception as e:
                print(f"[{name}] 第 {page} 頁異常: {e}")
                break

        # ==================== PDF 提取 ====================
        mock_html = "<html><body>"
        pdf_count = 0
        link_count = 0

        for post in all_posts:
            title = post.get("title", {}).get("rendered", "Unknown").strip()
            date_str = post.get("date", "")[:10]
            content = post.get("content", {}).get("rendered", "")
            post_link = post.get("link", "")

            soup = BeautifulSoup(content, "html.parser")
            
            found_pdf = False
            for a in soup.find_all("a", href=True):
                href = a.get("href", "").strip()
                if href and '.pdf' in href.lower():
                    display_text = title
                    link_text = a.get_text(strip=True)
                    if link_text and not is_generic_download_title(link_text):
                        if link_text.lower() not in title.lower():
                            display_text += f" - {link_text}"
                    
                    mock_html += f'<a href="{href}">{display_text}</a><br/>'
                    pdf_count += 1
                    found_pdf = True
                    print(f"[{name}] 找到 PDF → {display_text}")

            # v5.6.17: allow_page_notice_fallback - 無 PDF 文章用連結
            if not found_pdf and config.get("allow_page_notice_fallback") and post_link:
                mock_html += f'<a href="{post_link}">{title}</a><br/>'
                link_count += 1
                print(f"[{name}] 無PDF文章 → {title} (用文章連結)")

        mock_html += "</body></html>"
        
        print(f"[{name}] 完成！總文章 {len(all_posts)} 筆，PDF {pdf_count} 個，文章連結 {link_count} 個")
        return FetchResult(url=url, html=mock_html, engine="requests", status_code=200)
    # ---------------------------------


    # --- Contentful API Injection ---
    if config.get("type") == "contentful_api":
        import requests, json
        api_url = config.get("api_url")
        headers = config.get("api_headers", {})
        params = config.get("api_params", {})
        try:
            r = requests.get(api_url, params=params, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"  [{name}] ⚠️ Contentful API 回傳 {r.status_code}")
                return None
            data = r.json()
            asset_map = {}
            for asset in data.get("includes", {}).get("Asset", []):
                try:
                    asset_id = asset["sys"]["id"]
                    file_url = asset["fields"]["file"]["url"]
                    if file_url.startswith("//"):
                        file_url = "https:" + file_url
                    asset_map[asset_id] = file_url
                except Exception:
                    pass
            mock_html = "<html><body>"
            for item in data.get("items", []):
                fields = item.get("fields", {})
                title = fields.get("title", "Unknown Title")
                attach = fields.get("attach")
                if attach and isinstance(attach, dict):
                    asset_id = attach.get("sys", {}).get("id")
                    file_url = asset_map.get(asset_id)
                    if file_url:
                        mock_html += f'<a href="{file_url}">{title}</a><br/>'
            mock_html += "</body></html>"
            return FetchResult(url=url, html=mock_html, engine="requests", status_code=200)
        except Exception as e:
            print(f"  [{name}] ⚠️ Contentful API 失敗: {e}")
            return None
    # ---------------------------------

    try:
        result = fetch_requests(url, config, timeout=30)
        if result.status_code != 200:
            print(f"  [{name}] ⚠️ HTTP 錯誤碼: {result.status_code}")
        else:
            soup = BeautifulSoup(result.html, "html.parser")
            if has_useful_candidates(soup, config):
                return result
            print(f"  [{name}] requests 結果太空，改用 Playwright")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  [{name}] ⚠️ requests: {type(e).__name__}")

    # === 無條件嘗試 Playwright（HTTP錯誤/異常/結果空白時自動降級）===
    pw_result = fetch_with_playwright(name, config, url=url)
    if pw_result is None:
        return None # Playwright 也失敗才真正報錯
    return pw_result


# ─── 資產提取 ─────────────────────────────────────────────
def collect_anchor_nodes_by_selectors(soup: BeautifulSoup, selectors: List[str], config: Dict[str, Any]) -> List[Any]:
    anchors: List[Any] = []
    seen_pairs: Set[Tuple[str, str]] = set()

    for raw_sel in selectors:
        if not raw_sel:
            continue
        expanded_selectors = [raw_sel]
        broadened = broaden_selector(raw_sel)
        if broadened and broadened != raw_sel:
            expanded_selectors.append(broadened)

        for sel in expanded_selectors:
            try:
                nodes = soup.select(sel)
            except Exception:
                continue
            for node in nodes:
                anchor = node if getattr(node, "name", None) == "a" else node.find("a", href=True)
                if not anchor:
                    continue
                key = (anchor.get("href", ""), normalize_text(anchor.get_text(" ", strip=True)))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                anchors.append(anchor)

    return anchors


def collect_anchor_nodes(soup: BeautifulSoup, config: Dict[str, Any]) -> List[Any]:
    selectors: List[str] = []
    for key in ["asset_link_selector", "detail_link_selector", "link_selector", "title_selector"]:
        raw = config.get(key)
        if raw:
            selectors.append(raw)

    anchors = collect_anchor_nodes_by_selectors(soup, selectors, config)
    if anchors:
        return anchors

    fp_selector = config.get("fingerprint_selector") or "body"
    try:
        blocks = soup.select(fp_selector)
    except Exception:
        blocks = []
    if not blocks:
        blocks = [soup]

    seen_pairs: Set[Tuple[str, str]] = set()
    for block in blocks:
        for anchor in block.select("a[href]"):
            key = (anchor.get("href", ""), normalize_text(anchor.get_text(" ", strip=True)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            anchors.append(anchor)
    return anchors


def should_follow_detail_pages(config: Dict[str, Any]) -> bool:
    if "follow_detail_pages" in config:
        return bool(config.get("follow_detail_pages"))
    return (config.get("type") or "") in ARTICLE_SOURCE_TYPES


def make_asset_record(url: str, title: Optional[str], config: Dict[str, Any]) -> Optional[Dict[str, str]]:
    final_title = clean_title(title or "", config) if title else None
    if not final_title and title:
        final_title = salvage_title_from_text(title, config)
    if not final_title:
        final_title = fallback_title_from_url(url, config)
    if not final_title:
        return None
    return {"pdf_url": url, "title": final_title}


def extract_detail_assets(soup: BeautifulSoup, detail_url: str, config: Dict[str, Any]) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    seen: Set[str] = set()

    page_title = None
    h1 = soup.select_one("h1")
    if h1:
        page_title = clean_title(h1.get_text(" ", strip=True), config)
    if not page_title and soup.title:
        page_title = clean_title(soup.title.get_text(" ", strip=True), config)

    for a in soup.select("a[href]"):
        href = resolve_url(detail_url, a.get("href"))
        href = sanitize_url(href or "", config.get("url_sanitize", []))
        if not href or not is_download_url(href) or href in seen:
            continue
        seen.add(href)

        anchor_title = clean_title(a.get_text(" ", strip=True), config)
        effective_title = page_title if is_generic_download_title(anchor_title) else (anchor_title or page_title)
        record = make_asset_record(href, effective_title, config)
        if record:
            records.append(record)

    for selector in ["iframe[src]", "embed[src]", "object[data]"]:
        for node in soup.select(selector):
            href = node.get("src") or node.get("data")
            href = resolve_url(detail_url, href)
            href = sanitize_url(href or "", config.get("url_sanitize", []))
            if not href or not is_download_url(href) or href in seen:
                continue
            seen.add(href)
            record = make_asset_record(href, page_title, config)
            if record:
                records.append(record)

    if not records and config.get("allow_page_notice_fallback"):
        fallback_title = page_title or clean_title(soup.get_text(' ', strip=True), config)
        if fallback_title:
            records.append({
                "pdf_url": sanitize_url(detail_url, config.get("url_sanitize", [])),
                "title": fallback_title,
            })

    return records


def fetch_detail_page(name: str, detail_url: str, config: Dict[str, Any]) -> Optional[FetchResult]:
    use_playwright = config.get("use_playwright", False)
    try:
        result = fetch_requests(detail_url, config, timeout=12)
        if result.status_code == 200:
            soup = BeautifulSoup(result.html, "html.parser")
            if extract_detail_assets(soup, result.url, config):
                return result
            if config.get('allow_page_notice_fallback'):
                if soup.find('h1') or soup.find('title') or soup.get_text(' ', strip=True):
                    return result
    except Exception:
        pass

    if use_playwright:
        pw_result = fetch_with_playwright(name, config, url=detail_url)
        if pw_result is None:
            return None
        return pw_result
    return None




def slugify_fragment(text: str) -> str:
    text = normalize_text(text).lower()
    text = re.sub(r'[^\w一-鿿]+', '-', text)
    return text.strip('-')[:80] or 'notice'


def parse_text_notice_blocks(soup: BeautifulSoup, page_url: str, config: Dict[str, Any]) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    selectors = config.get('text_notice_selector') or []
    if isinstance(selectors, str):
        selectors = [selectors]
    notice_pattern = config.get('text_notice_pattern') or r'(?P<code>\d{2}-\d{4})\s+(?P<title>.+?)\s+(?:截止[:：]\s*(?P<deadline>\d{4}-\d{2}-\d{2})|已截止)'
    seen: Set[str] = set()

    for sel in selectors:
        try:
            containers = soup.select(sel)
        except Exception:
            containers = []
        for container in containers:
            heading = ''
            prev = container.find_previous(['h5','h4','h3'])
            if prev:
                heading = normalize_text(prev.get_text(' ', strip=True))
            text_blob = normalize_text(container.get_text(' ', strip=True))
            for m in re.finditer(notice_pattern, text_blob):
                code = normalize_text(m.groupdict().get('code') or '')
                title = normalize_text(m.groupdict().get('title') or '')
                deadline = normalize_text(m.groupdict().get('deadline') or '')
                full_title = f"{heading} - {title}" if heading and heading not in title else title
                full_title = clean_title(full_title, config) or salvage_title_from_text(full_title, config) or title
                if not full_title:
                    continue
                pseudo = page_url + '#' + slugify_fragment((heading + '-' + code + '-' + title).strip('-'))
                if pseudo in seen:
                    continue
                seen.add(pseudo)
                subtitle = f"{code} {full_title}".strip()
                if deadline:
                    subtitle += f" (截止: {deadline})"
                results.append({'pdf_url': pseudo, 'title': subtitle})
    return results

def extract_assets_from_listing(
    name: str,
    soup: BeautifulSoup,
    page_url: str,
    config: Dict[str, Any],
    max_detail_pages: int,
) -> List[Dict[str, str]]:
    assets: List[Dict[str, str]] = []
    detail_candidates: List[str] = []
    seen_assets: Set[str] = set()
    seen_details: Set[str] = set()

    asset_selectors = [config.get("asset_link_selector") or config.get("link_selector") or "a[href]"]
    detail_selectors = []
    if should_follow_detail_pages(config):
        detail_selectors = [
            config.get("detail_link_selector") or config.get("title_selector") or config.get("link_selector") or "a[href]"
        ]

    asset_anchors = collect_anchor_nodes_by_selectors(soup, [s for s in asset_selectors if s], config)
    detail_anchors = collect_anchor_nodes_by_selectors(soup, [s for s in detail_selectors if s], config)
    if should_follow_detail_pages(config) and not detail_anchors:
        detail_anchors = list(asset_anchors)

    accept_all = bool(config.get("accept_all_links"))
    for a in asset_anchors:
        href = resolve_url(page_url, a.get("href"))
        href = sanitize_url(href or "", config.get("url_sanitize", []))
        if not href or href in seen_assets:
            continue
        # accept_all_links: 此來源已在上游(如 nextjs_rsc)精準篩選好連結，
        # 不需再經 is_download_url 過濾，避免漏掉報名表單/內頁等合法通告。
        if not accept_all and not is_download_url(href):
            continue
        raw_text = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
        inferred_title = infer_listing_title(a, soup, config) or raw_text
        record = make_asset_record(href, inferred_title, config)
        if not record:
            continue
        seen_assets.add(href)
        assets.append(record)

    for a in detail_anchors:
        href = resolve_url(page_url, a.get("href"))
        href = sanitize_url(href or "", config.get("url_sanitize", []))
        if not href or href in seen_details:
            continue
        raw_text = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
        if is_article_candidate(href, config.get("url", page_url), raw_text):
            seen_details.add(href)
            detail_candidates.append(href)
        elif is_download_url(href) and href not in seen_assets:
            inferred_title = infer_listing_title(a, soup, config) or raw_text
            record = make_asset_record(href, inferred_title, config)
            if record:
                seen_assets.add(href)
                assets.append(record)

    if not asset_anchors and not detail_anchors:
        for a in collect_anchor_nodes(soup, config):
            href = resolve_url(page_url, a.get("href"))
            href = sanitize_url(href or "", config.get("url_sanitize", []))
            if not href:
                continue
            raw_text = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
            if is_download_url(href):
                if href in seen_assets:
                    continue
                inferred_title = infer_listing_title(a, soup, config) or raw_text
                record = make_asset_record(href, inferred_title, config)
                if record:
                    seen_assets.add(href)
                    assets.append(record)
            elif should_follow_detail_pages(config) and is_article_candidate(href, config.get("url", page_url), raw_text):
                if href not in seen_details:
                    seen_details.add(href)
                    detail_candidates.append(href)

    if not assets and config.get('text_notice_selector'):
        assets.extend(parse_text_notice_blocks(soup, page_url, config))

    if not should_follow_detail_pages(config):
        return assets

    detail_limit = int(config.get("detail_max_pages") or max_detail_pages)
    for detail_url in detail_candidates[:detail_limit]:
        result = fetch_detail_page(name, detail_url, config)
        if not result:
            continue
        detail_soup = BeautifulSoup(result.html, "html.parser")
        for record in extract_detail_assets(detail_soup, result.url, config):
            if record["pdf_url"] in seen_assets:
                continue
            seen_assets.add(record["pdf_url"])
            assets.append(record)

    if not assets and config.get('text_notice_selector'):
        assets.extend(parse_text_notice_blocks(soup, page_url, config))

    return assets


# ─── Cache / Meta 工具 ───────────────────────────────────


def discover_listing_pages(soup: BeautifulSoup, page_url: str, config: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()

    for u in config.get('listing_page_urls') or []:
        full = sanitize_url(resolve_url(page_url, u) or u, config.get('url_sanitize', []))
        if full and full not in seen:
            seen.add(full)
            urls.append(full)

    selectors = config.get('listing_link_selector') or []
    if isinstance(selectors, str):
        selectors = [selectors]
    for sel in selectors:
        for a in collect_anchor_nodes_by_selectors(soup, [sel], config):
            href = sanitize_url(resolve_url(page_url, a.get('href')) or '', config.get('url_sanitize', []))
            if not href or href in seen:
                continue
            if is_download_url(href):
                continue
            seen.add(href)
            urls.append(href)

    return urls

def build_regions(sources: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    regions: Dict[str, List[str]] = {}
    for source_name, conf in sources.items():
        region = conf.get("region") or "未分類"
        regions.setdefault(region, []).append(source_name)
    return regions


def iter_records_from_cache(cache: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(cache.get("notices"), list) and cache["notices"]:
        return [dict(x) for x in cache["notices"] if isinstance(x, dict)]

    grouped = cache.get("data") or {}
    records: List[Dict[str, Any]] = []
    if isinstance(grouped, dict):
        for source_name, arr in grouped.items():
            if not isinstance(arr, list):
                continue
            for item in arr:
                if not isinstance(item, dict):
                    continue
                record = dict(item)
                record.setdefault("source_site", source_name)
                records.append(record)
    return records


def build_grouped_cache(
    all_records: List[Dict[str, Any]],
    all_sources: Dict[str, Dict[str, Any]],
    last_updated: str,
) -> Dict[str, Any]:
    data = {source_name: [] for source_name in all_sources.keys()}
    normalized_records: List[Dict[str, Any]] = []

    for record in all_records:
        source_name = record.get("source_site") or "未知"
        source_conf = all_sources.get(source_name, {})
        normalized_title = clean_title(record.get("title", ""), source_conf) or fallback_title_from_url(record.get("pdf_url", ""), source_conf) or record.get("title", "") or record.get("pdf_url", "")
        normalized = {
            "source_site": source_name,
            "region": record.get("region", source_conf.get("region", "")),
            "pdf_url": record.get("pdf_url", ""),
            "title": normalized_title,
            "captured_date": record.get("captured_date", ""),
        }
        normalized_records.append(normalized)
        data.setdefault(source_name, []).append({
            "title": normalized_title,
            "url": normalized["pdf_url"],
            "pdf_url": normalized["pdf_url"],
            "date": normalized["captured_date"],
            "captured_date": normalized["captured_date"],
            "source_site": source_name,
            "region": normalized["region"],
        })

    for source_name, arr in data.items():
        arr.sort(key=lambda x: ((x.get("date") or x.get("captured_date") or ""), x.get("title") or ""), reverse=True)

    notices = sorted(
        [
            {
                "source_site": r.get("source_site", ""),
                "region": r.get("region", ""),
                "pdf_url": r.get("pdf_url", ""),
                "title": r.get("title", ""),
                "captured_date": r.get("captured_date", ""),
            }
            for r in normalized_records
        ],
        key=lambda x: ((x.get("captured_date") or ""), x.get("source_site") or "", x.get("title") or ""),
        reverse=True,
    )

    return {
        "last_updated": last_updated,
        "meta": {
            "version": "5.3.0",
            "total_sources": len(all_sources),
            "total_notices": len(notices),
            "design": "可下載資產抓取+列表頁內頁雙階段+來源隔離+盲信日期+30天沉底",
        },
        "data": data,
        "notices": notices,
        "_meta": {
            "version": "5.3.0",
            "regions": build_regions(all_sources),
            "source_order": list(all_sources.keys()),
            "total_sources": len(all_sources),
        }
    }


# ─── Supabase 操作 ────────────────────────────────────────
def supabase_fetch_all() -> List[Dict[str, Any]]:
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*&order=captured_date.desc&limit=10000"
    try:
        resp = SESSION.get(url, headers=headers, timeout=15)
        return resp.json() if resp.status_code == 200 else []
    except Exception:
        return []


def supabase_upsert(records: List[Dict[str, Any]]):
    if not records:
        return
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    for i in range(0, len(records), 100):
        batch = records[i:i+100]
        try:
            SESSION.post(url, headers=headers, json=batch, timeout=20)
        except Exception:
            pass


def supabase_update_records(records: List[Dict[str, Any]]):
    if not records:
        return
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    for rec in records:
        source_site = rec.get("source_site", "")
        asset_url = rec.get("pdf_url", "")
        if not source_site or not asset_url:
            continue
        payload = {
            "title": rec.get("title", ""),
            "region": rec.get("region", ""),
        }
        try:
            patch_url = (
                f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
                f"?source_site=eq.{quote(source_site, safe='')}"
                f"&pdf_url=eq.{quote(asset_url, safe='')}"
            )
            SESSION.patch(patch_url, headers=headers, json=payload, timeout=10)
        except Exception:
            pass


# ─── 本地 JSON 儲存 ────────────────────────────────────────
def load_local_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_updated": "", "notices": [], "data": {}, "_meta": {}}


def save_local_cache(data: Dict[str, Any]):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_fingerprints() -> Dict[str, Any]:
    if FINGERPRINTS_PATH.exists():
        try:
            with open(FINGERPRINTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_fingerprints(fp: Dict[str, Any]):
    with open(FINGERPRINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(fp, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ─── 單一來源處理 ──────────────────────────────────────────
def process_source(
    name: str,
    config: Dict[str, Any],
    fingerprints: Dict[str, Any],
    existing_keys: Set[Tuple[str, str]],
    today_str: str,
    force: bool = False,
    max_detail_pages: int = 12,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, bool, Optional[str], bool]:
    print(f"  [{name}] {config.get('url', '')[:80]}...")

    result = fetch_main_page(name, config)
    if not result:
        # If fetch_main_page returns None, it usually means network error or API error
        return [], [], fingerprints.get(name, ""), True, None, True

    soup = BeautifulSoup(result.html, "html.parser")
    fp_selector = config.get("fingerprint_selector", "body")
    new_fp = compute_fingerprint(soup, fp_selector)
    old_fp = fingerprints.get(name, "")

    if not force and new_fp and old_fp and new_fp == old_fp:
        tag = "🎭 PW" if result.engine == "playwright" else "⏭️"
        print(f"  [{name}] {tag} 指紋相同，跳過 (0.1s)")
        return [], [], new_fp, True, result.engine, False

    assets = extract_assets_from_listing(
        name=name,
        soup=soup,
        page_url=result.url,
        config=config,
        max_detail_pages=max_detail_pages,
    )

    if config.get('follow_listing_pages'):
        listing_pages = discover_listing_pages(soup, result.url, config)
        listing_limit = int(config.get('listing_max_pages') or len(listing_pages) or 0)
        seen_asset_urls = {a['pdf_url'] for a in assets}
        for listing_url in listing_pages[:listing_limit]:
            try:
                sub = fetch_page(listing_url, config, force_playwright=bool(config.get('listing_use_playwright')))
                sub_soup = BeautifulSoup(sub.html, 'html.parser')
                sub_assets = extract_assets_from_listing(
                    name=name,
                    soup=sub_soup,
                    page_url=sub.url,
                    config=config,
                    max_detail_pages=max_detail_pages,
                )
                for rec in sub_assets:
                    if rec['pdf_url'] in seen_asset_urls:
                        continue
                    seen_asset_urls.add(rec['pdf_url'])
                    assets.append(rec)
            except Exception:
                continue

    if not assets:
        print(f"  [{name}] ⚠️ 指紋變動但無可下載資產")
        return [], [], new_fp, False, result.engine, False

    region = config.get("region", "")
    new_records: List[Dict[str, Any]] = []
    updated_records: List[Dict[str, Any]] = []

    for item in assets:
        asset_url = item["pdf_url"]
        key = (name, asset_url)
        payload = {
            "source_site": name,
            "region": region,
            "pdf_url": asset_url,
            "title": item["title"],
            "captured_date": today_str,
        }
        if key in existing_keys:
            # ⚠️ 保留舊 captured_date：不要覆寫已存在項目的入庫日期
            payload.pop("captured_date", None)
            updated_records.append(payload)
        else:
            new_records.append(payload)
            existing_keys.add(key)

    tag = "🎭" if result.engine == "playwright" else ""
    print(f"  [{name}] {tag} 🆕{len(new_records)} 🔄{len(updated_records)} 📎{len(assets)}")
    return new_records, updated_records, new_fp, False, result.engine, False


# ─── CLI ──────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scout Notice Library v5.6.17 crawler")
    parser.add_argument("--dry-run", action="store_true", help="只預覽，不寫入 cache / fingerprints")
    parser.add_argument("--dry", action="store_true", help="同 --dry-run")
    parser.add_argument("--source", action="append", help="只跑指定來源，可重複使用")
    parser.add_argument("--force", action="store_true", help="忽略指紋快取，強制重跑")
    parser.add_argument("--max-detail-pages", type=int, default=12, help="每個來源最多深挖多少個內頁")
    return parser.parse_args()


# ─── 主程式 ───────────────────────────────────────────────
def main(
    dry_run: bool = False,
    only_sources: Optional[List[str]] = None,
    force: bool = False,
    max_detail_pages: int = 12,
):
    print("═" * 60)
    print("🦅 全港童軍通告自動化圖書館 v5.6.17")
    print("   可下載資產抓取 + 來源隔離 + 多來源分組 cache")
    pw_status = "✅ 已安裝" if _playwright_available else "⚠️ 未安裝 (動態網站將跳過)"
    print(f"   Playwright: {pw_status}")
    print(f"   啟動: {hkt_now_str()}")
    print("═" * 60)

    if not SOURCES_PATH.exists():
        print(f"❌ 找不到 {SOURCES_PATH}")
        sys.exit(1)

    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        root = json.load(f)
    all_sources = root.get("sources", {})
    sources = dict(all_sources)

    if only_sources:
        missing = [s for s in only_sources if s not in sources]
        if missing:
            print(f"❌ 找不到來源: {', '.join(missing)}")
            sys.exit(1)
        sources = {k: sources[k] for k in only_sources}

    pw_count = sum(1 for s in sources.values() if s.get("use_playwright"))
    print(f"📋 {len(sources)} 個來源 ({pw_count} 需 Playwright, {len(sources)-pw_count} 靜態)\n")

    today_str = hkt_today_str()
    now_str = hkt_now_str()

    fingerprints = load_fingerprints()
    local_cache = load_local_cache()
    local_records = iter_records_from_cache(local_cache)

    existing_keys: Set[Tuple[str, str]] = set()
    local_record_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for record in local_records:
        key = (record.get("source_site", ""), record.get("pdf_url", ""))
        if not all(key):
            continue
        existing_keys.add(key)
        local_record_map[key] = record

    if USE_SUPABASE:
        for record in supabase_fetch_all():
            key = (record.get("source_site", ""), record.get("pdf_url", ""))
            if all(key):
                existing_keys.add(key)

    all_new: List[Dict[str, Any]] = []
    all_updated: List[Dict[str, Any]] = []
    skipped = 0
    processed = 0
    pw_used = 0
    errors = 0
    error_sources: List[str] = []
    skipped_sources: List[str] = []

    source_items = list(sources.items())
    for i, (name, source_config) in enumerate(source_items, 1):
        print(f"[{i}/{len(source_items)}] {name}")
        # 標記為 expected_empty 的來源：直接跳過，不計錯誤，節省每日手動跑時間
        if source_config.get("expected_empty"):
            print(f"  [{name}] ⏭️ 標記為 expected_empty，直接跳過")
            skipped += 1
            skipped_sources.append(f"{name} (expected_empty)")
            fingerprints[name] = fingerprints.get(name, "")  # v5.6.15: 空白 hash，不寫字串
            continue
        try:
            new_recs, updated, fp, skip, engine, has_err = process_source(
                name=name,
                config=source_config,
                fingerprints=fingerprints,
                existing_keys=existing_keys,
                today_str=today_str,
                force=force,
                max_detail_pages=max_detail_pages,
            )
            fingerprints[name] = fp
            if skip:
                skipped += 1
                skipped_sources.append(name)
                processed += 1  # v5.6.15: skip means fingerprint match but page was fetched
            elif engine == "playwright":
                pw_used += 1  # v5.6.15: skip 時不計入
                processed += 1
            else:
                processed += 1
            if has_err:
                errors += 1
                error_sources.append(name)
            all_new.extend(new_recs)
            all_updated.extend(updated)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  [{name}] 🚨 處理過程中發生未預期錯誤跳過: {e}")
            skipped += 1
            skipped_sources.append(f"{name} (exception: {e})")
            error_sources.append(f"{name} (exception: {e})")

        if i < len(source_items):
            import random as _random
            time.sleep(_random.uniform(1.5, 4.0))  # v5.6.15: 拉長防封

    if not dry_run:
        if USE_SUPABASE:
            supabase_upsert(all_new)
            supabase_update_records(all_updated)
        else:
            for record in all_new:
                key = (record["source_site"], record["pdf_url"])
                local_record_map[key] = record
            for rec in all_updated:
                key = (rec.get("source_site", ""), rec.get("pdf_url", ""))
                if key in local_record_map:
                    # ⚠️ 保留舊 captured_date：只更新標題/分區，不覆寫入庫日期
                    local_record_map[key]["title"] = rec.get("title", local_record_map[key].get("title", ""))
                    local_record_map[key]["region"] = rec.get("region", local_record_map[key].get("region", ""))
            merged_records = list(local_record_map.values())
            grouped_cache = build_grouped_cache(merged_records, all_sources, now_str)
            grouped_cache.setdefault("_meta", {})["has_errors"] = (errors > 0)
            grouped_cache.setdefault("_meta", {})["expected_empty_sources"] = [
                name for name, cfg in sources.items() if cfg.get("expected_empty")
            ]
            grouped_cache.setdefault("_meta", {})["last_run"] = {
                "updated_at": now_str,
                "new": len(all_new),
                "updated": len(all_updated),
                "skipped": skipped,
                "processed": processed,
                "playwright_used": pw_used,
                "error_sources": error_sources,
                "skipped_sources": skipped_sources,
            }
            save_local_cache(grouped_cache)

        save_fingerprints(fingerprints)

    close_browser()

    print(f"\n{'═'*60}")
    print("📊 執行報告 v5.6.17")
    print(f"   🆕 新通告:     {len(all_new)}")
    print(f"   🔄 更新時間戳: {len(all_updated)}")
    print(f"   ⏭️  指紋相同:   {skipped}")
    print(f"   🔍 指紋變動:   {processed}")
    print(f"   🎭 Playwright: {pw_used} 次")
    print(f"   💾 模式:       {'Supabase' if USE_SUPABASE else '本地 JSON'}")
    print(f"   🧪 Dry run:    {'是' if dry_run else '否'}")
    print(f"   🕐 {now_str}")
    print("═" * 60)

    if all_new:
        print("\n🔍 新資產抽樣:")
        for rec in all_new[:5]:
            print(f"   [{rec['source_site']}] {rec['title'][:70]}")

    return {
        "new": len(all_new),
        "updated": len(all_updated),
        "skipped": skipped,
        "processed": processed,
        "pw_used": pw_used,
    }


if __name__ == "__main__":
    args = parse_args()
    main(
        dry_run=args.dry_run or args.dry,
        only_sources=args.source,
        force=args.force,
        max_detail_pages=args.max_detail_pages,
    )
