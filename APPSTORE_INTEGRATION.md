# SCOUT APP STORE × 通告圖書館 直連設計（2026-09-24）

研究稿。背景：SCOUT APP STORE（`playerkousas-rgb/website`）同本圖書館共用同一班用家；
未來方向係「用家投稿 → 管理者批核 → 新 APP 上架 → 自動觸發 PUSH 同 STORY」。
本文件記錄已驗證嘅事實、現階段做法同未來接線圖。

## 已驗證事實（經 live REST 查詢，見 `appstore.json`）

- Supabase project：`https://visqyeskdauipodudpxz.supabase.co`；公開 anon key 已 commit（RLS 限唯讀，website README 明確呢個係設計之內）。
- 表：`pages`（4）、`categories`（13）、`apps`（65，含 4 本進度紀錄冊同本圖書館）、`submissions`（投稿）。
- RLS：
  - `pages`／`categories`：匿名可 SELECT；寫入限 `is_store_admin()`（auth email = `ai@skwscout.org.hk`）。
  - `apps`：匿名 SELECT 限 `visible = true`；寫入限 admin。
  - `submissions`：匿名**讀唔到**；投稿只可經 `submit_work(jsonb)`、批核只可經 `review_work(uuid, boolean)`（admin）。
- RPC：`bump_clicks`／`bump_stars`／`bump_hearts`（匿名可調，fire-and-forget 統計）。
- 寫入憑證（service_role key／admin 密碼）**唔喺** website repo——要喺 Supabase Dashboard 攞。
- **同一 project 確認（2026-09-24 用戶）**：圖書館 push（`push_subscriptions`）同 App Store 共用此
  Supabase project。因此 repo 現有 `SUPABASE_SERVICE_KEY` secret 本来就係呢個 project 嘅
  service key（新格式 `sb_secret_…`／舊格式 `eyJ…` role=service_role）；`update-store-icons.yml`
  已加 fallback：`STORE_SERVICE_KEY || SUPABASE_SERVICE_KEY`。
- **改名注意**：Supabase display name 改「SCOUTAPPSTORE」零影響；ref／subdomain
  （`visqyeskdauipodudpxz`）唔可以改——URL 同所有 API key 都綁定 ref，改即全滅。

## 階段劃分

### 階段 0 — 現在：手動加原生 APP（用家自己做）
用家慢慢將自己嘅原生 APP 手動加入圖書館（cache.json「Scout System」來源／index.html items）。
本 repo 已有 snapshot（`appstore.json`）做對照，UI 唔自動改。

### 階段 1 — 測試寫入：store icon 換最高獎章 AVIF
`tools/update_store_award_icons.mjs` ＋ `.github/workflows/update-store-icons.yml`。
憑證二選一（repo secret）：`STORE_SERVICE_KEY`，或 `STORE_ADMIN_EMAIL`＋`STORE_ADMIN_PASSWORD`。
merge 前測試用 `icon_base` input 指去 branch raw；merge 後留空（用 main）。
呢個 script 係一次性測試工具——階段 2 完成後功成身退。

### 階段 2 — 未來：投稿→批核→上架→PUSH／STORY 自動閉環

**組件已預備、未開啟**（2026-09-24）：`tools/scrape_appstore.py`＋
`.github/workflows/scrape-appstore.yml`（只掛 workflow_dispatch，冇 schedule）。
離線測試已驗證：首次同步 64 項入 catalog、0 張新通告（baseline 防風暴）；
模擬「批核後新 app」（created_at 遲過 baseline）→ 剛好 1 張新 notice、url 去重生效。
啟用時：打開 workflow 內 schedule 註解＋停用 scrape.yml。

```
用家喺 store 投稿 (submit_work)
        ↓
管理者喺 store 後台批核 (review_work) → apps 表新增 visible=true 行
        ↓
core.py 每日 scrape 加一支「虛擬來源」：REST GET apps?visible=eq.true（anon key 就夠）
        ↓ 映射成 notice：title=name、url、pdf_url=url、source_site="SCOUT APP STORE"、
        ↓ tags=store tags（已係支部名）、description、icon=apps.icon
cache.json（captured_date = 系統首次捕獲日，跟現有哲學）
        ↓
notify.py（匿名 Push）＋ story-queue／story-daily 自動當「新通告」派發——零新 dispatcher
```

