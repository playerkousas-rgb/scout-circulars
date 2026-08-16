> ## ⚠️ 事後更正（2026-08-16）
>
> 本報告下方「v5.6.20 已修復 **港島西區** / **慈雲山區**」嘅結論**與事實不符**，特此更正。
>
> - 兩者喺 **8/14、8/15、8/16 三次排程繼續報錯**，`cache.json._meta.last_run.error_sources`
>   由 8/12 起連續每日都有佢哋，從來冇好過。
> - 當時判斷嘅根因（「Cloudflare 間歇 403/503」）**推論過闊**。實際上係站方
>   **針對性封鎖 `/wp-json/` REST API 路徑**：同一個 `group.scout.org.hk` 網域嘅
>   **深旺區**（`legacy_html`）由頭到尾一日都冇失敗過，證明網域層面通行無阻。
> - 當時加嘅 `fallback_urls` **實際上救唔到**：`_wp_api_fallback()` 內部行
>   `fetch_page(fb_url, config)`，而兩個來源 `use_playwright: false`，
>   即係 API 同 fallback 都用同一種抓法，等於冇 fallback。
>
> **真正修復見 v5.6.21（2026-08-16）**：兩個來源改用普通 HTML 頁抓取，
> 詳情見下方〈v5.6.21〉一節。

# 來源網站健康檢查報告 — 2026-08-13

檢查方法：以平台抓取器逐一訪問 `sources.json` 內全部 49 個來源的主頁/列表頁，
確認 (1) 頁面能否載入、(2) 有否通告內容、(3) 設定（URL/分頁/選擇器）是否仍然匹配。

## 總結

| 狀態 | 數量 | 來源 |
|---|---|---|
| ✅ 正常（可載入且有通告） | 42 | 其餘全部來源 |
| ✅ 正常但沒通告（expected_empty） | 3 | 西貢區、離島區、大嶼山區 |
| ✅ 正常但內容已搬遷 | 1 | 壁峰區（見下） |
| 🔧 發現問題並已修復 | 3 | 觀塘區、總會、九龍地域 |

前端 `index.html` 的 `RAW_CACHE_URL` 指向本 repo `main/cache.json`，設定正確。

## 已修復的問題（v5.6.19）

### 1. 觀塘區 — http 停止服務 ❌→✅
- `http://hkscout-ktd.org/...` 連線被拒（重試多次均失敗）；同站 **https** 正常。
- 修復：`sources.json` 觀塘區 URL 改為 https；`cache.json` 內兩筆舊 http 偽連結同步改 https，避免前端死連結。

### 2. 總會 — 2026 分頁 24 → 29 ❌→✅
- 通告列表「去最後一頁」已指向 page=29；設定只追蹤到第 24 頁，第 25–29 頁（2026 年 1–3 月通告）會漏抓。
- 修復：`listing_page_urls` 補至第 29 頁、`listing_max_pages` 改 29。

### 3. 九龍地域 — Playwright 超時偏短 ⚠️→✅
- Elementor 頁面慢載，原 `wait_timeout: 30000` 低於引擎預設，是 8/12 誤報的誘因之一。
- 修復：`wait_timeout` 改 60000。

### 4. core.py — 網路層自動重試（防短暫抖動誤報）
- 8/12 執行時 `error_sources` = 港島西區、九龍地域、慈雲山區；今日複查三者全部正常，屬短暫網路抖動。
- 修復：`fetch_requests` 對 ConnectionError / Timeout / SSL 短暫錯誤自動重試一次（間隔 2 秒），
  仍以原例外結束（保留 Playwright 降級路徑不變）。已附模擬測試驗證。

## 無須修復的備註

- **壁峰區**：網站正常，但區會已把內容搬到「最新消息」Google 試算表，頁面不再有 PDF 連結，
  因此近期抽不到新通告（cache 內有 10 條歷史紀錄，最後 2026-06-21）。其通告現經**新界東地域**
  Contentful feed 發布並已被抓取（cache 內已有「璧峰區-原野生活知識工作坊 A-101」等紀錄），暫不改設定；
  如未來該 Google Site 重新放通告，指紋機制會自動觸發。
