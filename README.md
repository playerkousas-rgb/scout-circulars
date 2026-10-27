# 香港童軍通告聚合器 v4/v5 骨架

> **2026-10-27 資料保留更新：** 程式碼保留 history；日常 JSON 改由 `data` 分支單一最新快照提供，
> 每日備份保留 30 日；Story 圖片改用臨時儲存，不再寫入 Git。
> main 的 JSON 只作種子／測試用途，不再每日更新。
> 部署、公開 URL、本機排程及救援步驟以 [DATA_STORAGE.md](DATA_STORAGE.md) 為準；下方舊版日常 commit 說明已被取代。

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
- **登記漏斗（2026-10-22）**：`api/push_events.py` + `push_funnel_daily` 表。只記「打開面板、按啟用、成功登記、只儲存篩選、iPhone 未加入主畫面、權限被拒、伺服器 4xx/5xx」等固定事件名的每日次數，**冇** endpoint、token、IP、user agent 或自由文字。用嚟一眼分清楚「推送壞咗」同「根本冇人完成設定」——舊版冇任何漏斗數據，所以睇到 8 個登記也判斷唔到邊一步走失。`stats.html` 同 `subscription_stats.py` 有對應區塊；`serve_local.py` 亦已掛 `/api/push-events`
- `api/push_config.py`、`api/push_subscriptions.py`、`api/push_events.py`：不讓瀏覽器直連 Supabase 的窄 Web Push API
- `api/pdf_proxy.py`：stdlib-only PDF byte bridge（2026-09-21）。「分享 → 轉換內文做圖」用 pdf.js 喺用戶部機 rasterize，但 49 個來源站大部分冇 CORS，所以呢個 function 淨係過橋攞 bytes：零依賴、零儲存、4MB 上限、`%PDF` magic 檢查、只 proxy cache.json 列出嘅通告 URL（防 open-relay），回應俾 Vercel edge cache 一星期
- `serve_local.py`：本機同時提供靜態頁 + `/api/push-*`
- `manifest.webmanifest`、`icon.svg`、`icons/`：PWA 安裝設定與全套圖示（見下文「圖示」）
- `.github/workflows/scrape.yml`：每日抓取、增量 enrichment、匿名 Web Push 與自動更新
- `.github/workflows/scrape-appstore.yml`（2026-09-24，**未開啟**）：未來取代 scrape.yml 嘅版本——core 抓取後加掃 SCOUT APP STORE（`tools/scrape_appstore.py`，anon key 唯讀、baseline 防舊 app 風暴、url 去重）。而家只掛 workflow_dispatch，啟用時先開 schedule 並停用 scrape.yml；唔使新 secrets
- `icons/orgs/` + `tools/fetch_org_logos.py` + `tools/build_org_avif.mjs` + `.github/workflows/org-icons.yml`（2026-09-21）：49 個童軍組織（總會＋5 地域＋43 區）官方徽號，正規化成 256/64 AVIF（每個 3–11KB），出 Story 時做區徽角標用。官方檔全部喺 scout.org.hk「Regions and Districts」頁；官方補捉行 `org-icons` workflow（Actions 手動掣）一次搞掂，預覽喺 `/icons/orgs/preview.html`
- `icons/awards/` + `tools/build_award_avif.mjs`（2026-09-24）：童軍總會四支部最高獎章——幼童軍**金紫荊獎章**、童軍**總領袖獎章**、深資童軍**榮譽童軍獎章**、樂行童軍**貝登堡獎章**——正規化成 256/64 AVIF（幾何同 orgs 一致：contain 232／60 置中透明底），作 4 個「進度追蹤」小工具（cubsbadge／scoutbadge／vsbadge／roverbadge）嘅 ICON；`awards.json` 係支部→獎章對照表，母圖放 `icons/awards/src/`，Vercel 只上 avif＋awards.json（見 `.vercelignore`）
- `appstore.json` + `tools/fetch_appstore.mjs`（2026-09-24）：直連 **SCOUT APP STORE**（`playerkousas-rgb/website`）嘅 Supabase。設定（`supabase_url`＋公開 `anon_key`、表結構、RPC、RLS 備忘）同今日 snapshot（pages／categories／apps）一次過放喺 `appstore.json`；anon key 屬公開金鑰、RLS 限唯讀，可安全 commit。要 refresh snapshot 就喺你部機或 Actions 行 `node tools/fetch_appstore.mjs`（sandbox 出唔到 supabase.co）。**寫入**（改 store 內容／icon 等）要 service role key 或 admin 登入，website repo 冇 commit 呢啲——要喺 Supabase Dashboard 攞
- `story_queue.py` + `.github/workflows/story-queue.yml`：手動清單工具（只保留 `workflow_dispatch`）。按 HKT 今日 `captured_date` join `enrich.json`，只收齊標題、頒佈日期、來源、四類分類、地域、原文附件連結、截止、對象、費用嘅通告；無張數上限。「Scout System 小工具」及無法歸入訓練／服務／活動／比賽的通告都唔入清單。每日發布流程會喺同一個 Story workflow 內暫存 queue，不觸發此手動工具
- `tools/render_story_templates.py`：Pillow 12 款 Story 模板出 1080×1920 PNG + JPEG。PNG 供專屬頁 hero／人工下載，JPEG 供 Meta 發佈；右上直貼真區徽（fallback 區→地域→總會）、CJK 逐字斷行、底部四卡使用截止／對象／費用／頒佈實數，並帶 `經 通告圖書館整理 @noscout.system` credit。訓練／活動／服務／比賽每類各設八句粵語標語，同一日同分類逐張輪流用下一句（超過八張先循環），唔會同一日撞句；除咗呢八句固定文案，唔會額外加「報名」宣傳字眼。每張圖的 QR 直接開原文附件（優先 `pdf_url`，欠缺時用 `url`），不經圖書館頁面。自動每日 batch 會先用每類本身的 AI 底圖；同日同類再有通告、否則要重覆底圖時，會依序借用 `unc_scope`、`unc_topsecret`、`unc_glitch` 三張「通告」底圖（仍保留原本訓練／活動／服務／比賽的分類、CTA 和資料），三張都用過才重覆。Actions runner 安裝 Noto Sans CJK、Pillow 及 `qrcode[pil]`
- `.github/workflows/story-draft.yml` + `.github/scripts/publish_instagram_stories.py`：每日只排一次 12:00 HKT（04:00 UTC），同一個 run 完成篩選、PNG/JPEG 出圖、更新 `stories` branch、發佈最多 **5 張不重複**的齊料 Story；各類先一張，缺類由其他通告補位（可同類，不可同一通告），queue／renderer 硬限五張，publisher 超額或重複即拒絕，亦沒有失敗重試／補發／重排。**發佈改為「驗證式閘門」而唔係靠等幾秒賭運氣**（2026-10-01 嗰日 5 張全部死喺 `9007 / 2207027`「媒體素材尚未準備好發佈」之後加）：
  1. **張圖要真係公開攞到先交俾 Meta**——runner 自己 GET 一次，要 200/206＋JPEG magic＋大細同本機一致，最多等 180 秒（每 3 秒一次）。Meta 係自己去抓 `image_url`，所以呢一步順便焫熱 CDN
  2. 圖片 URL 改用 **commit SHA 嘅 raw 連結**（唔再用 `stories` branch ref）：branch 路徑 force-push 之後，raw CDN 可以幾分鐘內都仲回舊嘢或者 404
  3. **container 要 `status_code=FINISHED` 先 `media_publish`**（每 3 秒 poll 一次、上限 120 秒）
  4. container 變 `ERROR`／`EXPIRED`／卡死 → **重建一次**。嗰個 container 從來冇 post 過，所以重建唔會出雙份；`media_publish` 本身就維持**一次過、唔重試**（佢係唯一「可能已經出咗」嘅 call）
  通告本身依然**唔會重新排隊、唔補發、唔順延到第二日**。成功會 log「image live in Xs / container ready in Xs」。另設 8MB 本機閘：Meta 上限 8MB，而 2026-10-01 換 AI 底圖之後 JPEG 由 ~130KB 升到 ~630KB（同一個 `train_blue` 模板 129KB → 407KB，重 3.2 倍），仲有 12 倍水位；將來底圖再重撞到頂，會喺出圖後即刻講明「要減底圖重量或者調低 `tools/render_story_templates.py` 嘅 JPEG quality」，唔會又變成一個謎。
  **順帶一提 2026-10-01 嗰次全軍覆沒嘅真正次序**：AI 底圖（commit `a5e4db7`，10-01 12:10 HKT merge）唔係兇手，張圖驗過係正常 baseline JPEG／1080×1920／YCbCr 三通道／冇 ICC；佢只係令 Meta 多咗幾秒處理，於是揭穿咗一個一直都喺度、靠「圖細所以僥倖贏 race」瞞住嘅 bug——create container 之後完全冇等就 publish。所以**唔應該退返向量底圖**，要修嘅係個流程。原有手動 `workflow_dispatch` 保留，預設只出草稿／preview artifact，不發 IG；明確選 `publish=true` 才會手動發佈。專屬頁讀取 branch 級 `stories/index.json` 顯示最近 7 日 PNG hero，raw.githubusercontent 承載圖片，Vercel 儲存零新增。Instagram 發佈所需 `INSTAGRAM_USER_ID`、`INSTAGRAM_ACCESS_TOKEN` 只放 GitHub Actions Secrets；Facebook Login 預設用 `graph.facebook.com`，Instagram Login 可用 repo variable `INSTAGRAM_GRAPH_API_BASE=https://graph.instagram.com`。Meta API 不支援 Story link sticker

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
const RAW_CACHE_URL = "https://raw.githubusercontent.com/YOUR_GITHUB_USER/YOUR_REPO/data/cache.json";
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

