#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_check_local_gain.py — 驗證本機補跑嘅「有冇增量」閘門
執行：python test_check_local_gain.py

覆蓋：來源隔離身份鍵、data 分組 vs notices 相容陣列、冇增量、有增量、
本機少咗嘢（只提示唔擋）、基準讀唔到（當有增量）、本機 cache 損毀（exit 2）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_local_gain import iter_notices, main, notice_key  # noqa: E402

fails: list[str] = []


def chk(cond, msg):
    if not cond:
        fails.append(msg)


def notice(title, url, source="Test區", captured="2026-09-14"):
    return {"title": title, "pdf_url": url, "source_site": source, "captured_date": captured}


def cache(items, last="2026-09-14 05:00:00"):
    grouped: dict[str, list] = {}
    for it in items:
        grouped.setdefault(it["source_site"], []).append({k: v for k, v in it.items() if k != "source_site"})
    return {"last_updated": last, "data": grouped}


def write(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


# ── 1. 身份鍵：同一 URL 唔同來源 = 兩則（來源隔離）────────────────
a = notice("甲", "https://x/a.pdf", "Test區")
b = notice("甲", "https://x/a.pdf", "九龍地域")
chk(notice_key(a) != notice_key(b), "同一 URL 但唔同來源必須係兩個關鍵")
chk(notice_key(a) == notice_key(notice("甲", "https://x/a.pdf", "Test區", "2026-01-01")),
    "標題／日期唔應該影響身份")

# ── 2. data 分組優先，唔好同 notices 相容陣列雙計 ────────────────
both = cache([a, b])
both["notices"] = [a, b, a]
chk(len(iter_notices(both)) == 2, f"應該只讀分組 data（2 則），實測 {len(iter_notices(both))}")
legacy = {"last_updated": "2026-09-14", "notices": [{"title": "t", "pdf_url": "https://x/1.pdf"}]}
chk(len(iter_notices(legacy)) == 1, "冇 data 時要回退去 notices 陣列")
chk(iter_notices({"data": {}}) == [], "空 data 唔應該回退去 notices")

with tempfile.TemporaryDirectory() as tmp:
    cwd = os.getcwd()
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_AUTHOR_DATE": "2026-09-14T00:00:00", "GIT_COMMITTER_DATE": "2026-09-14T00:00:00"}

    def run_git(*args):
        return subprocess.run(["git"] + list(args), cwd=repo, check=True,
                              capture_output=True, text=True, env=env)

    try:
        os.chdir(repo)
        run_git("init", "-q", "-b", "main")
        run_git("config", "user.email", "t@t")
        run_git("config", "user.name", "t")
        write("cache.json", cache([a]))          # 基準（＝ GitHub 嗰份）只有 a
        run_git("add", "-A")
        run_git("commit", "-qm", "baseline: only 甲")

        # ── 3. 有增量（本機多咗 b）→ exit 0 ────────────────────
        write("cache.json", cache([a, b]))
        rc = main(["x", "main", "--cache", "cache.json"])
        chk(rc == 0, f"本機多咗一則應該 exit 0（實測 {rc}）")

        # ── 4. 冇增量（內容一樣，就算 last_updated 唔同）→ exit 1 ─
        write("cache.json", cache([a], last="2026-09-14 05:00:00"))
        rc = main(["x", "main", "--cache", "cache.json"])
        chk(rc == 1, f"內容相同應該 exit 1（實測 {rc}）")

        # ── 5. 同時有新增有缺失 → 照樣 exit 0（只提示，唔擋）──────
        write("cache.json", cache([b]))
        rc = main(["x", "main", "--cache", "cache.json"])
        chk(rc == 0, f"有新增（就算同時有少）都要 exit 0（實測 {rc}）")

        # ── 6. 基準 ref 讀唔到 → 當新資料，exit 0 ────────────────
        write("cache.json", cache([a]))
        rc = main(["x", "main-nope", "--cache", "cache.json"])
        chk(rc == 0, f"基準冇 cache 應該當新資料（實測 {rc}）")

        # ── 7. 本機 cache 損毀 → exit 2（唔好推）────────────────
        with open("cache.json", "w", encoding="utf-8") as fh:
            fh.write('{"last_updated": "trunc')
        rc = main(["x", "main", "--cache", "cache.json"])
        chk(rc == 2, f"本機 cache 解析失敗應該 exit 2（實測 {rc}）")

    finally:
        os.chdir(cwd)

print("✅ test_check_local_gain.py：全部通過" if not fails else "❌ 失敗：")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)
