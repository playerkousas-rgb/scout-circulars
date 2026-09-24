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
   Supabase Realtime／DB webhook 要额外基建，暫時唔值。`submissions` 表匿名讀唔到，
   所以「新上架」訊號只能嚟自 `apps` 表出現新 `id`（用 `apps.id` 集合做 fingerprint 去重）。
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
| service_role key | Supabase Dashboard → Project Settings → API → `service_role` | 階段 1 寫入（bypass RLS） |
| admin 密碼 | Supabase Dashboard → Authentication → Users（`ai@skwscout.org.hk`） | 階段 1 替代途徑 |
| — | anon key 已喺 `appstore.json` | 階段 2 讀取，唔使額外 secrets |

service_role key 同 admin 密碼只放 GitHub repo secrets／Vercel env，**唔入 repo**。