## 時間視窗

- 通告：**今天／7天／15天／30天／3個月／6個月**，以捕獲日期過濾。
- 小工具（Scout System）：**唔以日期分類**（2026-10-01 改）。入咗小工具分頁（來源「Scout System」或六個內設分類）之後，
  同一排掣只剩 **「今天」** 同 **「之前發布」**：
  - 「之前發布」＝全部已發布嘅小工具（包括今天，亦包括冇日期嘅舊工具），係預設值；
  - 「今天」＝今日新上架嘅小工具。
  - 兩套視窗完全脫鈎：喺小工具分頁揀邊個掣都唔會改到通告嗰邊，反之亦然。
    舊有「6個月視窗額外包含 6 個月以上小工具」嘅特例，同埋卡片上嘅「6個月以上」標籤，都一併取消。
  - 離開小工具分頁（全港／地域／區會混合清單）時，小工具照跟通告視窗，
    唔會一撳「今天」就成版舊工具跳出嚟；但左欄 Scout System 嘅數字永遠報小工具視窗嘅真實件數，
    撳入去見到幾多件就寫幾多件。
- **「有更新」綠燈（2026-10-06 用戶規則：Scout System 唔好一直著燈）**：側欄嘅綠色高亮
  （`.region.has-updates`／`.source-btn.has-updates`）同發光數字 badge（`.count-badge.hot`）
  同「件數」分開計。通告照舊跟目前時間視窗；**Scout System 只認「今日新上架」**
  （`toolIsNewToday()`＝小工具「今天」掣嗰個 days: 1、HKT 日起計嘅門檻）。
  小工具係長期資產，「之前發布」永遠有貨，用件數做燈號等於 24 小時長著；
  而家今日冇新上架 → Scout System 一欄、六個內設分類、「全部 (Scout System)」全部熄燈，
  過咗 HKT 午夜即刻熄（唔係等足 24 小時），但**數字照報全部件數**（撳入去見到幾多件就寫幾多件），
  Scout System 一欄嘅 tooltip 會寫「（今日冇新上架）」。全港列嘅燈號同樣只計今日新上架嘅小工具。
  回歸測試：`node test_scout_system_light.js`

## 通告分類

搜尋列仲有一排**分類**標籤：**全部／訓練／服務／活動／比賽／小工具／公布／未分類**。活動只涵蓋大露營、營火會及其他活動；比賽是獨立分類。舊資料的 direct `competition`（或舊 `activity:competition`）會向後相容顯示為「比賽」。

