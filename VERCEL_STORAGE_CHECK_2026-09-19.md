# Vercel Functions Storage 爆額檢查報告 — 2026-09-19

## 問題背景（你之前爆嗰次）

- **症狀**：Vercel Dashboard → Usage → `The amount of storage used by Vercel Functions of your deployments` 爆到 **11.82GB / 10GB**（Hobby 上限 10GB）
- **時間線**：
  - 2026-09-16：10.49GB / 10GB，誤以為病源係 `api/render.py`（PyMuPDF ~110MB），移除咗佢
  - 2026-09-17：再爆到 11.82GB / 10GB，搵到真正病源
- **真正病源**：
  - 根目錄 `requirements.txt` 列住 `playwright`（wheel 46MB，解壓後 **137MB**，driver 135MB）+ `lxml` + `cryptography` + `requests` + `bs4` + `pywebpush`
  - Vercel Python runtime 會自動讀 **repo 根目錄** 嘅 `requirements.txt` / `pyproject.toml` / `Pipfile`，`pip install` 入 **每一個** `api/*.py` function bundle，而且官方明言 **「There is no automatic tree-shaking for Python」**
  - 每個 function bundle ~170MB
  - Functions Storage = 每個 retained deployment × 每個 bundle × 每個 region
  - Hobby 預設 retention 30 日 × 每日 ~3 個 bot commit（`[skip ci]` 只 skip GitHub Actions，skip 唔到 Vercel）→ 數十個部署 × ~170MB ≈ 10GB+

## 而家（2026-09-19）仲有無爆？

### 1. 本地 Bundle Guard 檢查（離線，唔使 Vercel token）

```
tracked 97 個檔；.vercelignore 擋走 72 個；上載 25 個

✅ 檢查 1：api/ 嘅 3 個檔全部只用標準庫／local module
✅ 檢查 2/3：requirements.txt 已被 .vercelignore 擋住，且冇列任何依賴
✅ 檢查 2/3：requirements.txt 已 ignore（Vercel 收唔到，零 pip install）
✅ 檢查 4：上載去 Vercel 嘅檔案 25 個，合共 1.05 MB（budget 2.00 MB）
    最大五個：icons/icon-512.png 288KB、icons/icon-maskable-512.png 180KB、index.html 157KB、subscription_catalog.json 92KB、icon.svg 65KB
✅ 檢查 5：includeFiles 指到嘅 2 個檔案全部存在且會上載

✅ 全部檢查通過：冇嘢會令 Vercel function bundle 脹返。
```

**結論：病源已斷**

- `requirements.txt` 而家係 **刻意留空**（得註解，0 個依賴）+ 已加入 `.vercelignore`（雙保險，Vercel 根本收唔到）
- `api/` 係 **100% 標準庫**（`http.server`, `json`, `os`, `re`, `hashlib` 等），`vercel-bundle-guard.yml` 每次 push 都會 AST 檢查
- 上載去 Vercel 嘅總體積 **1.05MB**（budget 2MB），主要係 `index.html` + `icons/*.png` + `subscription_catalog.json`
- Function bundle 模擬：
  - `push_config.py` zipped **13.8 KB**（未壓 105.6 KB）
  - `push_subscriptions.py` zipped **14.7 KB**（未壓 108.6 KB）
  - 對比之前 **~170MB**，細咗 **10,000 倍**

### 2. Functions Storage 粗略估算（修復後）

- 修復前：每個 deployment ~340MB（2 functions × 170MB）× 90 deployments（30日×3 bot commit）≈ 30GB 理論值，實測 11.82GB（可能壓縮/region 計算差異）
- **修復後**：每個 deployment ~30KB（2 × 15KB）× 90 = **~2.7MB**，離 10GB 上限好遠
- 每日增長：過去平均 ~3 deployments/日 × 30KB = **~90KB/日**，之前係 ~1GB/日

### 3. 舊巨型 Deployment 有無清走？

- `Vercel Deployment Prune` workflow 最後成功執行：
  - `2026-09-17T23:43:11Z`（run `35288079638`）— 就係修復當晚
  - 之前幾日都有連續 purge（`35063553560`, `35065066959`, `35065514225` 等）
- 理論上舊嘅 100–250MB bundle 應該已 DELETE
- **但要真正確認**，需要 Vercel API token 查 `GET /v6/deployments`（見下面「點樣手動驗證」）

### 4. 仲有咩會令佢再爆？

已檢查：

