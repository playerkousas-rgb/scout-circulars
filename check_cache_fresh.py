#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exit 0 when the given cache.json is fresh (last_updated is today in HKT).

由 2026-09-14 起，呢個判斷**唔再**用作「GitHub 今日已更新 → 本機跳過」——本機現
在每次都重新檢查全網，推唔推由 `check_local_gain.py`（有冇增量）決定。呢度淨係
剩低一個用途：判「上次 run 留低嘅未提交結果係咪今日嘅完整產出」（完整先值得補
commit；過期／損毀就還原重跑）。任何讀取／解析失敗都 exit 1（當成過期 → 寧願重跑）。
"""

from __future__ import annotations

import datetime
import json
import sys

try:  # Windows 冇裝 tzdata 又無法定位 IANA 資料庫時會擲錯；本機本身係 HKT，用本機時區就得
    from zoneinfo import ZoneInfo

    HKT = ZoneInfo("Asia/Hong_Kong")
except Exception:  # noqa: BLE001
    HKT = datetime.datetime.now().astimezone().tzinfo


def is_fresh(data: object, today: str) -> bool:
    if not isinstance(data, dict):
        return False
    return str(data.get("last_updated", ""))[:10] == today


def main(argv: list[str]) -> int:
    try:
        if len(argv) > 1 and argv[1] == "--stdin":
            raw = sys.stdin.buffer.read().decode("utf-8")
            data = json.loads(raw)
        else:
            path = argv[1] if len(argv) > 1 else "cache.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        today = datetime.datetime.now(HKT).strftime("%Y-%m-%d")
        fresh = is_fresh(data, today)
        print(f"cache last_updated={data.get('last_updated', '')!r} today={today} fresh={fresh}")
        return 0 if fresh else 1
    except Exception as exc:  # noqa: BLE001 - any failure means "stale, run backup"
        print(f"freshness check failed ({exc}); treating as stale")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
