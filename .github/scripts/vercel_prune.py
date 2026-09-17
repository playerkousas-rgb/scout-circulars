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
  MODE               "policy"（預設）＝只刪 >KEEP_DAYS 日嘅
                     "purge"         ＝一次過清走所有舊部署，只留最近
                                       KEEP_RECENT 個 ＋ alias 中嘅 production
                                       （用嚟即時釋放已經爆咗嘅存量；
                                        2026-09-17 Functions Storage 11.82GB
                                        就係要呢個 mode）
  DRY_RUN            "1"/"true" ＝只印會刪乜，唔真係 DELETE

行為：
  - 未設 secrets → 印 warning annotation ＋ 寫 job summary、exit 0（workflow 唔會紅，
    但喺 Actions 頁面一眼睇到「根本冇清到嘢」；舊版係完全無聲，害人以為清咗）
  - 列舉 project 全部 deployments（分頁），由新到舊排序
  - 跳過：最近 KEEP_RECENT 個、（policy mode 下）未夠 KEEP_DAYS 日、
    DELETE 回報 HTTP 錯（最常見：alias 中嘅 production 刪唔到）
  - 順帶印返 project 現時嘅 Deployment Retention Policy，方便對照
    （要改 policy 用 .github/workflows/vercel-retention.yml）
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.vercel.com"


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def warn(message: str) -> None:
    """GitHub Actions warning annotation — 喺 run 頁面頂當眼位置顯示。"""
    print(f"::warning::{message}")