- **分類次序：先睇標題，標題唔肯定先至加 PDF 內文**。標題通常最多關鍵資訊（例如「童軍繩結訓練班」「射箭公開賽」「社區服務隊招募」）。
  - 標題有強證據（明確字眼）→ 直接分類，**唔會**被 PDF 內文其他字眼搶走。
  - **2026-10-03 用戶規則：標題有「公告／公布／公佈」＝公布**（例如「總部公告」「區總部公布」「D-26-05 - …區會公布」），排喺服務／比賽／訓練之前。
    唯一例外係賽果：「成績公布／結果公布／公佈結果／賽果公布」＝比賽類（2026-10-01 定咗）。
  - **2026-10-06（第二批）：標題有「嘉許計劃」＝公布**（同「獎勵計劃」「津貼計劃」同組），
    「卓越領袖嘉許計劃2027」唔會再被內文「服務記錄」搶去服務——同一計劃嘅附錄（主要日期及安排）
    同 2026 年獲嘉許名單一直都係公布，之前係同一件事三個標籤。
  - **2026-10-06（第二批）：標題只有參考文件字眼（名單／行事曆／章程／指引）＝公布**，
    唔可以再由內文搶走。「傑出表現成員地域總監嘉許2026 - 獲嘉許名單」之前係服務
    （內文一句「無私奉獻的服務精神」），同「卓越領袖嘉許計劃2026 - 獲嘉許名單」唔一致。
    ⚠️ 真正賽果（成績公布／結果公布）屬比賽，喺較早嘅分支已經截住，不受影響。
  - **2026-10-06：標題有明確活動字眼（活動／嘉年華／開放日／體驗日／分享會…）但冇更強字眼
    （服務／比賽／訓練／大露營／營火會／參考文件）→ 一律歸活動**，唔可以由 PDF 內文搶走。
    個案：「2027年童軍獎券籌募活動」內文有一句「獎券銷售獎勵比賽」，舊版因此顯示成「比賽」；
    而同一張通告嘅回條（標題一樣有「活動」）就一直係「活動」——同一件事兩個標籤。
    注意標題同時有「訓練班」等更強字眼時，仍然以更強字眼為準（「…訓練班 (活動通告第21/26號)」＝訓練）。
  - **2026-10-09 用戶規則（標籤錯個案）**：
    - 標題有「之行／之旅」嘅行程（考察、參觀、文化遊）＝**活動**，內文嘅「探訪」
      呢類字唔可以搶走服務（個案：「探索歷史典藏、清真文化與創新科技之行」）。
      護欄：「服務之旅」仍係**服務**、「…之旅簡介會」仍係**訓練**（更強字眼行先）。
    - 標題有「入會／招收／招募」（入會表格、招收新會員、會員招募）＝**公布**
      （行政文件）；但「工作人員招募」＝服務、「XX錦標賽-隊員招募」＝比賽、
      「XX訓練班學員招募」＝訓練，即係只喺標題冇更強字眼時先生效。
    - 「座談會」＝**訓練**（同講座／簡介會同類）；「便覽」（通告索引／摘要）＝
      **公布**（參考文件，內文包含晒全月通告字眼，唔可以用內文分類）。
    - 「研習」＝**訓練**（裸詞涵蓋研習班／研習坊／研習日；個案：「跨支部海洋公園
      研習日」P105/2026 俾兜底成公布）。`story_queue`／出圖台 regex 早已收「研習」，
      今次 `TRAINING_TERMS` 對齊，三份一致。競賽類研習班（「立划板競賽研習班」）
      維持競賽字眼行先＝**比賽**。
  - **2026-10-15 用戶規則（第二批錯標籤个案）**：
    - **「……通告【YYYY 年 M 月】」＋「N月份通告一覽」＋「通告便覽」＝月度摘要＝公布**，
      而且**永遠唔准睇內文**（`MONTHLY_DIGEST_TITLE_RE` 入 `is_reference_document()`、
      `REFERENCE_TITLE_TERMS` 加「通告一覽」）。個案：「九龍地域通告【2026 年 10 月】」
      （Summary_2026_10.pdf）內文有「成績公佈」→ 俾「賽果＝比賽」嗰條規則搶走。
      呢類 digest 份 PDF 包晒全月通告字眼，一睇內文就必定分錯；成家人 45 筆（当中
      26 筆錯／未分類）。護欄：「划艇訓練班(活動通告第21/26號)」冇「年…月」結構，唔會誤傷。
    - **「出海記／大冒險」＝活動**（入 `OTHER_ACTIVITY_TERMS`，即係標題先決但喺
      `title_decisive` 之後）。個案：「九灣小漁夫出海記-水上文化親子大冒險」俾海報
      內文「訓練班」搶去做訓練。刻意**唔放** `ACTIVITY_STRONG_TERMS`——「維多利亞城區
      森林大冒險小幼童軍填色比賽」要維持**比賽**；「親子」全庫 69 筆、大半係工作坊／
      比賽，一律**唔收**。
    - 一張通告有兩份內容（例：「港島童軍皮藝會-皮革藝術與生活」＝展覽＋比賽）：
      用戶裁定「活動訓練都啱，但唔係比賽」「中 1 個都係啱呀」→ **唔設人手釘類別**，
      `fix_circulars_2026_10_15.py` 只用 `HUMAN_CONFIRMED` 標記「人工確認過、跳過重算」
      （`patch_entry` 淨係睇標題，呢類標題冇類別字眼，重算反而會俾兜底公布蓋走既有嘅
      「活動」）。「比賽」呢條路已由 `BODY_UNTRUSTED_TERMS`（內文「比賽／錦標」一律唔計）
      永久堵死，所以日後真係重跑 `enrich.py`（有 PDF 內文）判做活動或訓練都啱。
    - **內文嘅「賽果」片語一律唔計**（`BODY_UNTRUSTED_TERMS` ＋ `COMPETITION_RESULT_TERMS`：
      成績公佈／成績公布／結果公佈／結果公布／公佈結果／公布結果）。呢條 2026-10-01 規則
      由始至終係**標題**規則（「XX比賽-成績公布」呢類），內文出現通常只係附帶提及。
      實測零副作用：全庫靠「賽果」做證據嘅 competition entry 得 4 條，**4 條全部標題
      自己就有賽果字眼**（照舊比賽），淨係靠內文攞到證據嘅 0 條。只改 `subscription_tagging.py`：
      `story_queue`／出圖台 `BATCH_RE` 淨係睇標題、冇內文 fallback，唔使三份同步。
    - **根因：同一份 PDF 有兩個 enrich key**（總會在列表頁俾 `scout.org.hk/…`、地域站
      鏡像俾 `www.scout.org.hk/…`）。兩條 entry 各自由唔同次數嘅 run 寫入，所以可以
      各持唔同標籤——10-09 嗰批用新規則（啱），10-15 本機排程用**未 `git pull` 嘅舊
      代碼**覆寫咗鏡像嗰半（錯）。全庫 4,433 條 entry 有 219 組呢種鏡像重複、7 組標籤
      打架（用戶見到嘅錯標籤就係嗰 7 個 www 版本）。`summarize_cross_source_consistency()`
      靠「同標題＋同 captured_date」配對，呢種分歧睇唔到 → 新增
      `enrich.summarize_mirror_url_divergence()`：按**正規化 PDF URL**（除走 `www.`、
      保留 `?wpdmdl=` query）再比一輪，每次 enrich run 收尾自動報「同一份 PDF 但有 N 組
      標籤唔同」。⚠️ **本機排程開工前 must `git pull`**，否則舊規則會日夜覆寫新規則成果。
    - **鏡像收歛淨係處理「標題相同」嘅組**（比對用 `normalize`，空格／連字號分別照樣收歛）；
      同一份 PDF 喺兩個列表用咗**兩個唔同名**（分唔清邊個先係真名）→ 一律唔自動改，
      `fix_circulars_2026_10_15.py` 跑完只報告一次（`mirror_title_audit()`）。用戶 2026-10-15
      對呢類嘅裁決：「太複雜，見到時再對，舊嘅唔理了」。實測：呢類組 22 組、標籤衝突 **0** 組
      （另外 21 組係舊 v1.0 entry 完全冇 `categories`，等每晚 enrich 補，唔使人手理）。
      同場補返一個潛藏 bug：PASS 3 用咗 `title_is_decisive()`，但 `b24d5e1` 得返 call site
      冇咗定義（真數據行唔到入去所以一直冇爆）→ 而家有定義，並且用**合成個案**釘住
      ——淨係靠真數據 zero-diff 驗唔到呢條路。
      待用戶定政策：「章(Pxxx/2026)」呢一類（全庫 9 筆，例如「寰宇童軍章(P109/2026)」）
      而家跟規則＝標題冇課程字眼就兜底**公布**；若決定一律歸**訓練**，改 `TRAINING_TERMS`
      一條即係（三份同步）。測試：`test_circulars_2026_10_15.py`、`test_batch_category.js`。
  - 標題得弱證據（例如「訓練日」「盃」）或者睇唔出 → 先用 PDF 內文補充。
  - **內文範圍要收窄**（2026-10-09 用戶再次強調：「標題分不到才找內文，內文範圍
    太廣很易亂的」）：內文 fallback 只掃開首 `BODY_SCAN_LIMIT`（600）字（通告主旨
    位），兼夾淨係信事件類型專有詞（訓練班／工作坊／錦標賽／社區服務⋯）；附帶
    字眼 `BODY_UNTRUSTED_TERMS`（工作人員／探訪／服務／義工／比賽／錦標）喺內文
    一律唔計——呢堆字喺行程表／工作人員名單／會務簡介成日出現，好易亂。
  - 標題出現「行事曆／一覽／名單／章程」呢類排除詞 → 唔當活動本體。
  - 三份規則要同步改：`subscription_tagging.py`（權威）、`story_queue.py`（Story 清單）、`index.html` 出圖台 `BATCH_RE`／`batchCategory`（`?batch=1`）。測試：`test_tools_category.py`、`test_story_queue.py`、`test_batch_category.js`。
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

