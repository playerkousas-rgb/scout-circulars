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
- `index.html`：靜態前端（多分頁 / 手風琴 / 時間視窗 / 支部標籤 / 分享 / 匿名通知設定）
- `subscription_catalog.json`：受控官方支部、訓練、服務、活動與比賽訂閱選項（不設自由文字標籤）
- `subscription_tagging.py`：由標題、PDF 文字與參加對象產生可靠的支部／訂閱 IDs
- `push-client.js`、`sw.js`：瀏覽器 LocalStorage、Service Worker 與 Web Push 收件處理
- `notify.py`：GitHub Actions 的匿名 Push dispatcher（先聚合每個訂閱者的命中）
- `subscription_stats.py`：管理員本機執行，用 service key 統計訂閱人數及各支部／項目的訂閱數（只出彙總，不出個資）；`schema.sql` 末段亦有對應 SQL
- `api/push_config.py`、`api/push_subscriptions.py`：不讓瀏覽器直連 Supabase 的窄 Web Push API
- `api/render.py`：PDF → 圖片 API（分享圖片用；Vercel Python Function）
- `serve_local.py`：本機同時提供靜態頁 + `/api/render`
- `manifest.webmanifest`、`icon.svg`、`icons/`：PWA 安裝設定與全套圖示（見下文「圖示」）
- `.github/workflows/scrape.yml`：每日抓取、增量 enrichment、匿名 Web Push 與自動更新

## 圖示

主畫面圖示係「童軍之火」：燃燒中的金色紋章式百合花徽，火焰由中葉燒上去、兩旁渦卷亦着火，
下方係一本攤開嘅書同金色底座，背景係昏暗嘅舊圖書館——象徵童軍之火長燃，努力參加活動同訓練。
圖係繪畫風格點陣圖（AI 生成後裁切、置中、補邊、加暗角），**母圖放喺 `icons/src/`，所有尺寸由母圖輸出**：

| 檔案 | 用途 |
|---|---|
| `icons/src/icon-any-1024.png` | 母圖（方形，圖案約佔 82% 高度）→ `icon-192/512.png`、`notification-192.png`、`favicon-16/32.png`（加透明圓角）、`apple-touch-icon.png`（180px，不加圓角，iOS 自己裁） |
| `icons/src/icon-maskable-1024.png` | 母圖（圖案收在 80% 安全區內，量度後最遠亮點距中心 175px／上限 205px）→ `icon-maskable-192/512.png` |
| `icon.svg`、`icons/icon-maskable.svg` | 只係包住對應 192 PNG 嘅 SVG 外殼，畀 manifest 引用；**唔好手改** |
| `icons/badge.svg` → `icons/badge-96.png` | 單色白百合花剪影；Android 狀態列只取 alpha，所以唔可以用彩色圖 |

`sw.js` 推送通知用 `notification-192.png`（彩色）＋ `badge-96.png`（單色）——Android/Chrome 唔會穩定 raster SVG 通知圖，所以一定要 PNG。
`icons/preview.html` 模擬 iOS／Android 主畫面、通知同分頁 favicon 效果，本機開 `http://localhost:8000/icons/preview.html` 即可對照。

換圖流程（ImageMagick）：

```bash
cd icons
# 1) 圓角版（any）
convert src/icon-any-1024.png -alpha set \( -size 1024x1024 xc:black -fill white -draw "roundrectangle 0,0 1023,1023 232,232" \) -alpha off -compose CopyOpacity -composite /tmp/any-rounded.png
for s in 512 192 32 16; do convert /tmp/any-rounded.png -resize ${s}x${s} -strip icon-$s.png; done
mv icon-32.png favicon-32.png; mv icon-16.png favicon-16.png; cp icon-192.png notification-192.png
# 2) iOS 同 maskable（全出血）
convert src/icon-any-1024.png -resize 180x180 -strip apple-touch-icon.png
for s in 512 192; do convert src/icon-maskable-1024.png -resize ${s}x${s} -strip icon-maskable-$s.png; done
# 3) SVG 外殼（base64 包住 192 PNG）
python3 - <<'PY'
import base64
for png,svg in (('icon-192.png','../icon.svg'),('icon-maskable-192.png','icon-maskable.svg')):
    b=base64.b64encode(open(png,'rb').read()).decode()
    open(svg,'w').write('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 192 192" role="img" aria-label="香港童軍通告圖書館"><image width="192" height="192" xlink:href="data:image/png;base64,%s"/></svg>\n'%b)
PY
cd .. && node test_icons.js   # 確認 manifest / <head> / sw.js 引用嘅檔案全部存在且尺寸正確
```

`manifest.webmanifest` 嘅 `background_color`（安裝啟動畫面底色）係 `#0a0603`，同圖示近黑背景一致；`theme_color` 保留網站深藍，因為佢影響嘅係瀏覽器 UI 色。
iOS 會快取 apple-touch-icon：換圖後要刪除舊主畫面 App 再重新「加入主畫面」先見到新圖。

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

搜尋列仲有一排**分類**標籤：**全部／訓練／服務／活動／比賽／未分類**。活動只涵蓋大露營、營火會及其他活動；比賽是獨立分類。舊資料的 direct `competition`（或舊 `activity:competition`）會向後相容顯示為「比賽」。

- **分類次序：先睇標題，標題唔肯定先至加 PDF 內文**。標題通常最多關鍵資訊（例如「童軍繩結訓練班」「射箭公開賽」「社區服務隊招募」）。
  - 標題有強證據（明確字眼）→ 直接分類。
  - 標題得弱證據（例如「訓練日」「盃」）或者睇唔出 → 先用 PDF 內文補充。
  - 標題出現「行事曆／一覽／名單／章程」呢類排除詞 → 唔當活動本體。
