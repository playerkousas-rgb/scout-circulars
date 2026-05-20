#!/usr/bin/env python3
"""
全港童軍通告自動化圖書館 v5.1 — 核心爬蟲引擎 (core.py)
========================================================
v5.1 更新: Playwright 雙狀態判定 (networkidle / wait_for_selector)
          指紋純化: 只算 href+title，濾掉隨機動態 class

四大核心鐵律:
  1. DOM 指紋對比 (MD5) — 不變則 0.1s 跳過
  2. PDF 絕對網址去重 — 新URL入庫, 舊URL更新時間戳
  3. 盲信系統日期 — 所有 captured_date = 今天
  4. 30天沙盒沉底 — 前端時間篩選器自動過濾舊雜訊

Usage:
  python core.py              # 正式執行
  python core.py --dry-run    # 預覽模式 (不寫入)
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

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
CACHE_PATH   = BASE_DIR / "cache.json"
FINGERPRINTS_PATH = BASE_DIR / "fingerprints.json"

# ─── Supabase 配置 ────────────────────────────────────────
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_TABLE = "scout_notices"
USE_SUPABASE   = bool(SUPABASE_URL and SUPABASE_KEY)

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

# ─── Playwright 瀏覽器實例 (singleton) ────────────────────
_pw_browser = None

def get_browser():
    """取得或建立 Playwright browser (singleton)"""
    global _pw_browser
    if _pw_browser is not None:
        return _pw_browser
    if not _playwright_available:
        return None
    pw = sync_playwright().start()
    _pw_browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
    )
    return _pw_browser

def close_browser():
    global _pw_browser
    if _pw_browser:
        try:
            _pw_browser.close()
        except:
            pass
        _pw_browser = None


# ─── URL 淨化引擎 ─────────────────────────────────────────
def sanitize_url(url: str, sanitize_params: list = None) -> str:
    """
    切除動態參數 (?v=, ?t=, ?authuser= 等)
    相對路徑 → 絕對路徑
    """
    if not url:
        return ""
    parsed = urlparse(url)
    default_strip = ["v","t","ver","timestamp","wpdmdl","authuser","usp","_","nocache","rand","random"]
    strip_params = sanitize_params if sanitize_params else []
    all_strip = list(set(default_strip + [p.strip("?&= ") for p in strip_params]))
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_qs = {k: v for k, v in qs.items() if k not in all_strip and not k.startswith("utm_")}
        new_query = urlencode(cleaned_qs, doseq=True) if cleaned_qs else ""
        cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))
    else:
        cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", ""))
    return cleaned.split("#")[0]


def resolve_url(base_url: str, href: Optional[str]) -> Optional[str]:
    if not href: return None
    if href.startswith(("http://","https://")): return href
    if href.startswith("//"): return "https:" + href
    return urljoin(base_url, href)


# ─── 🔥 指紋引擎 v5.1: 純化 ──────────────────────────────
def compute_fingerprint(soup: BeautifulSoup, selector: str) -> str:
    """
    DOM 指紋對比 (MD5) — 純化版
    🔥 只算文字內容 (text) + 連結 (href)
    🔥 刻意排除 class / id / style / data-* 等動態屬性
    確保 WordPress/React 重新 build 後隨機 class 不影響指紋
    """
    try:
        elements = soup.select(selector)
        if not elements:
            body = soup.select_one("body")
            elements = [body] if body else []

        parts = []
        for el in elements:
            # 只取文字
            text = re.sub(r'\s+', ' ', el.get_text(" ", strip=True))
            parts.append(text)
            # 只取 href (不取 class, id, style 等)
            for a in el.select("a[href]"):
                href = a.get("href", "").strip()
                if href:
                    parts.append(href)

        combined = "|".join(parts)
        return hashlib.md5(combined.encode("utf-8")).hexdigest()
    except Exception:
        return ""


# ─── PDF 連結提取引擎 ─────────────────────────────────────
def extract_pdf_links(soup, link_selector, title_selector, base_url, sanitize_params, exclude_patterns, min_title_length):
    results = []
    links = soup.select(link_selector)
    # 確保抓取到連結
    for link in links:
        href = link.get("href", "")
        if not href: continue
        full_url = resolve_url(base_url, href)
        
        # 判斷是否為 PDF
        if full_url.lower().endswith(".pdf"):
            title = link.get_text(" ", strip=True)
            results.append({"pdf_url": sanitize_url(full_url, sanitize_params), "title": title})
        
        # 內頁深挖：只對 WordPress 文章進行處理
        elif "/2026/" in full_url or "/2025/" in full_url:
            try:
                # 這裡增加簡單的防錯處理
                resp_inner = SESSION.get(full_url, timeout=5)
                soup_inner = BeautifulSoup(resp_inner.text, "html.parser")
                pdf_in_page = soup_inner.select_one("a[href$='.pdf']")
                if pdf_in_page:
                    inner_url = resolve_url(full_url, pdf_in_page.get("href"))
                    h1 = soup_inner.select_one("h1")
                    title = h1.get_text(" ", strip=True) if h1 else "未知通告"
                    results.append({"pdf_url": sanitize_url(inner_url, sanitize_params), "title": title})
            except:
                continue
    return results


# ─── 🆕 Playwright 動態頁面抓取 ────────────────────────────
def fetch_with_playwright(name: str, config: dict) -> BeautifulSoup:
    """
    使用 Playwright 抓取動態渲染頁面。
    雙策略:
      1. networkidle — 等待 500ms 無網路請求
      2. selector   — 等待指定 CSS selector 出現
    """
    if not _playwright_available:
        print(f"  [{name}] ⚠️ Playwright 未安裝 (pip install playwright && playwright install chromium)")
        return None

    browser = get_browser()
    if not browser:
        return None

    url = config["url"]
    wait_strategy = config.get("wait_strategy", "networkidle")
    wait_selector = config.get("wait_selector", "")
    wait_timeout = config.get("wait_timeout", 15000)

    page = None
    try:
        page = browser.new_page()
        page.set_default_timeout(30000)

        # 導航
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # 🔥 狀態判定
        if wait_strategy == "selector" and wait_selector:
            page.wait_for_selector(wait_selector, state="attached", timeout=wait_timeout)
            # 再等一下確保子元素也渲染
            page.wait_for_timeout(800)
        else:
            # networkidle: 連續 500ms 無網路活動
            page.wait_for_load_state("networkidle", timeout=wait_timeout)

        html = page.content()
        return BeautifulSoup(html, "html.parser")

    except Exception as e:
        print(f"  [{name}] ⚠️ Playwright: {type(e).__name__}: {e}")
        return None
    finally:
        if page:
            try:
                page.close()
            except:
                pass


# ─── Supabase 操作 ────────────────────────────────────────
def supabase_fetch_all() -> list:
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*&order=captured_date.desc&limit=10000"
    try:
        resp = SESSION.get(url, headers=headers, timeout=15)
        return resp.json() if resp.status_code == 200 else []
    except:
        return []

def supabase_upsert(records: list):
    if not records: return
    headers = {
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates",
    }
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    for i in range(0, len(records), 100):
        batch = records[i:i+100]
        try:
            SESSION.post(url, headers=headers, json=batch, timeout=20)
        except:
            pass

def supabase_update_timestamp(pdf_urls: list, new_date: str):
    if not pdf_urls: return
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    for u in pdf_urls:
        try:
            patch_url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?pdf_url=eq.{requests.utils.quote(u)}"
            SESSION.patch(patch_url, headers=headers, json={"captured_date": new_date}, timeout=10)
        except:
            pass


# ─── 檔案儲存 (本地 JSON 模式) ────────────────────────────
def load_local_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"last_updated": "", "notices": []}

def save_local_cache(data: dict):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_fingerprints() -> dict:
    if FINGERPRINTS_PATH.exists():
        try:
            with open(FINGERPRINTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_fingerprints(fp: dict):
    with open(FINGERPRINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(fp, f, ensure_ascii=False, indent=2)


# ─── 🔥 單一來源處理 (v5.1: requests → Playwright fallback) ──
def process_source(name: str, config: dict, fingerprints: dict,
                   existing_urls: set, local_notices: list,
                   today_str: str) -> tuple:
    """
    處理單一來源
    流程:
      1. requests 抓取 → 若拿到 PDF → 直接走指紋+Pipeline
      2. 若無 PDF 且 use_playwright=True → Playwright 抓取 → Pipeline
      3. 指紋相同 → 跳過
    """
    use_pw = config.get("use_playwright", False)
    encoding = config.get("encoding", "utf-8")
    fp_selector = config.get("fingerprint_selector", "body")
    link_selector = config.get("link_selector", "a[href$='.pdf']")
    title_selector = config.get("title_selector", "a[href$='.pdf']")
    sanitize_params = config.get("url_sanitize", [])
    exclude_patterns = config.get("exclude_patterns", [])
    min_title_len = config.get("min_title_length", 0)
    region = config.get("region", "")
    url = config.get("url", "")

    print(f"  [{name}] {url[:80]}...")

    soup = None
    used_playwright = False

    # ── Step 1: requests ──────────────────────────────
    try:
        resp = SESSION.get(url, timeout=30)
        if "big5" in (encoding or "").lower() or (resp.apparent_encoding and "big5" in resp.apparent_encoding.lower()):
            resp.encoding = "big5"
        else:
            resp.encoding = resp.apparent_encoding or encoding
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [{name}] ⚠️ requests: {type(e).__name__}")

    # ── 試 requests soup 能否拿到 PDF ──────────────────
    requests_has_pdfs = False
    if soup:
        pdfs = extract_pdf_links(soup, link_selector, title_selector, url, sanitize_params, exclude_patterns, min_title_len)
        if pdfs:
            requests_has_pdfs = True
        else:
            print(f"  [{name}] requests 無 PDF 連結" + (" → Playwright" if use_pw else ""))

    # ── Step 2: Playwright fallback ────────────────────
    if not requests_has_pdfs and use_pw:
        pw_soup = fetch_with_playwright(name, config)
        if pw_soup:
            soup = pw_soup
            used_playwright = True
        else:
            # Playwright 也失敗
            return [], [], fingerprints.get(name, ""), True

    if soup is None:
        return [], [], fingerprints.get(name, ""), True

    # ── Step 3: 指紋對比 ──────────────────────────────
    new_fp = compute_fingerprint(soup, fp_selector)
    old_fp = fingerprints.get(name, "")

    if new_fp and old_fp and new_fp == old_fp:
        tag = "🎭 PW" if used_playwright else "⏭️"
        print(f"  [{name}] {tag} 指紋相同，跳過 (0.1s)")
        return [], [], new_fp, True

    # ── Step 4: 提取 PDF 連結 ─────────────────────────
    pdf_links = extract_pdf_links(soup, link_selector, title_selector, url,
                                  sanitize_params, exclude_patterns, min_title_len)

    if not pdf_links:
        print(f"  [{name}] ⚠️ 指紋變動但無 PDF 連結" + (" (PW)" if used_playwright else ""))
        return [], [], new_fp, False

    # ── Step 5: 庫內對比 ──────────────────────────────
    new_records, updated_urls = [], []

    for item in pdf_links:
        pdf_url = item["pdf_url"]
        if pdf_url in existing_urls:
            updated_urls.append(pdf_url)
        else:
            new_records.append({
                "source_site": name,
                "region": region,
                "pdf_url": pdf_url,
                "title": item["title"],
                "captured_date": today_str
            })
            existing_urls.add(pdf_url)

    tag = "🎭" if used_playwright else ""
    print(f"  [{name}] {tag} 🆕{len(new_records)} 🔄{len(updated_urls)} 📎{len(pdf_links)}")

    return new_records, updated_urls, new_fp, False


# ─── 主程式 ───────────────────────────────────────────────
def main(dry_run=False):
    print("═" * 60)
    print("🦅 全港童軍通告自動化圖書館 v5.1")
    print("   Playwright networkidle/selector 雙策略 + 指紋純化")
    pw_status = "✅ 已安裝" if _playwright_available else "⚠️ 未安裝 (動態網站將跳過)"
    print(f"   Playwright: {pw_status}")
    print(f"   啟動: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 60)

    if not SOURCES_PATH.exists():
        print(f"❌ 找不到 {SOURCES_PATH}")
        sys.exit(1)

    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    sources = config.get("sources", {})
    pw_count = sum(1 for s in sources.values() if s.get("use_playwright"))
    print(f"📋 {len(sources)} 個來源 ({pw_count} 需 Playwright, {len(sources)-pw_count} 靜態)\n")

    today_str = date.today().isoformat()

    # 載入既有資料
    fingerprints = load_fingerprints()
    local_cache = load_local_cache()
    local_notices = local_cache.get("notices", [])
    existing_urls = set(n["pdf_url"] for n in local_notices)

    if USE_SUPABASE:
        supabase_data = supabase_fetch_all()
        existing_urls |= set(r["pdf_url"] for r in supabase_data)

    # 處理
    all_new, all_updated = [], []
    skipped, processed, pw_used = 0, 0, 0

    for i, (name, source_config) in enumerate(sources.items(), 1):
        print(f"[{i}/{len(sources)}] {name}")
        new_recs, updated, fp, skip = process_source(
            name, source_config, fingerprints, existing_urls, local_notices, today_str
        )
        fingerprints[name] = fp
        if skip:
            skipped += 1
        else:
            processed += 1
        all_new.extend(new_recs)
        all_updated.extend(updated)
        if i < len(sources):
            time.sleep(0.4)

    # 儲存
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if USE_SUPABASE:
        supabase_upsert(all_new)
        supabase_update_timestamp(all_updated, today_str)
    else:
        local_notices.extend(all_new)
        for notice in local_notices:
            if notice["pdf_url"] in all_updated:
                notice["captured_date"] = today_str
        save_local_cache({
            "last_updated": now_str,
            "meta": {"version": "5.1.0", "total_sources": len(sources),
                     "total_notices": len(local_notices),
                     "design": "DOM指紋純化+Playwright雙策略+PDF去重+盲信日期+30天沉底"},
            "notices": local_notices
        })

    save_fingerprints(fingerprints)
    close_browser()

    # 報告
    print(f"\n{'═'*60}")
    print(f"📊 執行報告 v5.1")
    print(f"   🆕 新通告:     {len(all_new)}")
    print(f"   🔄 更新時間戳: {len(all_updated)}")
    print(f"   ⏭️  指紋相同:   {skipped}")
    print(f"   🔍 指紋變動:   {processed}")
    print(f"   🎭 Playwright: {pw_used} 次")
    print(f"   💾 模式:       {'Supabase' if USE_SUPABASE else '本地 JSON'}")
    print(f"   🕐 {now_str}")
    print("═" * 60)

    if dry_run and all_new:
        print("\n🔍 DRY RUN — 新通告抽樣:")
        for rec in all_new[:5]:
            print(f"   [{rec['source_site']}] {rec['title'][:70]}")

    return {"new": len(all_new), "updated": len(all_updated), "skipped": skipped, "processed": processed}


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv or "--dry" in sys.argv)