### 列表標題 vs PDF 標題（`--apply-title-fixes`）

`enrich.py` 會攞列表頁標題去 PDF 內文核對；對唔上而 PDF 標題夠清楚（相似度 < 90%）
就會「更正」。2026-10-03 起每日 Action 同本機 `run-local-scrape.bat` 都加咗
`--apply-title-fixes`，更正會寫入 `cache.json`（例：「D-26-05 - 26年10月區會公布 【New】」
→ PDF 真標題「區總部公布」）。

- 更正會記錄 `listing_title`（原本列表標題）；之後每次 `enrich.py` run 零下載
  「重新套用」一次（`reapply_stored_title_fixes`），因為 `core.py`（尤其 `--force`）
  每日都會用列表標題重建 `cache.json`，否則更正第二日就會被蓋走。
- 護欄：`heading_looks_like_title()` —— 公函欄位（由／致／知會／編號…）、檔號行
  （「行政通告第 13/2026號」）、欄位行（截止日期…）、表格／時間表行一律唔會寫入；
  舊版 enrich.json 冇 `listing_title` 嘅亂抽更正永遠唔會套用。
- 唔想要自動改名：把 workflow／.bat 嘅 `--apply-title-fixes` 移走即可（預設只報告）。

**2026-10-06（用戶個案：東九龍地域批次「抽取好奇怪、標籤有問題」）**：

- **表格列唔再當標題**：總會兩個「活動與訓練行事曆」PDF 嘅大標題係圖，文字層只剩表格，
  舊版就攞咗一行表格（「2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰」／
  「13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰」）當成「PDF 真標題」寫返 cache.json。
  連鎖反應：行事曆唔再符合 `REFERENCE_TITLE_TERMS`（「行事曆」）→ 分類變「訓練」，
  內文成個季度嘅活動全部變晒訂閱標籤。`looks_like_table_row()` 認日期清單／英文月份／
  表頭字眼／行首獨立日數，`_BODY_INSTRUCTION_RE` 認「請以劃線支票…」等內文指示句。
- **PDF metadata 標題只用嚟確認**：PDF 自帶嘅 `Title` 同列表標題一致 → `verified`
  （行事曆靠佢先認得返；metadata 可能係舊檔另存嘅錯名，所以永遠唔會攞嚟改名）。
- **列表標題係 PDF 標題嘅超集 → 維持列表標題**（`heading_contained_in_listing()`）：
  「東九龍地域50周年暨賽馬會童「SING」匯航計劃 - 地質生態導賞員訓練班」唔會再被縮短成
  「地質生態導賞員訓練班」（舊版因為 10/31 字相似度 0.32 < 0.9 就當列表標題錯）。
- **表格通告直接讀欄位**（`deadline_from_tables()`／`fee_from_tables()`）：純文字流會將
  表頭同資料行連成一串，舊版 3 行窗口攞第一個日期＝第一堂日期。
  26239「三級童軍標準艇訓練班」抽到 2027-01-02（真截止 2026-12-11，表格「截止日期」欄）；
  26242「地質生態導賞員訓練班」抽到 2027-01-13（真截止 2026-12-19）。費用只喺
  「費用($)」欄出現過都抽得到（26239 → HK$160）；「按金」欄唔會當費用。
- **課程標籤唔再由資格句抽出**（`_course_hit_is_requirement_noise()`）：
  「持有獨木舟教練資歷…將獲優先考慮」唔會再變成「獨木舟教練」課程標籤；
  「由…註冊中級童軍標準艇教練員…擔任班領導人」唔會再變成「童軍標準艇教練員」。
  標題自己講明嘅課程永遠保留，內文只要有「一個」非資格句出現都保留。
- **一次性清理**：`python fix_extraction_2026_10_06.py --dry-run`（已寫入 cache.json + enrich.json）。

