#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic personal-subscription tags for Scout Circulars.

The catalogue is deliberately controlled: a user can only subscribe to a
verified official course/badge or one of the agreed broad categories
(training, service, activity, competition). This keeps a new or odd local course name from
creating an unreliable push subscription.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "subscription_catalog.json"

# These are intentionally limited to the product taxonomy agreed for the UI.
TRAINING_TERMS = [
    "訓練班", "訓練課程", "技能訓練", "技能考核", "研習班", "工作坊", "講座", "培訓", "進修班",
]
SERVICE_TERMS = [
    "社區服務", "服務計劃", "義工服務", "志願服務", "服務活動", "服務日", "服務隊", "服務團",
    "義工招募", "公益服務", "社會服務", "探訪", "捐血", "籌款",
]
# 比賽是獨立興趣／瀏覽分類，不再含糊併入「其他活動」。只收明確賽事詞，
# 免得一般「挑戰」或機構名稱造成誤推。
COMPETITION_TERMS = ["比賽", "競賽", "公開賽", "錦標賽", "邀請賽", "挑戰賽", "會操"]
BIG_CAMP_TERMS = ["大露營", "大型露營", "童軍大露營"]
CAMPFIRE_TERMS = ["營火會", "campfire"]
OTHER_ACTIVITY_TERMS = [
    "活動", "嘉年華", "旅程", "參觀", "典禮", "日營", "露營", "遠足", "交流日", "旅行", "開放日",
]
# A calendar/guide is useful to browse, but is not itself a newly-open training
# course.  It must not trigger someone subscribed to "all training".
REFERENCE_TITLE_TERMS = [
    "行事曆", "一覽表", "訓練綱要", "課程大綱", "章程", "指引", "結果公布", "得獎名單", "名單",
]
ALL_MEMBERS_TERMS = ["所有成員", "全體成員", "各支部成員"]


def normalize(value: Any) -> str:
    """NFKC + whitespace-insensitive text suitable for Chinese matching."""
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value).lower()
    value = value.replace("\u00a0", " ")
    return re.sub(r"[\u200b-\u200f\ufeff\s]+", "", value)


@lru_cache(maxsize=4)
def load_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    catalog_path = Path(path) if path else CATALOG_PATH
    with catalog_path.open("r", encoding="utf-8") as fh:
        catalog = json.load(fh)

    if not isinstance(catalog, dict):
        raise ValueError("subscription_catalog.json must contain an object")
    branches = catalog.get("branches")
    topics = catalog.get("topics")
    if not isinstance(branches, list) or not isinstance(topics, list):
        raise ValueError("catalog needs branches and topics lists")

    branch_ids: Set[str] = set()
    for entry in branches:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("label"):
            raise ValueError("invalid branch entry in subscription catalog")
        ident = str(entry["id"])
        if ident in branch_ids:
            raise ValueError(f"duplicate branch id: {ident}")
        branch_ids.add(ident)

    topic_ids: Set[str] = set()
    for entry in topics:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("label"):
            raise ValueError("invalid topic entry in subscription catalog")
        ident = str(entry["id"])
        if ident in topic_ids:
            raise ValueError(f"duplicate topic id: {ident}")
        topic_ids.add(ident)
        allowed = entry.get("branches", [])
        if not isinstance(allowed, list) or any(x != "*" and x not in branch_ids for x in allowed):
            raise ValueError(f"invalid branch scope for topic: {ident}")

    catalog["_branch_ids"] = branch_ids
    catalog["_topic_ids"] = topic_ids
    catalog["_branch_by_id"] = {str(x["id"]): x for x in branches}
    catalog["_topic_by_id"] = {str(x["id"]): x for x in topics}
    return catalog


def catalog_branch_ids(catalog: Optional[Mapping[str, Any]] = None) -> Set[str]:
    return set((catalog or load_catalog()).get("_branch_ids", set()))


def catalog_topic_ids(catalog: Optional[Mapping[str, Any]] = None) -> Set[str]:
    return set((catalog or load_catalog()).get("_topic_ids", set()))


def _term_hits(value: Any, terms: Iterable[str]) -> List[str]:
    haystack = normalize(value)
    hits: List[str] = []
    for term in terms:
        needle = normalize(term)
        if needle and needle in haystack and term not in hits:
            hits.append(term)
    return hits