def summary(lines: list) -> None:
    """Append to the GitHub Actions job summary (falls back to stdout locally)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    text = "\n".join(lines) + "\n"
    if not path:
        print(text)
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        print(text)


class Vercel:
    def __init__(self, token: str, team_id: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.team_id = team_id

    def call(self, path: str, method: str = "GET", params: dict | None = None,
             body: dict | None = None):
        query = dict(params or {})
        if self.team_id:
            query.setdefault("teamId", self.team_id)
        url = f"{API}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}


def list_deployments(client: Vercel, project_id: str) -> list:
    """攞晒成個 project 嘅 deployment 列表（v6 用 `until` 分頁），由新到舊。"""
    deployments, until = [], None
    while True:
        params = {"projectId": project_id, "limit": "50"}
        if until:
            params["until"] = until
        page = client.call("/v6/deployments", params=params)
        batch = page.get("deployments") or []
        deployments += batch
        until = (page.get("pagination") or {}).get("until")
        if not until or not batch or len(deployments) > 2000:
            break
    deployments.sort(key=lambda d: d.get("created", 0), reverse=True)
    return deployments


def report_retention(client: Vercel, project_id: str) -> None:
    """印返現時 retention policy（read-only）；失敗唔影響 prune。"""
    try:
        project = client.call(f"/v2/projects/{urllib.parse.quote(project_id)}")
    except Exception as exc:  # noqa: BLE001 -  purely informational
        print(f"（讀唔到 retention policy：{exc}）")
        return
    policy = project.get("deploymentExpiration") or {}
    if not policy:
        print("Deployment Retention Policy：未設（用咗 plan 預設，Hobby＝30 日）")
        return
    print(
        "Deployment Retention Policy（日）："
        f"preview={policy.get('expirationDays')} "
        f"production={policy.get('expirationDaysProduction')} "
        f"canceled={policy.get('expirationDaysCanceled')} "
        f"errored={policy.get('expirationDaysErrored')} "
        f"deploymentsToKeep={policy.get('deploymentsToKeep')}"
    )
    print("  → 要縮短：跑 .github/workflows/vercel-retention.yml")


def main() -> int:
    token = os.environ.get("VERCEL_TOKEN", "")
    project_id = os.environ.get("VERCEL_PROJECT_ID", "")
    team_id = os.environ.get("VERCEL_TEAM_ID", "") or os.environ.get("VERCEL_ORG_ID", "")
    mode = (os.environ.get("MODE") or "policy").strip().lower()
    dry_run = truthy(os.environ.get("DRY_RUN", ""))
    keep_days = float(os.environ.get("KEEP_DAYS", "14"))
    keep_recent = int(os.environ.get("KEEP_RECENT", "5"))

    if mode not in {"policy", "purge"}:
        print(f"::error::MODE 只可以係 policy 或 purge（收到 {mode!r}）")
        return 1

    if not token or not project_id:
        message = ("未設定 VERCEL_TOKEN / VERCEL_PROJECT_ID secrets —— "
                   "今次 prune 乜都冇做，舊 deployments 一個都冇刪到。")
        warn(message)
        summary([
            "## ⚠️ Vercel prune 已跳過（冇清到任何嘢）",
            "",
            message,
            "",
            "設定方法（repo → Settings → Secrets and variables → Actions）：",
            "",
            "| Secret | 喺邊度攞 |",
            "|---|---|",
            "| `VERCEL_TOKEN` | Vercel → Account Settings → Tokens → Create（Scope 揀呢個 project） |",
            "| `VERCEL_PROJECT_ID` | Vercel project → Settings → General → Project ID |",
            "",
            "未設嘅話 Functions Storage 會一直累積：呢個 repo 每日有 ~3 個 bot commit，",
            "每個都開新 deployment，而 Vercel 會保留每個 deployment 嘅 function bundle。",
        ])
        print("設定方法見 .github/workflows/vercel-prune.yml 檔頭註解。")
        return 0

    client = Vercel(token, team_id)
    report_retention(client, project_id)

    print(f"\n列舉 deployments（mode={mode}, keep_recent={keep_recent}, "
          f"keep_days={keep_days}, dry_run={dry_run}）…")
    try:
        deployments = list_deployments(client, project_id)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        print(f"::error::列舉 deployments 失敗 HTTP {exc.code}：{detail}")
        return 1

    total = len(deployments)
    print(f"共 {total} 個 deployments。\n")
    if total == 0:
        summary(["## Vercel prune", "", "project 入面冇 deployments。"])
        return 0

    now = time.time() * 1000
    deleted = skipped = planned = 0
    rows = []
    for index, deployment in enumerate(deployments):
        uid = deployment.get("uid") or deployment.get("id") or ""
        url = deployment.get("url") or ""
        created = deployment.get("created", now)
        age_days = (now - created) / 86_400_000
        state = deployment.get("readyState") or deployment.get("state") or ""
        target = (deployment.get("target") or "").lower()

        if index < keep_recent:
            reason = f"keep: 最近 {keep_recent} 個"
        elif mode == "purge":
            reason = ""
        elif age_days <= keep_days:
            reason = f"keep: 未夠 {keep_days:.0f} 日"
        else:
            reason = ""

        if reason:
            rows.append(("keep", uid, url, age_days, state, target, reason))
            continue

        if dry_run:
            planned += 1
            rows.append(("would-delete", uid, url, age_days, state, target, ""))
            print(f"[dry-run] would delete {uid}  {url}  age={age_days:.1f}d  {state}")
            continue

        try:
            client.call(f"/v13/deployments/{urllib.parse.quote(uid)}", method="DELETE")
        except urllib.error.HTTPError as exc:
            # 最常見：alias 中嘅 production 刪唔到（403 / 409）→ 跳過，唔算失敗
            skipped += 1
            rows.append(("skip", uid, url, age_days, state, target, f"HTTP {exc.code}"))
            print(f"skip {uid}  HTTP {exc.code}  {url}")
            continue
        deleted += 1
        rows.append(("deleted", uid, url, age_days, state, target, ""))
        print(f"deleted {uid}  {url}  age={age_days:.1f}d")

    verb = "會刪" if dry_run else "刪咗"
    count = planned if dry_run else deleted
    headline = (f"完成（DRY RUN）：{verb} {count} 個 deployments，"
                f"保留 {total - count - skipped} 個，跳過 {skipped} 個。")
    if mode == "purge":
        headline = (f"完成（PURGE{'，DRY RUN' if dry_run else ''}）：{verb} {count} 個 deployments"
                    f"（只留最近 {keep_recent} 個 ＋ 刪唔到嘅 aliased production），"
                    f"跳過 {skipped} 個。")
    print("\n" + headline)

    lines = [
        f"## Vercel prune — mode `{mode}`{', DRY RUN' if dry_run else ''}",
        "",
        headline,
        "",
        f"共掃描 {total} 個 deployments：",
        "",
        "| 動作 | Deployment | 年齡 | 狀態 | Target |",
        "|---|---|---|---|---|",
    ]
    for action, uid, url, age_days, state, target, reason in rows[:60]:
        label = {
            "deleted": "🗑️ deleted",
            "would-delete": "🔎 would delete",
            "skip": f"⏭️ skip（{reason}）",
            "keep": f"✅ keep（{reason}）",
        }.get(action, action)
        shown = f"`{url}`" if url else f"`{uid[:12]}`"
        lines.append(f"| {label} | {shown} | {age_days:.1f}d | {state} | {target or '-'} |")
    if len(rows) > 60:
        lines.append(f"| … | 其餘 {len(rows) - 60} 個 | | | |")
    if dry_run:
        lines += ["", "> Dry run：冇真係刪任何嘢。確認過上面列表之後用 `dry_run=false` 再跑一次。"]
    summary(lines)

    if dry_run and planned == 0:
        warn("Dry run 結果係「冇嘢可刪」。如果用量仲係爆，檢查 KEEP_RECENT / KEEP_DAYS，"
             "或者用 mode=purge。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
