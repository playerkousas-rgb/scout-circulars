#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urljoin, urlparse, urlunparse, urlencode

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
SOURCES_PATH = BASE_DIR / "sources.json"
CACHE_PATH = BASE_DIR / "cache.json"
TIMEZONE = ZoneInfo("Asia/Hong_Kong")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
BAD_TITLE_FRAGMENTS = {"é", "ś", "ă", "æ", "°", "â", "ã"}
NAV_TEXT_PATTERNS = [
    "首頁",
    "主頁",
    "home",
    "更多",
    "read more",
    "詳情",
    "詳閱",
    "查看",
    "上一頁",
    "下一頁",
    "prev",
    "next",
    "facebook",
    "instagram",
    "youtube",
    "whatsapp",
    "分享",
    "share",
    "聯絡",
    "contact",
    "登入",
    "login",
    "register",
    "訂閱",
    "搜尋",
    "search",
    "menu",
    "download",
    "下載附件",
]
ARTICLE_FRIENDLY_TYPES = {
    "wordpress",
    "wordpress_list",
    "wordpress_page",
    "wordpress_post",
    "wordpress_archive",
    "wordpress_category",
    "wordpress_dynamic",
    "wordpress_elementor",
    "joomla_category",
    "joomla_archive",
    "home_news",
    "modern_cms",
    "structured_list",
    "legacy_html",
    "google_sites",
}


@dataclass
class FetchResult:
    url: str
    html: str
    engine: str
    status_code: int = 200