- **西貢區 / 離島區 / 大嶼山區**：網站正常、確實沒有通告，`expected_empty` 標記繼續有效。
- **慈雲山區**：cache 內有一筆「表格下載區」偽紀錄（WP fallback 兜底產物），屬 v5.6.17 設計行為，不影響新通告抓取。

## 工具

新增 `check_sources.py`（唯讀健康檢查，不寫 cache/fingerprints）：

```bash
python check_sources.py            # 檢查全部 49 來源
python check_sources.py 觀塘區 總會  # 只檢查指定來源
```

---

# 第二輪全檢 + 根因修復（v5.6.20）— 同日補充

## 三個 ERROR 來源的根因修復（按用家分析逐項處理）

| 來源 | 根因 | 修復 |
|---|---|---|
| ~~港島西區~~ ❌ **未修好，見 v5.6.21** | ~~`wp-json` 被 Cloudflare 間歇 403/503~~（判斷有誤：實為站方針對性封鎖 `/wp-json/`，非間歇性） | ~~① 第一頁 3 次重試 ② SESSION 瀏覽器標頭 ③ `fallback_urls`~~ — **重試無效**（唔係間歇問題）；**fallback 亦從未生效**（同樣走 requests，一樣被擋） |
| ~~慈雲山區~~ ❌ **未修好，見 v5.6.21** | 同上 | 同上。唯一成立嘅結論係：區會 2026-06-01 起已遷至 `group.scout.org.hk/tws`（通告 TWS-585-26），網址本身正確 |
| 九龍地域 | `use_playwright: true` 跳過 requests 只跑 PW；Elementor analytics 令 `networkidle` 永遠等唔完 → PW 回 `None` 整站 ERROR | HTML 已確認 server-render → `use_playwright: false`（requests 優先，失敗/空白先降級 PW）；PW fallback 嘅 `wait_strategy` 由 `networkidle` 改 `selector(table)` |

## 第二輪全檢額外發現：Google Drive 連結格式轉變（漏抓，非 ERROR）

- **深水埗東區**：2026-27 年度新通告改用 `drive.google.com/open?id=` 連結，`is_download_url` 唔認得 →
  「重走長征路薪火井岡行 D/03/2026」「嘉爾頓錦標賽區選拔賽 04/SSPE/S/2026」等一直靜靜漏抓。
- **油尖區**：3 條舊通告用 `drive.google.com/a/krscout.org/open?id=`，同樣漏抓。
- **修復**：`sanitize_url` 將所有 Drive `open?id=` 正規化為標準 `/file/d/<id>/view`
  （抽取、去重、enrich 下載自動生效；模擬測試確認新舊格式去重合併）。
- **補數**：已清除兩區 fingerprint，下輪執行會強制重掃補回。

## 第二輪全檢總表（49 來源）

- ✅ 正常且有新通告：42 個（包括上述已修復路徑）
- ✅ 正常、expected_empty：西貢區、離島區、大嶼山區
- ✅ 正常、內容改由新界東地域 feed 覆蓋：壁峰區
- 🔧 已修復：觀塘區(http→https)、總會(分頁 29)、九龍地域、深水埗東區、油尖區
- ❌ **當日誤報為已修復、實際仍然失敗**：港島西區、慈雲山區（連續錯到 8/16，見文首更正；已於 v5.6.21 真正修好）
- ❌ 仍無法連接：無（全部來源本日均成功載入至少一次；九龍塘區首次抓取短暫失敗、重試即正常）

## 測試

- 模擬測試 5 場景：WP 重試成功 / API 全敗→fallback / 無 fallback 全敗→error / 九龍地域 requests 優先 / 九龍地域空白→PW(selector wait) — 全部通過
- Drive `open?id=` 正規化 + 去重模擬測試通過
- `test_enrich.py` 14/14 通過；core.py / enrich.py 編譯通過

> ⚠️ 上述「API 全敗→fallback」一項**測試假設有誤**：當時只模擬咗 `wp-json` 被擋、
> 而 fallback 頁用另一條路徑成功。真實情況係 requests 層被擋，fallback 走同一條路
> 亦一樣失敗，所以測試綠燈但線上照樣紅。v5.6.21 嘅
> `test_group_scout_sources.py` 改為直接驗證最終抽到嘅 PDF 與標題，避免同類盲點。

---

# v5.6.21（2026-08-16）— 港島西區 / 慈雲山區 真正修復

## 根因

