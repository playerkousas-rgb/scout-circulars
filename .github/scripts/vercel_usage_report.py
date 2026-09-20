#!/usr/bin/env python3
"""
vercel_usage_report.py — 唯讀 Vercel 用量報告（唔刪任何嘢）
==========================================================
由 .github/workflows/vercel-usage-report.yml 調用。背景見
vercel-prune.yml 檔頭：2026-09-16/17 Functions Storage 兩度爆額
（10.49GB → 11.82GB / Hobby 上限 10GB），病源係舊 deployment 挾住
巨型 function bundle（playwright 137MB / PyMuPDF ~110MB）。

呢個腳本答一條問題：**而家仲有冇繼續漲大？** 做法（全部 GET，零寫入）：

  1. GET /v2/projects/{id}          → 讀現時 Deployment Retention Policy
  2. GET /v6/deployments（分頁）     → 列出 project 全部 retained deployments
       - 以 2026-09-17（bundle 瘦身完成）做分界：
         * pre-fix 仍 retained 嘅 = 可能仲揹住 100–250MB 舊 bundle
         * post-fix 嘅 = 每個約 1.2MB
       - 24 小時內新增 deployment 數 → 估算增長速度
  3. GET /v13/deployments/{uid}     → 只對最新 3 個做試探，搵 size 相關欄位
     （Vercel 冇公開 per-deployment bundle size；搵到就印，搵唔到當冇）
  4. GET /v1/billing/charges        → 設咗 VERCEL_TEAM_ID 先試；
     Hobby/未設計會 4xx，靜靜雞跳過，唔算失敗

輸出：stdout（Action log）＋ GITHUB_STEP_SUMMARY（markdown 表）＋
一條 ::notice:: annotation（等 gh api 讀得到重點，log 抓唔到都有救）。
未設 VERCEL_TOKEN / VERCEL_PROJECT_ID → warning ＋ exit 0（同 prune 一致）。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.vercel.com"
# 2026-09-17：requirements.txt 清空 + .vercelignore/excludeFiles 完成，
# 之後嘅 deployment bundle 應該係 ~1.2MB 級數。
BUNDLE_FIX_EPOCH_MS = 1789646400000  # 2026-09-17 12:00:00 UTC（約數，用嚟分 bucket）
POST_FIX_BUNDLE_MB = 1.2             # .vercelignore 後嘅上載體積（README 數字）
PRE_FIX_BUNDLE_MB_RANGE = (100, 250)  # playwright 137MB / PyMuPDF 110MB 年代嘅每部署體積


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def warn(message: str) -> None:
    print(f"::warning::{message}")


def notice(message: str) -> None:
    print(f"::notice::{message}")


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


def list_deployments(client: Vercel, project_id: str) -> list:
    """同 vercel_prune.py 一樣：v6 分頁列晒，由新到舊。"""
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


def find_size_hints(payload, depth=0, out=None, path=""):
    """喺任意 JSON 度搵名含 size 嘅欄位（診斷用；Vercel 冇公開 size 欄位）。"""
    if out is None:
        out = []
    if depth > 4 or len(out) > 12:
        return out
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_path = f"{path}.{key}" if path else key
            if "size" in key.lower() and isinstance(value, (int, float)):
                out.append((key_path, value))
            find_size_hints(value, depth + 1, out, key_path)
    elif isinstance(payload, list) and payload:
        find_size_hints(payload[0], depth + 1, out, f"{path}[0]")
    return out


def main() -> int:
    token = os.environ.get("VERCEL_TOKEN", "")
    project_id = os.environ.get("VERCEL_PROJECT_ID", "")
    team_id = os.environ.get("VERCEL_TEAM_ID", "") or os.environ.get("VERCEL_ORG_ID", "")

    if not token or not project_id:
        message = ("未設定 VERCEL_TOKEN / VERCEL_PROJECT_ID secrets —— "
                   "usage report 乇都查唔到。")
        warn(message)
        summary(["## ⚠️ Vercel usage report 已跳過", "", message])
        return 0

    client = Vercel(token, team_id)
    now = time.time() * 1000
    report: list = ["## Vercel 用量報告（唯讀檢查，唔刪任何部署）", ""]

    # ── 1. Retention policy ────────────────────────────────
    retention_text = "讀唔到"
    try:
        project = client.call(f"/v2/projects/{urllib.parse.quote(project_id)}")
        policy = project.get("deploymentExpiration") or {}
        retention_text = (
            f"preview={policy.get('expirationDays', '(預設30)')}日 / "
            f"production={policy.get('expirationDaysProduction', '(預設30)')}日"
        ) if policy else "未設定（用 plan 預設：Hobby 30 日）"
    except Exception as exc:  # noqa: BLE001 — 純資訊性
        retention_text = f"讀唔到（{exc}）"

    # ── 2. Deployment 清單 ─────────────────────────────────
    try:
        deployments = list_deployments(client, project_id)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        print(f"::error::列舉 deployments 失敗 HTTP {exc.code}：{detail}")
        return 1

    total = len(deployments)
    pre_fix = [d for d in deployments if (d.get("created") or 0) < BUNDLE_FIX_EPOCH_MS]
    post_fix = [d for d in deployments if (d.get("created") or 0) >= BUNDLE_FIX_EPOCH_MS]
    last24h = [d for d in deployments if (now - (d.get("created") or 0)) <= 86_400_000]
    production = [d for d in deployments if (d.get("target") or "").lower() == "production"
                  and d.get("readyState") == "READY"]

    est_low = len(pre_fix) * PRE_FIX_BUNDLE_MB_RANGE[0] + len(post_fix) * POST_FIX_BUNDLE_MB
    est_high = len(pre_fix) * PRE_FIX_BUNDLE_MB_RANGE[1] + len(post_fix) * POST_FIX_BUNDLE_MB

    newest = deployments[0] if deployments else {}
    newest_age_h = (now - (newest.get("created") or now)) / 3_600_000

    verdict_lines = []
    if pre_fix:
        ages = ", ".join(
            f"{(now - d.get('created', now)) / 86_400_000:.0f}日" for d in pre_fix[:5])
        verdict_lines.append(
            f"⛔ 仲有 {len(pre_fix)} 個瘦身前 deployment 未清（可能每個揹住 "
            f"{PRE_FIX_BUNDLE_MB_RANGE[0]}–{PRE_FIX_BUNDLE_MB_RANGE[1]}MB 舊 bundle）：{ages}。"
            "去 Actions → Vercel Deployment Prune → Run workflow（mode=purge）即刻釋放。")
    else:
        verdict_lines.append(
            f"✅ 冇瘦身前 deployment 殘留。Functions Storage 估算 ≈ "
            f"{total} 個 × ~{POST_FIX_BUNDLE_MB}MB ≈ {total * POST_FIX_BUNDLE_MB:.0f}MB，"
            "離 10GB 上限好遠。")
    daily_growth = len(last24h) * POST_FIX_BUNDLE_MB
    verdict_lines.append(
        f"過去 24 小時新增 {len(last24h)} 個 deployment（≈ +{daily_growth:.1f}MB/日）；"
        f"retention：{retention_text}。")
    if "預設" in retention_text or "30" in retention_text:
        verdict_lines.append(
            "提示：retention 仲係預設 30 日。想 Vercel 自己清走舊部署，"
            "行一次 Vercel Retention Policy workflow 將佢縮短。")

    report += [
        f"**Project deployments 總數：{total}**"
        f"（production READY：{len(production)}；最新一個係 {newest_age_h:.1f} 小時前）",
        f"- 瘦身前（2026-09-17 之前，可能巨型 bundle）：**{len(pre_fix)} 個**",
        f"- 瘦身後（~{POST_FIX_BUNDLE_MB}MB/個）：**{len(post_fix)} 個**",
        f"- Functions Storage 粗略估算：**{est_low:,.0f} – {est_high:,.0f} MB**"
        "（每個舊 bundle 當 100–250MB 計；Vercel 冇公開 per-deployment 實數）",
        f"- 過去 24 小時新增：{len(last24h)} 個 deployment",
        f"- Deployment Retention Policy：{retention_text}",
        "",
        "### 結論",
        "",
    ] + [f"- {line}" for line in verdict_lines]

    # ── 3. 最新 3 個 deployment 試探 size 欄位 ──────────────
    hints = []
    for deployment in deployments[:3]:
        uid = deployment.get("uid") or deployment.get("id") or ""
        if not uid:
            continue
        try:
            detail = client.call(f"/v13/deployments/{urllib.parse.quote(uid)}")
            hints += find_size_hints(detail)
        except Exception:  # noqa: BLE001 — 診斷性試探，失敗唔影響報告
            pass
    if hints:
        report.append("")
        report.append("### API 試探到嘅 size 欄位（診斷用）")
        report.append("")
        for key_path, value in hints[:12]:
            report.append(f"- `{key_path}` = {value}")

    # ── 4. Billing charges（設咗 team id 先試；Hobby 多半 4xx）──
    if team_id:
        try:
            charges = client.call("/v1/billing/charges")
            if charges:
                report.append("")
                report.append(f"### Billing charges（原樣前 800 字）")
                report.append("")
                report.append("```json")
                report.append(json.dumps(charges, ensure_ascii=False)[:800])
                report.append("```")
        except Exception:  # noqa: BLE001 — Hobby/未開通會失敗，靜靜跳過
            pass

    summary(report)
    compact = " | ".join(verdict_lines)[:3500]
    notice(f"Vercel 用量：{total} 個 deployments（瘦身前殘留 {len(pre_fix)} 個，"
           f"過去24h +{len(last24h)}）。重點：{compact}")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
