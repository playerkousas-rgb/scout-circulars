#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send one privacy-preserving Web Push summary per matching subscriber.

Run this after ``core.py`` and ``enrich.py``, before committing cache.json.
It compares the working cache to ``HEAD:cache.json`` so a normal re-scrape
never re-notifies historical notices.  If another writer (the local backup PC)
committed today's notices before this checkout, a same-day catch-up still
covers never-delivered items; delivery records keep reruns silent.
For each anonymous browser subscription
all matching new notices are aggregated first: 10 matches means one push, not
10 notification sounds.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from subscription_tagging import extract_subscription_metadata, load_catalog

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "cache.json"
ENRICH_PATH = ROOT / "enrich.json"
HKT = ZoneInfo("Asia/Hong_Kong")
PUSH_TTL_SECONDS = 3 * 24 * 60 * 60  # Per-message offline retention, not subscription expiry.
DEFAULT_SITE_URL = "https://scout-circulars.vercel.app"
# RFC 8291 caps one encrypted Web Push message at 4096 bytes. Each compact
# notice ID adds ~17 bytes to the `n=` URL plus ~19 bytes to the JSON
# `noticeIds` array, so capping at 60 IDs keeps a >100-match big-day payload
# around 2.5 KB — safely below the limit even before encryption overhead —
# instead of relying on busy days staying rare (a 120-match day is ~4.6 KB
# and already trips 413 Payload Too Large on some push services).
MAX_PAYLOAD_NOTICE_IDS = 60


class NotificationError(Exception):
    pass


class StorageError(NotificationError):
    pass


@dataclass
class SendResult:
    subscription_id: str
    notices: List[Dict[str, Any]]
    status: str  # sent | stale | failed
    error: str = ""


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise NotificationError(f"{path.name} must contain a JSON object")
    return value


def notice_url(item: Mapping[str, Any]) -> str:
    return str(item.get("pdf_url") or item.get("url") or "").strip()


def notice_source(item: Mapping[str, Any]) -> str:
    return str(item.get("source_site") or "").strip()


