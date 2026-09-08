# 匿名個人化 Web Push：部署與驗收

本功能讓使用者預先選擇**支部**和受控的**訓練／服務／活動／比賽**項目；系統只在兩者都命中的真正新增通告出現時發送通知。活動只分大露營、營火會、其他；比賽獨立。訓練項目自字典 2.0.0 起**按支部劃分**（每個支部有「所有 X 訓練」＋該支部訓練綱要內的非進度性徽章／特別訓練班；領袖分木章／非木章），單一訂閱最多可選 60 個項目。

## 本次合併後配合步驟（catalog 3.0.0）

1. 等待 Vercel 的 main 正式部署 Ready；重新整理網站／主畫面 App，確認通知面板已按支部分組，
   並有「全選：所有新通告」及「重新設定」。本次不新增環境變數，不要重新產生 VAPID 金鑰。
2. 已完成 catalog 2.0 的資料庫毋須再次 migration；舊訂閱仍可用，建議開啟通知設定檢查選項，
   按「更新通知設定」同步新的支部項目 ID。不需刪除訂閱或清除瀏覽器資料。
   若原先尚未部署 Web Push，仍需完成下文 Vercel／GitHub Secrets／Supabase 初始設定。
3. Windows 本機先確認工作目錄沒有未提交更改，在本機 main checkout 更新程式及依賴。
   工作排程器 → 找到原本執行 `run-local-scrape.bat` 的工作 → 內容 → 觸發程序 → 編輯，
   將每日 18:00 改成 07:00（香港本機時區）；編輯原工作，不要另建一份而留下晚上那份。
   確認「下次執行時間」、電腦開機及網絡。此儲存庫無法直接修改使用者的工作排程器。
4. Actions 的設定時間是香港 06:15，但排隊會延遲，不能以 30 分鐘 timeout 推斷 07:00 必已完成。
   查驗時最近兩次 schedule run 實際約 07:51／07:52 開始、07:57 結束。
   本機 07:00 不是與 Actions 互斥的保證；本機執行前應檢查該 workflow 有否 queued／in_progress，
   有就等完成再補跑。雲端 concurrency 不會鎖住本機 batch，之後才排入的雲端工作仍可能與本機重疊。
5. 現有 `run-local-scrape.bat` **沒有執行 `notify.py`**；只會更新圖書館，不會推送本機新發現的通告。
   如要本機也推送，需在 `enrich.py` 成功之後、git commit 之前執行 `python notify.py`，
   並在可信任本機環境提供與正式站相同的 Web Push／Supabase 設定（見下文）；不能提交金鑰到 Git。
   已提交本機新通告後再跑預設 notify.py，HEAD 基準會視它們為既有資料，不會補發。
   本次未修改本機 batch 的推送或排程，亦未執行真實通知驗收。

## 歷史升級說明（catalog 1.x → 2.0.0）

- `subscription_catalog.json` 的訓練項目全部重整（新增 `training:<支部>`、`training:領袖:木章`、`training:領袖:非木章`，以及各支部 `course:*`；`section`／`subgroup` 只供前端分組）。`category:training`、`category:service`、`category:competition` 與三個 `activity:*` ID 維持不變，舊訂閱仍可繼續收到通知。
- 舊版 `course:*` ID 全部保留（只有 `course:scout-parachuting-badge` 因 2026 綱要把跳傘章列入深資／樂行而改為 `course:shared-parachuting-badge`）。字典內不存在的舊 ID 會在使用者下次開啟面板時自動略過，並於重新儲存時以新選項取代。
- `MAX_TOPICS` 由 24 提高到 60：`api/push_common.py` 與 `schema.sql` 的 `push_subscriptions_topic_count` 必須一起改。**已建表的 Supabase 專案請重新執行 `schema.sql`**（內含 `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`），否則超過 24 項的儲存會被資料庫拒絕。
- `enrich.py` 以 catalog `version` 判斷 metadata 是否過期；每日 workflow 只會替新通告寫入 2.0.0 標籤。要讓歷史通告在個人化結果頁也能配對新 ID，可在本機執行一次 `python enrich.py --backfill-categories`（會重新下載 PDF，量較大）。

