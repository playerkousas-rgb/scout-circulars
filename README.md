# 香港童軍通告聚合器 v4/v5 骨架

本專案按你提供的核心哲學重建：

- **來源隔離（Source Isolation）**
- **物理對齊（Direct Mapping）**
- **按區會獨立分頁，不混成單一大陣列**
- **以 `cache.json` 作為前後端對接標準**
- **前端只讀 GitHub Raw CDN，不讀相對路徑**
- **新增補丁：列表頁 + 文章內頁兩階段抓取**
- **新資料一律以系統捕獲日期作排序日期**

## 檔案

- `core.py`：Python 爬蟲主程式
- `sources.json`：49 個來源映射設定
- `cache.json`：輸出資料與內部狀態
- `index.html`：靜態前端（多分頁 / 手風琴 / 時間視窗 / 支部標籤 / 分享）
- `api/render.py`：PDF → 圖片 API（分享圖片用；Vercel Python Function）
- `serve_local.py`：本機同時提供靜態頁 + `/api/render`
- `.github/workflows/update-cache.yml`：每日自動更新

## 快速開始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python core.py --verbose
```

只跑單一來源測試：

```bash
python core.py --source 總會 --verbose
python core.py --source 筲箕灣區 --max-detail-pages 8 --verbose
```

## 前端設定

`index.html` 內有：

```js
const RAW_CACHE_URL = "https://raw.githubusercontent.com/YOUR_GITHUB_USER/YOUR_REPO/main/cache.json";
```

請改成你的 GitHub Raw CDN。

亦可用 query string 臨時覆蓋：

```text
index.html?raw=https://raw.githubusercontent.com/<user>/<repo>/main/cache.json
```

## 搜尋與支部篩選

- 關鍵字欄只搜通告**名稱**（包含配對，NFKC 正規化，全形半形通用）。
- 支部用一排標籤篩選：**全部／小童軍／幼童軍／童軍／深資童軍／樂行童軍／領袖／家長／會務委員**（單選，再撳一次取消）。
- 判斷一張通告屬於邊個支部：
  1. `enrich.json` 有 `audience`（由 PDF 內文抽出）→ 以佢為準；
  2. 冇 `audience`（舊通告／抽唔到）→ 退而求其次睇標題。
- 兩者都用最長詞優先（longest-match），所以「童軍」不會誤中「小童軍」「幼童軍」「深資童軍」「樂行童軍」；「所有成員」當作全部支部命中。

## 通告分類

搜尋列仲有一排**分類**標籤：**全部／訓練班／服務／比賽／其他**。

- 純前端規則分類，**不改爬蟲、不改 cache**，每日抓取照常。
- 用通告標題 + `enrich.json` 標題做關鍵字判斷；一隻通告可以同時屬於多個類別（例如「社區服務計劃暨義工訓練」→ 服務 + 訓練班）。
- 「行事曆／一覽／名單／章程」嗰類會當「其他」，避免「活動與訓練行事曆」因為有「訓練」兩字而變成訓練通告。
- 卡片本身都會顯示分類標籤，想調整分類規則改 `index.html` 入面 `CATEGORY_KEYWORDS` / `CATEGORY_EXCLUDE` 即可。
- 分類係標題級猜想，唔一定 100% 準；重要通告請開附件確認。

執行回歸測試：

```bash
node test_search_members.js     # 支部 + 分類配對邏輯（直接由 index.html 抽出，唔係複製一份）
node test_share_branch.js       # 支部標籤 + 分享面板 DOM 測試（需要 jsdom）
```

## 分享通告

每張卡片有「分享」掣，彈出面板提供：

- **分享連結**：WhatsApp／Telegram／Facebook／X／LINE／電郵、系統分享（手機）、複製網址、複製文字（標題 + 截止／對象／費用 + 網址）。
  分享嘅網址係**附件直連（PDF）**，朋友一撳即開。
- **分享圖片**：把 PDF 頁面轉做 JPG，可以成張貼落 IG／WhatsApp。多頁通告可逐頁產生；支援直接分享（手機）、複製圖片、下載圖片。
  - **電腦**：系統「分享檔案去其他 app」唔穩定，所以「分享圖片／更多…」喺電腦會收埋，改用**複製圖片**或**下載圖片**。
  - **複製圖片**：產生圖片之後會預先用 canvas 轉好 PNG，撳「複製圖片」嗰刻直接寫剪貼簿，唔會有「撳完先 await 轉圖」嘅時序問題。

圖片由 `api/render.py`（Vercel Python Function）產生：`GET /api/render?url=<pdf>&page=1&dpi=130` → `image/jpeg`，
header `X-Pdf-Pages` 係總頁數。依賴 PyMuPDF（`api/requirements.txt`），內建 CJK 後備字型，Word 出嘅冇內嵌字型通告都畫得正。
成功結果由 Vercel CDN 快取一日，同一張通告無論幾多人分享都唔會重複打區會網站。
只回傳畫出嚟嘅圖片（唔係開放代理），內網／loopback／link-local 位址一律拒絕。

本機測試（`python -m http.server` 冇呢個 API）：

```bash
pip install -r api/requirements.txt
python serve_local.py            # http://localhost:8000/index.html，/api/render 已掛載
python test_render_api.py        # 離線測試：網址清理、SSRF、CJK 轉圖、錯誤碼、完整 HTTP 流程
```

## `cache.json` 結構

```json
{
  "last_updated": "2026-05-21 00:00:00",
  "data": {
    "總會": [
      {
        "title": "示例通告",
        "url": "https://example.com/a.pdf",
        "date": "2026-05-21",
        "captured_date": "2026-05-21",
        "source_site": "總會"
      }
    ]
  },
  "_meta": {
    "version": "5.0.0",
    "design": "source-isolated-cache",
    "regions": {
      "港島地域": ["港島地域", "灣仔區"]
    },
    "source_order": ["總會", "港島地域", "灣仔區"],
    "fingerprints": {
      "總會": {
        "hash": "md5...",
        "updated_at": "2026-05-21 00:00:00"
      }
    }
  }
}
```

## 重要實作決策

### 1. 日期規則
你最後選定的是：**只用系統捕獲日期**。

因此每一條通告都會：

- `date = 今天`
- `captured_date = 今天`

只要同一來源內同一網址再次被掃到，就會更新該日期，令它重新彈頂。

### 2. 去重規則
為避免「來源污染」，本版本採用：

- **同一來源內以 sanitize 後的 URL 作唯一鍵**
- 鍵值實作為 `來源名|網址`

這樣可以保證：

- 同一 PDF 在同一來源重覆出現不會重覆新增
- 不同來源即使碰巧引用同一 PDF，也不會互相覆蓋資料

這點是刻意向「來源隔離」傾斜。

### 3. 補丁為何以前會崩
常見原因：

- 列表頁只抓 `.pdf`，一加「內頁搜捕」就把所有導覽列 / 側欄 / 社交分享連結都當成文章
- 沒有限制 detail page 掃描數量
- 沒有區分「PDF 直鏈」與「文章內頁」
- 沒有來源隔離，導致單一來源爆炸時污染整體資料

本骨架已加入這些保護：

- 先抓直接 PDF
- 再抓同網域文章內頁
- 內頁掃描數量限制（預設 12）
- 抓到 `h1 + pdf` 即停
- 只更新當前來源分頁資料

## GitHub Actions

工作流會：

1. 每日定時執行 `core.py`
2. 自動提交 `cache.json`
3. 讓前端從 GitHub Raw 直接讀最新資料

## 下一步建議

如果你把你現有 repo 貼上來，我可以下一輪直接做：

- 對照你現有 `core.py` 修補崩潰點
- 併回你原本已成功抓到的來源
- 補埋 Vercel / Raw CDN / GitHub Actions 實際部署細節
