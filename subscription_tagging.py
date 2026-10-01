#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic personal-subscription tags for Scout Circulars.

The catalogue is deliberately controlled: a user can only subscribe to a
verified official course/badge or one of the agreed broad categories
(training, service, activity, competition, announcement). This keeps a new or
odd local course name from creating an unreliable push subscription.
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
    # 2026-09-14 擴充：「考驗」涵蓋各章考驗日／考驗營；「課程」涵蓋「…課程」通告。
    # （單個「章」字刻意唔收：實測會引入獎章申請／訂購表格／使用手冊等行政文件，寧漏勿錯。）
    "考驗", "課程",
]
SERVICE_TERMS = [
    "社區服務", "服務計劃", "義工服務", "志願服務", "服務活動", "服務日", "服務隊", "服務團",
    "義工招募", "公益服務", "社會服務", "探訪", "捐血", "籌款",
    # 2026-10-01 加：區會常用「XX(服務邀請)」做標題，招募童軍/領袖做義務工作人員
    # 幫手搞活動（例如「油尖區百年童行-童軍115追蹤挑戰賽(服務邀請)」），之前漏咗
    # 呢個詞令成份通告淨係撞中 COMPETITION_TERMS（賽事個名），完全走漏服務訊號。
    "服務邀請", "義工邀請",
]
# 2026-10-01 用戶要求：淨係撞中「服務／工作人員／義工」就必定係服務（唔使成個
# 片語一字不漏），務求「XX比賽工作人員招募」「XX開放日服務」呢類標題都歸得到
# 服務——但「服務組」要剔除，因為嗰個係童軍專章嘅分組標籤（技能組／服務組），
# 成句通常其實係訓練班（例如「童軍消防(服務組)專章訓練班」），唔係招義工。
SERVICE_BARE_TERMS = ["服務", "工作人員", "義工"]
SERVICE_BARE_EXCLUDE_TERM = "服務組"

# 標題出現呢啲詞＝通告本身係「招募人手幫手」，唔係比賽／訓練報名表格，即使標題
# 重複埋賽事個名（例如「...挑戰賽(服務邀請)」）都好，都唔應該再撞埋 competition／
# training：報緊名嗰班人去做義工，唔係去比賽或受訓。見 extract_categories。
SERVICE_INVITATION_TERMS = ["服務邀請", "義工邀請"]
# 比賽是獨立興趣／瀏覽分類，不再含糊併入「其他活動」。只收明確賽事詞，
# 免得一般「挑戰」或機構名稱造成誤推。
# 2026-10-01 擴充：補返實測 cache 入面出現、但舊清單漏咗嘅複合賽事詞（例如
# 「XX選拔賽」「XX田徑賽」「XX友誼賽」「XX大賽」同單獨「錦標」），同
# story_queue.py 嘅 _RE_COMPETITION 對齊。刻意唔收單獨「賽」字——「賽馬會」
# 呢類贊助機構名會變成假陽性。
COMPETITION_TERMS = [
    "比賽", "競賽", "公開賽", "錦標賽", "邀請賽", "挑戰賽", "會操", "練習賽", "體驗賽",
    "選拔賽", "田徑賽", "友誼賽", "大賽", "錦標", "實體賽",
    # 2026-10-01 用戶再次確認：「成績公佈」「結果公佈」「公佈結果」（連埋「公布」
    # 異體字）本身就代表緊一場賽事出咗成績，一定算比賽類，唔理個標題有冇再講
    # 多一次「比賽」「錦標賽」呢啲字——即使淨係得呢幾隻字都要贏過「公佈」兜底。
    # 服務／捐血／服務獎呢類通告唔會中招，因為服務檢查行先過比賽（見下面優先
    # 序），「XX服務獎...成績公布」會先撞中「服務」裸字而歸服務，唔會變比賽。
    "成績公佈", "成績公布", "結果公佈", "結果公布", "公佈結果", "公布結果",
]

BIG_CAMP_TERMS = ["大露營", "大型露營", "童軍大露營"]
CAMPFIRE_TERMS = ["營火會", "campfire"]
OTHER_ACTIVITY_TERMS = [
    "活動", "嘉年華", "繽紛日", "旅程", "參觀", "典禮", "日營", "露營", "遠足", "交流日", "旅行", "開放日",
    "體驗日",
]