設計決定：

1. **觸發用 polling 唔用 webhook**：現有 scrape 每日跑一次，頻率同今日更新一致；
   Supabase Realtime／DB webhook 要额外基建，暫時唔值。`submissions` 表匿名讀唔到、
   `apps` 亦冇 `visible_at`／`updated_at` 欄，所以「公開」訊號只能係
   **第一次觀察到某個 `url` 係 `visible=true`**（以 URL 做唯一識別，改名／改標籤／
   換 icon 都唔算新上架；隱藏 app 受 RLS 限制圖書館唔會見到）。
   **2026-11-07 用戶規則（取代 2026-11-06）**：「今天更新/發布」＝ **今日公開**，
   `created_at` 只係 store「入庫日」，唔係上架日；圖書館第一次見到個 URL 亦唔等於公開。
   三種狀態（用戶原話）：
   - 今天公開 = 今天上架；
   - 今天入庫但沒公開（`visible=false`）= 未上架（唔入 catalog、唔計今日，記喺
     `_meta.appstore.pending`；anon RLS 只見到已公開，live 模式見唔到呢類 app）；
   - 之前入庫，但今天公開 = 今天上架（`created_at` 舊過今日都照計）。
   實作（`tools/scrape_appstore.py`）：
   - `_meta.appstore.first_public[url]`＝首次觀察到 `visible=true` 嘅日子，係權威上架日；
     已公開過就保留，改名／改標籤／改描述／換 icon 都唔改日期；
   - `created_at` 只喺「首次同步／baseline 全失」或者防呆降級時做 fallback 日期；
   - 上過架之後喺 store 唔見咗 → `_meta.appstore.delisted`＋`pending`，再上架就係今日；
   - 一次性 `FIRST_PUBLIC_OVERRIDES` 修正 2026-11-07 嗰次 RUN 用舊規則把
     「遊戲學習」(created 11-06、11-07 公開) 寫成 11-06 嘅日期；
   - 防呆 ①：一次過太多「未見過嘅 URL」想變今日（baseline 斷咗／store 換 domain）→
     改用入庫日／BASELINE_DATE 並喺 log 警告；
   - 防呆 ②：store 回傳數目突然大幅縮水 → 當抓唔齊，保留舊 catalog／enrich，
     唔記下架（避免重現「一批舊 app 之後全部變今日」）。
2. **去重**：以 `url` 同現有 49 來源＋手動加入嘅項目對碰；同一 url 已收錄就 skip
  （用家階段 0 手動加過嘅原生 APP 唔會雙重派發）。實作時要確認 core.py 嘅 url 去重行為。
3. **ICON 來源反轉**：階段 2 起前端 tools icon 解像順序改為
   `store apps.icon` → 本地 `icons/awards/*.avif` fallback（「你攞佢 ICON」方向）；
   store 嗰邊 icon 若係 postimg 等外鏈，可考慮 harvest 返嚟 icons/ 做離線副本。
4. **Push／Story 分類**：store apps 映射去 `subscription_catalog.json` 嘅 tools（subtype
   assistant）；branch 標籤直接食 store tags（小童軍／幼童軍／童軍／深資童軍／樂行童軍）。
5. **寫入仍留喺 store**：圖書館唔寫 store；單向讀取，RLS  anon 足夠， circulars 唔需要
   service key（除非再要做階段 1 類測試）。

##  secrets 備忘（邊度搵）

| 需要 | 位置 | 用途 |
|---|---|---|
| service_role key | Supabase Dashboard → Project Settings → API → `service_role` | 階段 1 寫入（bypass RLS）；2026-11-15 起同時畀 appstore 同步用（讀取 visible=false） |
| admin 密碼 | Supabase Dashboard → Authentication → Users（`ai@skwscout.org.hk`） | 階段 1 替代途徑 |
| — | anon key 已喺 `appstore.json` | 一般讀取，唔使額外 secrets |

service_role key 同 admin 密碼只放 GitHub repo secrets／Vercel env，**唔入 repo**。

## 2026-11-15：APP STORE「收埋」× 圖書館隱藏同步（store-hidden.json）