def _make_category(tag_id: str, label: str, evidence: Iterable[str], subtype: str = "") -> Dict[str, Any]:
    result = {
        "id": tag_id,
        "label": label,
        "score": 3.0,
        "evidence": list(dict.fromkeys(evidence))[:4],
    }
    if subtype:
        result["subtype"] = subtype
    return result


def extract_categories(title: Any, text: Any = "") -> List[Dict[str, Any]]:
    """Classify into training, service, activity and competition.

    A workshop and a training class deliberately share the ``training`` tag.
    ``activity`` has exactly three subtypes: big camp, campfire and other;
    an explicit competition is a separate top-level category. More than one
    category can be valid for one circular.
    """
    title = str(title or "")
    text = str(text or "")
    title_hits = {
        "training": _term_hits(title, TRAINING_TERMS),
        "service": _term_hits(title, SERVICE_TERMS),
        "competition": _term_hits(title, COMPETITION_TERMS),
        "big_camp": _term_hits(title, BIG_CAMP_TERMS),
        "campfire": _term_hits(title, CAMPFIRE_TERMS),
        "other": _term_hits(title, OTHER_ACTIVITY_TERMS),
    }
    # PDF content is a fallback for a non-descriptive title.  It is intentionally
    # not used to override an obvious reference/calendar document title.
    text_hits = {
        "training": _term_hits(text, TRAINING_TERMS),
        "service": _term_hits(text, SERVICE_TERMS),
        "competition": _term_hits(text, COMPETITION_TERMS),
        "big_camp": _term_hits(text, BIG_CAMP_TERMS),
        "campfire": _term_hits(text, CAMPFIRE_TERMS),
        "other": _term_hits(text, OTHER_ACTIVITY_TERMS),
    }
    title_is_reference = bool(_term_hits(title, REFERENCE_TITLE_TERMS))
    text_is_reference = not normalize(title) and bool(_term_hits(text, REFERENCE_TITLE_TERMS))
    # Calendars, rules and lists are not a new course/service/event themselves.
    # Returning no category also prevents "all training" from being notified for
    # a quarterly timetable rather than a registration opportunity.
    if title_is_reference or text_is_reference:
        return []

    result: List[Dict[str, Any]] = []
    training = [] if title_is_reference else (title_hits["training"] or text_hits["training"])
    if training:
        result.append(_make_category("training", "訓練", training))

    service = title_hits["service"] or text_hits["service"]
    if service:
        result.append(_make_category("service", "服務", service))

    competition = title_hits["competition"] or text_hits["competition"]
    if competition:
        result.append(_make_category("competition", "比賽", competition))

    big_camp = title_hits["big_camp"] or text_hits["big_camp"]
    campfire = title_hits["campfire"] or text_hits["campfire"]
    # Activity subtypes are mutually exclusive for a clean subscription choice.
    # A named 大露營／營火會 remains useful even if its notice also mentions
    # service or training. A clear competition is never also put in 活動: users
    # who opted into a camp/campfire should not receive a contest by accident.
    if not competition and big_camp:
        result.append(_make_category("activity", "活動", big_camp, "big_camp"))
    elif not competition and campfire:
        result.append(_make_category("activity", "活動", campfire, "campfire"))
    elif not training and not service and not competition:
        # Broad words such as 「活動」 are only trusted in a title.  PDF body
        # text commonly mentions an unrelated activity in every type of notice.
        other = title_hits["other"] or (text_hits["other"] if not normalize(title) else [])
        if other:
            result.append(_make_category("activity", "活動", other, "other"))

    return result


def _scan_branch_tokens(value: Any, catalog: Mapping[str, Any]) -> Set[str]:
    """Scan longest aliases first so 幼童軍/深資童軍 never become 童軍."""
    text = normalize(value)
    if not text:
        return set()
    if any(normalize(term) in text for term in ALL_MEMBERS_TERMS):
        return set(catalog.get("_branch_ids", set()))

    aliases: List[Tuple[str, str]] = []
    for branch in catalog.get("branches", []):
        branch_id = str(branch.get("id", ""))
        for alias in branch.get("aliases", []) or []:
            normalized = normalize(alias)
            if normalized:
                aliases.append((normalized, branch_id))
    aliases.sort(key=lambda x: len(x[0]), reverse=True)

    found: Set[str] = set()
    index = 0
    while index < len(text):
        matched = next(((alias, ident) for alias, ident in aliases if text.startswith(alias, index)), None)
        if matched:
            alias, ident = matched
            found.add(ident)
            index += len(alias)
        else:
            index += 1
    return found