> **私隱界線**：不設登入，沒有姓名、電郵、電話、旅團、地域或區會推播欄位。地域／區會仍只保留作網站左欄瀏覽。瀏覽器啟用後，資料庫只保存 Web Push 協定必需的匿名 endpoint、加密金鑰、endpoint 雜湊、隨機本機 token 的雜湊，以及受控支部／項目 ID。

## 架構與一次推送的流程

```text
瀏覽器 LocalStorage
  └─ 支部 IDs + 受控 topic IDs + 隨機本機 token
       │（使用者按「啟用通知」後才建立）
       ▼
Vercel /api/push-subscriptions
  └─ 驗證同源、瀏覽器 provider endpoint、受控 catalog IDs
       ▼
Supabase（只 service_role 可讀寫）
  └─ push_subscriptions / push_deliveries
       ▲
GitHub Actions：core.py → enrich.py → notify.py
  └─ 比較 HEAD:cache.json，支部 AND topic 配對，按訂閱者聚合後最多一則 Push
       ▼
sw.js 顯示原生通知；所有結果開啟圖書館的精確 ?n=notice-id,… 篩選
```

`notify.py` 不是逐張通告推送：一位使用者同一批命中 10 張，仍只收到 1 則通知。當日稍後再次執行時，Service Worker 使用同一 `tag`、`renotify: false` 和明確 `silent: true` 更新彙總，避免再響鈴；`push_deliveries(subscription_id, notice_key)` 的唯一鍵同時防止 workflow 重跑重送相同通告。

每個點擊 URL 的 `n` 是由**公開來源名稱和通告 URL**算出的短、穩定 ID 清單，不含 subscription ID、LocalStorage token、支部或興趣設定，也不含 PDF URL。圖書館依此只顯示當次通知的 1／N 張卡片；所以使用者即使其後改了設定，仍可收藏和找回當次通告。

## 1. 建立 Supabase 表（一次）

1. 開啟 Supabase 專案的 **SQL Editor**。
2. 貼上並執行 repository 根目錄的完整 [`schema.sql`](schema.sql)。
3. 確認表格 `push_subscriptions` 和 `push_deliveries` 已建立。

可用以下不會顯示 endpoint 的查詢驗證：

```sql
select id, branch_ids, topic_ids, enabled, created_at, last_seen_at
from push_subscriptions
order by created_at desc;

select subscription_id, notice_key, batch_date, sent_at
from push_deliveries
order by sent_at desc;
```

兩張 Push 表已啟用 RLS，且沒有 `anon`／`authenticated` 政策；瀏覽器不能直接讀取。只有 server-side `service_role` 可讀寫。

## 2. 產生 VAPID 金鑰（一次）

在可信任的本機或受保護 CI shell 執行：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python generate_vapid.py
```

輸出有兩部分：

- `VAPID_PUBLIC_KEY=...`：單行 base64url 公開金鑰；瀏覽器建立訂閱時必需，可以放到 Vercel server environment 後由 `/api/push-config` 回傳。
- `-----BEGIN PRIVATE KEY----- ...`：**私鑰**；只可放在 GitHub Actions Secret `VAPID_PRIVATE_KEY`。不可放入 Vercel、前端 JavaScript、`index.html`、Git、issue、聊天室或截圖。

建議 `VAPID_SUBJECT` 使用站點網址，例如 `https://scout-circulars.vercel.app`。它是 VAPID 聲明的聯絡／來源值，不是訂閱者資料；也可不設，dispatcher 有同一預設值。

> 若日後更換 VAPID key pair，舊 browser subscription 需要重新啟用通知；先部署新的 public key，再更新 GitHub 私鑰，並在網站提示使用者重新訂閱。

## 3. 設定 Vercel（瀏覽器訂閱 API）

Vercel 專案的 **Settings → Environment Variables**（Production，預覽環境如要測試可另行加入）加入：

