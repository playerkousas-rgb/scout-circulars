#!/usr/bin/env python3
"""
訂閱統計（只限管理員本機執行）

用 Supabase service_role key 讀取 push_subscriptions，輸出：
  - 總訂閱數／已啟用數／最近 30 日活躍數
  - 每個支部有幾多人訂閱
  - 每個訂閱項目（topic）有幾多人訂閱
  - 登記漏斗（push_funnel_daily，2026-10-22 起）：打開面板、按啟用、
    成功登記、只儲存篩選、iOS 未加入主畫面、權限被拒等匿名次數

只輸出匿名彙總數字，唔會印出 endpoint、金鑰或任何可識別個人的資料。

用法：
  export SUPABASE_URL=https://xxxx.supabase.co
  export SUPABASE_SERVICE_KEY=...
  python3 subscription_stats.py            # 文字表格
  python3 subscription_stats.py --json     # JSON 輸出
  python3 subscription_stats.py --out subscription_stats.json   # 寫檔（GitHub Actions 用，前端 stats.html 讀）

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
FUNNEL_WINDOW_DAYS = 14
FUNNEL_RETENTION_DAYS = 400

# 只係顯示用標籤；event 名稱由 api/push_common.py 的 FUNNEL_EVENTS 控制。
FUNNEL_LABELS = {
    "panel_open": "打開通知設定面板",
    "enable_click": "按「啟用通知」",
    "subscribed": "成功登記（瀏覽器確認）",
    "save_only": "只按「只儲存篩選」（未登記）",
    "permission_denied": "通知權限被拒／被封鎖",
    "ios_home_screen_required": "iPhone／iPad 未加入主畫面",
    "unsupported_browser": "瀏覽器或連線不支援",
    "config_unavailable": "讀取通知服務設定失敗",
    "subscribe_failed": "瀏覽器建立訂閱失敗",
    "sync_ok": "舊有訂閱更新成功",
    "sync_failed": "舊有訂閱更新失敗",
    "server_reject": "伺服器拒收（4xx）",
    "server_error": "伺服器錯誤（5xx）",
}


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


def fetch_funnel(base_url: str, key: str, days: int = FUNNEL_WINDOW_DAYS) -> list[dict]:
    """讀取近 N 日匿名漏斗計數（每日每事件一列彙總）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
    query = urlencode(
        {
            "select": "day,event,count",
            "day": f"gte.{since}",
            "order": "day.asc",
            "limit": 5000,
        }
    )
    req = Request(
        f"{base_url}/rest/v1/push_funnel_daily?{query}",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        # 未跑過 schema.sql 的舊環境：漏斗只是額外資訊，不要令統計失敗。
        print(f"（漏斗統計暫時無法讀取：HTTP {exc.code}）", file=sys.stderr)
        return []
    except (URLError, TimeoutError, OSError) as exc:
        print(f"（漏斗統計暫時無法讀取：{exc}）", file=sys.stderr)
        return []


def _prune_funnel(base_url: str, key: str, days: int = FUNNEL_RETENTION_DAYS) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    req = Request(
        f"{base_url}/rest/v1/push_funnel_daily?{urlencode({'day': f'lt.{cutoff}'})}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        method="DELETE",
    )
    try:
        with urlopen(req, timeout=15):
            return
    except (HTTPError, URLError, TimeoutError, OSError):
        return


def summarise_funnel(funnel_rows: list[dict], days: int = FUNNEL_WINDOW_DAYS) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    totals: Counter[str] = Counter()
    today_counts: Counter[str] = Counter()
    for row in funnel_rows:
        event = str(row.get("event") or "")
        if not event:
            continue
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        totals[event] += count
        if str(row.get("day") or "") == today:
            today_counts[event] += count
    views = totals.get("panel_open", 0)
    enrolled = totals.get("subscribed", 0)
    return {
        "window_days": days,
        "since": (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat(),
        "totals": dict(totals.most_common()),
        "today": dict(today_counts.most_common()),
        "conversion_pct": round(enrolled * 100 / views, 1) if views else 0,
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarise(rows: list[dict], funnel_rows: list[dict] | None = None) -> dict:
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

    branch_labels, topic_labels = _labels()
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "labels": {
            "branches": {b: branch_labels.get(b, b) for b in branch_counter},
            "topics": {t: topic_labels.get(t, t) for t in topic_counter},
        },
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
        "funnel": summarise_funnel(funnel_rows or []),
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

    funnel = stats.get("funnel") or {}
    if funnel.get("totals"):
        print(f"\n--- 登記漏斗（近 {funnel.get('window_days')} 日，匿名彙總）---")
        for event, n in funnel["totals"].items():
            print(f"{n:>5}  {FUNNEL_LABELS.get(event, event)}")
        print(f"\n打開面板 → 成功登記轉換率：{funnel.get('conversion_pct')}%")
        if funnel.get("today"):
            print("今日：" + "、".join(
                f"{FUNNEL_LABELS.get(event, event)} {n}" for event, n in funnel["today"].items()
            ))
    else:
        print("\n--- 登記漏斗 ---\n（未有數據；2026-10-22 起的新版本才開始記錄。）")


def main() -> None:
    _load_dotenv()
    base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base_url or not key:
        sys.exit("請先設定 SUPABASE_URL 同 SUPABASE_SERVICE_KEY（可放入 .env）。")
    rows = fetch_subscriptions(base_url, key)
    funnel_rows = fetch_funnel(base_url, key)
    stats = summarise(rows, funnel_rows)
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _prune_funnel(base_url, key)
        print(f"已寫入 {out}（訂閱 {stats['total']}，啟用 {stats['enabled']}）")
    elif "--json" in sys.argv:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_report(stats)


if __name__ == "__main__":
    main()
