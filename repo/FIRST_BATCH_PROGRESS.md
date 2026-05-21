# 第一批修站進度（港島地域 / 灣仔區 / 維多利亞城區 / 港島南區）

## 已完成修正

### 港島地域
- 原本使用 `https://www.hkirscout.org.hk/tc/circular/index.html`
- 該頁實際上是通告分類入口，不是通告列表容器
- 已改為：
  - `https://www.hkirscout.org.hk/tc/circular/summary/index.html`
- 目前策略：
  - 鎖定表格容器
  - 在表格內全量抓取所有通告連結

### 灣仔區
- 原本只知道「最新告示」區塊，但首頁本身沒有下載檔
- 已改為：
  - 鎖定 `catid=51` 的 Joomla 文章連結作為 notice 容器
  - 進文章內頁後若無附件，允許以文章頁本身作 notice fallback
- 目的：
  - 即使這類區會公告沒有 PDF，也能把更新展示給成員看

### 維多利亞城區
- 保持使用 Google Sites 的 `訓練-活動資訊` 頁
- 依據使用者指引，鎖定 `role="main"` 作主內容容器
- 全量抓取 Drive / PDF 連結
- 本地因無 Playwright runtime，暫未驗證成功；需以 GitHub Actions 為準

### 港島南區
- 不再用首頁，而改為：
  - `https://sites.google.com/hkirscout.org.hk/hks/活動及訓練班`
- 因為這一頁才是實際放通告下載的位置
- 同樣鎖定 `role="main"` 容器，抓取所有 Drive / PDF 連結
- 本地因無 Playwright runtime，暫未驗證成功；需以 GitHub Actions 為準

---

## 本地驗證結果

### 港島地域
- 狀態：PASS
- 可抓到：5 筆
- 樣例：
  - 港島地域通告便覽(2026年5月)
  - 港島地域通告便覽(2026年4月)

### 灣仔區
- 狀態：PASS_BUT_ACTIONS_VERIFY
- 可抓到：10 筆
- 樣例：
  - 區會15/5 - 22/5/2026辦公時間
  - 區會 15/5/2026 辦公時間 (更新)

### 維多利亞城區
- 狀態：本地 FAIL_NO_ASSETS
- 原因：本地無 Playwright runtime；Google Sites 主內容未實際渲染
- 但從人工抓頁內容可確認該頁確實有 Drive 通告連結

### 港島南區
- 狀態：本地 FAIL_NO_ASSETS
- 原因：本地無 Playwright runtime；Google Sites 主內容未實際渲染
- 但從人工抓頁內容可確認 `活動及訓練班` 頁確實有大量 Drive 通告連結

---

## 結論

第一批目前進度：
- **已真正修通**：港島地域、灣仔區
- **已定位正確通告容器，待 GitHub Actions 驗證**：維多利亞城區、港島南區