| 變數 | 放置位置 | 說明 |
|---|---|---|
| `SUPABASE_URL` | Vercel + GitHub Secret | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Vercel + GitHub Secret | service role key；只在 server-side function / Action 使用 |
| `VAPID_PUBLIC_KEY` | **只在 Vercel** | public VAPID key |

然後重新部署 Vercel。`vercel.json` 已把漂亮路徑 `/api/push-config`、`/api/push-subscriptions` rewrite 到 Python functions，並將受控 catalog 包含在 function bundle。

**不要**把 `VAPID_PRIVATE_KEY` 放到 Vercel；Vercel 完全不負責發送通知，只有 GitHub Actions 的 `notify.py` 需要它。

部署後，在無痕視窗或 terminal 檢查：

```bash
curl -sS https://YOUR-VERCEL-DOMAIN/api/push-config
```

完成設定時應含有：

```json
{"ok":true,"enabled":true,"vapidPublicKey":"..."}
```

若為 `"enabled": false`，先確認 Vercel 的三個變數均已套用到該 deployment；不要讓前端直連 Supabase 排錯。

## 4. 設定 GitHub Actions（dispatcher）

在 GitHub repository 的 **Settings → Secrets and variables → Actions** 新增以下 **Secrets**：

| Secret | 必要性 | 說明 |
|---|---:|---|
| `SUPABASE_URL` | 必要 | 同 Vercel |
| `SUPABASE_SERVICE_KEY` | 必要 | 同 Vercel；給 `core.py` 和 `notify.py` server-side 使用 |
| `VAPID_PRIVATE_KEY` | 必要才啟用推播 | 完整 PEM，保留多行也可以；程式也接受字面 `\n` |
| `VAPID_SUBJECT` | 建議 | 例如 `https://YOUR-VERCEL-DOMAIN` |

在 **Variables**（不是 Secret）設定：

| Variable | 說明 |
|---|---|
| `SITE_URL` | **所有**通知點擊後開啟的正式 HTTPS 圖書館網址，例如 `https://YOUR-VERCEL-DOMAIN`；必須與使用者訂閱時的網站 origin 相同，讓 Service Worker 可安全開啟精確 `?n=` 結果。 |

`.github/workflows/scrape.yml` 只有在 `VAPID_PRIVATE_KEY` 存在時才執行 `notify.py`，因此可先安全部署網頁與資料庫，再啟用 Action secret。私鑰未設定時既有每日爬蟲不會失敗。

> GitHub Actions 要能推送更新 cache，repository 的 Actions workflow permissions 仍須允許 `contents: write`；這是既有自動 commit 的需要，與 Push 無關。

## 5. 本機測試（不發送真通知）

複製範例，不要把 `.env` 加入 Git：

```bash
cp .env.example .env
# 以真實值填入 .env；shell 使用時：
set -a; source .env; set +a
python serve_local.py
```

`serve_local.py` 會提供靜態頁、`/api/render`、`/api/push-config` 和 `/api/push-subscriptions`。在 `http://localhost:8000` 時瀏覽器可能不允許真正的 Push subscription；正式測試請用 Vercel 的 HTTPS 網址。

安全回歸測試：

```bash
python -m py_compile core.py enrich.py subscription_tagging.py notify.py serve_local.py api/push_common.py api/push_config.py api/push_subscriptions.py
python test_enrich.py
python test_push_common.py
python test_notify.py
node test_search_members.js
node test_push_client.js
node test_sw.js
node test_personalized_view.js  # 需要 jsdom
python notify.py --dry-run
```

`--dry-run` 只讀訂閱資料並報告配對／聚合數量，絕不發送通知或寫入 delivery 紀錄。若 `HEAD:cache.json` 不存在，它會安全略過，而不是把所有歷史通告推送。

## 6. 使用者端驗收

