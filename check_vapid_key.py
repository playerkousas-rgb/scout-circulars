#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check a VAPID private key WITHOUT ever printing it.

2026-09-09 事故：GitHub Actions 嘅 ``VAPID_PRIVATE_KEY`` 讀唔到，三個訂閱全部
``ValueError: Could not deserialize key data``。呢個腳本畀你喺本機核對手上嘅
PEM 係咪真係一把可用嘅 private key，以及佢推算出嘅公鑰係咪同網站
``/api/push_config`` 嗰把一樣 —— 全程只印公鑰同長度，**絕不印私鑰內容**，
所以可以放心喺 terminal 跑，唔使將 secret 貼去任何地方。

用法（喺 repo 資料夾）：
    python check_vapid_key.py vapid_private.pem
    python check_vapid_key.py            # 由 stdin 貼入，貼完按 Ctrl-Z / Ctrl-D
    python check_vapid_key.py key.pem --expect BBwm73x0qdTk03Bi_...

退出碼：0 = 私鑰有效（有 --expect 時還要公鑰吻合）；1 = 無效／唔吻合。
"""

from __future__ import annotations

import argparse
import re
import sys

from notify import (
    VAPID_PRIVATE_DER_BYTES,
    diagnose_vapid_pem,
    normalize_vapid_pem,
    vapid_public_key_from_pem,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", help="PEM 檔案；省略就由 stdin 讀")
    parser.add_argument("--expect", default="", help="網站 /api/push_config 嘅 vapidPublicKey，用嚟對照")
    args = parser.parse_args(argv[1:])

    if args.path:
        with open(args.path, encoding="utf-8") as handle:
            raw = handle.read()
        print(f"讀自檔案：{args.path}")
    else:
        print("請貼入 PEM（之後按 Ctrl-D / Windows 按 Ctrl-Z 再 Enter）：", flush=True)
        raw = sys.stdin.read()

    if not raw.strip():
        print("❌ 冇讀到任何內容")
        return 1

    pem = normalize_vapid_pem(raw)
    match = re.search(r"-----BEGIN ([A-Z ]+)-----(.*?)-----END", pem, re.DOTALL)
    label = match.group(1).strip() if match else "(無 header)"
    body = re.sub(r"\s+", "", match.group(2)) if match else ""

    # 只報告形狀，唔報告內容
    print(f"header label      : {label}")
    print(f"base64 body       : {len(body)} 字元（唔顯示內容）")
    print(f"原始輸入有幾多行   : {len(raw.strip().splitlines())}")
    print(f"原本有無 literal \\n : {'有（已自動還原）' if chr(92) + 'n' in raw else '冇'}")

    problem = diagnose_vapid_pem(pem)
    if problem:
        print(f"❌ {problem}")
        return 1
    print(f"✅ 可以讀成 private key（DER {VAPID_PRIVATE_DER_BYTES} bytes 格式正常）")

    public_key = vapid_public_key_from_pem(pem)
    print(f"🔑 推算出嘅公鑰    : {public_key}")

    if not args.expect:
        print("   （未指定 --expect；請自己同網站 /api/push_config 嘅 vapidPublicKey 對照）")
        return 0

    expected = args.expect.strip()
    if public_key == expected:
        print("✅ 公鑰同 --expect 一樣：呢把私鑰配呢個網站")
        return 0
    print(f"❌ 公鑰唔吻合。--expect 係：{expected}")
    print("   即係呢把私鑰唔係網站用緊嗰把 —— 推送會全部失敗。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