- ✅ 冇 `pyproject.toml` / `Pipfile` / `api/requirements.txt` / `uv.lock` 漏網上載
- ✅ `vercel.json` 嘅 `excludeFiles` 擋走晒 `*.html,*.md,*.svg,*.bat,*.bak,*.sql,icons/**,...`，只留 `subscription_catalog.json` 用 `includeFiles` 包
- ✅ `cache.json`（3.3MB）/ `enrich.json`（1.6MB）/ `icons/src/`（1.6MB）等大檔已 `.vercelignore`
- ⚠️ **Retention Policy 仲係預設 30 日**（如果未行過 `Vercel Retention Policy` workflow）：
  - 就算而家每個 deployment 得 30KB，30日×3/日=90 個都係細
  - 但想更保險，建議縮到 `preview=1w, production=1m`，等 Vercel 自己背景清

## 點樣手動驗證（你而家可以去 Vercel Dashboard 睇）

1. **Vercel → Project → Usage → Functions**：
   - 睇 `The amount of storage used by Vercel Functions of your deployments` 而家幾多 GB
   - 如果修復後有 prune，應該已跌返去 **< 0.1GB**

2. **Vercel → Project → Deployments**：
   - 睇最舊嗰幾個 deployment 係幾時
   - 如果仲見到 2026-09-17 之前嘅，佢哋可能仲揹住巨型 bundle

3. **手動跑用量報告（已幫你加返 workflow）**：
   - 呢個 branch 已經加咗 `vercel-usage-report.yml` + `vercel_usage_report.py`（之前喺 `arena/01a0b1b5` 有，但 main 未有）
   - 去 GitHub → repo → Settings → Secrets → 確認有：
     - `VERCEL_TOKEN`（Vercel → Account Settings → Tokens → Create，Scope 揀呢個 project）
     - `VERCEL_PROJECT_ID`（Vercel project → Settings → General → Project ID）
     - `VERCEL_TEAM_ID`（個人帳戶留空，team 先要）
   - 然後 Actions → **Vercel Usage Report** → Run workflow
   - 佢會出：
     - 總 deployments 數
     - 瘦身前殘留幾個（如果 >0 就要再 purge）
     - 過去 24h 新增幾個
     - Retention policy 現況

4. **如果仲有殘留**：
   - Actions → **Vercel Deployment Prune** → Run workflow → `mode=purge, keep_recent=5`
   - 即刻 DELETE 舊 deployments，即時釋放
   - 然後 Actions → **Vercel Retention Policy** → Run workflow → `preview=1w, production=1m` 縮短保留期，防日後再積

## 今次幫你做咗咩

1. 跑咗 `vercel_bundle_guard.py`，確認全部 5 項檢查通過，上載 1.05MB，function bundle 13–14KB
2. 模擬咗 Vercel Python bundle 打包，確認零第三方依賴
3. 檢查咗 `.vercelignore` / `vercel.json` / `requirements.txt` / `api/` imports / 其他 manifest，冇漏網
4. 查咗最近 GitHub Actions：
   - Prune workflow 喺 2026-09-17 修復當晚成功跑過，應該已清舊部署
   - Scrape / Notify 每日正常，平均 3 deployments/日
5. **補返** `Vercel Usage Report` workflow（唯讀監控）到呢個 branch，等你可以持續監察

## 建議下一步

- [ ] 去 Vercel Dashboard → Usage 確認 Functions Storage 而家數值（預期 < 0.5GB，如果已 prune）
- [ ] 如果見到仲有舊部署殘留，跑一次 Prune（purge mode）
- [ ] 跑一次 Retention Policy workflow 將 preview 縮到 1w，減少未來累積
- [ ] Merge 呢個 branch 嘅 `vercel-usage-report.yml` 去 main，等每次 push 自動出報告
- [ ] 如果 Functions Storage 已跌返，考慮喺 Vercel Dashboard → Settings → Security → Deployment Retention Policy 手動設短啲（同 workflow 做嘅一樣）

## 總結

**病源已斬斷，唔會再以 170MB/個嘅速度爆。**

- 而家每個 deployment Functions Storage ≈ 30KB，增長 ~90KB/日，離 10GB 好遠
- 舊巨型 bundle 喺 2026-09-17 已 prune（需 Dashboard 最終確認）
- 已加監控 workflow，之後任何令 bundle 脹返嘅改動會即刻 CI 紅（bundle-guard），用量異常會自動報告（usage-report）

如果你可以提供 `VERCEL_TOKEN` + `VERCEL_PROJECT_ID`（或者喺 GitHub Secrets 設好後手動跑 Usage Report workflow），我可以幫你讀埋真實 Vercel API 數字。