1. 以同一正式 HTTPS 網址開啟網站。
2. 在「個人化通告通知」選擇至少一個支部，再選受控的訓練、服務、活動或比賽；課程選項會按已選支部過濾，沒有自由文字輸入欄。選單只顯示項目基礎名稱（例如「地圖閱讀」）；訓練班、工作坊及課程等正式變體會自動配對。
3. 按「只儲存選項」：重新整理後，選項仍應在該瀏覽器；此步不要求通知權限也不寫 server subscription。
4. 按「啟用通知」，接受瀏覽器權限；Supabase 應新增一列，但沒有任何人身識別資料或地區欄位。
5. 停止通知後，browser subscription 會取消，API 會刪除對應資料列。若使用者剛好離線，失效 endpoint 在 dispatcher 收到 404／410 時也會清理。
6. 有一張命中通告時，通知標題是 `🔔 [項目／通告名]`，內文只有「點擊查看通告」；兩張以上時只應有一則 `🔔 你關注的項目有 N 項新通告`，內文只有「按此查看全部」。兩者都必須開啟圖書館（不可直達 PDF），網址帶 `?n=` 的短 notice-ID 清單，並恰好顯示本次 1／N 張卡片而不混入其他通告；卡片的收藏功能仍可用。

## 操作與故障排除

| 現象 | 檢查方法 |
|---|---|
| 網頁顯示「通知服務尚未完成設定」 | `GET /api/push-config`；確認 Vercel 有 `SUPABASE_URL`、service key、`VAPID_PUBLIC_KEY`，後重新 deploy。 |
| API 回 `origin_not_allowed` | 只可由同源頁面 POST。確認沒有把前端 API URL 改成 `localhost` 或另一個 domain。 |
| Action 沒有 notify step | GitHub Secret `VAPID_PRIVATE_KEY` 尚未設定，這是刻意的安全 fallback。 |
| Action notify 失敗 | 檢查 GitHub three required secrets、PEM 是否完整、Supabase schema 是否已執行。不要把 secret 值貼進 log。 |
| 不想再收通知 | 使用網頁「停止這部裝置通知」，或從 browser site settings 取消通知；後者的失效 endpoint 會在下一次發送失敗時清理。 |
| 新通告沒有推送 | `notify.py` 只看 workflow 開始前的 `HEAD:cache.json` 沒有的來源+URL，且需要支部 **和** topic 都命中。這是防止歷史／無差別推送的設計。 |

## 成本與資料保留

此方案使用既有 Vercel、Supabase free tier 與 GitHub Actions；沒有外部 notification SaaS、帳戶系統或 paid database lookup。資料量只隨啟用裝置數量增加。`push_deliveries` 是為了去重的最小紀錄，不含 payload、標題或人身資訊；可按營運需要在 Supabase 以排程保留有限時間，但不要刪除太快而破壞重跑去重。

## 通知安裝提示、支部配對及離線保留（2026-09-07）

- 通知面板會一直顯示手機／電腦接收步驟，而不只在權限失敗時顯示。
  iPhone／iPad 需 iOS／iPadOS 16.4+，在 Safari「分享 → 加入主畫面」後，
  從圖示開啟並允許通知；未安裝時不會嘗試訂閱。Android 建議加入主畫面，
  支援的瀏覽器亦可直接啟用。`manifest.webmanifest` 及 PNG 圖示提供 standalone 安裝設定
  （`any` ＋ `maskable` 兩套、180px `apple-touch-icon`）；通知本身用 `icons/notification-192.png`
  ＋ 單色 `icons/badge-96.png`，來源 SVG 與重新輸出方法見 README「圖示」一節。
- 電腦需允許網站及作業系統通知、保持連線，並讓瀏覽器開啟或在背景接收。
  不需一直開着本站分頁；省電／勿擾／瀏覽器限制仍可能影響送達。
- `notify.py` 的 `PUSH_TTL_SECONDS = 259200`（72 小時／3 日）是**每則推送的離線保留時間**，
  並非訂閱有效期或保證送達期限。裝置無法接收超過 3 日，較早通知可能過期而不補發，
  但不會自動取消訂閱，亦不會刪除網站通告。通知仍在測試中，建議每天開啟圖書館檢查更新，不只依賴推送。
- 所有通知選項先按支部分組，每個支部內列活動、服務、比賽及訓練。
  家長支部只有活動／比賽，不會再令其他已選支部的服務／訓練消失。
  「家長的活動」或「小童軍的活動」任一組命中便通知，同一通告只計一次。
  「家長的活動＋小童軍的比賽」不會錯配成家長比賽或小童軍活動。

