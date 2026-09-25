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
# 1. 新測試 workflow（2026-09-25 已擴充到跑齊全部 28 個測試檔）
cp ci-proposed/test.yml .github/workflows/test.yml

# 2. 每日爬蟲加「修復歷史污染標題」步驟（scrape.yml.patch 已經裝咗，見下）
git apply ci-proposed/scrape-hks-titles.patch

git add .github/workflows/
git commit -m "👷 CI: 自動跑測試 + 每日自動修復污染標題"
git push
```

裝完之後可以刪走 `ci-proposed/`。

---

## 1. `test.yml` — 每次 push / PR 自動跑全套測試

### 點解需要

呢個 repo 出事嘅模式一直都係**靜默失敗**（抓錯嘢但唔報錯）。
但測試檔本身**從來冇自動跑過** —— `scrape.yml` 只有 `schedule` +
`workflow_dispatch`，冇 `pull_request` / `push` trigger。
PR #3 開咗都只係跑緊 Vercel，零個測試。

即係話**測試自己就係另一個靜默失敗來源**：改壞 `core.py` 嘅標題邏輯，
港島南區 24 筆會靜靜變返 `view`，冇任何嘢會叫。

### 2026-09-25 更新：清單補齊

原本只列 8 個測試檔，另外 **15 個從來冇跑過**（share-launch、mobile_compact、
personalized_view、push_client、report_feedback、sw、time_windows、pdf_proxy、
push_common、tools_category、notify、story_queue、publish_instagram_stories、
tko_notice_blocks、tme_title_mismatch）。後果係佢哋嘅期望值靜靜腐化：

| 測試 | 腐化咗嘅期望 | 實情 |
|---|---|---|
| `test_personalized_view.js` | 領袖「一般項目」只有 服務／活動／比賽 | catalog 3.1.0 起多咗獨立分類「小工具」 |
| 同上 | 私隱句要有「不收集姓名」 | 句字已縮短做「設定先留在本機 LocalStorage」 |
| 同上 | `#push-edit-help` 要有「原有選項會保留」 | 已改寫成「儲存前不會改動訂閱」 |

（另外兩個失敗係真 code bug，唔係測試問題：出圖台列出永遠用唔到嘅小工具
款式；`archiveHtml` 只喺非工具分支加，令「6個月以上」標籤永遠唔會出現。
兩個都喺 `index.html` 修好。）

### 內容

| 步驟 | 作用 |
|---|---|
| 語法檢查 | `core.py` / `enrich.py` / `check_stale.py` / `check_sources.py` |
| Python 測試 | 標題 fallback、靜默偵測、來源修復、enrich 欄位／Drive、meta refresh、tko 區塊、TME 標題、小工具分類、push 驗證、通知發送、PDF bridge、Story 隊列／發佈 |
| jsdom 測試 | 儀表板、收藏、分享面板、分享啟動頁、支部配對、手機收合、通知設定、push client、回報表單、service worker、時間視窗、圖示 |
| cache 完整性守門 | 一發現 `view`/`preview`/`edit`/`open` 垃圾標題即 **fail** |

全部測試**離線**（重建 DOM / mock），唔會連外網、唔會打區會網站，
所以每次 push 都跑係安全嘅。

> ⚠️ **第一次跑會紅兩格，係「正確嘅紅」**：`test_url_title_fallback.py` 同
> cache 完整性守門會報 cache.json 有 24 筆標題係 `view`（港島南區）。
> 呢個係真嘢 —— 見下面第 3 節，跑一次修復就轉綠。

## 2. `scrape.yml.patch` —（**已經安裝咗，唔使再 apply**）

每日爬蟲後跑 `check_stale.py` 印低結果，唔使等你記得人手去睇。
`.github/workflows/scrape.yml` 而家有「Step 3: 健康檢查（報告記錄在 Action log）」,
所以呢個 patch 已經 apply 過（再 apply 會 fail，屬正常）。

## 3. `scrape-hks-titles.patch` — 每日自動修復污染標題（建議安裝）

### 點解需要

2026-05 港島南區 24 筆通告嘅標題寫咗做 `view`（Google Sites 上 Drive 連結
冇 anchor 文字，舊 `fallback_title_from_url()` 攞咗 URL 尾段）。
`core.py` 之後已經修好，**新抓嘅唔會再中**，但：

- 已經入庫嘅記錄唔會再被抓（來源頁已經唔列出嗰 24 條舊通告），
- `core.py` 用 `(source_site, pdf_url)` 認「已存在」，所以佢哋永遠唔會被重新命名。

結果：24 張通告卡喺 6 個月視窗入面一直顯示標題「view」，而
`test_url_title_fallback.py` 同 cache 完整性守門會一直紅。
`fix_hks_titles.py` 就係為呢件事寫嘅一次性工具 —— 對照表係逐份開 PDF
核實過嘅真標題（唔靠 PDF metadata，因為好多份 metadata 都係錯）。

### 為咩要放喺 workflow 而唔係人手跑

`cache.json` 每日由 Action 重寫（`core.py` → `build_grouped_cache` →
`json.dumps(..., indent=2)`）。喺 PR branch 手改 `cache.json` 再合併，
好易同 bot 嘅新版本撞，最壞情況係蓋走一日通告。放喺 workflow 就係
同一個 writer 一次過做，冇 merge 風險。

`fix_hks_titles.py` 冇嘢要改就即刻 exit 0（唔會掂 cache.json、唔會寫備份），
所以可以永遠留在 workflow 入面，唔會阻礙之後任何一次跑。