def notice_key(item: Mapping[str, Any]) -> str:
    """Source isolation mirrors core.py's `(source_site, pdf_url)` identity."""
    value = f"{notice_source(item)}\x1f{notice_url(item)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def notice_id(item: Mapping[str, Any]) -> str:
    """Return a compact, opaque and deterministic browser-facing notice ID.

    It is intentionally derived only from a source and public circular URL,
    not from a subscription or any browser identifier. The matching FNV-1a
    implementation in ``index.html`` lets a clicked notification show exactly
    this delivery's cards without sending preferences to the library URL.
    """
    value = f"{notice_source(item)}\x1f{notice_url(item)}".encode("utf-8")
    hashed = 0xCBF29CE484222325
    for byte in value:
        hashed ^= byte
        hashed = (hashed * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{hashed:016x}"


def iter_notices(cache: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Read grouped cache once; do not double-count the compatibility `notices` array."""
    grouped = cache.get("data")
    result: List[Dict[str, Any]] = []
    if isinstance(grouped, Mapping) and grouped:
        for source, values in grouped.items():
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, Mapping):
                    continue
                record = dict(item)
                record.setdefault("source_site", str(source))
                if notice_url(record):
                    result.append(record)
        return result
    for item in cache.get("notices", []) or []:
        if isinstance(item, Mapping) and notice_url(item):
            result.append(dict(item))
    return result


def load_baseline_cache(ref: str) -> Optional[Dict[str, Any]]:
    """Load cache.json from git before the current workflow started.

    Returning None is intentionally safe: a fresh checkout with no baseline
    must never spam all historic notices.
    """
    completed = subprocess.run(
        ["git", "show", f"{ref}:cache.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def find_new_notices(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> List[Dict[str, Any]]:
    previous_keys = {notice_key(item) for item in iter_notices(baseline)}
    result: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for item in iter_notices(current):
        key = notice_key(item)
        if key in previous_keys or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def find_catchup_notices(
    current: Mapping[str, Any],
    already_found: Sequence[Dict[str, Any]],
    batch_date: str,
) -> List[Dict[str, Any]]:
    """Return same-day cached notices that the baseline diff did not discover.

    Covers the local-backup-first ordering: the home PC committed today's
    notices before this checkout, so the ``HEAD`` diff is empty even though
    nobody has notified them yet.  Only items captured exactly on
    ``batch_date`` qualify, and per-subscription delivery records still filter
    out anything already sent — a same-day rerun stays silent.
    """
    seen = {notice_key(item) for item in already_found}
    result: List[Dict[str, Any]] = []
    for item in iter_notices(current):
        key = notice_key(item)
        if key in seen:
            continue
        if str(item.get("captured_date") or item.get("date") or "")[:10] != batch_date:
            continue
        seen.add(key)
        result.append(item)
    return result


def enrichment_for(item: Mapping[str, Any], enrich: Mapping[str, Any]) -> Dict[str, Any]:
    value = enrich.get(notice_url(item)) if isinstance(enrich, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else {}


def notice_metadata(item: Mapping[str, Any], enrich: Mapping[str, Any]) -> Dict[str, Any]:
    """Use fresh PDF tags, with a title/audience fallback for non-PDF notices."""
    extra = enrichment_for(item, enrich)
    fallback = extract_subscription_metadata(
        item.get("title", ""),
        "",
        extra.get("audience", ""),
    )
    branch_tags = {str(x) for x in (extra.get("branch_tags") or fallback["branch_tags"]) if isinstance(x, str)}
    topic_tags = {str(x) for x in (extra.get("subscription_tags") or fallback["subscription_tags"]) if isinstance(x, str)}
    return {
        "branch_tags": branch_tags,
        "topic_tags": topic_tags,
        "deadline": str(extra.get("deadline") or ""),
        "fee": str(extra.get("fee") or ""),
        "audience": str(extra.get("audience") or ""),
        "details": extra.get("subscription_tag_details") or fallback.get("subscription_tag_details") or [],
    }


def subscription_matches(subscription: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    """OR across selected branch/topic pairs; never cross-match two pairs.

    Legacy generic IDs remain supported using their catalog scope. The explicit
    all:new mode includes notices without tags, but discovery/delivery deduping
    still happens in matching_groups and find_new_notices.
    """
    branches = set(subscription.get("branch_ids") or [])
    topics = set(subscription.get("topic_ids") or [])
    if "all:new" in topics:
        return True
    notice_branches = set(metadata.get("branch_tags") or [])
    notice_topics = set(metadata.get("topic_tags") or [])
    by_id = load_catalog()["_topic_by_id"]
    for topic_id in topics:
        topic = by_id.get(topic_id)
        if not topic:
            continue
        scope = set(topic.get("branches") or [])
        eligible = branches & notice_branches
        if "*" not in scope:
            eligible &= scope
        if eligible and topic.get("match_topic", topic_id) in notice_topics:
            return True
    return False


def trim(value: Any, limit: int) -> str:
    value = " ".join(str(value or "").split())
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


def payload_notice_ids(notices: Sequence[Mapping[str, Any]]) -> List[str]:
    """Unique, deterministic notice IDs capped at ``MAX_PAYLOAD_NOTICE_IDS``.

    The library's ``?n=`` filter then shows the first 60 cards of a bigger
    batch; the notification title and payload ``count`` still report the true
    total. Capping here keeps every encrypted push under the RFC 8291
    4096-byte limit regardless of how many notices one day brings.
    """
    return list(dict.fromkeys(notice_id(item) for item in notices))[:MAX_PAYLOAD_NOTICE_IDS]


def notification_results_url(site_url: str, notices: Sequence[Mapping[str, Any]]) -> str:
    """Link every push to the library, narrowed to this non-personal batch.

    ``n`` contains compact opaque notice IDs only. It deliberately does not
    contain a subscription ID, branch choice, topic choice, or a PDF URL.
    Preserve any configured deployment path/query while replacing a stale
    notification filter if there is one.
    """
    parts = urlsplit(site_url)
    path = parts.path or "/"
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "n"]
    query.append(("n", ",".join(payload_notice_ids(notices))))
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query, safe=","), parts.fragment))


def batch_date_for(notices: Sequence[Mapping[str, Any]], default: str) -> str:
    # Normal scheduled runs have one HKT captured date.  Keep the fallback so
    # manual invocation remains deterministic.
    dates = [str(n.get("captured_date") or n.get("date") or "")[:10] for n in notices]
    dates = [d for d in dates if len(d) == 10]
    return dates[0] if dates and len(set(dates)) == 1 else default


def build_push_payload(
    notices: Sequence[Mapping[str, Any]],
    enrich: Mapping[str, Any],
    site_url: str,
    default_batch_date: str,
    *,
    silent: bool = False,
) -> Dict[str, Any]:
    """Build one native notification for one browser subscription."""
    if not notices:
        raise ValueError("cannot create a notification without notices")
    date = batch_date_for(notices, default_batch_date)
    library_url = notification_results_url(site_url, notices)
    if len(notices) == 1:
        item = notices[0]
        return {
            "title": f"🔔 {trim(item.get('title') or '新通告', 120)}",
            "body": "點擊查看通告",
            # Never deep-link a notification to a PDF: cards in the library
            # retain the browser-only bookmark action and show the exact batch.
            "url": library_url,
            # Keep the tag stable for this device/day. If another workflow run
            # finds an extra match, sw.js updates this notification with a
            # stable tag; dispatcher marks that second delivery silent.
            "tag": f"scout-circulars-personal-{date}",
            "count": 1,
            "batchDate": date,
            "noticeIds": payload_notice_ids(notices),
            "silent": bool(silent),
        }

    return {
        # `count`/title report the true total even when the linked library
        # filter (and `noticeIds` below) is capped at MAX_PAYLOAD_NOTICE_IDS.
        "title": f"🔔 你關注的項目有 {len(notices)} 項新通告",
        "body": "按此查看全部",
        "url": library_url,
        # One stable tag lets a later same-day update replace this notification
        # without asking the OS to play another sound.
        "tag": f"scout-circulars-personal-{date}",
        "count": len(notices),
        "batchDate": date,
        "noticeIds": payload_notice_ids(notices),
        "silent": bool(silent),
    }


class SupabaseClient:
    def __init__(self, url: str, service_key: str):
        self.url = url.rstrip("/")
        self.service_key = service_key

    def request(self, method: str, table: str, query: Optional[Mapping[str, Any]] = None, payload: Any = None, prefer: str = "") -> Any:
        url = f"{self.url}/rest/v1/{table}"
        if query:
            url += "?" + urlencode(query, doseq=True, safe="(),.*")
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, headers=headers, data=data, method=method.upper())
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read()
        except HTTPError as exc:
            raise StorageError(f"Supabase HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise StorageError("無法連接 Supabase") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def active_subscriptions(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self.request(
                "GET",
                "push_subscriptions",
                {
                    "select": "id,endpoint,p256dh,auth,branch_ids,topic_ids",
                    "enabled": "eq.true",
                    "order": "id.asc",
                    "limit": "1000",
                    "offset": str(offset),
                },
            )
            if not isinstance(page, list):
                raise StorageError("訂閱資料格式無效")
            valid = [dict(row) for row in page if isinstance(row, Mapping) and row.get("id")]
            rows.extend(valid)
            if len(page) < 1000:
                break
            offset += len(page)
        return rows

    def delivered_pairs(self, keys: Iterable[str]) -> Set[Tuple[str, str]]:
        values = list(dict.fromkeys(str(value) for value in keys if value))
        pairs: Set[Tuple[str, str]] = set()
        for start in range(0, len(values), 80):
            batch = values[start:start + 80]
            expression = "in.(" + ",".join(batch) + ")"
            rows = self.request(
                "GET",
                "push_deliveries",
                {"select": "subscription_id,notice_key", "notice_key": expression},
            )
            if not isinstance(rows, list):
                raise StorageError("發送紀錄格式無效")
            for row in rows:
                if isinstance(row, Mapping) and row.get("subscription_id") and row.get("notice_key"):
                    pairs.add((str(row["subscription_id"]), str(row["notice_key"])))
        return pairs

    def notified_subscription_ids_for_batch(self, batch_date: str) -> Set[str]:
        """Find devices already alerted in this HKT day.

        A later run still sends a replacement payload so its list is current,
        but marks it silent. This is stronger than relying on OS-specific
        `renotify: false` behaviour alone.
        """
        found: Set[str] = set()
        offset = 0
        while True:
            rows = self.request(
                "GET",
                "push_deliveries",
                {
                    "select": "subscription_id",
                    "batch_date": f"eq.{batch_date}",
                    "order": "id.asc",
                    "limit": "1000",
                    "offset": str(offset),
                },
            )
            if not isinstance(rows, list):
                raise StorageError("當日發送紀錄格式無效")
            found.update(str(row["subscription_id"]) for row in rows if isinstance(row, Mapping) and row.get("subscription_id"))
            if len(rows) < 1000:
                return found
            offset += len(rows)

    def record_deliveries(self, subscription_id: str, notices: Sequence[Mapping[str, Any]], batch_date: str) -> None:
        payload = [
            {"subscription_id": subscription_id, "notice_key": notice_key(item), "batch_date": batch_date}
            for item in notices
        ]
        if payload:
            self.request("POST", "push_deliveries", payload=payload, prefer="resolution=ignore-duplicates,return=minimal")

    def delete_subscription(self, subscription_id: str) -> None:
        self.request("DELETE", "push_subscriptions", {"id": f"eq.{subscription_id}"}, prefer="return=minimal")


def vapid_config(*, require_private_key: bool = True) -> Optional[Dict[str, str]]:
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not private_key and not url and not service_key:
        return None
    if not url or not service_key or (require_private_key and not private_key):
        raise NotificationError("Web Push secrets are incomplete")
    return {
        "private_key": private_key.replace("\\n", "\n"),
        "subject": os.environ.get("VAPID_SUBJECT", "https://scout-circulars.vercel.app").strip() or "https://scout-circulars.vercel.app",
        "url": url,
        "service_key": service_key,
    }


# Secrets/variables the send path needs. Names only — values are never logged.
REQUIRED_PUSH_ENV: Tuple[str, ...] = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "VAPID_PRIVATE_KEY")
OPTIONAL_PUSH_ENV: Tuple[str, ...] = ("VAPID_SUBJECT",)


def secrets_preflight() -> Dict[str, bool]:
    """Which push settings are present. Booleans only, so this is safe to log."""
    return {name: bool(os.environ.get(name, "").strip()) for name in REQUIRED_PUSH_ENV + OPTIONAL_PUSH_ENV}


def missing_required_push_env() -> List[str]:
    return [name for name in REQUIRED_PUSH_ENV if not os.environ.get(name, "").strip()]


def print_secrets_preflight() -> None:
    """Print the presence of each push setting so a misconfiguration is visible.

    2026-09-09: the step failed in ~2 s on two runs and the only surviving
    evidence was "Process completed with exit code 1", because job logs live on
    blob storage that is not always fetchable. Naming the missing setting (never
    its value) turns that into a one-line diagnosis.
    """
    state = secrets_preflight()
    print("🔐 推播設定檢查：" + "　".join(f"{name}={'✅' if ok else '❌缺少'}" for name, ok in state.items()))


def annotate_failure(message: str) -> None:
    """Emit a GitHub Actions error annotation carrying the real reason.

    Annotations are plain REST metadata readable from
    ``GET /repos/{o}/{r}/check-runs/{id}/annotations``, unlike the step log body
    which lives on blob storage. Escaping follows the workflow-command syntax.
    """
    text = " ".join(str(message).split())[:400]
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A")
    print(f"::error title=notify::{text}", flush=True)


def _push_status(error: Exception) -> Optional[int]:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def send_web_push(subscription: Mapping[str, Any], payload: Mapping[str, Any], config: Mapping[str, str]) -> None:
    try:
        from pywebpush import webpush
    except ImportError as exc:
        raise NotificationError("pywebpush is not installed; install requirements.txt") from exc
    info = {
        "endpoint": subscription["endpoint"],
        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
    }
    webpush(
        subscription_info=info,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        vapid_private_key=config["private_key"],
        vapid_claims={"sub": config["subject"]},
        ttl=PUSH_TTL_SECONDS,
        timeout=12,
    )


def send_group(
    subscription: Mapping[str, Any],
    delivery_notices: List[Dict[str, Any]],
    summary_notices: List[Dict[str, Any]],
    enrich: Mapping[str, Any],
    site_url: str,
    batch_date: str,
    config: Mapping[str, str],
    silent: bool = False,
) -> SendResult:
    subscription_id = str(subscription.get("id", ""))
    try:
        payload = build_push_payload(summary_notices, enrich, site_url, batch_date, silent=silent)
        send_web_push(subscription, payload, config)
        return SendResult(subscription_id, delivery_notices, "sent")
    except Exception as exc:  # pywebpush has its own exception type; avoid import at module load.
        status = _push_status(exc)
        if status in (404, 410):
            return SendResult(subscription_id, delivery_notices, "stale", str(status))
        return SendResult(subscription_id, delivery_notices, "failed", f"{type(exc).__name__}: {str(exc)[:120]}")


def push_failures_are_systemic(failed: int, attempted: int) -> bool:
    """Only a strict majority of failed sends blocks the pipeline.

    One bad endpoint (429/5xx/TLS from a single push service) must not stop
    the cache commit the way it did on 2026-09-09: the failed send simply is
    not recorded, so the same-day catch-up safety net retries it on the next
    run. An over-half failure rate instead points at a systemic cause such as
    an invalid VAPID key, where halting before the commit is still correct.
    """
    return attempted > 0 and failed * 2 > attempted


def matching_groups(
    subscriptions: Sequence[Mapping[str, Any]],
    newly_discovered: Sequence[Dict[str, Any]],
    daily_summary_pool: Sequence[Dict[str, Any]],
    enrich: Mapping[str, Any],
    delivered: Set[Tuple[str, str]],
) -> Dict[str, Tuple[Mapping[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """Return delivery candidates plus the complete same-day notification view.

    ``new_matches`` controls whether a push is sent. ``summary_matches`` also
    includes an earlier same-day match, so a later run replaces the existing
    summary instead of making its first item disappear from the notification.
    """
    all_for_metadata = list(daily_summary_pool) + list(newly_discovered)
    metadata = {notice_key(item): notice_metadata(item, enrich) for item in all_for_metadata}
    groups: Dict[str, Tuple[Mapping[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]] = {}
    for subscription in subscriptions:
        subscription_id = str(subscription.get("id", ""))
        if not subscription_id:
            continue
        new_matches = [
            item for item in newly_discovered
            if (subscription_id, notice_key(item)) not in delivered
            and subscription_matches(subscription, metadata[notice_key(item)])
        ]
        if not new_matches:
            continue
        summary_matches = [
            item for item in daily_summary_pool
            if subscription_matches(subscription, metadata[notice_key(item)])
        ]
        # Defensive fallback for a manually found historical notice whose
        # captured_date does not equal this HKT batch date.
        summary_keys = {notice_key(item) for item in summary_matches}
        summary_matches.extend(item for item in new_matches if notice_key(item) not in summary_keys)
        groups[subscription_id] = (subscription, new_matches, summary_matches)
    return groups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="發送個人化 Web Push（每訂閱者每批最多一則）")
    parser.add_argument("--baseline-ref", default="HEAD", help="更新前含 cache.json 的 git ref（預設 HEAD）")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", DEFAULT_SITE_URL), help="所有通知點擊後的正式圖書館網址（須與訂閱 origin 相同）")
    parser.add_argument("--batch-date", default="", help="覆蓋 HKT 批次日期 YYYY-MM-DD（測試用）")
    parser.add_argument("--workers", type=int, default=12, help="並行推送數量（1–24，預設 12）")
    parser.add_argument("--dry-run", action="store_true", help="只列出匹配數，不發送也不寫入發送紀錄")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not CACHE_PATH.exists():
        print("❌ 找不到 cache.json，略過推播")
        return 1
    baseline = load_baseline_cache(args.baseline_ref)
    if baseline is None:
        print(f"⚠️ 找不到 {args.baseline_ref}:cache.json；為避免把歷史通告全部推送，已安全略過。")
        return 0

    current = read_json(CACHE_PATH)
    enrich = read_json(ENRICH_PATH) if ENRICH_PATH.exists() else {}
    batch_date = args.batch_date or datetime.now(HKT).date().isoformat()
    try:
        datetime.strptime(batch_date, "%Y-%m-%d")
    except ValueError:
        print("❌ --batch-date 必須是 YYYY-MM-DD", file=sys.stderr)
        return 2

    notices = find_new_notices(current, baseline)
    # 同日補發安全網：本機後備可能喺呢次 checkout 之前已寫入今日通告，
    # 令上面嘅 HEAD diff 係空 —— 但從來未有人通知過佢哋。只納入 captured_date
    # 係今日嘅項目；下面每訂閱者嘅 delivered 紀錄仍然會擋走已發送嘅，唔會重複響。
    catchup = find_catchup_notices(current, notices, batch_date)
    if catchup:
        print(f"🔔 推播：發現 {len(catchup)} 則今日已入庫但未經此批次發現嘅通告，一併納入。")
    notices = notices + catchup
    if not notices:
        print("🔔 推播：今次沒有真正新增通告，0 次發送。")
        return 0
    print(f"🔔 推播：偵測到 {len(notices)} 則真正新增通告。")

    # A later same-day run may discover more notices after an earlier summary
    # has already been delivered. Include every matching notice captured today
    # in the replacement payload, while only recording / triggering delivery
    # for genuinely new matches below.
    summary_pool: List[Dict[str, Any]] = []
    summary_seen: Set[str] = set()
    newly_discovered_keys = {notice_key(item) for item in notices}
    for item in iter_notices(current) + notices:
        item_date = str(item.get("captured_date") or item.get("date") or "")[:10]
        key = notice_key(item)
        if key not in newly_discovered_keys and item_date != batch_date:
            continue
        if key not in summary_seen:
            summary_seen.add(key)
            summary_pool.append(item)

    print_secrets_preflight()
    try:
        config = vapid_config(require_private_key=not args.dry_run)
    except NotificationError as exc:
        missing = missing_required_push_env()
        detail = f"{exc}（缺少 repo secret：{', '.join(missing) or '未知，請對照上面一行'}）"
        print(f"❌ 推播設定錯誤：{detail}", file=sys.stderr)
        print("   一則通知都未發出；cache 仍會由下一個步驟提交（見 scrape.yml 嘅 steps.notify 條件），")
        print("   補好 secret 後同日補發仍然有效。")
        annotate_failure(f"推播設定錯誤：{detail}")
        return 1
    if config is None:
        print("ℹ️ Web Push 尚未設定 VAPID / Supabase secrets；已略過，不影響爬蟲。")
        return 0
    client = SupabaseClient(config["url"], config["service_key"])
    try:
        subscriptions = client.active_subscriptions()
        if not subscriptions:
            print("🔔 推播：目前沒有啟用中的匿名訂閱，0 次發送。")
            return 0
        delivered = client.delivered_pairs(notice_key(item) for item in notices)
        already_notified_today = client.notified_subscription_ids_for_batch(batch_date)
    except StorageError as exc:
        # Nothing has been sent yet, so no delivery record can be lost and a
        # rerun cannot double-push. The step still reports failure (a red run is
        # the only thing that gets noticed), but scrape.yml commits the cache
        # anyway — 2026-09-09 root cause B: a dispatch failure must never take
        # the day's cache down with it.
        print(f"❌ 推播資料庫錯誤：{exc}", file=sys.stderr)
        print("   讀取訂閱／發送紀錄失敗，一則通知都未發出；cache 仍會由下一個步驟提交。")
        annotate_failure(f"推播資料庫錯誤：{exc}")
        return 1

    groups = matching_groups(subscriptions, notices, summary_pool, enrich, delivered)
    matched_notices = sum(len(group[1]) for group in groups.values())
    silent_updates = sum(1 for subscription_id in groups if subscription_id in already_notified_today)
    print(f"🔔 推播：{len(subscriptions)} 個訂閱中，{len(groups)} 個有命中；合共 {matched_notices} 個新通告配對。")
    if silent_updates:
        print(f"   當中 {silent_updates} 則為同日靜音更新（取代既有彙總，不再響鈴）。")
    if not groups:
        return 0
    if args.dry_run:
        for subscription_id, (_subscription, new_matches, summary_matches) in groups.items():
            print(f"   [dry-run] 訂閱 {subscription_id[:8]}… ← 新增 {len(new_matches)} 項；通知會顯示當日合共 {len(summary_matches)} 項、只發 1 則")
        return 0

    workers = max(1, min(24, args.workers))
    results: List[SendResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                send_group,
                subscription,
                new_matches,
                summary_matches,
                enrich,
                args.site_url,
                batch_date,
                config,
                subscription_id in already_notified_today,
            ): subscription_id
            for subscription_id, (subscription, new_matches, summary_matches) in groups.items()
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    record_failures = 0
    send_failures = 0
    sent = stale = 0
    for result in results:
        if result.status == "sent":
            try:
                client.record_deliveries(result.subscription_id, result.notices, batch_date)
                sent += 1
            except StorageError as exc:
                # Still fatal before the cache commit, by design. A rerun may
                # deliver a duplicate only in this rare post-send recording
                # failure, preferable to silently losing every future
                # notification.
                print(f"❌ 無法寫入發送紀錄：{exc}", file=sys.stderr)
                record_failures += 1
        elif result.status == "stale":
            try:
                client.delete_subscription(result.subscription_id)
                stale += 1
            except StorageError as exc:
                print(f"❌ 無法清理失效訂閱：{exc}", file=sys.stderr)
                record_failures += 1
        else:
            # A single endpoint error (429/5xx/TLS, or one oversized payload)
            # warns but no longer fails the step: no delivery record is
            # written, so the same-day catch-up retries this subscriber on the
            # next run while the cache still commits normally.
            print(f"⚠️ 訂閱 {result.subscription_id[:8]}… 推播失敗：{result.error}", file=sys.stderr)
            send_failures += 1

    print(f"🔔 推播完成：送出 {sent} 則合併通知；移除失效訂閱 {stale}；推播失敗 {send_failures}。")
    if record_failures:
        print(f"❌ {record_failures} 項資料庫寫入失敗；為避免日後重複推送，已中止提交流程。", file=sys.stderr)
        annotate_failure(f"{record_failures} 項發送紀錄寫入失敗，已中止提交流程")
        return 1
    if push_failures_are_systemic(send_failures, len(results)):
        sample = next((str(result.error) for result in results if result.status == "failed"), "")
        message = f"{send_failures}/{len(results)} 個訂閱推播失敗：過半屬系統性錯誤（例如 VAPID 設定失效）"
        print(f"❌ {message}，已中止提交流程。首個錯誤：{sample}", file=sys.stderr)
        annotate_failure(f"{message}；首個錯誤：{sample}")
        return 1
    if send_failures:
        print(f"   {send_failures}/{len(results)} 個失敗屬個別 endpoint 錯誤（未過半）；未寫入發送紀錄，同日補發會重試，cache 照常提交。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
