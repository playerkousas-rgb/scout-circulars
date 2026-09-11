#!/usr/bin/env python3
"""
訂閱統計（只限管理員本機執行）

用 Supabase service_role key 讀取 push_subscriptions，輸出：
  - 總訂閱數／已啟用數／最近 30 日活躍數
  - 每個支部有幾多人訂閱
  - 每個訂閱項目（topic）有幾多人訂閱

只輸出匿名彙總數字，唔會印出 endpoint、金鑰或任何可識別個人的資料。

用法：
  export SUPABASE_URL=https://xxxx.supabase.co
  export SUPABASE_SERVICE_KEY=...
  python3 subscription_stats.py            # 文字表格
  python3 subscription_stats.py --json     # JSON 輸出

（或者放入 .env 之後 `set -a; source .env; set +a` 再執行。）
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
PAGE_SIZE = 1000


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _labels() -> tuple[dict[str, str], dict[str, str]]:
    try:
        catalog = json.loads((ROOT / "subscription_catalog.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    branches = {b["id"]: b.get("label", b["id"]) for b in catalog.get("branches", [])}
    topics = {}
    for t in catalog.get("topics", []):
        group = t.get("group", "")
        br = [b for b in t.get("branches", []) if b != "*"]
        prefix = f"{'/'.join(br)} · " if br else ""
        topics[t["id"]] = f"{prefix}{group} · {t.get('label', t['id'])}".strip(" ·")
    return branches, topics


def fetch_subscriptions(base_url: str, key: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        query = urlencode(
            {
                "select": "branch_ids,topic_ids,enabled,created_at,last_seen_at,catalog_version",
                "order": "created_at.asc",
                "limit": PAGE_SIZE,
                "offset": offset,
            }
        )
        req = Request(
            f"{base_url}/rest/v1/push_subscriptions?{query}",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"},
        )
        try:
            with urlopen(req, timeout=20) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            sys.exit(f"Supabase 回應 {exc.code}：{exc.read().decode('utf-8', 'replace')[:300]}")
        except (URLError, TimeoutError, OSError) as exc:
            sys.exit(f"無法連線 Supabase：{exc}")
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarise(rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    enabled = [r for r in rows if r.get("enabled", True)]
    active_30d = [r for r in enabled if (_parse_ts(r.get("last_seen_at")) or now) >= cutoff]
    new_30d = [r for r in rows if (_parse_ts(r.get("created_at")) or now) >= cutoff]

    branch_counter: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    version_counter: Counter[str] = Counter()
    for r in enabled:
        branch_counter.update(set(r.get("branch_ids") or []))
        topic_counter.update(set(r.get("topic_ids") or []))
        version_counter[r.get("catalog_version") or "(unknown)"] += 1

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "total": len(rows),
        "enabled": len(enabled),
        "disabled": len(rows) - len(enabled),
        "active_last_30d": len(active_30d),
        "new_last_30d": len(new_30d),
        "avg_topics_per_subscriber": round(
            sum(len(r.get("topic_ids") or []) for r in enabled) / len(enabled), 1
        ) if enabled else 0,
        "by_branch": dict(branch_counter.most_common()),
        "by_topic": dict(topic_counter.most_common()),
        "by_catalog_version": dict(version_counter.most_common()),
    }


def print_report(stats: dict) -> None:
    branch_labels, topic_labels = _labels()
    print("=== 通知訂閱統計 ===")
    print(f"產生時間：{stats['generated_at']}")
    print(f"總訂閱：{stats['total']}（啟用 {stats['enabled']}／停用 {stats['disabled']}）")
    print(f"最近 30 日活躍：{stats['active_last_30d']}　最近 30 日新增：{stats['new_last_30d']}")
    print(f"平均每人訂閱項目：{stats['avg_topics_per_subscriber']}")

    print("\n--- 按支部（一人可選多個）---")
    for bid, n in stats["by_branch"].items():
        print(f"{n:>5}  {branch_labels.get(bid, bid)}")

    print("\n--- 按訂閱項目（一人可選多個）---")
    for tid, n in stats["by_topic"].items():
        print(f"{n:>5}  {topic_labels.get(tid, tid)}")

    print("\n--- 字典版本 ---")
    for v, n in stats["by_catalog_version"].items():
        print(f"{n:>5}  {v}")


def main() -> None:
    _load_dotenv()
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base_url or not key:
        sys.exit("請先設定 SUPABASE_URL 同 SUPABASE_SERVICE_KEY（可放入 .env）。")
    rows = fetch_subscriptions(base_url, key)
    stats = summarise(rows)
    if "--json" in sys.argv:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_report(stats)


if __name__ == "__main__":
    main()