**2026-10-06（第二批：以今日通告為例，補內文抽取＋標籤規則）**：

- **截止日唔一定要有「截止」兩個字**：內文寫「必須於 2026 年 11 月 30 日（星期一）或之前
  填妥回條，交回…」（26228 獎券活動）舊版完全抽唔到。`extract_deadline()` 而家認
  「（完整日期）…（16 字內）…或之前／前交回／遞交／提交／電郵／傳真」，而且日期同動作
  之間唔可以跨句號／分號——所以「每年 6 月 30 日前提交」（26227）＋下一段
  「2026 年 10 月 31 日呈交」唔會亂抽成截止日（有測試）。換行寫法（日期同「或之前」分兩行）
  都會前後拼一行試，仍然受同一句號／分號限制。
- **費用加「售價」標籤**：紀念品／盲盒訂購類通告寫「售價：每個港幣 50 元」
  （東九龍地域「東九50時間錦囊」盲盒訂購）→ HK$50。
- **參加資格清單要讀齊**：「參加資格」後面係（1）（2）（3）… 編號清單時，
  `locate_label_scope(follow_list=True)` 會續讀，直到撞到下一個欄位（費用／名額／報名…）。
  26241「一個石籃的故事」之前只讀 2 行，漏咗「持有有效委任狀之會務委員」。
- **今日數據**：`fix_extraction_2026_10_06.py` 第二批會（一）按新規則重算 26232／26231 分類；
  （二）補 26228／26229 截止日 2026-11-30、26241 對象。
- **防止未來誤分類**：`石籃的故事` 加入受控強活動詞；總會／地域來源日後遇到同類標題時，會按活動處理。分類回歸測試覆蓋有／無 PDF 文字兩種情況；本次不改歷史資料。

**2026-10-06（第三批：用戶點名「大會操」分類）**：

用戶點名兩條通告——總會「2026年香港童軍大會操(四)」（26332）同荃灣區「香港童軍大會操
荃灣區會旅遊巴士安排」（A202603）——兩條都被判「比賽」。根因：`COMPETITION_TERMS`
收咗「會操」（為咗「步操比賽會操」呢類賽事），於是任何標題有「會操」二字嘅通告
都會先撞中比賽。但**香港童軍大會操（Scout Rally）係全港週年活動／典禮**，訂咗
「所有比賽」嘅訂閱者會收到旅遊巴士安排呢類資訊。

| 規則 | 內容 |
|---|---|
| `RALLY_ACTIVITY_TERMS = ["香港童軍大會操"]` | 標題有「香港童軍大會操」一律＝**活動**（`activity/other`），內文有「比賽」字眼都唔可以搶走（標題為準）。用戶理由：比賽可以算活動嘅一種，活動唔一定係比賽；訂「比賽」嘅人想睇嘅係真正賽事，大會操唔係 |
| **「有服務XX 一定是歸服務」**（用戶同日補充） | 大會操嘅服務邀請／義工招募／義務工作人員招募仍然＝**服務**，唔會被大會操規則食咗。「服務獎勵」呢類表揚通告除外（2026-10-03 規則：服務獎勵＝公布） |
| `LOST_PROPERTY_TERMS`（失物認領／失物待領／失物領回／失物處理） | 失物通告係行政公告＝**公布**，即使標題掛住大會操或賽事個名（「…大會操失物認領安排」「國際賽船大會-失物待領」） |
| 用戶確認：**只收全名「香港童軍大會操」** | 「九龍地域會操」「聯隊週年大會操」等其他會操唔跟呢條規則，維持原判（有測試釘住）。用戶指出呢類地域通告好多時同步操比賽混埋一齊，所以唔放寬 |

優先序（`extract_categories()`）：失物認領(公布) > 香港童軍大會操(服務 > 活動) > 服務邀請 > 標題公布 > 公布覆蓋 > 強活動 > …

三個分類器同步改（否則前端出圖台同 IG Story 會同 app 行開）：
`subscription_tagging.extract_categories()`（enrich → 推播／分類）、
`story_queue.classify_category()`（IG Story 候選）、`index.html batchCategory()`（?batch=1 出圖台）。

資料欠帳由 `python fix_rally_categories_2026_10_06.py`（先 `--dry-run`）補正：11 條
大會操／失物認領通告由標題重算分類，訂閱標籤 `category:competition → activity:other`；
其他欄位（截止／費用／對象／`enrich_version`）一個字都冇改，所以舊 entry 之後仍然可以
用 `--backfill-categories` 執返落 PDF 重抽。零下載、唔改 `cache.json`。

**同日追認：「服務獎勵應該歸獎勵」**。規則本身冇改（`服務獎勵` 一直喺
`ANNOUNCEMENT_OVERRIDE_TERMS` 入面，同童軍獎勵／旅團獎勵／優異旅團／傑出旅團／
功績獎勵／津貼計劃／嘉許計劃一樣＝公布；青年獎勵計劃除外＝訓練），但 enrich.json
有兩條規則生效前抽嘅舊 entry 仲掛住「服務」：總會「地域服務獎勵計劃 - 附件(一)」
兩個 copy（25976／26061）。呢個唔係純顯示問題——`notify.py notice_metadata()` 係
**存量標籤優先**（`extra.get("subscription_tags") or fallback[...]`），所以佢哋會推畀
訂「服務」嘅人。`python fix_award_categories_2026_10_06.py` 已補正（服務 → 公布，
`category:service → category:announcement`），同一套 surgical patch，同樣零下載。
完全冇存檔分類嘅舊 entry 唔使補：notify.py 對佢哋會用標題 fallback，前端
`itemCategories()` 對空陣列亦兜底做「公布」。

**2026-10-09（用戶點名：「標籤錯」5 張＋「標題錯」1 張）**：

用戶列出 5 張標籤錯嘅通告（全部 2026-10-09 總會新入庫）同 1 張標題錯嘅港島南區
通告，並要求「修改後同時吸取經驗更改規則」。根因全部係**標題冇類別字眼時俾
PDF 內文／欄位表垃圾搶走**：