站方**針對性封鎖 `/wp-json/` REST API 路徑**，而非整個網域或間歇性抖動。證據：

| 來源 | 網域 | 抓取方式 | 近 24 次 run 報錯 |
|---|---|---|---|
| 柴灣區 / 筲箕灣區 / 元朗西區 / 大埔北區 | 各自獨立網域 | `wordpress_api` | **0 次**（全部無 `fallback_urls` 都照常成功） |
| **深旺區** | **group.scout.org.hk** | `legacy_html` | **0 次** ← 同網域對照組 |
| **港島西區** | **group.scout.org.hk**/hkw | `wordpress_api` | **5 次** |
| **慈雲山區** | **group.scout.org.hk**/tws | `wordpress_api` | **5 次** |

即係話：**WP REST API 本身冇問題**（其他 4 個區日日成功），
**`group.scout.org.hk` 網域亦冇問題**（深旺區日日成功），
出事嘅係「`group.scout.org.hk` + `/wp-json/`」呢個組合。
8/16 當日 `playwright_used = 0` 而深旺區出現喺 skipped 名單（＝成功抓到並計到指紋），
進一步證明 runner 用純 requests 打呢個網域嘅普通 HTML 完全冇問題。

## 修復方式：改抓普通 HTML 頁（唔再靠 fallback）

按「童軍區會多屬義務領袖、網站架構好少改動，一次成功通常可用幾年」嘅實情，
直接把主路徑換成穩定嘅 HTML 頁，而唔係加多層 fallback：

| 來源 | 新 URL | 做法 |
|---|---|---|
| 港島西區 | `https://group.scout.org.hk/hkw/circular/` | 年度**索引頁**（2012–2026 全部年度連結，多年冇改過）。`follow_listing_pages` 自動跟入 `circular2026/` 等年度頁 → **2027 年會自動出現，唔使每年手改設定** |
| 慈雲山區 | `https://group.scout.org.hk/tws/` | 主頁已 server-render 全部 post 內容及 PDF 直連；實測共 2 頁（`page/3/` 已無內容），設 `listing_page_urls` 抓埋第 2 頁 |

兩者同時：`type` 由 `wordpress_api` → `legacy_html`、移除唔會觸發嘅 `fallback_urls`。

## 額外處理：標題污染

慈雲山區有啲 post（例如 `PT996`）冇獨立標題、連結文字得個編號，
原本 `title_selector: "h1, h2, h3, .entry-title"` 會令 `infer_listing_title`
退到「全頁揀頭 5 個標題」，結果**錯抄隔壁 post 嘅標題**。
移除該來源嘅 `title_selector` 後，改為優先用 PDF anchor 自身文字（正正就係通告名），
`PT996` 會如實顯示為 `PT996`，唔會扮成第二篇通告。

> 註：一度試過喺 `core.py` 加 `max_title_length` 上限，但實測發現本來源
> 有合法標題長達 70 字（例如「童軍射擊章(技能組)暨 深資童軍射擊(A-304)訓練班 …」），
> 加長度上限會誤殺真通告，故**放棄該做法，core.py 維持零改動**。

## 影響範圍

- **只改 `sources.json` 兩個來源**，其餘 47 個來源設定逐項比對確認無變動
- **`core.py` 完全冇改**（`git diff core.py` 為空）
- 已清空兩者 `fingerprints.json`，下次排程會強制重掃補回
- 資料完整性：修復前 cache 內兩區通告仍齊全（港島西區 2026 年 11 條、慈雲山區 5 條），
  即係「未漏通告，但由 8/12 起已停止更新」，一出新通告就會漏 —— 今次修復正好趕喺漏之前

## 測試

新增 `test_group_scout_sources.py`（離線，唔連外網）：

```bash
python test_group_scout_sources.py
```

依實測 DOM 重建假頁面，驗證：抓得到頁面、跟到年度頁/分頁、抽到正確 PDF、
指紋計得出、標題唔係「下載/Download」、標題唔夾雜內文、無重複 URL、
`PT996` 唔會錯抄隔壁標題、以及唔會再用 `wordpress_api` / 殘留 `fallback_urls`。

- `test_group_scout_sources.py` 全部通過
- `test_enrich.py` 14/14 通過；core.py / enrich.py / check_sources.py 編譯通過
