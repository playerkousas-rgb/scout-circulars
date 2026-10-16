#!/usr/bin/env python3
"""Offline, idempotent backfill from manually verified original issue dates.

Never fetches, publishes, notifies, changes run fingerprints, or stamps old
notices as newly captured. Backfills carry an explicit notification/Story
suppression flag, including the one whose real issue date is today.

Usage: python fix_logbook_2026_10_16.py --dry-run
       python fix_logbook_2026_10_16.py

Evidence: LOGBOOK_REVIEW_2026-10-16.md and its implementation addendum. The
short eligibility excerpts below are review fixtures, NOT raw pdfplumber dumps.
Undated/unresolved files are deliberately absent.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote

from enrich import ENRICH_VERSION, extract_audience
from subscription_tagging import extract_subscription_metadata

ROOT = Path(__file__).resolve().parent
REVIEW_DATE = "2026-10-16"
SOURCE = "沙田南區"
PREFIX = "https://www.stsd-scout.org/programme/view_notice/"

# ID, ORIGINAL ISSUE DATE, title, deadline, audience, fee. Empty means not
# verified; admissions/subsidies never inherit another notice's signup fields.
VERIFIED = [
    (175, "2026-09-02", "急救證書課程", "2026-09-15", "", ""),
    (174, "2026-09-01", "幼童軍歷史章訓練班", "2026-09-13", "幼童軍", "HK$50"),
    (173, "2026-07-02", "「豐盛生命」正向情緒日營", "2026-08-01", "小童軍、家屬", "免費（每家庭另收 HK$50 可退還按金）"),
    (172, "2026-06-24", "2026-2027年度第一次幼童軍支部領袖會議", "2026-06-28", "領袖", "免費"),
    (170, "2026-05-15", "港鐵安全體驗天地同樂日", "2026-06-20", "小童軍", "HK$20"),
    (169, "2026-05-09", "龍舟章訓練班", "2026-05-17", "童軍", "免費"),
    (168, "2026-04-23", "招募龍舟隊成員2026", "2026-05-17", "童軍、深資童軍、樂行童軍、領袖、會務委員", "免費"),
    (167, "2026-03-30", "【取錄通知書】第70屆步操基本訓練班", "", "", ""),
    (166, "2026-03-30", "【取錄通知書】第21屆童軍步操基本訓練班", "", "", ""),
    (165, "2026-03-15", "小童軍Boxing體驗日", "2026-04-20", "小童軍", "HK$30"),
    (164, "2026-03-06", "沙田區童軍運動五十周年紀念晚宴", "2026-03-23", "各支部成員、領袖、會務委員、家屬", "HK$350／人"),
    (163, "2026-02-15", "深資樂行童軍聯團活動—霓虹燈製作工作坊", "2026-03-15", "童軍（15歲或以上）、深資童軍、樂行童軍、領袖、會務委員", "HK$100"),
    (162, "2026-02-01", "第21屆童軍步操基本訓練班", "2026-03-26", "童軍", "HK$70"),
    (161, "2026-02-01", "第70屆步操基本訓練班", "2026-03-26", "深資童軍、樂行童軍、領袖", "HK$70"),
    (160, "2026-01-15", "童軍原野烹飪章（教導組）訓練班", "2026-02-14", "童軍", "HK$75"),
    (159, "2026-01-15", "童軍原野烹飪章（技能組）訓練班", "2026-02-14", "童軍", "HK$75"),
    (158, "2025-12-15", "2025-2026年度第二次小童軍支部領袖會議", "2026-01-17", "領袖", "免費"),
    (157, "2025-11-05", "童軍支部技能錦標賽2025（顏明秀副會長盾）", "2025-12-01", "童軍", "HK$200／隊"),
    (156, "2025-10-01", "童軍專章考驗日2025", "2025-10-26", "童軍", "HK$5／章"),
    (155, "2025-10-01", "幼童軍技能比賽2025 李美琪副主席（銀碟賽）", "2025-10-26", "幼童軍", "HK$120／隊"),
    (154, "2025-10-01", "小童軍支部比賽2025 蕭麗馨副主席（主席盃）", "2025-10-31", "小童軍", "HK$150／隊"),
    (148, "2025-07-08", "沙田南旅團支援計劃（2025-26年度）", "2026-03-31", "", ""),
]

PIKFUNG = [
    ("1XdP3YhKUPcS8p19F0YG-knAelOjhx4Nn", "2026-10-16", "公民章、精神健康章、社區參與章、積極公民—國家安全大使及議會探索章訓練班", "2026-12-07", "HK$60"),
    ("1lRpizyjj4c4RQ8CTSYOCwYhAv9fptWY3", "2026-08-15", "第7屆原野烹飪訓練班—技能組", "2026-10-16", "HK$100"),
    ("1uNeOTX4XTfcvebSu8vSuZa3d3qzX9p2U", "2026-08-15", "第7屆原野烹飪訓練班—教導組", "2026-10-16", "HK$100"),
]

# Canonical paths, reviewed eligibility evidence and the expected correction.
# Cases deliberately retain real committee/leader participants, and distinguish
# the addressee/service target from eligibility. No participant names retained.
AUDIENCE_FIXES = {
    "/uploads/tc/circulars/26408/kt72_26.pdf": (
        "參加資格：持有有效領袖委任書、教練員／會務委員委任證或受薪職員；\n完成領袖初級訓練班；或完成童軍運動基本原則訓練班（單元1A及單元1B）。\n費用：港幣60元", "領袖、會務委員、受薪職員"),
    "/uploads/tc/circulars/26409/kt73_26.pdf": (
        "參加資格：持有有效領袖委任書、教練員／會務委員委任證或受薪職員；\n完成領袖初級訓練班；或完成童軍運動基本原則訓練班（單元1A及單元1B）。\n費用：港幣60元", "領袖、會務委員、受薪職員"),
    "/uploads/tc/circulars/26353/trg20_26_9thsectionaltrainingmethodscoursem2ab.pdf": (
        "參加資格：持有有效童軍支部領袖委任書、非支部領袖委任書或受薪職員。\n費用：見原文", "領袖、受薪職員"),
    "/uploads/tc/circulars/26376/sp19_2026-cuboree2026_youthsubsidy.pdf": (
        "受資助資格：年齡為8至11歲，持有有效幼童軍紀錄冊及童軍成員編號的幼童軍（必須獲得家長或監護人的同意）。\n資助金額：每位港幣300元", "幼童軍"),
    "/uploads/tc/circulars/26401/p109-26.pdf": (
        "服務對象必須為非童軍成員。\n參加資格：持有有效所屬支部紀錄冊之深資童軍及樂行童軍支部成員。\n費用：見原文", "深資童軍、樂行童軍"),
    "/uploads/tc/circulars/26402/p110-26.pdf": (
        "（六）參加資格：持有有效所屬支部紀錄冊之深資童軍及樂行童軍支部成員\n（七）班領導人資格：\n班領導人必須為本會委任之寰宇童軍章導師", "深資童軍、樂行童軍"),
    "/pdf/circular 2026/cir_2026_pt14.pdf": (
        "參加對象：深資童軍支部領袖、旅團負責領袖、團執行委員會主席及學校旅負責老師。\n會議形式：網上", "領袖、團執行委員會主席、學校旅負責老師"),
}


def reviewed_metadata(title, audience, source, evidence=""):
    if title.startswith("【取錄通知書】"):
        # A historical admission list is not a course currently enrolling.
        meta = extract_subscription_metadata("取錄名單", "", "", source=source)
        meta["categories"][0]["evidence"] = ["人工覆核：取錄通知書"]
        for detail in meta["subscription_tag_details"]:
            detail["evidence"] = ["人工覆核：取錄通知書"]
    else:
        meta = extract_subscription_metadata(title, evidence, audience, source=source)
    return {
        "categories": meta["categories"], "branch_tags": meta["branch_tags"],
        "subscription_tags": meta["subscription_tags"],
        "subscription_tag_details": meta["subscription_tag_details"],
        "subscription_catalog_version": meta["catalog_version"],
    }


def apply_review(cache, enrich):
    """Return copies plus change counts; no I/O or external side effects."""
    cache, enrich = copy.deepcopy(cache), copy.deepcopy(enrich)
    added = corrected = 0
    rows = [(SOURCE, PREFIX + str(i), date, title, deadline, audience, fee)
            for i, date, title, deadline, audience, fee in VERIFIED]
    rows += [("壁峰區", f"https://drive.google.com/file/d/{i}/view", date,
              title, deadline, "童軍", fee)
             for i, date, title, deadline, fee in PIKFUNG]
    for source, url, date, title, deadline, audience, fee in rows:
        # Match endpoints/Drive IDs independently of www, tracking parameters.
        identity = urlsplit(url).path.rstrip("/")
        exists = any(urlsplit(str(x.get("pdf_url") or x.get("url") or "")).path.rstrip("/") == identity
                     for x in cache.get("data", {}).get(source, []))
        if exists:
            continue  # NEVER overwrite an existing captured date/record.
        common = dict(title=title, pdf_url=url, captured_date=date,
                      published_date=date, source_site=source, region="新界東地域",
                      backfilled_at=REVIEW_DATE, suppress_notifications=True)
        cache.setdefault("data", {}).setdefault(source, []).append(dict(common, url=url, date=date))
        cache.setdefault("notices", []).append(common)
        if url not in enrich:
            enrich[url] = dict(
                source=source, title=title, deadline=deadline, audience=audience, fee=fee,
                method="manual-reviewed-original", error="", reviewed_at=REVIEW_DATE,
                date_evidence="原文發出日期：" + date, evidence_url=url,
                enrich_version=ENRICH_VERSION,
                **reviewed_metadata(title, audience, source),
            )
        added += 1
    if added:
        for source in {x[0] for x in rows}:
            cache["data"][source].sort(key=lambda x: (x.get("date", ""), x.get("title", "")), reverse=True)
        cache["notices"].sort(key=lambda x: (x.get("captured_date", ""), x.get("source_site", ""), x.get("title", "")), reverse=True)
        if "total_notices" in cache.get("meta", {}):
            cache["meta"]["total_notices"] = len(cache["notices"])
    for url, entry in list(enrich.items()):
        path = unquote(urlsplit(url).path).lower()
        if path not in AUDIENCE_FIXES:
            continue
        evidence, expected = AUDIENCE_FIXES[path]
        audience = extract_audience(evidence)
        assert audience == expected, (url, audience, expected)
        patch = dict(entry, audience=audience, audience_evidence=evidence,
                     audience_reviewed_at=REVIEW_DATE,
                     audience_review_method="manual-original-eligibility-excerpt",
                     **reviewed_metadata(entry.get("title", ""), audience, entry.get("source", ""), evidence))
        # Audience-only review must not undo already approved categories or
        # their top-level subscription type tags using a partial PDF excerpt.
        if "categories" in entry:
            patch["categories"] = entry["categories"]
            category_tags = {x for x in entry.get("subscription_tags", []) if x.startswith(("category:", "activity:"))}
            patch["subscription_tags"] = sorted(category_tags | {x for x in patch["subscription_tags"] if not x.startswith(("category:", "activity:"))})
            details = [x for x in entry.get("subscription_tag_details", []) if x.get("id") in category_tags]
            patch["subscription_tag_details"] = sorted(details + [x for x in patch["subscription_tag_details"] if not x.get("id", "").startswith(("category:", "activity:"))], key=lambda x: x["id"])
        if patch != entry:
            enrich[url] = patch
            corrected += 1
    return cache, enrich, {"backfilled": added, "audiences_corrected": corrected}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cp, ep = ROOT / "cache.json", ROOT / "enrich.json"
    old_cache, old_enrich = json.loads(cp.read_text()), json.loads(ep.read_text())
    cache, enrich, counts = apply_review(old_cache, old_enrich)
    print(json.dumps(counts, ensure_ascii=False))
    if not args.dry_run:
        for path, old, new in ((cp, old_cache, cache), (ep, old_enrich, enrich)):
            if new != old:
                path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