# 來源級分類：呢啲來源發布嘅通告一律歸類「小工具」，唔使靠標題關鍵詞。
# 注意：分類固定係小工具，但**支部照行正常抽取**——每個工具本身有支部標籤
# （例如「幼童軍計時器」），由標題／對象抽出；抽唔到就同其他通告一樣入未分類，
# 唔好一刀切當全支部，否則幼童軍訂閱者會收到領袖嘅工具。
# 新來源直接喺呢度加名就得（同 sources.json 嘅來源名一致）。
TOOLS_SOURCES = {"Scout System"}
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


def _service_signal_hits(value: Any) -> List[str]:
    """SERVICE_BARE_TERMS 係裸字（唔使成個片語），但要先剔走「服務組」先再比對，
    否則「童軍消防(服務組)專章訓練班」呢類訓練班通告會被誤判做服務。"""
    haystack = normalize(value)
    haystack_no_group = haystack.replace(normalize(SERVICE_BARE_EXCLUDE_TERM), "")
    hits: List[str] = []
    for term in SERVICE_BARE_TERMS:
        needle = normalize(term)
        if needle and needle in haystack_no_group and term not in hits:
            hits.append(term)
    return hits


def _badge_stem(label: str) -> str:
    """「模擬飛行章」→「模擬飛行」; anything that is not a badge name → ''."""
    label = str(label or "").strip()
    return label[:-1] if label.endswith("章") and len(label) >= 3 else ""


def _badge_variants(label: str) -> List[str]:
    """Official course titles rarely spell a badge as 「X章」.

    HKSA notices write 「童軍模擬飛行(教導組)專章訓練班」, 「童軍露營訓練班」 or
    「射擊專章考驗」.  Generate those forms from the controlled badge label so a
    badge stays a single subscription item.
    """
    stem = _badge_stem(label)
    if not stem:
        return []
    return [
        f"{stem}專章",
        f"{stem}(興趣組)專章", f"{stem}(技能組)專章", f"{stem}(服務組)專章", f"{stem}(教導組)專章",
        f"{stem}(興趣組)章", f"{stem}(技能組)章", f"{stem}(服務組)章", f"{stem}(教導組)章",
        f"{stem}訓練班", f"{stem}工作坊", f"{stem}考驗",
    ]


def _mask_term(value: Any, term: str) -> str:
    """Remove every occurrence of a normalised term from normalised text."""
    haystack = normalize(value)
    needle = normalize(term)
    return haystack.replace(needle, "\u2400") if needle else haystack


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


def is_reference_document(title: Any, text: Any = "") -> bool:
    """A timetable / rule book / result list is not itself something to enrol in."""
    if _term_hits(title, REFERENCE_TITLE_TERMS):
        return True
    return not normalize(title) and bool(_term_hits(text, REFERENCE_TITLE_TERMS))