- `enrich.json` 每條會多一個 `categories` 欄：`[{id, label, score, evidence}...]`；前端直接用呢個欄位過濾／排序。
- 一隻通告可以同時屬於多個類別（例如「社區服務計劃暨義工訓練」→ 服務 + 訓練班）。
- 每日 GitHub Action / 本機 `python enrich.py` 會自動為**新通告**填 `categories`。
- 舊通告未有 `categories` 或仍使用較舊 taxonomy → 前端會顯示「其他」或保留相容映射。要補歷史分類，本機跑：
  ```bash
  python enrich.py --backfill-categories --limit 500
  ```
  （呢個會再下載未分類嘅 PDF，量大時請分批／夜晚跑，避免觸發站方封鎖。）
- 想調整分類規則，改 `subscription_tagging.py` 的受控分類詞表；不要為罕見／不可靠的名稱加推播匹配。
- 分類係 PDF 內文級估算，唔一定 100% 準；重要通告請開附件確認。

執行回歸測試：

```bash
node test_search_members.js     # 支部 + 分類配對邏輯（直接由 index.html 抽出，唔係複製一份）
node test_share_branch.js       # 支部標籤 + 分享面板 DOM 測試（需要 jsdom）
python test_notify.py           # Push 去重、交集和合併通知邏輯（不會發網絡請求）
python test_push_common.py      # API 受控 ID 與 endpoint SSRF 防護
node test_push_client.js        # LocalStorage／匿名 subscription lifecycle（不需 jsdom）
node test_sw.js                 # Service Worker 只接受同源精確圖書館結果 URL
node test_icons.js              # manifest／<head>／sw.js 引用嘅圖示檔案存在、PNG 尺寸正確、badge 係單色 PNG
node test_personalized_view.js  # 受控下拉 + 精確 ?n= 推播結果頁／手機收合 UI（需要 jsdom）
```

## 匿名個人化 Web Push

通知功能採取**零個資、零成本優先**的設計：沒有登入、帳戶、姓名、電郵、電話、旅團或地域推播條件。地域／區會資料仍只用於左欄瀏覽。

1. 使用者按搜尋列／「★ 收藏」旁的 **🔔 通知** 掣（手機為頂欄 🔔）開啟設定面板，所有選項都是**點一下即剔**的受控項目，桌面不必按 Ctrl／Shift。先揀支部，再選服務、活動、比賽；訓練則**按支部列出**該支部現行訓練綱要內的非進度性徽章及特別訓練班（例如童軍的「童軍領導才」），另有「所有 X 訓練」一鍵訂閱；領袖訓練分為**木章訓練班**與**非木章訓練班**。設定先寫入該瀏覽器的 LocalStorage，不會上傳自由文字。選單只顯示「地圖閱讀」等項目基礎名稱；訓練班、工作坊、課程等正式題名變體會自動配對。
2. 啟用通知時，瀏覽器才產生標準 Web Push subscription。後端只保存該協定必要的匿名 endpoint／加密金鑰，以及已選受控 ID；endpoint 以雜湊作唯一鍵，LocalStorage 的隨機 token 只以雜湊保存。
3. `enrich.py` 用標題、PDF 文字與既有參加對象寫出 `branch_tags` 和 `subscription_tags`。不可靠的名稱不會硬猜；「初級空勤章」「初級空勤員章訓練班／工作坊」等官方別名共用同一受控項目。
4. `notify.py` 比較本輪 cache 與 `HEAD:cache.json`，只處理真正新增 URL（來源 + URL 共同識別）。每個訂閱要同時命中**支部 AND 關注項目**，同一人所有命中先合併，因此 10 個命中只送 1 則通知。
5. 同日後續執行會用相同通知 tag 搭配 `renotify: false` 及明確 `silent: true` 更新／取代彙總；`push_deliveries` 的唯一鍵也會阻止 workflow 重跑重送同一通告。通知只用極簡標題／行動文字，**一律開啟圖書館**而非 PDF；URL 的 `?n=` 只含本批公開通告的短雜湊 ID，因此恰好顯示本次 1／N 項，不讀取或暴露用戶設定。

手機版會把地域／區會改為側滑抽屜，並把篩選與 ScoutSystem 接入收合，個人化通知設定則以底部面板開啟；頂部只保留通告圖書館版號和最後更新，讓卡片先出現。「每天自動更新」說明、免責提示、來源／資料／資產統計和診斷入口則收進桌面側欄最底部、預設關閉的「網站資料及診斷」，手機不顯示。桌面仍可按需要查看。

完整的 Supabase、Vercel、GitHub Actions secret 與驗收步驟見 **[`PUSH_SETUP.md`](PUSH_SETUP.md)**。VAPID 私鑰只放 GitHub Actions，絕不可放到 Vercel 或瀏覽器。

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

1. 每日定時執行 `core.py`；不論是否使用 Supabase，都會重建公開的 `cache.json`。
2. 執行 `enrich.py` 的增量標籤／欄位抽取。
3. 如已設定 `VAPID_PRIVATE_KEY`，執行 `notify.py`，先做每位匿名訂閱者的支部＋興趣交集和合併，再發送 Web Push。
4. 自動提交 `cache.json`、`enrich.json` 和 `fingerprints.json`，讓前端從 GitHub Raw 讀取最新資料。

## 下一步建議

如果你把你現有 repo 貼上來，我可以下一輪直接做：

- 對照你現有 `core.py` 修補崩潰點
- 併回你原本已成功抓到的來源
- 補埋 Vercel / Raw CDN / GitHub Actions 實際部署細節