**背景**：用戶新規則——曾經上架嘅 app 喺 APP STORE 被收埋（`visible=false`）/再放出，
圖書館唔刪 cache.json 記錄同原始日期；「收埋」要跟住隱藏，「放出」要連原日期一齊返。
隱藏信號唔可以靠 git history 推斷，要由 store 嘅 runtime 狀態同步。

**RLS 實情（2026-11-15 覆核，三處一致）**：
哨兵 migration 係 `website` repo 嘅 `migrations/20260924-market.sql`：
`create policy "public catalogue" on public.apps for select using (visible = true)`
——anon **睇唔到** `visible=false` 列。佐證：`APPSTORE_INTEGRATION.md`（2026-09-24，
同日 live REST 驗證）、`scrape.yml` 舊註釋（「RLS 限 visible=true」）。
⚠️ `docs/50` 真理倉 SG11-b 條目稱「apps 表匿名可 `select("*")`、收埋只係前端過濾」——
**與 migration 實檔矛盾**，以 migration 為準（讀 code 會誤以為 `store.js`
client-side `a.visible !== false` 係唯一把關）。

**同步鏈（隱藏生效最長 1 天）**
1. `scrape.yml`／`scrape-appstore.yml`：appstore 步驟注入
   `STORE_SERVICE_KEY: ${{ secrets.STORE_SERVICE_KEY || secrets.SUPABASE_SERVICE_KEY }}`
   （secret 名稱複用 `update-store-icons.yml` 現有慣例）。`tools/scrape_appstore.py`
   優先用 service key 讀 `apps`（bypass RLS，睇到 `visible=false`）；冇 key 就退回 anon
   （會 printing `::warning::`，曾經上架而收埋嘅 app 會當 store-missing（delisted）處理——
   行為同 2026-11-07 以前一樣）。
2. `scrape_appstore.py`：曾經公開過而而家 `visible=false` → 保留 cache.json／enrich.json
   記錄同原 `captured_date`，URL 寫入 `store-hidden.json`（data 分支，`data_snapshot.py`
   已收錄此檔）；唔會當 delisted、唔會過當「今日重新上架」。從未公開而 `visible=false`
   → 未上架不收錄。store-missing（連 service key 都搵唔到）→ delisted（舊行為）。
   疑似抓唔齊 → `store-hidden.json` 凍結唔郁（防誤收全館）。
3. 前端 `loadHiddenApps()`：讀 `store-hidden.json`（`?hidden=` 可覆寫；`?raw=` 鏈式推導；
   本地 `/store-hidden.json`）。靜默失敗原則：斷網／404／壞 JSON → 乜都唔收埋（fail-open），
   PWA 離線唔阻畫面。**瀏覽器唔可以直接查 Supabase 判斷收埋**（anon 見唔到隱藏列，
   直查永遠回空陣列，收埋咗嘅 app 會靜靜重新出現）——呢個 PR 早期試過直連，
   因上述 RLS 實情放棄。
4. 顯示層：收埋咗嘅 app 喺正常瀏覽／搜尋／全港／分類／側欄計數全部唔見；
   `⭐ 我的收藏` 仍然見到卡片，標示「⚠️ 已下架（可撳 ★ 取消收藏）」，開啟掣鎖死；
   通告（非小工具）記錄照舊（原站已移除邏輯不受影響）。

**未做／可選（需要另開 PR 或用戶操作）**：
- `first_public` 唔變（仍靠每日快照首次觀察）；`apps` 表冇 `first_visible_at` 欄，
  入庫日（`created_at`）≠ 上架日，唔可以頂替。
- 若想收埋「即時」生效：website repo 加 `security definer` RPC
  （例如 `library_hidden_apps() returns setof text`，`grant execute to anon`），
  前端改讀 RPC；鏡像路徑繼續保留做後備。⚠️ RPC 會令「哪些 URL 已收埋」對公眾可見
  （先公開後收埋嘅 app，URL 本來就公開過）——需要用戶明確同意先整。
- `docs/50` SG11-b 條目建議據實修正（隱藏＝RLS 真正過濾的前端 + 伺服器雙重，
  敏感 App 照樣唔可以單靠收埋當安全邊界）。