| 用戶指出嘅通告 | 當日錯乜 | 規則修正 | 回歸測試 |
|---|---|---|---|
| 探索歷史典藏、清真文化與創新科技之行（26366） | 內文一句「探訪」搶去服務 | `OTHER_ACTIVITY_TERMS` 加「之行／之旅」→ 活動（「服務之旅」仍係服務） | `test_circulars_2026_10_09.py`＋`test_batch_category.js` |
| 港島地域羽毛球會-入會表格（26370） | 內文提及「訓練班」搶去訓練 | `MEMBERSHIP_ADMIN_TERMS = [入會, 招收, 招募]` → 公布 | 同上 |
| 港島地域羽毛球會-招收2026-2027年度下半年新會員（26369） | 內文提及「比賽」搶去比賽 | 同上（招收新會員＝行政公布） | 同上 |
| 港島地域通告便覽(2026年10月)（26380） | 便覽內文有「工作人員」搶去服務 | `REFERENCE_TITLE_TERMS` 加「便覽」→ 公布 | 同上 |
| 港島童軍生態小組-觀鳥章(興趣組)領袖座談會（26363） | 標題冇字眼，兜底公布 | `TRAINING_TERMS` 加「座談會」→ 訓練（同講座／簡介會同類） | 同上 |
| 港島南區 靜觀品茶工作坊（Drive 14jc…） | anchor 文字係成份通告內文（170 字欄位表） | `core.extract_activity_name_title()`：認到「活動名稱」欄位就抽欄位值做標題 →「靜觀品茶工作坊」 | 同上 |

護欄（新規則唔可以反噬既有優先序，全部有測試釘住）：「工作人員招募」＝服務、
「XX邀請賽-隊員招募」＝比賽、「XX訓練班-學員招募」＝訓練、「與你『童』行」
（冇「之行」二字）唔會誤中。三個分類器（`subscription_tagging.py`／`story_queue.py`／
`index.html batchCategory`）同步改，`story_queue` 順手補返漏咗嘅「公開賽／邀請賽／
練習賽／體驗賽／會操」同參考文件步驟，同訂閱分類對齊。

資料欠帳由 `python fix_circulars_2026_10_09.py`（先 `--dry-run`）補正：用戶點名 6 張
重算分類（連同場「之行-報名表格」跟活動歸活動），同類存量（2026-01 至 09 通告便覽、
2026-05 羽毛球會入會系列、座談會、靜觀品茶地域版）由標題補返分類；靜觀品茶欄位表
標題抽成「靜觀品茶工作坊」並記 `listing_title`（原貌 170 字，`enrich.py` 每次 run
自動重新套用）。同場清走港島南區 24 筆殘留 `view` 標題（見下方「`cache.json` 有
24 筆標題係 `view`」一節；今次連 `notices` 副本一齊清）。

**同日再報：「跨支部海洋公園研習日」（P105/2026）公布→訓練**，兼夾重申分類原則
「標題分不到才找內文，內文範圍太廣很易亂的」。根因：`TRAINING_TERMS` 淨係收
「研習班」，「研習日／研習坊」全部跌落兜底公布。規則修正：`TRAINING_TERMS` 收
裸詞「研習」（三份規則對齊）；內文 fallback 收窄成 `BODY_SCAN_LIMIT`（只掃開首
600 字）＋ `BODY_UNTRUSTED_TERMS`（工作人員／探訪／服務／義工／比賽／錦標喺內文
唔計，只信事件類型專有詞）。同類存量研習家族（搜集章／會議程序／執行委員會／
氣象／風帆先修研習班、單車／定向教練研習坊、立划板競賽研習班→比賽、各報名
表格／通知書跟返主件）由 `fix_circulars_2026_10_09.py` 一齊補返（合共 30 項）。
回歸測試：`test_circulars_2026_10_09.py`（`test_yanyi_family_is_training_from_title`、
`test_body_scope_narrowed_per_user_rule`）＋`test_batch_category.js`。

### 用戶名單（2026-10-06）逐條對照：規則改咗乜、測試釘死喺邊

| 用戶指出嘅通告 | 當日錯乜 | 規則修正 | 回歸測試（`test_enrich.py`） |
|---|---|---|---|
| 三級童軍標準艇訓練班（26239） | 截止抽到第一堂日期 2027-01-02（真值 2026-12-11）；費用空白（真值 HK$160）；多咗「童軍標準艇教練員」課程標籤 | `deadline_from_tables()`／`fee_from_tables()`；`_course_hit_is_requirement_noise()` | ③ 4 條 |
| …地質生態導賞員訓練班（26242） | 標題被縮短成短名；截止抽到第一堂 2027-01-13（真值 2026-12-19）；多咗「獨木舟教練」標籤 | `heading_contained_in_listing()`；表格欄；資格句過濾 | ④ 3 條 |
| 2026 Oct 10, 11, 17, 18, 24-25 四級童軍標準艇訓練班 楊劍聰（26243） | 行事曆 PDF 大標題係圖，表格列被當成「PDF 真標題」寫返 cache；連帶分類變訓練、內文課程變標籤 | `looks_like_table_row()`＋`_BODY_INSTRUCTION_RE`＋`_SECTION_LABEL_RE`；metadata 只用嚟確認 | ① 3 條 |
| 13, 17, 20, 23, 31 地質生態導賞員訓練班 楊劍聰（26244） | 同上 | 同上 | ② 2 條 |
| 2027年童軍獎券籌募活動（出現兩次） | 主通告歸「比賽」（內文有『銷售獎勵比賽』）但回條歸「活動」；兩個 copy 唔一致 | 標題活動字眼優先；`summarize_cross_source_consistency()` 每次 run 檢查兩邊一致性 | ⑤ 2 條＋跨來源 3 條 |
| 東九龍地域步操、團呼及快樂傘比賽2026 - 成績公布（26235） | 兩個來源一個有標籤一個冇（東九龍地域完全冇 enrich） | `is_enrichable_url()` 接受 `?wpdmdl=`；7 日補漏窗 | ⑥ 1 條＋連結 6 條 |
| …一個石籃的故事（26241） | 標題無「活動」字眼時可能兜底成「公布」 | `石籃的故事` 加入強活動標題規則；兩個來源的分類器都加回歸測試 | ⑦ 分類測試 |

每次 `enrich.py` run 收尾會自動報三樣（唔改數據，只提示）：
`⏭ 連結形狀未支援`、`⚠️ 今次有 N 條抽唔到`、`⚠️ 同一通告喺多個來源但結果唔齊／唔同`。

### 同一份通告：總會抽到、東九龍地域抽唔到（2026-10-06 根因＋防復發）

用戶問題：「同一份通告，總會網站出的能抽到，東九龍地域網站出的抽不到」。根因**唔係**
PDF 唔同（兩個 URL 送到嘅係同一份 PDF），而係 enrich 嘅**入場閘**：

1. `collect_targets()` 以前用 `url.endswith(".pdf")` 決定下唔下載。總會站條 link 係
   `…/uploads/tc/circulars/26239/SA69.pdf`（過閘），東九龍地域條 link 係
   `/circulars/download/?wpdmdl=5653`（唔以 `.pdf` 結尾）→ **當時會靜默跳過**，
   未有 enrich entry 時前端唯有 fallback 顯示「公布」。目前入口已接受此下載格式；此 PR 不補寫任何舊 entry。
