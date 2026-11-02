#!/usr/bin/env python3
"""Apply reviewed category corrections before publishing the public snapshot.

This is a small allowlist of user-confirmed category rules, not a heuristic
cleanup pass. Run after scrape/enrich and before publishing data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from subscription_tagging import extract_subscription_metadata  # noqa: E402

ENRICH_PATH = ROOT / "enrich.json"

# Apply to every mirrored copy sharing these exact titles.
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


def apply_corrections(enrich: dict) -> dict[str, int]:
    """Mutate category metadata in enrich in place; leave notice inventory intact."""
    corrected = 0
    for record in enrich.values():
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

    return {"corrected_categories": corrected}


def main() -> None:
    enrich = json.loads(ENRICH_PATH.read_text(encoding="utf-8"))
    summary = apply_corrections(enrich)
    ENRICH_PATH.write_text(json.dumps(enrich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Reviewed category corrections: " + ", ".join(f"{key}={value}" for key, value in summary.items()))


if __name__ == "__main__":
    main()
