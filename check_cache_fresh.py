#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exit 0 when the given cache.json is fresh (last_updated is today in HKT).

Used by run-local-scrape.bat so the home PC stays a true backup: if the
GitHub Action already refreshed the cache today, the PC skips instead of
racing it on the same files.  Any read/parse failure exits 1 (treated as
stale, so the backup still runs rather than silently skipping).
"""

from __future__ import annotations

import datetime
import json
import sys
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")


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