2. 就算閘過得到，每日 workflow 只做「當日 captured_date」——之前被跳過嘅永遠冇人返轉頭補。

修正同防復發（全部有測試）：

| 機制 | 做乜 |
|---|---|
| `is_enrichable_url()` | 除 `.pdf` 之外接受 WPDM `?wpdmdl=` 下載端點；下載返嚟仍然要過 `%PDF` magic bytes，唔係 PDF 就記 `not_pdf`（唔會亂塞內容） |
| `INCREMENTAL_CATCHUP_DAYS = 7` | 增量模式補做最近 7 日仍然冇 enrich 紀錄嘅通告，舊漏帳自動執返 |
| `has_current_enrichment_tags()` | 預設增量不會只因 `enrich_version` 升級而重寫已完整舊 entry；要更新歷史分類須明確執行 `--backfill-categories` |
| **每次 run 都印「連結形狀未支援」警號** | `summarize_skipped_links()`：列出跳過幾多條、按 `.docx`／`.xlsx`／網頁分類、涉邊個來源、例子 URL。以後有新來源／新連結形狀，唔會再靜默 |
| **run 尾錯誤摘要** | 抽唔到嘅原因逐個來源報（`not_pdf` / `download: …`），例如 WPDM 要 cookie 就會即刻見到 |
| 測試 | `is_enrichable_url`、`collect_targets`（今日＋補漏窗）、`summarize_skipped_links` 全部有回歸測試 |

⚠️ **唔會再由另一個來源搬欄位**：同一份通告出現喺兩個來源（總會鏡像＋地域站）時，
兩條 entry 必須各自由自己嘅 PDF 抽——即係「從那來就如實反映」。腳本早期版本曾經
把總會 entry 嘅欄位複製落東九龍地域 entry（記 `derived_from`），已全部撤回
（`fix_extraction_2026_10_06.py` 會刪除任何有 `derived_from` 嘅 entry）。

**本次只防止未來重犯，不補改歷史資料**：沒有修改 `cache.json` 或 `enrich.json` 的舊通告紀錄。抽取防線包括：郵寄地址不當作參加對象；未成年同意書的家長／監護人不當作活動對象；「石籃的故事」標題按活動處理。回歸測試覆蓋這些情況。

`ENRICH_VERSION` 升至 3.6，供新抽取資料標記版本。預設增量不會只因版本升級而重寫已完整的舊 entry；只有資料缺漏的新通告會按既有補漏窗處理。若日後需要主動重算歷史資料，才明確執行 `--backfill-categories`。

執行回歸測試：

```bash
node test_search_members.js     # 支部 + 分類配對邏輯（直接由 index.html 抽出，唔係複製一份）
node test_report_feedback.js    # 問題回報／意見反映 payload 對齊 Scout Admin；預覽頁／Cloudflare 注入已清走
node test_share_branch.js       # 支部標籤 + 分享面板 DOM 測試（需要 jsdom）
node test_time_windows.js       # 「今天」午夜界線；小工具唔以日期分類（今天／之前發布）；Scout System 綠燈只認今日新上架
node test_scout_system_light.js # Scout System 側欄綠燈：今日冇新上架就熄燈，但件數照報（需要 jsdom）
node test_batch_category.js     # 出圖台 ?batch=1 分類（公告／公布規則，直接由 index.html 抽出）
python test_notify.py           # Push 去重、交集和合併通知邏輯（不會發網絡請求）
python test_push_common.py      # API 受控 ID 與 endpoint SSRF 防護
python test_tools_category.py   # 「小工具」分類、全選通告／全選小工具兩個剔項
node test_push_client.js        # LocalStorage／匿名 subscription lifecycle（不需 jsdom）
node test_sw.js                 # Service Worker 只接受同源精確圖書館結果 URL
node test_icons.js              # manifest／<head>／sw.js 引用嘅圖示檔案存在、PNG 尺寸正確、badge 係單色 PNG
node test_personalized_view.js  # 受控下拉 + 精確 ?n= 推播結果頁／手機收合 UI（需要 jsdom）
python test_enrich.py           # enrich 欄位抽取 + 分類規則（包括 ⑧ 大會操＝活動／失物認領＝公布）
python test_story_queue.py      # IG Story 候選挑選 + 分類兜底（同 enrich 規則對齊）
python test_rally_categories_2026_10_06.py  # 大會操＝活動、失物認領＝公布：規則 + enrich.json 存量資料
python test_award_categories_2026_10_06.py  # 獎勵／津貼／嘉許一類（包括服務獎勵）＝公布：規則 + 存量資料
```

## 匿名個人化 Web Push

通知功能採取**零個資、零成本優先**的設計：沒有登入、帳戶、姓名、電郵、電話、旅團或地域推播條件。地域／區會資料仍只用於左欄瀏覽。

1. 使用者按搜尋列／「★ 收藏」旁的 **🔔 通知** 掣（手機為頂欄 🔔）開啟設定面板，所有選項都是**點一下即剔**的受控項目，桌面不必按 Ctrl／Shift。面板最頂是兩個互相獨立的全選剔項：**「全選：所有通告」**（`all:notices`，小工具以外的所有新通告，包括公布及未分類）與**「全選：所有小工具」**（`all:tools`，所有支部的小工具）；兩個都剔即等於所有新消息，兩者都不分支部。剔了其中一個，下面就只剩未被蓋住的部分可以逐項揀（例如只剔「所有通告」時，就只剩小工具按支部逐個選）。舊版單一 `all:new` 保留相容，載入時自動顯示成兩個都剔。其餘仍是先揀支部，再選服務、活動、比賽、小工具、公布；訓練則**按支部列出**該支部現行訓練綱要內的非進度性徽章及特別訓練班（例如童軍的「童軍領導才」），另有「所有 X 訓練」一鍵訂閱；領袖訓練分為**木章訓練班**與**非木章訓練班**。設定先寫入該瀏覽器的 LocalStorage，不會上傳自由文字。選單只顯示「地圖閱讀」等項目基礎名稱；訓練班、工作坊、課程等正式題名變體會自動配對。
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
   - **2026-10-06：增量模式加 7 日補漏窗**（`INCREMENTAL_CATCHUP_DAYS`）——最近 7 日入庫
     但 `enrich.json` 仲係冇紀錄嘅通告會自動補做（已經有當前版本標籤嘅唔會重抽）。
     原因：`collect_targets()` 以前會靜靜跳過一啲 URL 形狀（東九龍地域入庫通告用
     WordPress Download Manager `/circulars/download/?wpdmdl=NNNN`，唔以 `.pdf` 結尾），
     當時該來源未有 enrich entry，前端唯有 fallback 顯示「公布」。而家
     `is_enrichable_url()` 接受 `?wpdmdl=`，下載返嚟照樣要過 `%PDF` magic bytes；此 PR 不會補寫歷史 entry。
     要主動重算既有資料，仍須明確執行 `python enrich.py --backfill-categories` 或 `--backfill`。
   - **2026-10-06：抽取規則升版只標記新抽資料**；預設增量不會單因 `enrich_version` 不同而改寫已完整 entry。
     如要重算舊版 entry，須明確使用 `--backfill-categories`。
