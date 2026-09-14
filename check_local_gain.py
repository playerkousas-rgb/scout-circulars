#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本機補跑嘅「有冇增量」閘門（2026-09-14 加）。

背景：`run-local-scrape.bat` 之前係「GitHub Action 今日已跑過（cache 嘅
`last_updated` 係今日）→ 本機直接跳過」。但本機嘅定位係**後備補底**：佢應該自己
重新檢查一次全網來源，真係搵到嘢先當數。只係「睇吓 GitHub 有冇今日份」並唔係
補底 —— Action 成功但漏咗某個來源嘅時候，本機就永遠唔會發現。

呢個腳本將判斷由「時間」改成「內容」：

    python check_local_gain.py [baseline-ref] [--cache cache.json]

  * exit 0 → 本機 cache 有 baseline（預設 `origin/main`）冇嘅通告：值得 commit + push
  * exit 1 → 冇增量：本機同 Action 產出等價，唔使製造 commit，亦唔使打 rebase 仗
  * exit 2 → 本機 cache 讀取／解析失敗：唔好 push（宁可留返俾下一次）

通告身份鍵同 `notify.py` 完全一致（來源名 + sanitize 後嘅網址），所以「本機搵到
但 Action 未搵到」呢啲項目，正正就係 06:00 notify 嗰轉靠 `find_catchup_notices()`
補發嘅那一類 —— 本機推咗出去唔會令通知靜默流失。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Mapping


def notice_url(item: Mapping[str, Any]) -> str:
    return str(item.get("pdf_url") or item.get("url") or "").strip()


def notice_source(item: Mapping[str, Any]) -> str:
    return str(item.get("source_site") or "").strip()


def notice_key(item: Mapping[str, Any]) -> str:
    """同 notify.py：來源隔離嘅 (source_site, url) 身份。"""
    value = f"{notice_source(item)}\x1f{notice_url(item)}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def iter_notices(cache: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """先讀分組 `data`；冇先回退去相容性嘅 `notices` 陣列（同 notify.py 一樣）。"""
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


def keys_and_items(cache: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {notice_key(item): item for item in iter_notices(cache)}


def read_json(path: str) -> Mapping[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_from_git(ref: str, path: str = "cache.json") -> Mapping[str, Any]:
    out = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip() or f"git show {ref}:{path} 失敗")
    return json.loads(out.stdout.decode("utf-8"))


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="本機補跑：有冇 GitHub 冇嘅通告？")
    parser.add_argument("baseline", nargs="?", default="origin/main", help="基準 git ref（預設 origin/main）")
    parser.add_argument("--cache", default="cache.json", help="本機 cache 路徑")
    parser.add_argument("--list", type=int, default=8, help="列出多少則新增通告（預設 8）")
    args = parser.parse_args(argv[1:])

    try:
        local = read_json(args.cache)
    except Exception as exc:  # noqa: BLE001 - 讀唔到就唔好推
        print(f"⚠️ 讀取本機 {args.cache} 失敗（{exc}）；本次唔好 push。")
        return 2

    try:
        baseline = read_from_git(args.baseline)
    except Exception as exc:  # noqa: BLE001 - 基準冇（例如首次）→ 當有增量
        print(f"⚠️ 讀取基準 {args.baseline}:cache.json 失敗（{exc}）；當做一次新資料處理。")
        return 0

    local_map = keys_and_items(local)
    base_map = keys_and_items(baseline)
    new_keys = [k for k in local_map if k not in base_map]
    gone_keys = [k for k in base_map if k not in local_map]

    print(
        f"本機 {len(local_map)} 則｜{args.baseline} {len(base_map)} 則｜"
        f"本機多 {len(new_keys)} 則｜本機冇咗 {len(gone_keys)} 則"
    )
    print(f"（last_updated：本機 {local.get('last_updated', '?')}／基準 {baseline.get('last_updated', '?')}）")

    if gone_keys:
        by_source: Dict[str, int] = {}
        for key in gone_keys:
            src = notice_source(base_map[key]) or "(無來源名)"
            by_source[src] = by_source.get(src, 0) + 1
        detail = "、".join(f"{s}×{n}" for s, n in sorted(by_source.items(), key=lambda kv: -kv[1])[:6])
        print(f"ℹ️ 基準有、本機冇嘅通告：{detail}")
        print("   （如果唔係你特意移除來源，呢個數字應該係 0；而家只提示，唔擋 push。）")

    if not new_keys:
        print("✅ 本機冇 GitHub 冇嘅通告：唔使 commit（兩邊等價）。")
        return 1

    print(f"🎯 本機搵到 {len(new_keys)} 則 GitHub 未有嘅通告：")
    for key in new_keys[: max(0, args.list)]:
        item = local_map[key]
        title = str(item.get("title") or "(冇標題)").strip().replace("\n", " ")
        print(f"   - [{notice_source(item)}] {title[:60]}｜{notice_url(item)[:70]}")
    if len(new_keys) > args.list:
        print(f"   …另加 {len(new_keys) - args.list} 則")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
