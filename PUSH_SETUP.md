# 匿名個人化 Web Push：部署與驗收

本功能讓使用者預先選擇**支部**和受控的**訓練／服務／活動／比賽**項目；系統只在兩者都命中的真正新增通告出現時發送通知。活動只分大露營、營火會、其他；比賽獨立。

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
