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
- `index.html`：靜態前端（多分頁 / 手風琴 / 時間視窗 / 只顯示明確日期）
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
