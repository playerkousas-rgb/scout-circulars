#!/usr/bin/env python3
"""Apply reviewed, durable corrections to the public notice snapshot.

This is intentionally a small allowlist of user-confirmed corrections, not a
heuristic cleanup pass. Run after scrape/enrich and before publishing data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from subscription_tagging import extract_subscription_metadata

CACHE_PATH = ROOT / "cache.json"
ENRICH_PATH = ROOT / "enrich.json"

# Confirmed false positive: this TKO detail page is not a valid circular.
REMOVED_NOTICE_URLS = {
    "https://hkscout-tko.org/notice/?nid=209",
}

# The event is duplicated by the General Association and New Territories East
# Region, so fix category metadata by title rather than a single source URL.
CATEGORY_CORRECTIONS = {
    "童軍訓練班及活動專用特惠菜式",
    "新東毅行.越嶺同行",
}


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


def apply_corrections(cache: dict, enrich: dict) -> dict[str, int]:
    """Mutate cache/enrich in place and return a concise change summary."""
    removed_cache = 0
    notices = cache.get("notices")
    if isinstance(notices, list):
        kept = [row for row in notices if row.get("pdf_url") not in REMOVED_NOTICE_URLS]
        removed_cache += len(notices) - len(kept)
        cache["notices"] = kept

    grouped = cache.get("data")
    if isinstance(grouped, dict):
        for source, rows in list(grouped.items()):
            if not isinstance(rows, list):
                continue
            kept = [row for row in rows if row.get("pdf_url", row.get("url")) not in REMOVED_NOTICE_URLS]
            removed_cache += len(rows) - len(kept)
            grouped[source] = kept

    if isinstance(cache.get("meta"), dict) and isinstance(cache.get("notices"), list):
        cache["meta"]["total_notices"] = len(cache["notices"])

    removed_enrich = 0
    corrected = 0
    for url in list(enrich):
        record = enrich[url]
        if url in REMOVED_NOTICE_URLS:
            del enrich[url]
            removed_enrich += 1
            continue
        if not isinstance(record, dict) or record.get("title") not in CATEGORY_CORRECTIONS:
            continue

        source = record.get("source", record.get("source_site", ""))
        metadata = extract_subscription_metadata(
            record.get("title", ""),
            "",
            record.get("audience", ""),
            source=source,
        )
        new_categories = metadata["categories"]
        new_category_ids = _category_ids(new_categories)

        # Keep any independently evidenced course/topic subscriptions while
        # replacing the stale top-level category and its detail.
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
        record["subscription_catalog_version"] = metadata["catalog_version"]
        corrected += 1

    return {
        "removed_cache_rows": removed_cache,
        "removed_enrich_rows": removed_enrich,
        "corrected_categories": corrected,
    }


def main() -> None:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    summary = apply_corrections(cache, enrich)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ENRICH_PATH.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Reviewed notice corrections: " + ", ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
