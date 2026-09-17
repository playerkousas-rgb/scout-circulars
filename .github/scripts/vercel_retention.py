#!/usr/bin/env python3
"""
vercel_retention.py — 設定／檢查 Vercel project 嘅 Deployment Retention Policy
==============================================================================
由 .github/workflows/vercel-retention.yml 調用。

點解要有呢個 script
------------------
單靠「以後嘅 deployment 變細」**唔會**釋放已經食咗嘅 Functions Storage：
舊部署仲喺度，每個都挾住一個 ~170MB 嘅 function bundle。要清走存量只有兩條路：
  (a) 逐個 DELETE deployment —— .github/scripts/vercel_prune.py（mode=purge）
  (b) 縮短 retention policy，等 Vercel 自己背景清 —— 就係呢個 script
兩者並用：(a) 即刻見效，(b) 防止日後再累積。

Hobby 預設 retention 係 **30 日**（Canceled / Errored / Pre-Production /
Production 全部 30 日）。呢個 repo 每日有 ~3 個 bot commit（`[skip ci]` 只
skip GitHub Actions，skip 唔到 Vercel），30 日 ≈ 90 個 deployment 全部留住。

⚠️ API 陷阱（實測過，唔好行返轉頭）
-----------------------------------
通用嘅 `PATCH /v9/projects/{idOrName}` **寫唔到** retention：body 放
`deploymentExpiration` 會回 `400 Invalid request: should NOT have additional
property "deploymentExpiration"` —— 佢喺 Project resource 上係 read-only。
真正寫到嘅係專用 sub-resource（由官方 terraform-provider-vercel 嘅
client/project_deployment_retention.go 確認）：

    PATCH /v9/projects/{projectId}/deployment-expiration?teamId={teamId}
    body: {"expiration": "7d",            # ← preview／pre-production
           "expirationProduction": "30d",
           "expirationCanceled": "1d",
           "expirationErrored": "7d"}

留意欄位名係 `expiration`（唔係 `expirationDays`），值係**字串 duration**
（`1d` / `1w` / `1m` / `2m` / `3m` / `6m` / `1y` / `unlimited`），
同 GET 返嚟嘅 `deploymentExpiration`（用日數 integer）唔同一套。

環境變數（由 workflow 注入）：
  VERCEL_TOKEN        Vercel → Account Settings → Tokens
  VERCEL_PROJECT_ID   Vercel project → Settings → General → Project ID
  VERCEL_TEAM_ID      選配（個人帳戶唔使；team 帳戶要）
  EXPIRATION_PREVIEW / EXPIRATION_PRODUCTION /
  EXPIRATION_CANCELED / EXPIRATION_ERRORED   字串 duration
  DRY_RUN             "1"/"true" ＝只印現況同將要設嘅值，唔 PATCH
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.vercel.com"

VALID = {"1d", "1w", "1m", "2m", "3m", "6m", "1y", "unlimited"}

# retention 由長到短，用嚟把 "7d" 之類轉返日數印俾人睇
DAYS = {"1d": 1, "1w": 7, "1m": 30, "2m": 60, "3m": 90, "6m": 180, "1y": 365,
        "unlimited": 36500}


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def warn(message: str) -> None:
    print(f"::warning::{message}")


def summary(lines: list) -> None:
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


def format_days(value) -> str:
    """GET 返嚟嘅 deploymentExpiration 用日數；轉返人睇得明嘅 duration。"""
    if value is None:
        return "（未設）"
    try:
        days = int(value)
    except (TypeError, ValueError):
        return str(value)
    for label, number in DAYS.items():
        if number == days:
            return f"{label}（{days} 日）"
    return f"{days} 日"


def main() -> int:
    token = os.environ.get("VERCEL_TOKEN", "")
    project_id = os.environ.get("VERCEL_PROJECT_ID", "")
    team_id = os.environ.get("VERCEL_TEAM_ID", "") or os.environ.get("VERCEL_ORG_ID", "")
    dry_run = truthy(os.environ.get("DRY_RUN", ""))

    wanted = {
        "expiration": os.environ.get("EXPIRATION_PREVIEW", "1w"),
        "expirationProduction": os.environ.get("EXPIRATION_PRODUCTION", "1m"),
        "expirationCanceled": os.environ.get("EXPIRATION_CANCELED", "1d"),
        "expirationErrored": os.environ.get("EXPIRATION_ERRORED", "1w"),
    }
    invalid = {k: v for k, v in wanted.items() if v not in VALID}
    if invalid:
        print(f"::error::retention 值無效：{invalid}。只可以用 {sorted(VALID)}")
        return 1

    if not token or not project_id:
        message = ("未設定 VERCEL_TOKEN / VERCEL_PROJECT_ID secrets —— "
                   "retention policy 冇改到，仍然係 plan 預設（Hobby＝30 日）。")
        warn(message)
        summary([
            "## ⚠️ Vercel retention policy 未改到（冇設 secrets）",
            "",
            message,
            "",
            "| Secret | 喺邊度攞 |",
            "|---|---|",
            "| `VERCEL_TOKEN` | Vercel → Account Settings → Tokens → Create（Scope 揀呢個 project） |",
            "| `VERCEL_PROJECT_ID` | Vercel project → Settings → General → Project ID |",
            "",
            "或者手動改：Vercel project → **Settings → Security → "
            "Deployment Retention Policy**。",
        ])
        return 0

    client = Vercel(token, team_id)
    quoted = urllib.parse.quote(project_id)

    # ── 1. 讀返現況 ──
    try:
        project = client.call(f"/v2/projects/{quoted}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        print(f"::error::讀 project 失敗 HTTP {exc.code}：{detail}")
        print("  → 檢查 VERCEL_PROJECT_ID 同 VERCEL_TOKEN 嘅 scope。")
        return 1

    before = project.get("deploymentExpiration") or {}
    before_rows = [
        ("Pre-Production（preview）", before.get("expirationDays")),
        ("Production", before.get("expirationDaysProduction")),
        ("Canceled", before.get("expirationDaysCanceled")),
        ("Errored", before.get("expirationDaysErrored")),
    ]
    print("現時 Deployment Retention Policy：")
    for label, value in before_rows:
        print(f"  {label}: {format_days(value)}")
    if not before:
        print("  （project 未設自訂 policy → 用緊 plan 預設）")

    label_map = {
        "expiration": "Pre-Production（preview）",
        "expirationProduction": "Production",
        "expirationCanceled": "Canceled",
        "expirationErrored": "Errored",
    }
    print("\n將要設為：")
    for key, value in wanted.items():
        print(f"  {label_map[key]}: {value}（{DAYS[value]} 日）")

    if dry_run:
        print("\n[dry-run] 冇 PATCH 任何嘢。")
        summary([
            "## Vercel retention policy — DRY RUN",
            "",
            "| 狀態 | 現時 | 將會設為 |",
            "|---|---|---|",
            *[f"| {label_map[k]} | {format_days(before.get(_before_key(k)))} | `{v}` |"
              for k, v in wanted.items()],
            "",
            "> 冇真係改。確認過之後用 `dry_run=false` 再跑一次。",
        ])
        return 0

    # ── 2. PATCH 專用 sub-resource ──
    try:
        client.call(f"/v9/projects/{quoted}/deployment-expiration",
                    method="PATCH", body=wanted)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        print(f"::error::PATCH deployment-expiration 失敗 HTTP {exc.code}：{detail}")
        if exc.code == 400 and "additional property" in detail:
            print("  → 呢個 project 可能要 teamId；設 VERCEL_TEAM_ID / VERCEL_ORG_ID 再試。")
        print("  → 後備方法：Vercel project → Settings → Security → "
              "Deployment Retention Policy 手動設。")
        return 1

    # ── 3. 讀返嚟驗證（唔好淨係信 200）──
    try:
        after = (client.call(f"/v2/projects/{quoted}").get("deploymentExpiration") or {})
    except Exception:  # noqa: BLE001 - 驗證失敗唔應該令成個 step 紅
        after = {}

    rows, mismatch = [], []
    for key, value in wanted.items():
        label = label_map[key]
        got = after.get(_before_key(key))
        rows.append((label, format_days(before.get(_before_key(key))), value,
                     format_days(got)))
        if got is not None and int(got) != DAYS[value]:
            mismatch.append(f"{label}: 想要 {value}（{DAYS[value]} 日），實得 {got} 日")

    print("\n結果：")
    for label, was, want, got in rows:
        print(f"  {label}: {was} → {want}（API 現值：{got}）")

    summary([
        "## Vercel retention policy 已更新",
        "",
        "| 狀態 | 之前 | 設為 | API 現值 |",
        "|---|---|---|---|",
        *[f"| {label} | {was} | `{want}` | {got} |" for label, was, want, got in rows],
        "",
        "✅ 生效。Vercel 背景 job 通常喺 **48 小時內**開始刪過期部署。"
        if not mismatch else
        "⚠️ 有欄位同要求唔符：" + "；".join(mismatch),
        "",
        "**注意**：retention 有例外，以下部署唔會被刪 ——",
        "- 最近 3 個 deployment（Hobby）",
        "- 最近 3 個 state=Ready 嘅 production deployment（Hobby）",
        "- 仲掛住 production alias 嘅 deployment",
        "- 仲有開住嘅 branch／PR 嘅最新 preview deployment",
        "",
        "所以要**即刻**釋放存量，仲要跑一次 `Vercel Deployment Prune`（mode=purge）。",
    ])

    if mismatch:
        warn("；".join(mismatch))
    return 0


def _before_key(want_key: str) -> str:
    """PATCH body 欄位名 → GET response 欄位名（兩套唔同）。"""
    return {
        "expiration": "expirationDays",
        "expirationProduction": "expirationDaysProduction",
        "expirationCanceled": "expirationDaysCanceled",
        "expirationErrored": "expirationDaysErrored",
    }[want_key]


if __name__ == "__main__":
    sys.exit(main())
