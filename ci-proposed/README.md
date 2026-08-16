# 待安裝嘅 CI 設定

呢個資料夾嘅嘢**唔會自動生效**，要你手動搬入 `.github/workflows/`。

## 點解要你自己搬

Arena 用嘅 GitHub App 冇 `workflows` 權限，push 含 `.github/workflows/`
改動嘅 commit 會被 GitHub 直接拒絕：

```
refusing to allow a GitHub App to create or update workflow
`.github/workflows/scrape.yml` without `workflows` permission
```

所以檔案放喺呢度俾你過目同安裝。

## 安裝方法（兩分鐘）

```bash
# 1. 新測試 workflow
cp ci-proposed/test.yml .github/workflows/test.yml

# 2. 每日爬蟲加健康檢查
git apply ci-proposed/scrape.yml.patch

git add .github/workflows/
git commit -m "👷 CI: 自動跑測試 + 每日健康檢查"
git push
```

裝完之後可以刪走 `ci-proposed/`。

---

## 1. `test.yml` — 每次 push / PR 自動跑全套測試

### 點解需要

呢個 repo 出事嘅模式一直都係**靜默失敗**（抓錯嘢但唔報錯）。
但八個測試檔本身**從來冇自動跑過** —— `scrape.yml` 只有 `schedule` +
`workflow_dispatch`，冇 `pull_request` / `push` trigger。
PR #3 開咗都只係跑緊 Vercel，零個測試。

即係話**測試自己就係另一個靜默失敗來源**：改壞 `core.py` 嘅標題邏輯，
港島南區 24 筆會靜靜變返 `view`，冇任何嘢會叫。

### 內容

| 步驟 | 作用 |
|---|---|
| 語法檢查 | `core.py` / `enrich.py` / `check_stale.py` / `check_sources.py` |
| 6 個 Python 測試 | 標題 fallback、靜默偵測、三個來源修復、group.scout 來源、enrich 欄位、enrich Drive |
| 2 個 jsdom 測試 | `errors.html` 儀表板、`index.html` 收藏功能 |
| cache 完整性守門 | 一發現 `view`/`preview`/`edit`/`open` 垃圾標題即 **fail** |

全部測試**離線**（重建 DOM / mock），唔會連外網、唔會打區會網站，
所以每次 push 都跑係安全嘅。

## 2. `scrape.yml.patch` — 每日爬蟲後做健康檢查

抓完之後跑 `check_stale.py` 印低結果，唔使等你記得人手去睇。

刻意用 `|| true`：健康檢查只係**報告**，唔應該令抓取成果冇得 commit。
