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
- `index.html`：靜態前端（多分頁 / 手風琴 / 時間視窗 / 支部標籤 / 分享（文案＋社交＋IG 分享圖 4:5，另設 📱 Story 版 1080×1920＋內文轉圖，多版可一次過分享／合併成一份多頁 PDF）/ 匿名通知設定 / 問題回報／意見反映）。通告專屬頁：每張通告有深鏈 `?n=<16hex>`（同 push ID 同源），單一 ID 著陸會直接彈出該通告嘅專屬頁（標題＋區徽＋截止/對象/費用/名額＋開附件/分享/複製連結），分享面板「複製連結」一撳攞鏈，貼上 IG Story link sticker 就形成 Story → 圖書館閉環
  - IG 分享圖（2026-09-21；**2026-09-22 由「深藍底＋字」重寫成 12 款設計**）：瀏覽器 canvas 即畫 1080×1350（feed 4:5）／1080×1920（Story），用人者裝置字體同記憶體，**唔經任何 Vercel function／storage**；取代 2026-09-16 移除嘅 server-side render（PyMuPDF）——Vercel 爆容量嘅真兇係 Python 依賴入 bundle（見 VERCEL_EMERGENCY_CLEANUP_2026-09-19.md），唔係圖片儲存，所以 server render 唔會返嚟。12 款、md5 揀款、縮圖 picker 見「分享通告」一節
  - 問題回報／意見反映（2026-09-24）：頂欄叮噹旁一粒 **💬**（手機 sticky 頂欄；桌面喺 🔔 通知隔籬）。入去已經有兩個分頁，唔另外加下拉。頁尾／側欄文字入口保留。問題回報填 **APP + 什麼問題**；意見反映填 **有什麼意見**（例如想要什麼幫助）；**姓名／電郵／電話全部選填**。表單 `POST` 去 Scout Admin 嘅 Apps Script（[playerkousas-rgb/scout-admin](https://github.com/playerkousas-rgb/scout-admin)），無本站後端、唔經 Vercel function。回歸測試：`node test_report_feedback.js`
- `subscription_catalog.json`：受控官方支部、訓練、服務、活動與比賽訂閱選項（不設自由文字標籤）
- `subscription_tagging.py`：由標題、PDF 文字與參加對象產生可靠的支部／訂閱 IDs
- `push-client.js`、`sw.js`：瀏覽器 LocalStorage、Service Worker 與 Web Push 收件處理
- `notify.py`：GitHub Actions 的匿名 Push dispatcher（先聚合每個訂閱者的命中）
- `check_cache_fresh.py`／`check_local_gain.py`：本機補跑（`run-local-scrape.bat`）舊版嘅兩個閘門（前者判斷「cache 係咪今日」，後者判斷「本機有冇 GitHub 未有嘅通告」）。**2026-09-14 起 `run-local-scrape.bat` 已唔再 call 佢哋**（見下文「本機補漏」），檔案同 `test_check_local_gain.py` 保留作參考／診斷用途
- `subscription_stats.py`：管理員本機執行，用 service key 統計訂閱人數及各支部／項目的訂閱數（只出彙總，不出個資）；`schema.sql` 末段亦有對應 SQL
- `api/push_config.py`、`api/push_subscriptions.py`：不讓瀏覽器直連 Supabase 的窄 Web Push API
- `api/pdf_proxy.py`：stdlib-only PDF byte bridge（2026-09-21）。「分享 → 轉換內文做圖」用 pdf.js 喺用戶部機 rasterize，但 49 個來源站大部分冇 CORS，所以呢個 function 淨係過橋攞 bytes：零依賴、零儲存、4MB 上限、`%PDF` magic 檢查、只 proxy cache.json 列出嘅通告 URL（防 open-relay），回應俾 Vercel edge cache 一星期
- `serve_local.py`：本機同時提供靜態頁 + `/api/push-*`
- `manifest.webmanifest`、`icon.svg`、`icons/`：PWA 安裝設定與全套圖示（見下文「圖示」）
- `.github/workflows/scrape.yml`：每日抓取、增量 enrichment、匿名 Web Push 與自動更新
- `.github/workflows/scrape-appstore.yml`（2026-09-24，**未開啟**）：未來取代 scrape.yml 嘅版本——core 抓取後加掃 SCOUT APP STORE（`tools/scrape_appstore.py`，anon key 唯讀、baseline 防舊 app 風暴、url 去重）。而家只掛 workflow_dispatch，啟用時先開 schedule 並停用 scrape.yml；唔使新 secrets
- `icons/orgs/` + `tools/fetch_org_logos.py` + `tools/build_org_avif.mjs` + `.github/workflows/org-icons.yml`（2026-09-21）：49 個童軍組織（總會＋5 地域＋43 區）官方徽號，正規化成 256/64 AVIF（每個 3–11KB），出 Story 時做區徽角標用。官方檔全部喺 scout.org.hk「Regions and Districts」頁；官方補捉行 `org-icons` workflow（Actions 手動掣）一次搞掂，預覽喺 `/icons/orgs/preview.html`
- `icons/awards/` + `tools/build_award_avif.mjs`（2026-09-24）：童軍總會四支部最高獎章——幼童軍**金紫荊獎章**、童軍**總領袖獎章**、深資童軍**榮譽童軍獎章**、樂行童軍**貝登堡獎章**——正規化成 256/64 AVIF（幾何同 orgs 一致：contain 232／60 置中透明底），作 4 個「進度追蹤」小工具（cubsbadge／scoutbadge／vsbadge／roverbadge）嘅 ICON；`awards.json` 係支部→獎章對照表，母圖放 `icons/awards/src/`，Vercel 只上 avif＋awards.json（見 `.vercelignore`）
- `appstore.json` + `tools/fetch_appstore.mjs`（2026-09-24）：直連 **SCOUT APP STORE**（`playerkousas-rgb/website`）嘅 Supabase。設定（`supabase_url`＋公開 `anon_key`、表結構、RPC、RLS 備忘）同今日 snapshot（pages／categories／apps）一次過放喺 `appstore.json`；anon key 屬公開金鑰、RLS 限唯讀，可安全 commit。要 refresh snapshot 就喺你部機或 Actions 行 `node tools/fetch_appstore.mjs`（sandbox 出唔到 supabase.co）。**寫入**（改 store 內容／icon 等）要 service role key 或 admin 登入，website repo 冇 commit 呢啲——要喺 Supabase Dashboard 攞
- `story_queue.py` + `.github/workflows/story-queue.yml`：手動清單工具（只保留 `workflow_dispatch`）。按 HKT 今日 `captured_date` join `enrich.json`，只收齊標題、頒佈日期、來源、四類分類、地域、原文附件連結、截止、對象、費用嘅通告；無張數上限。「Scout System 小工具」及無法歸入訓練／服務／活動／比賽的通告都唔入清單。每日發布流程會喺同一個 Story workflow 內暫存 queue，不觸發此手動工具
- `tools/render_story_templates.py`：Pillow 12 款 Story 模板出 1080×1920 PNG + JPEG。PNG 供專屬頁 hero／人工下載，JPEG 供 Meta 發佈；右上直貼真區徽（fallback 區→地域→總會）、CJK 逐字斷行、底部四卡使用截止／對象／費用／頒佈實數，並帶 `經 通告圖書館整理 @noscout.system` credit。訓練／活動／服務／比賽每類各設八句粵語標語，同一日同分類逐張輪流用下一句（超過八張先循環），唔會同一日撞句；除咗呢八句固定文案，唔會額外加「報名」宣傳字眼。每張圖的 QR 直接開原文附件（優先 `pdf_url`，欠缺時用 `url`），不經圖書館頁面。款式由 `md5(url)` 定死，同一通告永遠同款。Actions runner 安裝 Noto Sans CJK、Pillow 及 `qrcode[pil]`
- `.github/workflows/story-draft.yml` + `.github/scripts/publish_instagram_stories.py`：每日只排一次 15:30 HKT（07:30 UTC），同一個 run 完成篩選、PNG/JPEG 出圖、更新 `stories` branch、發佈所有齊料 Story；沒有本地張數上限，亦沒有失敗重試／補發／重排。原有手動 `workflow_dispatch` 保留，預設只出草稿／preview artifact，不發 IG；明確選 `publish=true` 才會手動發佈。專屬頁讀取 branch 級 `stories/index.json` 顯示最近 7 日 PNG hero，raw.githubusercontent 承載圖片，Vercel 儲存零新增。Instagram 發佈所需 `INSTAGRAM_USER_ID`、`INSTAGRAM_ACCESS_TOKEN` 只放 GitHub Actions Secrets；Facebook Login 預設用 `graph.facebook.com`，Instagram Login 可用 repo variable `INSTAGRAM_GRAPH_API_BASE=https://graph.instagram.com`。Meta API 不支援 Story link sticker

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
# 爬蟲依賴（requests / beautifulsoup4 / playwright）刻意唔放喺 repo 根目錄：
# Vercel 會自動把根目錄 requirements.txt pip install 入 **每個** api/*.py
# function bundle，而且冇 tree-shaking —— playwright 一個套件解壓後 137MB，
# 乘開幾十個 retained deployment 就係 2026-09-17 Functions Storage 爆額嘅病源。
pip install -r .github/requirements-scrape.txt
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
node test_report_feedback.js    # 問題回報／意見反映 payload 對齊 Scout Admin；預覽頁／Cloudflare 注入已清走
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
- **IG 分享圖（2026-09-22 大改：12 款設計）**：分享面板撳「產生 IG 分享圖」即
  喺用戶部機用 canvas 畫（零 function、零 storage）。12 款 = 訓練 3 色斜帶／比賽金框黑／
  活動軍綠／服務 WANTED 羊皮紙／通告 6 款 UNC 風（瞄準鏡・絕密檔案・故障霓虹・羊皮紙・
  紅 WANTED・黑金），**同 Actions 嘅 Pillow 草稿（`tools/render_story_templates.py`）
  同一套視覺語言**，連揀款算法都一樣（`md5(pdf_url||url||title) % pool`，見下面
  `md5Hex`）——所以同一張通告，app 出嘅圖同 Story 草稿係同一款。撳 4:5／9:16 切換
  feed／Story 版，下面有 12 款縮圖可以即場換款（縮圖就係實際效果）。區徽（`icons/orgs`
  嘅 AVIF）直貼右上角（唔加白框），fallback 鏈 區 → 地域 → 總會。Story 版另加直連原文 QR。
  分類標語**只喺自動化先加**（Actions 每日 Story，同埋 `?batch=1` 出圖台）；分享面板手動出圖
  唔加標語，QR 左邊留位，用戶喺 IG 自己加字更彈性（2026-09-24 決定）。
- **內文轉圖（PDF → 圖）多版處理（2026-09-25）**：撳「📄 轉換內文做圖」之後，
  多版通告會多三粒掣：
  - 「📤 分享全部版數」（手機）：一個 Web Share 面板載晒所有版嘅 PNG，
    揀 WhatsApp 就一次過傳晒（換版編號喺檔名），**唔會再加任何文字**。
  - 「📄 合併成一份 PDF」：喺用戶部機砌一份真多頁 PDF（`buildPdfBytes`，
    零依賴：每版 JPEG 用 `DCTDecode` 直嵌，xref 偏移自己寫）——一個檔案＝全部版。
    合併好出「⬇️ 下載 PDF」（可以直接拖入 WhatsApp Web／電腦版對話）同
    「📤 分享 PDF」（手機）。**點解要 PDF**：瀏覽器剪貼板一次只放得「一張」圖
    （Chrome 明文限制），所以多過一版冇可能靠 Ctrl+V 一次過貼晒；PDF 唔會被
    WhatsApp 二次壓縮，收件人一開就睇齊。
  - 「💾 全部版數」照舊逐版存 PNG（File System Access／逐張下載）。
  單版通告維持原狀（下載圖片／複製圖片／分享圖片）。
- **圖片分享唔加文字（2026-09-25）**：IG 圖同內文圖嘅「貼去 WhatsApp／Telegram…」
  改用 `share-launch.html#target=…&mode=image`：只複製張圖、只開平台本身，
  **唔會預填任何文案**（張圖已經有齊內文，再加文字好奇怪）。`mode=image` 明文
  拒絕 `text`／`url`（防第日有人偷偷加返）。系統分享（手機）本身就只傳檔案。
- **電腦分享先試 app、再退網頁（2026-09-24）**：WhatsApp／Telegram 嘅「分享至」同 PDF／IG 圖「貼去」
  共用 `share-launch.html`。先試 `whatsapp:`／`tg:`，頁面仍有焦點且可見 2.5 秒就轉去真正網頁版，
  唔經下載頁。文字分享會帶文案／連結去 app 同網頁版（Telegram Web A 用 `tgaddr`）；
  圖片分享用 `mode=image`，唔帶文字（見上）。
  瀏覽器唔提供安裝／啟動結果：失焦、隱藏或離頁會取消自動跳轉，避免 app 開咗後又開網頁；
  如果只係取消系統提示，請用一直可見嘅「改用網頁版」。亦可以「再試開電腦版」。
  網頁版仍可能要登入；唔會代用戶登入或發送。分享資料只放 URL fragment，唔送本站伺服器。
  圖片先開始寫剪貼板、再開分享頁，揀對話後 Ctrl／⌘+V 貼圖；唔會用文案覆蓋剪貼板張圖，
  亦唔會幫用戶預填文字。
  Facebook／X 繼續開網頁，LINE 用官方分享連結，電郵用系統 `mailto:`（無法猜用戶嘅 webmail）。
  手機連結／系統分享保持原狀。分享面板維持精簡，冇加返文案預覽框同各區說明字。
> 「分享圖片」（PDF → JPG）功能已於 2026-09-16 移除：附加價值有限，而佢令每個 Vercel
> deployment 嘅 function bundle 包埋 PyMuPDF（約 110MB），直接導致 Functions Storage
> 爆額（見下文「Vercel 用量」一節）。分享連結、複製網址／文字等功能不受影響。

本機測試：

```bash
python serve_local.py            # http://localhost:8000/index.html，/api/push-* 已掛載
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

### 本機補漏（`run-local-scrape.bat` + `run-local-scrape-logged.bat`）

雲端 Action 係主線；本機（Windows 工作排程器）係後備補底。**2026-09-14 起本機流程縮到最短，兩個閘門全部移除**：

1. 由 GitHub 下載最新（`git pull --rebase --autostash`）
2. `python core.py --force` —— 全網重新巡邏，唔理 cache 有幾 fresh
3. `python enrich.py --verbose` —— 增量抽 PDF 文字
4. 有任何改動 → `commit` + `push`。完。

**移除咗嘅兩個閘門**（舊版靠呢兩個決定「推唔推」，正正係「網站時間戳唔郁」嘅根源）：

- ~~freshness gate~~：舊版「`check_cache_fresh.py`：GitHub 今日已 push 過 → 本機跳過」。只要 Action 成功，
  本機嗰日就完全唔檢查 —— Action「成功但漏咗某個來源」嗰種情況永遠冇人補到。
- ~~gain check~~：`check_local_gain.py` 逐則比較本機 cache 同 `origin/main`，「冇額外發現就唔 commit」。
  結果係大多數日子本機行完都唔 push，網站「更新時間」原地踏步，用户無從確認本機到底有冇行。

而家冇任何「內容等價就唔推」嘅判斷：`core.py` 每次 run 都會重寫 `cache.json` 嘅 `last_updated`
（`core.py` 內 `now_str = hkt_now_str()` → `build_grouped_cache(...)`），所以**每次成功 run 必定有 diff →
必定 push → 網站時間戳每日必定移動**，呢個就係用户驗證本機有冇行嘅唯一憑據。
`check_local_gain.py` / `check_cache_fresh.py` 仍然留喺 repo（`test_check_local_gain.py` 照跑），
只係 `run-local-scrape.bat` 唔再 call 佢哋。

其他規則：

- **開工先清場**（自癒）：清走殘留 `.git\index.lock`、abort 半成品 `rebase`／`merge`／`cherry-pick`，
  再 `git reset -q HEAD`（淨係 unstage，工作區改動一個字都冇損）+ 還原三個資料檔。
  呢步係 2026-09-14 事故嘅正解：上次 run 死咗喺 `git add` 之後、`git commit` 之前，index 留低暫存改動，
  之後每日 `git pull --rebase` 都俾 `cannot pull with rebase: Your index contains uncommitted changes` 擋死，
  連「拉返修好嘅腳本」都拉唔到 —— 死循環。
- **殘餘一律棄置，唔搶救**：因為 `core.py --force` 會全網重抓一次，之前未 commit 嘅新通告今次會再發現返。
  只郁 `cache.json`／`enrich.json`／`fingerprints.json` 三個檔，你手頭改緊嘅其他檔一個字都冇損。
- **所有 pull 用 `--rebase --autostash`**：需要 Git for Windows 2.27 或以上；呢個亦係「任何其他檔
  未提交」唔再擋住每日排程嘅保險。
- **起手 `set PYTHONUTF8=1`／`PYTHONIOENCODING=utf-8`**：排程器會將輸出 redirect 落 log 檔，
  Windows 預設用 cp950，`core.py`／`enrich.py` 一打 emoji 就 `UnicodeEncodeError` 死喺中途 ——
  呢個本身就係「留低未 commit 嘅 staged 殘餘」嘅來源之一。
- **git 身份自癒**：`user.name`／`user.email` 完全未設嘅話，寫入 repo-local 後備身份（唔郁你嘅 global 設定），
  否則所有自動 commit 必死。
- **rebase 衝突自動處理**（多數係本機同 Action 各寫一份 `cache.json`）：本機嗰份先留底喺
  `logs\conflict-backup\` 同 `backup/local-scrape` 分支，然後 `reset --hard origin/main` 繼續當日流程。
  舊版淨係 abort，留低一個永遠 push 唔出嘅本地 commit，之後每日撞同一個衝突。
- **有「已 commit 但未曾 push」嘅本機補跑結果會即刻補推**：`notify.py` 嘅同日 catch-up 只補發
  `captured_date` 係當日嘅項目，跨日留低嘅結果如果一直唔推，就會變成靜默冇通知。
- **死咗都會執手尾**：任何一步失敗都會行 `:failed` → 先試搶救本次成果（三個檔要讀得開 JSON 而且有真 diff，
  就 commit，能 push 就 push）→ 清走本次半成品（reset + checkout 三個資料檔）→ **自動重試一次** →
  仍然失敗先 exit 1。目的係「今日死 ≠ 聽日死」。
- **自己更新自己都得**：呢個 .bat 本身就係由呢個 repo pull 落嚟。如果頭先嗰 pull 改動咗腳本自己
  （例如你啱啱 merge 咗 PR），本次會即刻安全收工（exit 0，唔算失敗），下一次排程自然用新版行 ——
  cmd 係按 byte offset 慢慢讀 .bat，繼續行落去會「半舊半新」甚至讀錯位，呢種失敗最難睇。
  **呢個係「排程改指 repo 內腳本」之後先至真正生效嘅保護。**
- **GitHub 郁唔到 ≠ 今日唔使補底**：`git pull` 失敗會分情況 —— rebase 衝突先處理；斷網／授權
  則照樣巡邏全部來源（成果留本地，之後任何一日返到網自動補推）。舊版係「GitHub 郁親 → 本機當日完全冇檢查」再 exit 1。
- **`no_change` 會 exit 1**：`core.py` exit 0 但 `cache.json` 完全冇變 = `last_updated` 冇移動 =
  今日網站時間戳唔會動，即係用戶賴以確認嘅訊號斷咗，所以當失敗處理（Task Scheduler 履歴會顯示紅色）。
- log 喺 `logs\scrape.log`（UTF-8，`logs/` 已 gitignore，過 2 MB 自動轉名做 `scrape.log.1`）。
  喺 cmd 睇請先 `chcp 65001`，否則係亂碼：
  `powershell -c "Get-Content -Encoding UTF8 logs\scrape.log -Tail 60"`。

> **⚠️ 排程器指去邊度？** Task Scheduler 每日 05:00 行嘅如果係 `C:\Users\User\ScoutPushSecrets\run-local-scrape-logged.bat`
> （repo 以外嘅舊版 copy，child 內硬編碼 `cd` 去 repo 路徑），咁上面所有修改佢一律收唔到 ——
> 佢唔會 pull 自我更新。請把「動作/Actions」嘅「程式或指令碼」改成 **repo 內**嘅
> `run-local-scrape-logged.bat`，「起始於」填 repo 根目錄；之後排程行嘅永遠係 repo 最新腳本。
> `ScoutPushSecrets` 舊檔留低唔郁即可。


## Vercel 用量：Functions Storage 爆額（2026-09-16 診斷）

**症狀**：Hobby 用量頁 **Functions Storage 10.49 GB / 10 GB（已超限）**、
Deployment Storage ~930 MB 持續上升（8 月中 ~190 MB 起）。

**唔係 bandwidth／唔係真人流量**：站內訪客計數器（只有跑 JS 嘅真人才 +1）累計約 400 次、
Web Push 訂閱者 7 個；每次開頁由 Vercel 落嘅資料約 0.3 MB，全月真人流量 < 0.5 GB。

**真因（兩條曲線都對得上）**：

1. `api/render.py` 嘅 function bundle 包埋 **PyMuPDF**（連內建 CJK 後備字型，安裝後約
   **110 MB／個部署**）。Vercel 會**保留每個 deployment 嘅 function bundle**，而 Hobby
   Functions Storage 上限 10 GB。
2. **每次 commit 落 main 都開一個新 deployment** —— 包括 bot 嘅 `[skip ci]` commit
   （`[skip ci]` 只 skip GitHub Actions，**skip 唔到 Vercel**）。9 月 5-6 日（加入產生圖片
   功能嗰兩日，曲線起飛點）起約 95 個部署 × ~110 MB ≈ 10.5 GB → 爆額。
   加入功能之前 push_config / push_subscriptions 嘅 bundle 得幾 MB，所以 9/5 前貼地 0。
3. Deployment Storage 同一個病：每個部署保留成個 repo ~9 MB —— 其中 `cache.json` 3.35 MB +
   `enrich.json` 1.58 MB **根本冇人由 Vercel 讀**（前端只讀 GitHub Raw）—— × ~100 個部署 ≈ 930 MB。

**即時止血（Vercel Dashboard 手動，兩步）**：

1. **Deployments → 刪走舊 deployments**（只留最新 production + 最近一兩個）→
   即時釋放近 10 GB Functions Storage。刪唔到 alias 中嘅 production 係正常。
2. **Settings → Git → Ignored Build Step** 貼以下一行（exit 0 = skip build）：
   只改資料檔／報告嘅 commit 唔再觸發 build，部署頻率由每日 6+ 次跌返每日 ~1 次：

   ```bash
   git diff --name-only HEAD^ HEAD | grep -qvE '^(cache\.json|enrich\.json|fingerprints\.json|subscription_stats\.json|.*\.md|logs/.*)$' || exit 0; exit 1
   ```

**長期（已喺 repo 內）**：

- `.vercelignore`：每個 deployment 由 ~8.4 MB 降到 ~1.2 MB（Deployment Storage 增長慢 7 倍，
  同時唔再公開 `cache.json` 等 5 MB 死重俾人／bot 下載）。
- `.github/workflows/vercel-prune.yml`：每週一自動刪走 >14 日嘅舊 deployments
  （保留最近 5 個 + 最新 production）。需加 `VERCEL_TOKEN` 同 `VERCEL_PROJECT_ID` 兩個
  secrets；未加時 workflow 自動跳過，唔會紅。
- 2026-09-16 已**移除**產生圖片功能（`api/render.py` + 前端分享圖片 UI + `api/requirements.txt`）。

> ⚠️ **呢一日嘅結論「Functions Storage 病源消失」係錯嘅** —— 見下一節。


## Functions Storage 再爆（2026-09-17 覆診：真正病源係根目錄 `requirements.txt`）

**症狀**：移除 `api/render.py` 之後一日，**11.82 GB / 10 GB**（比前一日 10.49 GB 再升）。
用戶懷疑係「本機 push 把之前 DELETE 咗嘅檔加返」。

**呢個懷疑已排除**：查 `c1854af`「Local backup scrape」只改咗 `cache.json` /
`enrich.json` / `fingerprints.json` 三個資料檔，冇還原任何被刪嘅 code；
`api/render.py` 同 `api/requirements.txt` 依然唔喺 repo 入面。

**真正病源：根目錄 `requirements.txt` 列住 `playwright>=1.52.0`。**

Vercel Python runtime 嘅官方行為（[Python runtime 文件](https://vercel.com/docs/functions/runtimes/python)）：

> “Define dependencies in `pyproject.toml` (with or without a `uv.lock`),
> `requirements.txt`, or a `Pipfile` …”
> “By default, Python Vercel Functions include all files from your project that
> are reachable at build time. **There is no automatic tree-shaking for Python.**”

即係：Vercel 會把 **repo 根目錄** 嘅 `requirements.txt` 全套 pip install 落
**每一個** `api/*.py` function bundle，完全唔理 `api/` 有冇 import 佢。

實測（`pip download` + `unzip` + `du`）：

| 套件 | wheel | 解壓後 |
|---|---|---|
| `playwright` 1.63.0 | 46 MB | **137 MB**（`playwright/driver` 佔 135 MB） |
| `lxml` / `cryptography` / `requests` / `bs4` / `pywebpush` | — | ~30 MB |

→ 每個 function bundle **~170 MB**。而 `api/push_common.py` /
`api/push_config.py` / `api/push_subscriptions.py` 其實係 **100% 標準庫**
（`base64` `hashlib` `json` `os` `re` `datetime` `http.server` `pathlib`
`typing` `urllib`）—— 一個第三方套件都唔使，137 MB 純綷係死重。

`Functions Storage` = 每個 **retained** deployment × 每個 bundle × 每個 region。
Hobby 預設 retention **30 日**，而呢個 repo 每日有 ~3 個 bot commit
（`[skip ci]` 只 skip GitHub Actions，**skip 唔到 Vercel**）
→ 數十個部署 × ~170 MB ≈ 10 GB+。

所以 2026-09-16 斬咗 `api/render.py`（PyMuPDF ~110 MB）只係換咗個更大的：
根目錄 `requirements.txt` 嘅 playwright（137 MB）一路都喺度，
`push_config` / `push_subscriptions` 兩個 function 照樣被塞爆。

**修法（今次一次過做齊三層，全部已喺 repo 內）**：

1. **斬斷來源** —— 根目錄 `requirements.txt` 清空（佢嘅職責而家只係
   「Vercel Function 部署 runtime 依賴」，答案係零），爬蟲／通知依賴搬去
   `.github/requirements-scrape.txt` 同 `.github/requirements-notify.txt`
   （`.github/` 唔會上載去 Vercel）。順帶修好 `notify.yml` 口口聲聲話
   「絕不安裝 Playwright」但其實一路都裝緊嘅 bug，同移除全 repo 冇人
   import 嘅 `lxml`。
2. **雙保險** —— `requirements.txt` / `pyproject.toml` / `Pipfile` /
   `uv.lock` / `api/requirements.txt` / `.github/` 全部加入 `.vercelignore`，
   Vercel 連睇都睇唔到；`vercel.json` 加 `excludeFiles`，function bundle 由
   ~1.2 MB 靜態檔再降到只剩 `api/*.py` + `subscription_catalog.json`（~120 KB）。
3. **清走存量** —— 單靠上面兩步 **唔會** 釋放已經食咗嘅 11.82 GB（舊部署仲喺度）。
   所以要配合：
   - `.github/workflows/vercel-retention.yml`：用 REST API 把 project 嘅
     Deployment Retention Policy 由 Hobby 預設 30 日縮到
     preview 7d / production 30d / canceled 1d / errored 7d。
     ⚠️ 通用嘅 `PATCH /v9/projects/{id}` **寫唔到** `deploymentExpiration`
     （會回 `400 should NOT have additional property`，佢係 read-only）；
     要用專用 sub-resource
     `PATCH /v9/projects/{projectId}/deployment-expiration`，
     body 用 `{"expiration":"7d","expirationProduction":"30d",...}`
     （字串 duration，唔係 `expirationDays` 數字）。
   - `.github/workflows/vercel-prune.yml`：新增 `mode=purge`（一次過刪走
     所有舊部署，只留最近 3 個 ＋ alias 中嘅 production）同 `dry_run`。
     要即刻釋放 11 GB 就用 `mode=purge` 手動 dispatch 一次。
   - `.github/workflows/vercel-bundle-guard.yml`：每次 push 都驗證
     「`api/` 只用標準庫」＋「根目錄冇會令 Vercel pip install 嘅 manifest
     漏網」＋「上傳體積唔超 budget」，防止日後有人無意中加返。

### 區徽工具檔爆 budget（2026-09-22：check 4 紅 → 綠）

Check 4 一度紅：上傳 231 個檔、4.15 MB（budget 2 MB）。病源係新入庫嘅
`icons/orgs/` **三類 Vercel 完全唔使嘅檔**（49 個組織 × 每款）：

| 檔 | 邊個用 | 應唔應該上 Vercel |
| --- | --- | --- |
| `icons/orgs/*-256.png`（49 隻，~3.5MB） | Pillow 出 Story 草稿先用；Pillow 喺 GitHub Actions 跑、讀 git checkout | ❌ 唔使 |
| `icons/orgs/src/`（官方原圖 9.2MB） | `tools/fetch_org_logos.py` 捉落嚟嘅母圖 | ❌ 唔使 |
| `icons/orgs/official_urls.json` | 上面嗰個工具嘅資料 | ❌ 唔使 |
| `icons/orgs/orgs.json` ＋ `*-256.avif` ＋ `*-64.avif` | **前端 badge runtime**（`fetch('icons/orgs/orgs.json')` 係相對路徑，行 Vercel） | ✅ 必須留 |

三類一 `.vercelignore`，上傳即由 4.15 MB 跌到 **0.97 MB（＋2 個 PWA 圖示豁免）**。
`.github/scripts/vercel_bundle_guard.py` 同時加咗 `BUDGET_ALLOWLIST`：
`icons/icon-512.png`（PWA 安裝）同 `icons/icon-maskable-512.png` 係部署真係要嘅
（`manifest.webmanifest` 指住佢哋，ignore 咗安裝會爛），所以佢哋**唔計 budget**
但一定要喺 report 度交代理由 —— 想加新檔入豁免就要答「冇咗佢 Vercel 上面會壞乜」。
**唔准為咗令 check 4 變綠而 ignore 呢兩個 PWA 圖示。**

**你而家要做嘅兩件事**（repo 改唔到 Vercel 帳戶設定）：

1. 確認 `VERCEL_TOKEN` ＋ `VERCEL_PROJECT_ID` 兩個 Actions secrets 已設。
   未設嘅話 prune / retention 兩個 workflow 會 **靜靜地跳過**，咩都唔會清到 ——
   而家佢哋會喺 run summary 出 ⚠️ warning，唔再係無聲無息。
2. Actions → **Vercel Deployment Prune** → Run workflow →
   `mode=purge`、`dry_run=false` → 即刻釋放存量。
   之後再跑一次 **Vercel Retention Policy** 把 retention 縮短，
   等佢日後自動清。


## 下一步建議

如果你把你現有 repo 貼上來，我可以下一輪直接做：

- 對照你現有 `core.py` 修補崩潰點
- 併回你原本已成功抓到的來源
- 補埋 Vercel / Raw CDN / GitHub Actions 實際部署細節