### 字典 3.0：支部內項目及全選

- 新選項用受控 ID `branch:<支部>:<舊分類 ID>`，例如 `branch:家長:activity:other`。
  每項以 `branches` 指定支部，以 `match_topic` 對應現有通告分類標籤；
  推送及個人化列表都要求同一選項的支部與分類同時命中。不必重新下載歷史 PDF。
- 舊共用 `category:*`／`activity:*` ID 保留相容：設定介面按原已選支部展開成獨立選項，
  儲存／同步時改用新 ID；伺服器仍能按各舊項目的支部範圍配對。
  過時的 `training:家長` 已移除；家長支部沒有訓練／服務選項。
- 「全選：所有新通告」對應 `all:new`，不需逐項選數百個項目，也不受 60 項限制困擾。
  包括沒有支部或分類標籤的通告；並非將所有支部及已知分類取交集。
  API 儲存時統一成一個 topic ID 及現有八個支部 ID，符合目前 SQL 的 1..8 支部／1..60 項目限制，
  不需要 schema migration。`all:new` 才是全選判斷依據，並不依賴通告命中這八個支部。
- 全選仍經過新通告比較及 delivery 去重：沒有新通告不推送，不會重推歷史庫。
  同批新通告合併為一則，同日補跑沿用現有靜音更新摘要機制。
  取消全選可回到支部自選；當次面板未儲存的細項會保留，重開則按最後儲存的模式載入。
- 必須一併部署新的 catalog、介面、API 及 Actions 的 notify.py 才支援新 ID；
  本機補跑仍需實際執行 notify.py 才會發出推送。

部署後仍需用真實 iPhone／Android／桌面裝置，配合正式 VAPID／Supabase 設定驗證送達。
單元測試只驗證 TTL 傳值及篩選／安裝限制，不代表已完成真實離線 72 小時送達測試。


### 家長參與對象及「今天」範圍補充

- 「家長＋活動」要求通告有家長參與對象標籤，亦有已選活動項目標籤，不能只因為是活動便推送。
  「港島童軍繽紛日」這類活動按對象配對；分類器加入「繽紛日」活動詞，不硬編碼個別通告或擴大參與對象。
- 通知設定頂部固定提示：系統仍在測試中，推送可能延遲／遺漏，建議每天到圖書館查看更新。
- 目前 `captured_date` 只有香港日期、沒有時分；`parseDate()` 以香港當日 00:00 解讀，
  「今天」按該時間起 24 小時篩選，而非從實際入庫時間起計。18:00 新增的項目過午夜後
  重新整理／觸發篩選便離開「今天」，仍可從 7 天等範圍及收藏找到，不是刪除。
  技術邊界：現有比較用 `<=`，恰好翌日 00:00:00.000 尚符合，再往後便不符合；頁面沒有午夜自動刷新計時器。
- 此 checkout 的 Actions 排程是香港時間 06:15（UTC 22:15），實際啟動或會延遲。
  `run-local-scrape.bat` 目前只有抓取／enrich／上載，沒有執行 `notify.py`；
  單靠此補跑腳本不會即時推送。以上為現況說明，本次未變更排程、本機腳本或時間篩選規則。


### 重新設定、升團及新增家庭成員

- 「重新設定」先確認，再清空目前面板的全選／支部／項目；只改草稿，不刪 LocalStorage、
  client token 或推送訂閱，也不呼叫停止通知。重新選擇並按儲存／更新後，才取代舊設定。
  空白草稿不能儲存／啟用，避免誤把仍在使用的訂閱清空。
- 增加小朋友不必重新設定：直接加選新支部及該支部項目，其他支部已選項目完整保留；
  儲存後同步同一裝置的原有訂閱，不會另開一份重複通知訂閱。
- 升團可取消舊支部，選新支部及項目；其他家人的支部不用取消。
  若只想全部重新選擇，可用「重新設定」。新支部不會自動繼承另一支部的項目。