3. 如已設定 `VAPID_PRIVATE_KEY`，執行 `notify.py`，先做每位匿名訂閱者的支部＋興趣交集和合併，再發送 Web Push。
4. 自動提交 `cache.json`、`enrich.json` 和 `fingerprints.json`，讓前端從 GitHub Raw 讀取最新資料。

### 本機補漏（`run-local-scrape.bat` + `run-local-scrape-logged.bat`）

雲端 Action 係主線；本機（Windows 工作排程器）係後備補底。**2026-09-14 起本機流程縮到最短，兩個閘門全部移除**：

1. 由 GitHub 下載最新（`git pull --rebase --autostash`）
2. `python core.py --force` —— 全網重新巡邏，唔理 cache 有幾 fresh
3. `python enrich.py --verbose --apply-title-fixes` —— 增量抽 PDF 文字（連 PDF 標題更正）
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

### Vercel Usage Report workflow 已刪除（2026-10-14）

`vercel-usage-report.yml` + `.github/scripts/vercel_usage_report.py` +
`test_vercel_usage_report.py` 已全部移除，**唔好再加返**。原因：

1. 佢係 `on: push:`（冇 `paths` 過濾、冇 concurrency）—— 每次 push 到**任何**
   branch 都跑一次，包括每日 bot 嘅 `Local backup scrape` commit 同埋 Agent 開嘅
   工作 branch。實際效果係為咗一份「睇吓 storage 有冇再漲」嘅報告，
   每日多幾十次 Actions run ＋每次一串 `api.vercel.com` GET。
2. `VERCEL_TOKEN` 過期之後，佢由 2026-10-06 起日日紅／日日出 warning（10-09
   已改成軟著陸 exit 0，但每次 push 照樣跑），代價遠大過回報。
3. 2026-09-17 瘦身之後 Functions Storage 已經唔再漲（每個部署 ~30KB），
   **持續監察嘅前提本身已經唔存在**。

要睇用量：Vercel Dashboard → **Usage**（Functions Storage / Deployment Storage 一個頁搞定）；
要防止日後 bundle 脹返：`.github/workflows/vercel-bundle-guard.yml` 每次 push 照樣行
（佢淨係睇 repo 自己，唔打任何外部 API，所以留低）。
`VERCEL_TOKEN` / `VERCEL_PROJECT_ID` 兩個 secrets 仍然要設 —— 而家得返
**Vercel Deployment Prune**（每週一 cron）同 **Vercel Retention Policy**（手動）用；
唔設佢哋就靜靜跳過，唔會 fail、唔會發電郵。


## 已知待處理（2026-09-25 發現，刻意未修）

### `cache.json` 有 24 筆標題係 `view`（港島南區）

- 位置：`cache.json` → `data.港島南區`，24 筆 Drive 連結通告，`captured_date` 全部 `2026-05-21`。
- 成因：2026-05 舊版 `fallback_title_from_url()` 攞 Drive URL 尾段（`/file/d/<id>/view` →
  `"view"`）做標題。`core.py` 已經修好（`URL_TAIL_NOT_A_FILENAME` / `looks_like_opaque_id`），
  新抓嘅唔會再中 —— 但**已入庫嘅記錄唔會再被抓**（來源頁已經唔列出嗰 24 條），
  `core.py` 又用 `(source_site, pdf_url)` 認「已存在」，所以錯標題會永遠留低，
  6 個月視窗照樣顯示 24 張「view」卡。
- 影響：`python test_url_title_fallback.py` 同一項、`ci-proposed/test.yml` 嘅
  cache 完整性守門會紅（呢個係「正確嘅紅」）。
- 修法（一行，工具早已經寫好，對照表逐份 PDF 核實過）：

  ```bash
  python fix_hks_titles.py --dry-run   # 睇會改邊 24 筆（應該全中，冇漏）
  python fix_hks_titles.py             # 寫入 cache.json（會留 .bak 備份，已 gitignore）
  ```

  想自動化：`ci-proposed/scrape-hks-titles.patch` 會喺每日爬蟲流程加
  `python fix_hks_titles.py`（乾淨時 no-op，唔會阻礙之後任何一次跑），
  由同一個 writer 改 `cache.json`，避免 PR 同 bot 撞（見 `ci-proposed/README.md` 第 3 節）。
- 2026-09-25 決定：**暫時唔修**（唔喺 PR 手改 bot 每日重寫嘅 `cache.json`）。
- **2026-10-09 已修**（用戶「標題錯」個案同場處理）：`python fix_circulars_2026_10_09.py`
  用同一份 `fix_hks_titles.TITLE_BY_FILE_ID` 對照表清走 24 筆 `view` 標題，
  **連 `notices` 副本都一齊清**（舊 `fix_hks_titles.py` 只處理 `data`）。
  呢 24 條來源頁早已唔列出、唔會再被抓，所以一次過寫入就永久生效，
  `python test_url_title_fallback.py` 第 6 節轉綠。

### 測試 workflow 未安裝（所以上面嘅腐化冇人叫）

`.github/workflows/` 冇 `test.yml`：Arena 用嘅 GitHub App 冇 `workflows` 權限，
push 含 workflow 改動嘅 commit 會被 GitHub 拒絕，所以 `ci-proposed/test.yml`
要你自己 `cp` 入去。2026-09-25 已把清單由 8 個測試檔補齊到 **28 個**
（另外 15 個由來冇跑過，期望值已經腐化過，詳見 `ci-proposed/README.md`）。

## 下一步建議

如果你把你現有 repo 貼上來，我可以下一輪直接做：

- 對照你現有 `core.py` 修補崩潰點
- 併回你原本已成功抓到的來源
- 補埋 Vercel / Raw CDN / GitHub Actions 實際部署細節
