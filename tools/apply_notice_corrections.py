#!/usr/bin/env python3
"""Apply reviewed notice corrections before publishing the public snapshot.

This is a small allowlist of user-confirmed rules, not a heuristic cleanup
pass. Run after scrape/enrich and before publishing data.

2026-11-04 擴充：除咗分類，仲可以
  * 還原被 PDF 假標題改壞嘅通告名（cache.json + enrich.json 同步）；
  * 補「歲數／支部或以上」推出嘅 audience／branch_tags；
  * 為永遠唔會被 enrich.py 處理嘅「網頁型通告」（例如將軍澳區
    /notice/?nid=209）補一條只含標題分類嘅 enrich entry，等前端唔使
    一律兜底做「公布」。
2026-11-07 再加：還原被區會信頭地址（「香港青衣長康邨康美樓 C301 室」）
寫壞嘅兩張青衣區「取錄通知」標題；cache 兩份副本＋enrich 同步。
2026-11-16 再加：元朗西區喺 WordPress 區塊將 `/circular/activity12/13/15-2026.pdf`
誤植做 `.pdf.pdf`（404），將 cache 兩份副本同 enrich 統一搬返去真單一 `.pdf`
網址（保留原本入庫日、清走舊 404 錯誤記錄，並為已過 7 日增量窗嘅舊檔補齊欄位）。
所有修正都係冪等（每日跑一次都唔會重複寫／重複算）。
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from enrich import ENRICH_VERSION  # noqa: E402
from subscription_tagging import extract_subscription_metadata  # noqa: E402

CACHE_PATH = ROOT / "cache.json"
ENRICH_PATH = ROOT / "enrich.json"
# 寫入資料嘅 audit 標記；舊 entry 可能仍帶住舊日期，唔影響規則本身。
REVIEW_LABEL = "apply_notice_corrections 2026-11-16"

# Apply to every mirrored copy sharing these exact titles.
CATEGORY_CORRECTIONS = {
    "童軍訓練班及活動專用特惠菜式",
    "新東毅行.越嶺同行",
    # 2026-11-04 用戶確認：呢張係聖誕聯誼活動，唔係行政公布。
    "冬日弦音 • 聖誕燒烤派對",
    # 2026-11-04 用戶確認：獎學金／傑出服務獎係獎項公布，唔係招募義工。
    "葛量洪青少年制服團隊傑出服務奬2026-2027",
    # 2026-11-05：一般大會操仍係活動，但明確列出步操／隊列／升旗賽果要係比賽。
    "2026年香港童軍大會操步操比賽、隊列比賽及升旗比賽成績公布",
    # 2026-11-05：集訓及建造班兩張通告都係訓練；標題規則更新後要重寫舊 enrich 標籤。
    "童軍田徑會第35期會員集訓(P116/2026)",
    "帆布獨木舟建造班",
    "第 22屆初級航空活動章訓練班暨第6屆童軍風箏章(興趣組)訓練班",
    # 2026-11-06 用戶確認：學生隊員制服資助計劃＝公布（同津貼計劃同組嘅
    # 行政資助計劃）；「資助計劃」亦已加入三份分類規則，重寫舊 enrich 標籤。
    "學生隊員制服資助計劃",
}

# 2026-11-04：標題被 `--apply-title-fixes` 寫壞嘅通告，還原做列表頁原名。
# key = PDF URL（同 enrich.json / cache.json 一致），value = 正確通告名。
TITLE_CORRECTIONS = {
    "https://scout.org.hk/uploads/tc/circulars/26576/CPA202607_Grantham_Chi_2026.pdf":
        "葛量洪青少年制服團隊傑出服務奬2026-2027",
    # 2026-11-07 用戶報告：青衣區兩張「取錄通知」被 PDF 信頭地址
    # 「香港青衣長康邨康美樓 C301 室」當成標題。列表頁原名先係權威；
    # enrich.py 3.10 已擋地址行，呢兩條負責清走舊 snapshot 入面已寫壞嘅紀錄
    # （兩份 cache 副本＋enrich 都要還原，否則改完下一次 run 又會蓋返）。
    "https://tyd.scout-ntr.org.hk/dist_cir/notice_train/d260701-1.pdf":
        "取錄通知",
    "https://tyd.scout-ntr.org.hk/dist_cir/notice_train/sc260901-1.pdf":
        "取錄通知",
}

# 2026-11-04 用戶規則：內文「2.1 11至26歲…的童軍、深資童軍或樂行童軍支部
# 成員」係申請資格，唔係通告名。由歲數對照表還原嘅適用支部（見
# subscription_tagging.branches_from_min_age），順手寫返做 labelled audience。
AUDIENCE_CORRECTIONS = {
    "https://scout.org.hk/uploads/tc/circulars/26576/CPA202607_Grantham_Chi_2026.pdf":
        "童軍、深資童軍、樂行童軍",
}

# 網頁型通告（URL 唔係 .pdf，enrich.py 永遠唔會落載）嘅標題分類。
# 分類／支部都交返畀權威規則 extract_subscription_metadata() 計，唔人手釘 ID。
UNENRICHED_NOTICE_URLS = {
    # 「11-2026 小童軍支部 - 「小草」賀新春—小童軍親子利是封設計比賽」＝比賽
    "https://hkscout-tko.org/notice/?nid=209": "competition",
}

# 2026-11-16：元朗西區 WordPress 文章將 `/circular/*.pdf` 連結誤寫做 `.pdf.pdf`（404），
# 真檔位於同路徑單一 `.pdf`。除下列已發生嘅三張外，`_canonical_notice_url()` 亦會自動
# 收斂 `ylw-scout.org.hk/circular/*.pdf.pdf`，同 `core.normalize_known_double_pdf_url` 一致。
URL_CORRECTIONS = {
    "https://www.ylw-scout.org.hk/circular/activity12-2026.pdf.pdf":
        "https://www.ylw-scout.org.hk/circular/activity12-2026.pdf",
    "https://www.ylw-scout.org.hk/circular/activity13-2026.pdf.pdf":
        "https://www.ylw-scout.org.hk/circular/activity13-2026.pdf",
    "https://www.ylw-scout.org.hk/circular/activity15-2026.pdf.pdf":
        "https://www.ylw-scout.org.hk/circular/activity15-2026.pdf",
}

# 元朗西區三份因 `.pdf.pdf` 404 而漏抽嘅真 PDF 核實內容（activity12/13 已過 7 日增量窗，
# activity15 若只跑 apply_notice_corrections 亦可即時補齊；若 enrich.py 已成功實抽則不覆寫）。
REPAIRED_PDF_BACKFILLS = {
    "https://www.ylw-scout.org.hk/circular/activity12-2026.pdf": {
        "source": "元朗西區",
        "title": "元朗西區50週年紀念填色比賽 - activity12-2026",
        "deadline": "2026-09-20",
        "audience": "小童軍、幼童軍",
        "audience_evidence": "本區已宣誓之小、幼童軍成員。",
        "fee": "全免",
    },
    "https://www.ylw-scout.org.hk/circular/activity13-2026.pdf": {
        "source": "元朗西區",
        "title": "元朗西區慶祝50週年小童軍競技比賽 - activity13-2026",
        "deadline": "2026-10-15",
        "audience": "小童軍",
        "audience_evidence": "已宣誓之小童軍成員，參賽隊員必須在賽事舉行當日年滿4歲及不足8歲。",
        "fee": "HK$200",
    },
    "https://www.ylw-scout.org.hk/circular/activity15-2026.pdf": {
        "source": "元朗西區",
        "title": "元朗西區50周年幼童軍主席盾比賽 - activity15-2026",
        "deadline": "2026-11-21",
        "audience": "幼童軍",
        "audience_evidence": "本區已宣誓及持有效幼童軍記錄冊之幼童軍成員。(比賽當日之成員必須年滿七歲半及未滿十二歲)",
        "fee": "HK$200.00",
    },
}

_DOUBLE_PDF_RE = re.compile(r"(?:\.pdf){2,}$", re.IGNORECASE)


def _canonical_notice_url(url: str) -> str:
    """回傳已知錯位連結嘅正確 URL；無需修正則回原字串。"""
    if not url:
        return ""
    if url in URL_CORRECTIONS:
        return URL_CORRECTIONS[url]
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    if host in {"ylw-scout.org.hk", "www.ylw-scout.org.hk"} and (parts.path or "").lower().startswith("/circular/"):
        if _DOUBLE_PDF_RE.search(parts.path or ""):
            new_path = _DOUBLE_PDF_RE.sub(".pdf", parts.path)
            return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))
    return url


def _migrate_cache_urls(cache: dict, enrich: dict) -> int:
    """把 cache（data + notices）同 enrich 入面嘅錯位 `.pdf.pdf` 網址搬去真單一 `.pdf`，
    同時保留最早 captured_date 並清走舊 404 錯誤記錄。回傳實際改動筆數。
    """
    changed = 0
    arrays: list[tuple[str, list]] = []
    for source_name, arr in (cache.get("data") or {}).items():
        if isinstance(arr, list):
            arrays.append((source_name, arr))
    if isinstance(cache.get("notices"), list):
        arrays.append(("", cache["notices"]))

    for default_source, arr in arrays:
        deduped: list[dict] = []
        by_key: dict[tuple[str, str], dict] = {}
        list_modified = False
        for item in arr:
            if not isinstance(item, dict):
                deduped.append(item)
                continue
            raw_pdf = str(item.get("pdf_url") or "")
            raw_url = str(item.get("url") or "")
            new_pdf = _canonical_notice_url(raw_pdf) if raw_pdf else ""
            new_url = _canonical_notice_url(raw_url) if raw_url else ""
            if new_pdf != raw_pdf:
                item["pdf_url"] = new_pdf
                list_modified = True
                changed += 1
            if raw_url and new_url != raw_url:
                item["url"] = new_url
                list_modified = True
            eff_url = str(item.get("pdf_url") or item.get("url") or "")
            src = str(item.get("source_site") or default_source or "")
            key = (src, eff_url)
            if eff_url and key in by_key:
                # 同一來源同時有舊 .pdf.pdf 同新 .pdf 兩條記錄時，合併並保留最早入庫日
                keeper = by_key[key]
                for date_field in ("captured_date", "date"):
                    old_d = str(keeper.get(date_field) or "")
                    cur_d = str(item.get(date_field) or "")
                    if cur_d and (not old_d or cur_d < old_d):
                        keeper[date_field] = cur_d
                list_modified = True
                changed += 1
                continue
            if eff_url:
                by_key[key] = item
            deduped.append(item)
        if list_modified and len(deduped) != len(arr):
            arr[:] = deduped

    for old_url in list(enrich.keys()):
        new_url = _canonical_notice_url(old_url)
        if new_url == old_url:
            continue
        old_entry = enrich.pop(old_url, None)
        changed += 1
        if isinstance(old_entry, dict) and not old_entry.get("error") and new_url not in enrich:
            enrich[new_url] = old_entry

    return changed


def _is_category_tag(tag: Any) -> bool:
    """True for top-level category IDs and branch-scoped all-training IDs."""
    value = str(tag or "")
    return value.startswith(("category:", "activity:", "training:"))


def _category_ids(categories: list[dict]) -> set[str]:
    ids = set()
    for category in categories:
        category_id = category.get("id")
        if category_id == "activity":
            ids.add(f"activity:{category.get('subtype', 'other').replace('_', '-')}")
        elif category_id:
            ids.add(f"category:{category_id}")
    return ids


def _cache_item(cache: dict, url: str) -> dict | None:
    """搵返 cache.json 入面呢個 URL 嘅通告（data 分組優先，再睇 notices）。"""
    for arr in (cache.get("data") or {}).values():
        if not isinstance(arr, list):
            continue
        for item in arr:
            if isinstance(item, dict) and (item.get("pdf_url") or item.get("url") or "") == url:
                return item
    for item in cache.get("notices") or []:
        if isinstance(item, dict) and (item.get("pdf_url") or item.get("url") or "") == url:
            return item
    return None


def _set_title_in_cache(cache: dict, url: str, title: str) -> int:
    """cache.json 嘅 data[source] 同 notices 兩份副本都要改，避免 UI／推播唔同步。"""
    changed = 0
    arrays = [a for a in (cache.get("data") or {}).values() if isinstance(a, list)]
    arrays.append(cache.get("notices") or [])
    for arr in arrays:
        for item in arr:
            if not isinstance(item, dict):
                continue
            if (item.get("pdf_url") or item.get("url") or "") != url:
                continue
            if item.get("title") != title:
                item["title"] = title
                changed += 1
    return changed


def _rewrite_category_metadata(record: dict) -> None:
    """用現行規則重算分類／訂閱標籤，保留獨立嘅課程 topic 標籤。"""
    source = record.get("source", record.get("source_site", ""))
    metadata = extract_subscription_metadata(
        record.get("title", ""),
        "",  # 標題先決；唔好再餵 PDF 內文（2026-10-09 用戶規則）
        record.get("audience", ""),
        source=source,
    )
    new_categories = metadata["categories"]
    new_category_ids = _category_ids(new_categories)

    old_tags = record.get("subscription_tags") or []
    record["subscription_tags"] = sorted(
        {str(tag) for tag in old_tags if not _is_category_tag(tag)} | new_category_ids
    )
    old_details = record.get("subscription_tag_details") or []
    kept_details = [
        detail for detail in old_details
        if isinstance(detail, dict) and not _is_category_tag(detail.get("id"))
    ]
    replacement_details = [
        detail for detail in metadata["subscription_tag_details"]
        if detail.get("id") in new_category_ids
    ]
    detail_by_id = {detail["id"]: detail for detail in kept_details + replacement_details}
    record["subscription_tag_details"] = [detail_by_id[key] for key in sorted(detail_by_id)]
    record["categories"] = new_categories
    record["branch_tags"] = metadata["branch_tags"]
    record["subscription_catalog_version"] = metadata["catalog_version"]


def apply_corrections(enrich: dict, cache: dict | None = None) -> dict[str, int]:
    """Mutate notice metadata in place; leave notice inventory intact.

    ``cache`` is optional so the original unit tests can exercise category
    corrections in isolation. Title/inventory corrections need the cache.
    """
    corrected = 0
    restored_titles = 0
    injected = 0
    migrated_urls = 0
    repaired_pdfs = 0

    # 0) 修正錯位 `.pdf.pdf` 連結（cache 兩份副本 + enrich 同步，保留原入庫日）
    if cache:
        migrated_urls = _migrate_cache_urls(cache, enrich)

    # 1) 還原寫壞咗嘅通告名（cache + enrich 同步，唔會再被 reapply 蓋走）
    if cache:
        for url, title in TITLE_CORRECTIONS.items():
            entry = enrich.get(url)
            if not isinstance(entry, dict) or _cache_item(cache, url) is None:
                continue
            if _set_title_in_cache(cache, url, title):
                restored_titles += 1
            if entry.get("title") != title or entry.get("title_check") != "verified":
                entry["title"] = title
                entry["title_check"] = "verified"
                entry["title_restored_by"] = REVIEW_LABEL
            # 舊嘅假標題曾經被當成 PDF 標題寫入；留低 audit 但唔再生效。
            if entry.get("listing_title") == entry.get("title"):
                entry.pop("listing_title", None)

    # 2) 補歲數／「支部或以上」抽出嘅 labelled audience
    for url, audience in AUDIENCE_CORRECTIONS.items():
        entry = enrich.get(url)
        if isinstance(entry, dict) and entry.get("audience") != audience:
            entry["audience"] = audience

    # 3) 用戶確認嘅分類修正（標題為準，套用到所有鏡像副本）
    for record in enrich.values():
        if not isinstance(record, dict) or record.get("title") not in CATEGORY_CORRECTIONS:
            continue
        _rewrite_category_metadata(record)
        corrected += 1

    # 4) 網頁型通告：enrich.py 唔會處理，幫佢補一條標題分類 entry
    if cache:
        for url, expected_category in UNENRICHED_NOTICE_URLS.items():
            item = _cache_item(cache, url)
            if not item:
                continue
            title = str(item.get("title") or "")
            if not title:
                continue
            record = enrich.get(url)
            current_ids = [c.get("id") for c in (record or {}).get("categories", []) if isinstance(c, dict)]
            if record and current_ids == [expected_category] and record.get("enrich_version") == ENRICH_VERSION:
                continue
            source = str(item.get("source_site") or item.get("region") or "")
            metadata = extract_subscription_metadata(title, "", "", source=source)
            categories = metadata["categories"]
            # 用戶已裁定嘅類別優先用；其餘情況照權威規則。
            if not any(c.get("id") == expected_category for c in categories):
                categories = [{"id": expected_category,
                               "label": {"competition": "比賽", "activity": "活動",
                                         "service": "服務", "training": "訓練",
                                         "announcement": "公布"}.get(expected_category, "公布"),
                               "score": 3.0, "evidence": ["用戶確認 2026-11-04"]}]
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 將軍澳區標題自帶「(截止: YYYY-MM-DD)」，順手填返前端顯示用嘅截止日。
            deadline_match = re.search(r"\(截止[:：]\s*(\d{4}-\d{2}-\d{2})\)", title)
            enrich[url] = {
                "source": source,
                "title": title,
                "deadline": deadline_match.group(1) if deadline_match else "",
                "audience": "",
                "audience_evidence": "",
                "fee": "",
                "categories": categories,
                "branch_tags": metadata["branch_tags"],
                "subscription_tags": sorted(
                    set(metadata["subscription_tags"])
                    | {f"category:{expected_category}"}
                ),
                "subscription_tag_details": metadata["subscription_tag_details"],
                "subscription_catalog_version": metadata["catalog_version"],
                "method": "site-listing",
                "error": "",
                "title_check": "verified",
                "enriched_at": now,
                "enrich_version": ENRICH_VERSION,
                "notice_correction": REVIEW_LABEL,
            }
            injected += 1

        # 5) 補齊因 `.pdf.pdf` 404 而漏抽嘅真 PDF 核實欄位（若 enrich.py 已成功實抽則不覆寫）
        for url, spec in REPAIRED_PDF_BACKFILLS.items():
            item = _cache_item(cache, url)
            if not item:
                continue
            existing = enrich.get(url)
            if isinstance(existing, dict) and not existing.get("error") and existing.get("deadline") and existing.get("audience"):
                continue
            title = str(item.get("title") or spec["title"])
            source = str(item.get("source_site") or spec["source"])
            audience = spec["audience"]
            metadata = extract_subscription_metadata(title, "", audience, source=source)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            enrich[url] = {
                "source": source,
                "title": title,
                "deadline": spec["deadline"],
                "audience": audience,
                "audience_evidence": spec["audience_evidence"],
                "fee": spec["fee"],
                "categories": metadata["categories"],
                "branch_tags": metadata["branch_tags"],
                "subscription_tags": metadata["subscription_tags"],
                "subscription_tag_details": metadata["subscription_tag_details"],
                "subscription_catalog_version": metadata["catalog_version"],
                "method": "text",
                "error": "",
                "title_check": "verified",
                "enriched_at": now,
                "enrich_version": ENRICH_VERSION,
                "notice_correction": REVIEW_LABEL,
            }
            repaired_pdfs += 1

    summary = {"corrected_categories": corrected}
    if restored_titles:
        summary["restored_titles"] = restored_titles
    if injected:
        summary["injected_entries"] = injected
    if migrated_urls:
        summary["migrated_urls"] = migrated_urls
    if repaired_pdfs:
        summary["repaired_pdfs"] = repaired_pdfs
    return summary


def main() -> None:
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    summary = apply_corrections(enrich, cache)
    ENRICH_PATH.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Reviewed notice corrections: " + ", ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
