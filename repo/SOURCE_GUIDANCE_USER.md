# 使用者提供的逐站監控指引（人工整理）

這份文件整理自使用者在對話中提供的 CSV / 表格內容。
用途：

1. 作為 `sources.json` 精修參考
2. 作為高風險來源的 selector / 標題抽取策略備忘
3. 作為 smoke test 後續修站的優先依據

## 重要原則
- 以來源隔離為先
- 每個來源按其實際結構處理，不用一刀切
- 優先鎖定「通告表格第一列 / 最新消息區塊 / Google Sites role=main / WordPress entry-title」
- 某些來源要同時抓日期欄位與標題
- 某些來源應忽略固定雜訊，例如 `Form`、`表格`、`置頂`、Google 頁尾系統連結等

## 使用者特別指出的結構提示（摘要）

### 港島地域
- 港島地域：第一個 table 第一行 a 文字，並比對上載日期
- 灣仔區：鎖定「最新告示」區塊，過濾末尾括號次數
- 港島西區：最新年份資料夾 > 最新檔名
- 柴灣區：`.entry-title`，排除 Sticky Post
- 維多利亞城區：Google Sites `role="main"` 前 3 個連結文字
- 南區：原站失效，可考慮地域頁中「南區」關鍵字通告
- 筲箕灣區：首頁「最新消息」區塊，排除 slider
- 港島北區：training 頁面第一個連結文字

### 九龍地域
- 九龍地域：entry-content 內所有 PDF 標題，全頁比對，忽略 `Form` / `表格`
- 紅磡區：最新消息區塊，前三個文章標題
- 何文田區：活動及訓練頁面內最新連結文字
- 九龍城區：各 section 下最新一條連結，建議全頁連結標題比對
- 九龍塘區：第一行日期 + 標題，任一變更即觸發
- 旺角區：Google Sites `role="main"` 全量連結文字
- 深旺區：首頁最新消息第一個連結文字
- 深水埗東區：content 區所有 PDF 標題，全量比對
- 深水埗西區：首頁最新文章 `.entry-title` / `.post-title`
- 油尖區：最新文章 `.entry-title`，忽略置頂 / 公告

### 東九龍地域
- 地域總部：所有最新年份連結文字，全量字串比對
- 西貢區：首頁 main 區 `.entry-title` / `article` 第一個文字連結
- 慈雲山區（課程 / 活動）：Joomla category，分別抓 id=34 / 35 第一條文章標題
- 黃大仙區：entry-content 內所有連結 innerText 全量比對
- 九龍灣區：靜態 `notice.html`，table 第一行非標頭 innerText
- 秀茂坪區：Google Sites `role="main"` 全量 a 文字；忽略 Google 頁尾連結
- 將軍澳區：main 內容 / 表格第一列標題與日期
- 觀塘區：`.items-row` / `article` 最新一篇文章標題，若無日期排序則全頁 hash
- 鯉魚門區：`.entry-title` 或 `article`，監控首頁所有文章標題

### 新界地域
- 新界地域：Big5 / youth table，抓第一行非標頭 td 的通告編號 + 標題
- 元朗東區：首頁 Latest News / `.entry-title` 第一筆
- 元朗西區：category/通告/ 最頂端第一篇文章標題 + 日期
- 十八鄉區：main 內容區內最新文章標題與連結
- 屯門西區：content 區最新文章標題與日期
- 北葵涌區：最新消息 / 通告區塊（如 `.post-title`）
- 屯門東區：首頁最新通告 / 近期活動區塊第一個 a 文字
- 荃灣區：通告表格第一行日期 + 編號 + 標題
- 南葵涌區：鎖定 `#活動與訓練通告` 錨點下清單
- 青衣區：`.entry-title` 最新消息，識別 `category-notice`
- 離島區：Google Sites 主內容區，掃描最新 button / 文字連結

### 新界東地域
- 地域總部：`.post-item` / `.entry-title` 最頂第一條通告，建議同抓 `post-date`
- 雙魚區：`.entry-title a` 最新一條通告文字 + href
- 壁峰區：Google Sites `div[role="main"]` 全量文字生成 hash
- 大埔北區：`.entry-title a` 最新一則通告
- 大埔南區：靜態表格 / 列表第一個下載連結文字（檔名）+ 發布日期
- 沙田西區：`/wp/notice/` 首位文章 `.entry-title a`
- 沙田南區：`/programme/notice` 第一筆文章 URL + 日期
- 沙田東區：`notice.html` 全頁通告標題對比
- 沙田北區：`circulars.php` table 內所有文字，全量抓取

## 備註
- 使用者 CSV 與現行 `sources.json` 在少數名稱上有輕微差異，例如：
  - `維多利亞港區` / `維多利亞城區`
  - `南區` / `港島南區`
- 之後修站時，這份指引應被視為**高優先人工經驗來源**。