class ScoutCrawler:
    def __init__(self, verbose: bool = False, max_detail_pages: int = 12):
        self.verbose = verbose
        self.max_detail_pages = max_detail_pages
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def log(self, *parts: Any) -> None:
        if self.verbose:
            print(*parts)

    def today(self) -> str:
        return datetime.now(TIMEZONE).strftime("%Y-%m-%d")

    def now_ts(self) -> str:
        return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

    def load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def save_json(self, path: Path, data: Any) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def normalize_ws(self, value: str) -> str:
        value = html_lib.unescape(value or "")
        value = unicodedata.normalize("NFKC", value)
        value = value.replace("\u00a0", " ")
        value = re.sub(r"[\u200b-\u200f\ufeff]", "", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def clean_title(self, raw_title: str, conf: Dict[str, Any]) -> Optional[str]:
        title = self.normalize_ws(raw_title)
        if not title:
            return None

        regex = conf.get("title_filter_regex")
        if regex:
            try:
                title = re.sub(regex, "", title).strip()
            except re.error:
                pass

        exclude_patterns = conf.get("exclude_patterns") or []
        for pattern in exclude_patterns:
            if pattern and pattern.lower() in title.lower():
                return None

        for bad in BAD_TITLE_FRAGMENTS:
            if bad in title:
                return None

        min_len = int(conf.get("min_title_length") or 4)
        if len(title) < min_len:
            return None

        return title

    def fallback_title_from_url(self, url: str, conf: Dict[str, Any]) -> Optional[str]:
        path = unquote(urlparse(url).path)
        name = path.rsplit("/", 1)[-1]
        name = re.sub(r"\.pdf$", "", name, flags=re.I)
        name = name.replace("_", " ").replace("-", " ")
        return self.clean_title(name, conf)

    def looks_like_notice_url(self, url: str) -> bool:
        lowered = url.lower()
        path = unquote(urlparse(url).path).lower()
        host = urlparse(url).netloc.lower()
        if re.search(r"\.pdf(?:$|[?#])", lowered):
            return True
        if path.endswith(".pdf"):
            return True
        if "drive.google.com" in host or "docs.google.com" in host:
            return True
        return False

    def sanitize_url(self, href: str, base_url: str, patterns: Optional[List[str]] = None) -> Optional[str]:
        href = (href or "").strip()
        if not href:
            return None
        if href.startswith(("javascript:", "mailto:", "tel:")):
            return None
        if href.startswith("#"):
            return None

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        parsed = parsed._replace(fragment="")

        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        cleaned_items = list(query_items)

        for pattern in patterns or []:
            if pattern.startswith("?"):
                key = pattern[1:].split("=", 1)[0]
                if not key:
                    continue
                if key == "wpdmdl" and not self.looks_like_notice_url(absolute):
                    continue
                cleaned_items = [(k, v) for k, v in cleaned_items if k != key]
            elif pattern.startswith("#"):
                parsed = parsed._replace(fragment="")

        new_query = urlencode(cleaned_items, doseq=True)
        cleaned = urlunparse(parsed._replace(query=new_query))
        cleaned = cleaned.rstrip("?&")
        return cleaned

    def fetch_requests(self, url: str, conf: Dict[str, Any], timeout: int = 20) -> FetchResult:
        resp = self.session.get(url, timeout=timeout)
        forced_encoding = conf.get("encoding")
        resp.encoding = forced_encoding or resp.apparent_encoding or "utf-8"
        return FetchResult(url=resp.url, html=resp.text, engine="requests", status_code=resp.status_code)

    def fetch_playwright(self, url: str, conf: Dict[str, Any]) -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Playwright unavailable: {e}") from e

        wait_strategy = conf.get("wait_strategy") or "networkidle"
        wait_timeout = int(conf.get("wait_timeout") or 15000)
        wait_selector = conf.get("wait_selector")

        with sync_playwright() as p:  # pragma: no cover
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout)
            if wait_strategy == "selector" and wait_selector:
                page.wait_for_selector(wait_selector, timeout=wait_timeout)
            else:
                page.wait_for_load_state("networkidle", timeout=wait_timeout)
            content = page.content()
            final_url = page.url
            browser.close()
            return FetchResult(url=final_url, html=content, engine="playwright", status_code=200)

    def html_has_useful_content(self, html: str, conf: Dict[str, Any]) -> bool:
        soup = BeautifulSoup(html, "lxml")
        fp_sel = conf.get("fingerprint_selector")
        link_sel = conf.get("link_selector")
        if fp_sel:
            try:
                if soup.select(fp_sel):
                    return True
            except Exception:
                pass
        if link_sel:
            try:
                if soup.select(link_sel):
                    return True
            except Exception:
                pass
        return bool(soup.select("a[href$='.pdf'], a[href*='drive.google.com']"))

    def fetch_page(self, url: str, conf: Dict[str, Any], force_playwright: bool = False) -> FetchResult:
        use_playwright = bool(conf.get("use_playwright")) or force_playwright
        first_error: Optional[Exception] = None

        try:
            result = self.fetch_requests(url, conf)
            if not use_playwright:
                return result
            if self.html_has_useful_content(result.html, conf):
                return result
            self.log(f"[fallback] requests result looks empty, switching to Playwright: {url}")
            return self.fetch_playwright(url, conf)
        except Exception as e:
            first_error = e
            if not use_playwright:
                raise

        try:
            return self.fetch_playwright(url, conf)
        except Exception as pe:
            if first_error:
                raise RuntimeError(f"requests failed: {first_error}; playwright failed: {pe}") from pe
            raise

    def fingerprint_payload(self, soup: BeautifulSoup, conf: Dict[str, Any]) -> str:
        selector = conf.get("fingerprint_selector") or "body"
        try:
            nodes = soup.select(selector)
        except Exception:
            nodes = []

        if not nodes:
            nodes = [soup.body or soup]

        chunks: List[str] = []
        for node in nodes:
            anchors = node.select("a[href]")
            if anchors:
                for a in anchors:
                    href = self.sanitize_url(a.get("href", ""), "", conf.get("url_sanitize")) or (a.get("href") or "")
                    text = self.normalize_ws(a.get_text(" ", strip=True))
                    if href or text:
                        chunks.append(f"{href}|{text}")
            else:
                chunks.append(self.normalize_ws(node.get_text(" ", strip=True)))

        payload = "\n".join(c for c in chunks if c).strip()
        return payload

    def fingerprint_hash(self, html: str, conf: Dict[str, Any]) -> str:
        soup = BeautifulSoup(html, "lxml")
        payload = self.fingerprint_payload(soup, conf)
        return hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()

    def source_domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def is_article_candidate(self, url: str, base_url: str, text: str) -> bool:
        if not url or self.looks_like_notice_url(url):
            return False
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if self.source_domain(url) != self.source_domain(base_url):
            return False

        lowered_url = url.lower()
        for bad_host_piece in ["facebook.com", "instagram.com", "youtube.com", "wa.me", "twitter.com", "x.com"]:
            if bad_host_piece in lowered_url:
                return False

        path = parsed.path.lower()
        if re.search(r"\.(jpg|jpeg|png|gif|svg|webp|zip|rar|doc|docx|xls|xlsx|ppt|pptx)$", path):
            return False

        lowered_text = (text or "").strip().lower()
        if any(pattern in lowered_text for pattern in NAV_TEXT_PATTERNS):
            return False

        if len(lowered_text) and len(lowered_text) < 2:
            return False

        return True

    def anchors_from_selector(self, soup: BeautifulSoup, selector: Optional[str]) -> List[Any]:
        if not selector:
            return []
        try:
            nodes = soup.select(selector)
        except Exception:
            return []

        anchors: List[Any] = []
        for node in nodes:
            if getattr(node, "name", None) == "a":
                anchors.append(node)
            else:
                found = node.find("a", href=True)
                if found:
                    anchors.append(found)
        return anchors

    def extract_from_main_page(
        self,
        source_name: str,
        page_url: str,
        html: str,
        conf: Dict[str, Any],
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        soup = BeautifulSoup(html, "lxml")
        direct_notices: List[Dict[str, str]] = []
        article_candidates: List[str] = []
        seen_notice_urls = set()
        seen_article_urls = set()

        anchors = self.anchors_from_selector(soup, conf.get("link_selector"))
        anchors += self.anchors_from_selector(soup, conf.get("title_selector"))
        if not anchors:
            anchors = list(soup.select("a[href]"))

        for a in anchors:
            href = a.get("href")
            sanitized = self.sanitize_url(href, page_url, conf.get("url_sanitize")) if href else None
            if not sanitized:
                continue

            raw_text = a.get_text(" ", strip=True)
            title = self.clean_title(raw_text, conf)

            if self.looks_like_notice_url(sanitized):
                if not title:
                    title = self.fallback_title_from_url(sanitized, conf)
                if not title:
                    continue
                if sanitized in seen_notice_urls:
                    continue
                seen_notice_urls.add(sanitized)
                direct_notices.append(
                    {
                        "title": title,
                        "url": sanitized,
                        "source_site": source_name,
                    }
                )
            elif self.is_article_candidate(sanitized, page_url, raw_text):
                if sanitized in seen_article_urls:
                    continue
                seen_article_urls.add(sanitized)
                article_candidates.append(sanitized)

        return direct_notices, article_candidates

    def extract_from_detail_page(
        self,
        source_name: str,
        detail_url: str,
        html: str,
        conf: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")

        pdf_candidates = []
        for selector in [
            "a[href$='.pdf']",
            "a[href*='.pdf?']",
            "a[href*='drive.google.com']",
            "a[href*='/file/d/']",
            "iframe[src$='.pdf']",
            "iframe[src*='.pdf?']",
            "embed[src$='.pdf']",
            "object[data$='.pdf']",
        ]:
            try:
                pdf_candidates.extend(soup.select(selector))
            except Exception:
                pass

        pdf_url = None
        for node in pdf_candidates:
            href = node.get("href") or node.get("src") or node.get("data")
            cleaned = self.sanitize_url(href, detail_url, conf.get("url_sanitize")) if href else None
            if cleaned and self.looks_like_notice_url(cleaned):
                pdf_url = cleaned
                break

        if not pdf_url:
            return None

        title = None
        h1 = soup.find("h1")
        if h1:
            title = self.clean_title(h1.get_text(" ", strip=True), conf)

        if not title:
            og = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "og:title"})
            if og and og.get("content"):
                title = self.clean_title(og.get("content", ""), conf)

        if not title and soup.title:
            title = self.clean_title(soup.title.get_text(" ", strip=True), conf)

        if not title:
            title = self.fallback_title_from_url(pdf_url, conf)

        if not title:
            return None

        return {
            "title": title,
            "url": pdf_url,
            "source_site": source_name,
        }

    def should_follow_detail_pages(self, conf: Dict[str, Any], direct_count: int, article_count: int) -> bool:
        if article_count == 0:
            return False
        if "follow_detail_pages" in conf:
            return bool(conf.get("follow_detail_pages"))
        if direct_count == 0:
            return True
        return (conf.get("type") or "") in ARTICLE_FRIENDLY_TYPES

    def collect_notices(self, source_name: str, source_url: str, html: str, conf: Dict[str, Any]) -> List[Dict[str, str]]:
        direct_notices, article_candidates = self.extract_from_main_page(source_name, source_url, html, conf)
        notices = list(direct_notices)
        seen = {item["url"] for item in direct_notices}

        if not self.should_follow_detail_pages(conf, len(direct_notices), len(article_candidates)):
            return notices

        self.log(f"[detail] {source_name}: scanning up to {self.max_detail_pages} detail pages")
        for detail_url in article_candidates[: self.max_detail_pages]:
            try:
                detail_result = self.fetch_page(detail_url, conf)
                notice = self.extract_from_detail_page(source_name, detail_result.url, detail_result.html, conf)
                if not notice:
                    continue
                if notice["url"] in seen:
                    continue
                seen.add(notice["url"])
                notices.append(notice)
            except Exception as e:
                self.log(f"[detail-skip] {source_name}: {detail_url} -> {e}")
                continue

        return notices

    def build_regions(self, sources: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
        regions: Dict[str, List[str]] = {}
        for name, conf in sources.items():
            region = conf.get("region") or "未分類"
            regions.setdefault(region, []).append(name)
        return regions

    def empty_cache(self, sources: Dict[str, Dict[str, Any]], meta_root: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meta_root = meta_root or {}
        regions = self.build_regions(sources)
        source_order = list(sources.keys())
        return {
            "last_updated": None,
            "data": {name: [] for name in source_order},
            "_meta": {
                "project": meta_root.get("project", "全港童軍通告自動化圖書館"),
                "version": meta_root.get("version", "5.0.0"),
                "design": meta_root.get("design", "DOM指紋對比 + PDF絕對網址去重 + 系統日期 + 來源隔離"),
                "total_sources": meta_root.get("total_sources", len(source_order)),
                "regions": regions,
                "source_order": source_order,
                "fingerprints": {},
            },
        }

    def ensure_cache_shape(self, cache: Dict[str, Any], sources: Dict[str, Dict[str, Any]], meta_root: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not cache or not isinstance(cache, dict):
            return self.empty_cache(sources, meta_root)

        cache.setdefault("last_updated", None)
        cache.setdefault("data", {})
        cache.setdefault("_meta", {})
        cache["_meta"].setdefault("project", (meta_root or {}).get("project", "全港童軍通告自動化圖書館"))
        cache["_meta"].setdefault("version", (meta_root or {}).get("version", "5.0.0"))
        cache["_meta"].setdefault("design", (meta_root or {}).get("design", "DOM指紋對比 + PDF絕對網址去重 + 系統日期 + 來源隔離"))
        cache["_meta"]["regions"] = self.build_regions(sources)
        cache["_meta"]["source_order"] = list(sources.keys())
        cache["_meta"]["total_sources"] = (meta_root or {}).get("total_sources", len(sources))
        cache["_meta"].setdefault("fingerprints", {})

        for name in sources.keys():
            cache["data"].setdefault(name, [])
            if not isinstance(cache["data"][name], list):
                cache["data"][name] = []

        return cache

    def update_source_records(
        self,
        cache: Dict[str, Any],
        source_name: str,
        notices: List[Dict[str, str]],
        captured_date: str,
    ) -> Tuple[int, int]:
        bucket = cache["data"].setdefault(source_name, [])
        existing_map = {item.get("url"): item for item in bucket if item.get("url")}
        created = 0
        updated = 0

        for notice in notices:
            key = notice["url"]
            if key in existing_map:
                record = existing_map[key]
                record["title"] = notice["title"]
                record["date"] = captured_date
                record["captured_date"] = captured_date
                record["source_site"] = source_name
                updated += 1
            else:
                record = {
                    "title": notice["title"],
                    "url": notice["url"],
                    "date": captured_date,
                    "captured_date": captured_date,
                    "source_site": source_name,
                }
                bucket.append(record)
                existing_map[key] = record
                created += 1

        def sort_key(item: Dict[str, Any]) -> Tuple[str, str]:
            return (item.get("date") or "", item.get("title") or "")

        bucket.sort(key=sort_key, reverse=True)
        return created, updated

    def run(self, only_sources: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
        source_root = self.load_json(SOURCES_PATH, {})
        if not source_root or "sources" not in source_root:
            raise RuntimeError("sources.json 不存在或格式錯誤")

        meta_root = source_root.get("_meta") or {}
        sources: Dict[str, Dict[str, Any]] = source_root["sources"]
        if only_sources:
            missing = [name for name in only_sources if name not in sources]
            if missing:
                raise RuntimeError(f"sources.json 找不到來源: {', '.join(missing)}")
            sources = {name: sources[name] for name in only_sources}

        cache = self.load_json(CACHE_PATH, {})
        cache = self.ensure_cache_shape(cache, source_root["sources"], meta_root)

        total_created = 0
        total_updated = 0
        total_skipped = 0
        now_ts = self.now_ts()
        today = self.today()

        for source_name, conf in sources.items():
            source_url = conf["url"]
            self.log(f"\n=== {source_name} ===")
            try:
                result = self.fetch_page(source_url, conf)
                fp_hash = self.fingerprint_hash(result.html, conf)
                prev_fp = (((cache.get("_meta") or {}).get("fingerprints") or {}).get(source_name) or {}).get("hash")

                if prev_fp == fp_hash and not force:
                    total_skipped += 1
                    self.log(f"[skip] fingerprint unchanged ({result.engine})")
                    continue

                notices = self.collect_notices(source_name, result.url, result.html, conf)
                if not notices:
                    self.log(f"[warn] no notices extracted ({result.engine})")

                created, updated = self.update_source_records(cache, source_name, notices, today)
                total_created += created
                total_updated += updated

                cache["_meta"]["fingerprints"][source_name] = {
                    "hash": fp_hash,
                    "updated_at": now_ts,
                    "engine": result.engine,
                    "source_url": result.url,
                    "item_count": len(notices),
                }
                self.log(f"[ok] {source_name}: created={created}, refreshed={updated}, extracted={len(notices)}, engine={result.engine}")
            except Exception as e:
                self.log(f"[error] {source_name}: {e}")
                cache["_meta"].setdefault("errors", {})[source_name] = {
                    "message": str(e),
                    "updated_at": now_ts,
                }
                continue

        cache["last_updated"] = now_ts
        cache["_meta"]["last_run"] = {
            "updated_at": now_ts,
            "created": total_created,
            "refreshed": total_updated,
            "skipped": total_skipped,
            "processed_sources": len(sources),
        }
        self.save_json(CACHE_PATH, cache)
        return cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scout Notice Library crawler")
    parser.add_argument("--source", action="append", help="只跑某一個來源，可重複使用")
    parser.add_argument("--force", action="store_true", help="忽略 fingerprint，強制重新解析")
    parser.add_argument("--verbose", action="store_true", help="輸出詳細日誌")
    parser.add_argument("--max-detail-pages", type=int, default=12, help="每個來源最多進入多少個文章內頁")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    crawler = ScoutCrawler(verbose=args.verbose, max_detail_pages=args.max_detail_pages)
    try:
        crawler.run(only_sources=args.source, force=args.force)
        return 0
    except Exception as e:
        print(f"Fatal: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