def extract_branch_ids(title: Any, audience: Any = "", *, catalog: Optional[Mapping[str, Any]] = None) -> Set[str]:
    """Use labelled PDF audience first; only fall back to a cleaned title."""
    catalog = catalog or load_catalog()
    if str(audience or "").strip():
        return _scan_branch_tokens(audience, catalog)

    # 「香港童軍總會」is organisational wording, not an audience declaration.
    clean_title = re.sub(r"香港\s*童軍(?:總會)?", "", str(title or ""))
    return _scan_branch_tokens(clean_title, catalog)


def _topic_detail(entry: Mapping[str, Any], evidence: Iterable[str]) -> Dict[str, Any]:
    return {
        "id": str(entry["id"]),
        "label": str(entry["label"]),
        "group": str(entry.get("group", "")),
        "kind": str(entry.get("kind", "")),
        "evidence": list(dict.fromkeys(str(x) for x in evidence if x))[:4],
    }


def extract_subscription_metadata(
    title: Any,
    text: Any = "",
    audience: Any = "",
    *,
    catalog: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create the branch/topic IDs used by the dispatcher and personal view."""
    catalog = catalog or load_catalog()
    title = str(title or "")
    text = str(text or "")
    combined = f"{title}\n{text}"
    categories = extract_categories(title, text)

    topic_ids: Set[str] = set()
    details: List[Dict[str, Any]] = []
    by_id = catalog.get("_topic_by_id", {})

    # Top-level type tags are driven by the classifier, not by a broad keyword
    # in the user preference.  This ensures a "training" subscription receives
    # both 訓練班 and 工作坊 as requested.
    category_mapping = {
        "training": "category:training",
        "service": "category:service",
        "competition": "category:competition",
    }
    for category in categories:
        topic_id = category_mapping.get(category.get("id"))
        if category.get("id") == "activity":
            topic_id = f"activity:{category.get('subtype', 'other').replace('_', '-')}"
        entry = by_id.get(topic_id or "")
        if entry:
            topic_ids.add(str(topic_id))
            details.append(_topic_detail(entry, category.get("evidence", [])))

    course_entries: List[Tuple[Mapping[str, Any], List[str]]] = []
    for topic in catalog.get("topics", []):
        if topic.get("kind") != "course":
            continue
        # The controlled label is the user-facing base item (for example
        # 「地圖閱讀」), while aliases retain official full titles. Generate only
        # clear course-form variants from that base: matching a bare generic
        # label such as 「遊戲」 would be too broad and could cause a false push.
        base = str(topic.get("label", "")).strip()
        variants = [
            f"{base}{suffix}"
            for suffix in ("訓練班", "工作坊", "課程", "訓練課程", "訓練", "研習班", "培訓", "進修班")
            if base
        ]
        hits = _term_hits(combined, [*(topic.get("aliases", []) or []), *variants])
        if hits:
            topic_ids.add(str(topic["id"]))
            course_entries.append((topic, hits))
            details.append(_topic_detail(topic, [f"標題／內文：{hit}" for hit in hits]))

    branch_ids = extract_branch_ids(title, audience, catalog=catalog)
    # A verified course provides a safe fallback scope only when the PDF has no
    # labelled audience and the title did not identify a branch.
    if not branch_ids:
        for course, _hits in course_entries:
            branch_ids.update(str(x) for x in course.get("branches", []) if x != "*")

    # Stable, de-duplicated display values.
    detail_map = {str(item["id"]): item for item in details}
    details = [detail_map[key] for key in sorted(detail_map)]
    return {
        "categories": categories,
        "branch_tags": sorted(branch_ids),
        "subscription_tags": sorted(topic_ids),
        "subscription_tag_details": details,
        "catalog_version": str(catalog.get("version", "")),
    }


def matching_topics_for_branches(
    branches: Iterable[str], catalog: Optional[Mapping[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Return dropdown choices visible for the currently selected branches."""
    catalog = catalog or load_catalog()
    selected = {str(x) for x in branches}
    result: List[Dict[str, Any]] = []
    for topic in catalog.get("topics", []):
        scope = {str(x) for x in topic.get("branches", [])}
        if "*" in scope or not selected or scope.intersection(selected):
            result.append(dict(topic))
    return result
