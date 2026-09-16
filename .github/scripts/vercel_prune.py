#!/usr/bin/env python3
"""
vercel_prune.py — 刪走過舊嘅 Vercel deployments（釋放 Functions / Deployment Storage）
=====================================================================================
由 .github/workflows/vercel-prune.yml 調用；邏輯刻意放喺獨立檔案而唔係
workflow 嘅 run: | heredoc —— 因為 bash heredoc 結束符必須喺 column 0，
同 YAML block scalar 嘅縮排規則衝突（2026-09-16 就係咁搞到 workflow parse 失敗）。

環境變數（由 workflow 注入）：
  VERCEL_TOKEN       Vercel → Account Settings → Tokens（Scope 揀目標 project）
  VERCEL_PROJECT_ID  Vercel project → Settings → General → Project ID
  KEEP_DAYS          刪除幾日之前嘅 deployments（預設 14）
  KEEP_RECENT        無條件保留最近幾個 deployments（預設 5）

行為：
  - 未設 secrets → 印一句說話、exit 0（workflow 唔會紅）
  - 列舉 project 全部 deployments（分頁），由新到舊排序
  - 跳過：最近 KEEP_RECENT 個、未夠 KEEP_DAYS 日、DELETE 回報 HTTP 錯
    （最常見：alias 中嘅 production 刪唔到）
"""

import json
import os
import time
import urllib.error
import urllib.request


def main():
    tok = os.environ.get("VERCEL_TOKEN", "")
    pid = os.environ.get("VERCEL_PROJECT_ID", "")
    if not tok or not pid:
        print("未設定 VERCEL_TOKEN / VERCEL_PROJECT_ID secrets，跳過 prune。")
        print("設定方法見 .github/workflows/vercel-prune.yml 檔頭註解。")
        return

    keep_days = float(os.environ.get("KEEP_DAYS", "14"))
    keep_recent = int(os.environ.get("KEEP_RECENT", "5"))
    headers = {"Authorization": f"Bearer {tok}"}

    def api(url, method="GET"):
        req = urllib.request.Request(url, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    # 攞晒成個 project 嘅 deployment 列表（分頁）
    deps, until = [], None
    while True:
        url = f"https://api.vercel.com/v13/deployments?projectId={pid}&limit=50"
        if until:
            url += f"&until={until}"
        page = api(url)
        deps += page.get("deployments", [])
        until = (page.get("pagination") or {}).get("until")
        if not until or len(deps) > 800:
            break

    deps.sort(key=lambda d: d.get("created", 0), reverse=True)
    now = time.time() * 1000
    deleted = skipped = 0
    for i, dep in enumerate(deps):
        age_days = (now - dep.get("created", now)) / 86_400_000
        if i < keep_recent:
            continue                      # 無條件保留最近 N 個
        if age_days <= keep_days:
            continue                      # 未夠舊
        try:
            api(f"https://api.vercel.com/v13/deployments/{dep['uid']}", "DELETE")
            deleted += 1
            print(f"deleted {dep['uid']}  {dep.get('url')}  age={age_days:.0f}d")
        except urllib.error.HTTPError as e:
            # 常見：alias 中嘅 production 刪唔到 → 跳過
            skipped += 1
            print(f"skip {dep['uid']}  HTTP {e.code}")
    print(f"完成：刪咗 {deleted} 個舊 deployments（>{keep_days:.0f} 日），跳過 {skipped} 個。")


if __name__ == "__main__":
    main()