def extract_categories(title: Any, text: Any = "", source: Any = "") -> List[Dict[str, Any]]:
    """Classify into exactly one of training / service / activity / competition
    / announcement.

    2026-10-01（用戶決定）：一篇通告淨係可以有一個分類，唔再容許「又訓練又
    比賽」「又比賽又服務」咁樣同時顯示兩個標籤。撞中幾個分類嘅字眼時，按
    固定優先序淨揀一個：服務 > 比賽 > 公佈 > 訓練 > 活動（活動之下 big_camp／
    campfire／其他三揀一，跟返原本邏輯）。行政性質、純公告類通告冇撞中服務
    ／比賽／訓練／活動任何關鍵詞，一律兜底歸類做「公佈」（announcement）——
    呢個係成員訂閱時可以揀唔要嘅分類，但永遠唔會輸畀「成績公佈算比賽類」呢
    條規則，因為服務／比賽嘅檢查行先。Notices from a TOOLS_SOURCES source are
    always ``tools`` regardless of wording.
    """
    source_name = str(source or "").strip()
    if source_name in TOOLS_SOURCES:
        return [_make_category("tools", "小工具", [f"來源：{source_name}"])]
    title = str(title or "")
    text = str(text or "")

    # 標題明確話係「服務邀請／義工邀請」＝呢張通告本身就係招募義工，一定淨係
    # 服務，唔會因為標題重複咗賽事個名（...挑戰賽）或掛住訓練字眼就變成
    # 比賽／訓練（2026-10-01：用戶報告「又比賽又服務」唔應該出現）。
    invitation_hits = _term_hits(title, SERVICE_INVITATION_TERMS)
    if invitation_hits:
        return [_make_category("service", "服務", invitation_hits)]

    title_hits = {
        "training": _term_hits(title, TRAINING_TERMS),
        "service": _term_hits(title, SERVICE_TERMS) + _service_signal_hits(title),
        "competition": _term_hits(title, COMPETITION_TERMS),
        "big_camp": _term_hits(title, BIG_CAMP_TERMS),
        "campfire": _term_hits(title, CAMPFIRE_TERMS),
        "other": _term_hits(title, OTHER_ACTIVITY_TERMS),
    }
    # PDF content is a fallback for a non-descriptive title.  It is intentionally
    # not used to override an obvious reference/calendar document title.
    text_hits = {
        "training": _term_hits(text, TRAINING_TERMS),
        "service": _term_hits(text, SERVICE_TERMS) + _service_signal_hits(text),
        "competition": _term_hits(text, COMPETITION_TERMS),
        "big_camp": _term_hits(text, BIG_CAMP_TERMS),
        "campfire": _term_hits(text, CAMPFIRE_TERMS),
        "other": _term_hits(text, OTHER_ACTIVITY_TERMS),
    }

    # 優先序 1：服務（撞中「服務／工作人員／義工」裸字或任何 SERVICE_TERMS 片語）
    # 2026-10-01：呢兩個檢查刻意擺喺 is_reference_document 判斷之前——「成績
    # 公佈算比賽類」，一張「XX比賽-結果公布」或「XX比賽-參賽名單」嘅通告唔應
    # 該因為標題撞中「結果公布／名單」等行政文件字眼就被截咗去「公佈」，服務
    # ／比賽嘅明確訊號必須贏過泛用嘅行政文件判斷。
    service = title_hits["service"] or text_hits["service"]
    if service:
        return [_make_category("service", "服務", service)]

    # 優先序 2：比賽（明確賽事詞，例如「XX錦標賽」「XX盃」「XX成績公布」）
    competition = title_hits["competition"] or text_hits["competition"]
    if competition:
        return [_make_category("competition", "比賽", competition)]

    # Calendars, rules and lists are not a new course/service/event themselves.
    # 行政性質、純公告類通告（委員會會議紀錄、選舉、總部公布、交數、行事曆等）
    # 歸入「公佈」——呢個分類刻意擺喺訓練／活動之前，但喺服務／比賽之後，令
    # 「比賽結果公布」「比賽參賽名單」呢類通告唔會被呢度截咗去（見上面優先序
    # 1、2）。「公佈」係畀成員訂閱時可以剔走嘅行政類別，唔會變成 Story。
    if is_reference_document(title, text):
        reference_hits = _term_hits(title, REFERENCE_TITLE_TERMS) or _term_hits(text, REFERENCE_TITLE_TERMS)
        return [_make_category("announcement", "公布", reference_hits)]

    # 優先序 3：訓練（訓練班／工作坊／考驗日／課程）
    training = title_hits["training"] or text_hits["training"]
    if training:
        return [_make_category("training", "訓練", training)]

    # 優先序 4：活動——big_camp／campfire／其他三揀一，維持原本邏輯
    big_camp = title_hits["big_camp"] or text_hits["big_camp"]
    if big_camp:
        return [_make_category("activity", "活動", big_camp, "big_camp")]

    campfire = title_hits["campfire"] or text_hits["campfire"]
    if campfire:
        return [_make_category("activity", "活動", campfire, "campfire")]

    # Broad words such as 「活動」 are only trusted in a title.  PDF body
    # text commonly mentions an unrelated activity in every type of notice.
    other = title_hits["other"] or (text_hits["other"] if not normalize(title) else [])
    if other:
        return [_make_category("activity", "活動", other, "other")]

    # 2026-10-01：最後兜底都歸類做「公佈」（而唔係乜都冇），等呢類通告都可以喺
    # 訂閱設定度俾成員揀「唔想收」——呢班通常係成員最唔想睇嘅行政類一次性通告。
    return [_make_category("announcement", "公布", [])]


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
    source: Any = "",
    tag_hint: Any = "",
) -> Dict[str, Any]:
    """Create the branch/topic IDs used by the dispatcher and personal view.

    ``tag_hint`` carries site-owner labels scraped with the item (for example
    the 支部 tags on Scout System tools). It is used only when the PDF has no
    labelled audience: a labelled audience stays the most reliable signal.
    """
    catalog = catalog or load_catalog()
    title = str(title or "")
    text = str(text or "")
    source_name = str(source or "").strip()
    combined = f"{title}\n{text}"
    categories = extract_categories(title, text, source_name)

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
        "tools": "category:tools",
        "announcement": "category:announcement",
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
    reference = is_reference_document(title, text)
    for topic in catalog.get("topics", []):
        if topic.get("kind") != "course" or reference:
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
        variants.extend(_badge_variants(base))
        # ``exclude`` lists longer official names that merely contain this item
        # (「滑浪風帆章」 contains 「風帆章」; 「…章教練員訓練班」 is a leader
        # course, not the youth badge).  Mask them before matching.
        haystack = combined
        for blocked in topic.get("exclude", []) or []:
            haystack = _mask_term(haystack, blocked)
            if _badge_stem(blocked):
                haystack = _mask_term(haystack, _badge_stem(blocked))
        hits = _term_hits(haystack, [*(topic.get("aliases", []) or []), *variants])
        if hits:
            course_entries.append((topic, hits))

    # 優先用 PDF 抽出嘅對象；冇嘅時候先用站方標籤（tag_hint），最後先睇標題。
    audience_effective = str(audience or "").strip() or str(tag_hint or "").strip()
    branch_ids = extract_branch_ids(title, audience_effective, catalog=catalog)
    # A verified course provides a safe fallback scope only when the PDF has no
    # labelled audience and the title did not identify a branch.
    if not branch_ids:
        for course, _hits in course_entries:
            branch_ids.update(str(x) for x in course.get("branches", []) if x != "*")

    # Several branches share a badge name (幼童軍／童軍／深資童軍 all have an
    # 急救章).  Keep only the branch-specific items the audience can enrol in so
    # a 幼童軍 subscriber is not pushed the 童軍 version.
    for course, hits in course_entries:
        scope = {str(x) for x in course.get("branches", [])}
        if branch_ids and "*" not in scope and not scope.intersection(branch_ids):
            continue
        topic_ids.add(str(course["id"]))
        details.append(_topic_detail(course, [f"標題／內文：{hit}" for hit in hits]))

    # Per-branch "all training" items (訓練:童軍, 訓練:領袖:木章, …) so a user
    # can follow every 童軍 course while only following 木章 classes as a 領袖.
    if any(c.get("id") == "training" for c in categories):
        matched_sections = {
            str(course.get("section", "")) for course, _hits in course_entries if str(course["id"]) in topic_ids
        }
        for topic in catalog.get("topics", []):
            if topic.get("kind") != "training":
                continue
            scope = {str(x) for x in topic.get("branches", [])}
            if not scope.intersection(branch_ids):
                continue
            evidence = [f"支部：{x}" for x in sorted(scope.intersection(branch_ids))]
            section = str(topic.get("section", "") or "")
            aliases = topic.get("aliases", []) or []
            if section and section in matched_sections:
                evidence = [f"類別：{section}"]
            elif aliases:
                # 木章: only a training notice that names a wood badge module.
                haystack = combined
                for blocked in topic.get("exclude", []) or []:
                    haystack = _mask_term(haystack, blocked)
                hits = _term_hits(haystack, aliases)
                if not hits:
                    continue
                evidence = [f"標題／內文：{hit}" for hit in hits]
            blocked_by = topic.get("excludes_topic")
            if blocked_by and str(blocked_by) in topic_ids:
                continue
            topic_ids.add(str(topic["id"]))
            details.append(_topic_detail(topic, evidence))

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
        if topic.get("legacy") or topic.get("id") == "category:training":
            continue
        if selected and ("*" in scope or scope.intersection(selected)):
            result.append(dict(topic))
    return result
