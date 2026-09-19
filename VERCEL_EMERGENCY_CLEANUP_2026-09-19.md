# 🚨 緊急：Functions Storage 11.99GB / 10GB 仲爆緊 — 清理指引

> 你張圖：Functions Storage **11.99GB / 10GB**，Deployment Storage 1.65GB / 10GB
> 即係話：**修復後（2026-09-17）舊嘅巨型 deployment 一個都冇清到**，仲繼續累積。

## 點解修復咗都仲係 11.99GB？

### 已修復嘅（新部署已經瘦）

- `requirements.txt` 清空 + `.vercelignore` 擋走 → 新 deployment function bundle 由 **170MB → 14KB**
- 本地 `vercel_bundle_guard.py` 全部通過，上載 1.05MB
- 新部署每日增長 ~90KB，理論上 90 個部署先得 2.7MB

### 未修復嘅（舊部署仲喺度）

- **Functions Storage = 所有 retained deployment × 每個 bundle**
- Vercel 預設 retention 30 日，每日 ~3 個 bot commit（`[skip ci]` skip 唔到 Vercel）→ 30日≈90個部署
- 2026-09-05 至 2026-09-17 期間，每個部署 170MB×2=340MB，50個就已經 **17GB**
- **Prune workflow 雖然顯示 success，但其實乜都冇做**：
  - `vercel_prune.py` 如果未設 `VERCEL_TOKEN` / `VERCEL_PROJECT_ID`，會出 `::warning::` 然後 `exit 0`（唔會紅，但冇刪任何嘢）
  - 你去 Actions → Vercel Deployment Prune → 點入最近一次 run → 睇 Job Summary，應該會見到「⚠️ Vercel prune 已跳過（冇清到任何嘢）」
  - 呢個係 2026-09-17 加嘅保護（舊版完全無聲），但如果你冇設 secrets，就一直清唔到

**結論**：11.99GB 幾乎全部係 2026-09-17 之前嘅舊巨型 bundle，新嘅瘦部署只佔零頭。

## 即時止血（三揀一，最快係 Dashboard）

### 方法 A：Vercel Dashboard 手動刪（最快，5分鐘見效）

1. 去 **Vercel → 你的 Project → Deployments**
2. 右上角 **Filter** → 揀 **Created before 2026-09-17**
3. 逐個點入 → **... → Delete Deployment**
   - 注意：Production（有 alias 嗰個）刪唔到，會回 403/409，skip 佢
   - 目標：只留最近 **5 個** + Production
4. 刪完去 **Usage** 頁面，Functions Storage 應該即刻由 11.99GB 跌到 **<0.1GB**
   - Vercel 有時要幾分鐘先更新用量數字

> 小貼士：Vercel Dashboard 一次只可以刪一個，如果有 100 個舊部署，會有啲煩。可以用方法 B 一次過清。

### 方法 B：設 Secrets + 跑 Prune Workflow（一次過清）

1. **攞 Token 同 Project ID**：
   - Vercel → **Account Settings → Tokens** → Create Token → Scope 揀呢個 project → Copy
   - Vercel → **Project → Settings → General → Project ID** → Copy

2. **去 GitHub → 你的 repo → Settings → Secrets and variables → Actions → New repository secret**：
   - `VERCEL_TOKEN` = 上面個 token
   - `VERCEL_PROJECT_ID` = 上面個 Project ID
   - `VERCEL_TEAM_ID` = 如果係個人帳戶留空，Team 帳戶先要（Team → Settings → General → Team ID）

3. **去 Actions → Vercel Deployment Prune → Run workflow**：
   - `mode` = **purge**
   - `keep_recent` = **5**
   - `keep_days` = **14**（purge mode 會忽略呢個）
   - `dry_run` = **false**
   - Run

4. 睇 Job Summary，應該會見到「🗑️ deleted 70 個 deployments」之類

5. 再去 Vercel Usage 確認跌返

### 方法 C：用 Vercel CLI 本機清（如果你有裝）

```bash
npm i -g vercel
vercel login
vercel ls --project scout-circulars  # 列出所有 deployments
# 然後逐個刪舊嘅
vercel rm <deployment-url> --yes
```

## 防止日後再爆（已幫你落咗兩道防線）

### 1. `vercel.json` 加 `ignoreCommand`（呢個 PR 已加）

```json
"ignoreCommand": "bash -c 'if [[ \"$VERCEL_GIT_COMMIT_MESSAGE\" == *\"[skip ci]\"* ]] ...'"
```

- 以後任何 commit message 有 `[skip ci]` 或 `[vercel skip]` 嘅，Vercel **唔會開新 deployment**
- 你嘅 bot commit（`🤖 Auto-update circulars [skip ci]` / `📊 Update subscription stats [skip ci]` / `Local backup scrape`）全部有 `[skip ci]`，所以以後 **零增長**
- 只有人手 push（冇 `[skip ci]`）先會部署，真人改動先需要部署

> 呢個係 Vercel 官方建議做法：Dashboard → Settings → Git → Ignored Build Step 都可以設，但 `vercel.json` 更可靠（跟 repo 走）

### 2. 縮短 Retention Policy（建議）

- Vercel Dashboard → **Project → Settings → Security → Deployment Retention Policy**
  - Pre-Production（preview）: **1w**（7日）
  - Production: **1m**（30日）
  - Canceled: **1d**
  - Errored: **1w**
- 或者 Actions → **Vercel Retention Policy** → Run workflow（要同上面一樣設 secrets）

咁就算唔小心有 bot deployment，都只會留 7 日自動清。

### 3. 監控

- 已補回 **Vercel Usage Report** workflow（每次 push 自動跑，唯讀）
- 去 Actions → Vercel Usage Report → Run，可以見到：
  - 總 deployments 數
  - 瘦身前殘留幾個（>0 就要再 purge）
  - 過去24h新增幾個
  - Retention 現況

## 點樣確認已修好

1. Vercel → Usage → Functions Storage 應該 **< 0.5GB**
2. Vercel → Deployments → 只剩最近 5 個 + Production，全部係 2026-09-17 之後
3. GitHub → Actions → Vercel Bundle Guard 綠燈（每次 push 自動檢查）
4. 下次 bot commit（00:15 HKT scrape + 06:00 HKT notify）之後，Vercel Deployments **唔應該**新增（因為 ignoreCommand）

## 今次改動

- `vercel.json`：加 `ignoreCommand` 跳過 `[skip ci]` 部署 → 以後 bot commit 零增長
- 保留之前所有修復：`requirements.txt` 空 + `.vercelignore` + `excludeFiles` + bundle guard
- 新增呢個緊急清理指引

## 如果你而家冇時間手動刪

最少要做：

1. Merge 呢個 PR（`ignoreCommand`）→ 阻止繼續漲
2. 設 `VERCEL_TOKEN` / `VERCEL_PROJECT_ID` secrets
3. 跑一次 Prune（purge mode）+ Retention Policy（1w/1m）

做完之後 11.99GB 應該即刻跌返，之後就算每日有 bot commit，都唔會再開 Vercel deployment，Functions Storage 會維持喺幾十 MB。
