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

---

# v5.6.22（2026-08-16）— 三個「靜默失敗」來源

呢三個來源**從來冇出現喺 `error_sources`**，所以每日報告都話健康，
但實際上抓錯嘢或者長期漏抓。純睇 error 清單係捉唔到，要對比網站實際內容先發現。

## 1. 觀塘區 — 由頭到尾冇抓過真通告 ❌→✅

- **問題**：cache 內兩筆「1 支部通告-童軍」「1 支部通告-幼童軍」，
  URL 係 `event-and-program.html#…`，其實只係**分類目錄連結**，唔係通告。
  舊設定 notes 自己都寫明係暫代方案（「先以分類件數變化作 fallback 監控；
  後續若找到實際下載頁再切換」），但一直未切換。
- **真實結構**（Phoca Download / Joomla）：
  總頁 → 6 個支部分類頁 `event-and-program/category/*` → 通告內頁
  `event-and-program/file/*.html`（例如第21屆初級航空活動章訓練班，2026-08-06）
- **修復**：`follow_listing_pages` 跟入 6 個分類頁 → `follow_detail_pages`
  收錄 `file/*.html`。因為內頁唔係 `.pdf` 結尾，要開 `accept_all_links` 繞過
  `is_download_url`；另把 `?tmpl=component`（同一通告嘅 Details 彈窗版）
  加入 `url_sanitize` 去重。
- 已清走 cache 內兩筆假通告。

## 2. 深水埗西區 — type 由頭到尾設錯 ❌→✅

- **問題**：設定寫 `type: "wordpress"` + `.entry-title` 選擇器，
  但 `sspw.krscout.org` **實際係 Google Sites**（自訂網域）。
  所有選擇器 match 唔到，只靠兜底抽到 2 筆雜項，其中一筆標題直情係 `view`。
- **修復**：改 `type: "google_sites"`，直抓 Drive PDF 連結，
  加 `exclude_patterns` 隔走 Report abuse 等；
  `title_selector` 用 Google Sites 標準 `.C9DxTc`，
  令「下載通告」呢類通用字樣唔會變標題，而係取返區塊內真標題。
- 已清走 cache 內「view」雜項。

## 3. 旺角區 — Drive `resourcekey` 遺失，長期漏 2 個 PDF ❌→✅

- **問題**：Drive 內實際有 **5 個 PDF**，cache 長期只有 3 個。
- **根因**（`core.py` bug，非設定問題）：舊式（約 2015 年前建立）Drive 資料夾
  除咗 `id` 仲要帶 `resourcekey`，否則 `embeddedfolderview` 回 **HTTP 500**。
  原本 regex 只捉 `id=([\w-]+)`，把 `resourcekey` 丟棄 →
  「深資童軍」同「區會/其他文件」兩個舊資料夾永遠 500，靜靜漏咗：
  - `MKD VS&RS比賽2025_通告.pdf`（2025-10-23）
  - `香港童軍115周年旺角區童里匯聚樂融融嘉年華…通告.pdf`（2025-12-18）
- **修復**：regex 連 `resourcekey` 一齊捉（支援 `&` 同 `&amp;`、
  以及新式 `/drive/folders/?resourcekey=`），同一 id 若有 key 優先保留；
  另外資料夾非 200 時會明確 log 出嚟，唔會再靜靜吞咗。
- 已驗證 7 種 URL 格式向後兼容（無 key 嘅資料夾行為不變）。

## 測試

新增 `test_source_fixes_v5_6_22.py`（離線）：

```bash
python test_source_fixes_v5_6_22.py
```

驗證觀塘區抓到真通告且無分類目錄/重複、深水埗西區只收 Drive PDF 且標題正確、
旺角區 5 個 PDF 一個都唔少。另加 7 個 `resourcekey` URL 格式向後兼容測試。

- `test_source_fixes_v5_6_22.py`、`test_group_scout_sources.py` 全部通過
- `test_enrich.py` 14/14 通過；全部檔案編譯 OK
- 三個來源指紋已清空，下輪強制重掃

## 給日後嘅提醒

`error_sources` 為空 **唔等於** 全部來源健康。呢三個都係「有嘢抓到、
但抓錯嘢」，機制上唔會報錯。

### ~~抽查資產數 <5 筆嘅來源~~ → 改用 `check_stale.py`（v5.6.23）

原本寫「抽查資產數少過 5 筆嘅來源」，**呢個定位唔好，已推翻**：

- **93% 來源（43/46）都有 5 筆以上**，中位數 54 筆 →
  「<5 筆」只覆蓋到最尾 7%，其餘 93% 完全冇監察。
  總會（838 筆）、筲箕灣區（504 筆）如果今日壞咗，永遠唔會被 flag。
- **站方定期清舊通告**係常見做法，剩返兩三張唔代表壞咗。
- 數量係**存量**，同「而家仲運作緊嗎」冇必然關係。

改用**「N 個月冇新通告」**（預設 90 日）做主準則。以實際數據校準：

| 指標 | 數值 |
|---|---|
| 46 個來源歷來最長靜默 | **81 日** |
| 出通告間隔 90 百分位 | 37 日 |
| 90 日門檻今日誤報數 | **0** |

90 日門檻對現有來源零誤報，同時對「清舊通告」「已累積幾百張」兩種情況都免疫。

### 但 90 日有盲點，所以加咗第二條準則

如果來源**持續抓到假嘢**，`captured_date` 會一直更新，永遠唔會過期。
實測：用純 90 日門檻回帶到 8/16 修復前，**三個壞咗嘅來源全部走漏**
（距今只有 9–17 日）。所以另加「內容型態」檢查，捉標題係
`view`／`1 支部通告-童軍` 呢類垃圾。回帶驗證成功捉返觀塘區同深水埗西區。

⚠️ 特意**唔當「URL 有 #」為垃圾**：將軍澳區等站通告內容直接寫喺 HTML，
用 `notice.php#錨點` 指向該則通告，係正常設計。第一版規則曾經誤報咗佢，已修正 ——
判斷重點係「標題有冇真內容」，唔係 URL 型態。

### 兩條準則都捉唔到嘅情況

**旺角區式漏抓**（抓到嘅嘢正常，但少咗兩張）淨睇 cache 係偵測唔到嘅，
必須同網站實際內容對比。呢類建議每季人手抽查一次，或者用
`check_sources.py` 連線核對。

### 網頁診斷儀表板已同步（v5.6.24）

`errors.html`（你平時睇嗰個報告）原本用 **14 日**做「長期未更新」門檻，
同 90 日校準結果唔一致 —— 實測會日日列出 **26 個**其實正常嘅來源（暑假淡季），
造成警報疲勞，真問題反而會被淹沒。

已同步修正：

| 項目 | 舊 | 新 |
|---|---|---|
| 長期未更新門檻 | 14 日 | **90 日** |
| expected_empty 來源 | 照計入 | **排除** |
| 疑似抓錯內容 | 冇 | **新增卡片 + 表格** |

網頁邏輯同 `check_stale.py` **完全對齊**，已用真實 cache 交叉驗證兩者結果一致。

### 新鮮度分欄（v5.6.25）

單一「90 日」門檻只答到「有冇死」，答唔到「幾新鮮」。已改成六欄分佈：

| 今天 | 7 天內 | 14 天內 | 1 個月內 | 3 個月內 | 超過 3 個月 |
|---|---|---|---|---|---|
| 1 | 12 | 6 | 11 | 15 | 0 |

（2026-08-16 實測，45 個來源，已排除 expected_empty；網頁同 `check_stale.py` 數字一致）

- 六欄互斥且窮盡，總和必定等於來源總數
- 撳任何一欄可篩選下面清單；再撳一次還原
- 只有「超過 3 個月」係紅色警示，31–90 日標為「淡季靜止」（暑假常態，唔算異常）
- 疑似抓錯內容嘅來源，即使日期新鮮都會喺狀態欄標紅

回歸測試：`test_errors_dashboard.js`（jsdom，17 項檢查，含點擊互動）。

### 用法

```bash
python check_stale.py              # 預設 90 日
python check_stale.py --days 60    # 自訂門檻
python check_stale.py --json       # 接 CI（有問題 exit 1）
```

`test_check_stale.py` 涵蓋 8 組情境，包括「500 張但停止更新要 flag」、
「1 張但持續更新唔好 flag」、「錨點通告唔好誤報」、「六欄互斥且窮盡」等。

---

## v5.6.26 — 修復港島南區 24 筆標題為 "view"

### 根因

Google Drive 連結格式係 `https://drive.google.com/file/d/<id>/view`。
`core.py` 嘅 `fallback_title_from_url()` 喺 anchor 冇文字時，會攞 URL
**最尾一段**做標題 —— 而 Drive 連結最尾一段永遠係 `view`。

`clean_title()` 本身有 generic 黑名單擋 `download`／`檢視`，但**漏咗 `view`**，
所以呢個假標題一路穿過所有檢查寫入 cache。

### 影響範圍

- 港島南區 36 筆之中 **24 筆**（67%）標題係 `view`
- 24 筆嘅 Drive 連結**全部有效**，只係標題錯 —— 即係「有嘢但認唔出」

### 修復

**一、防止復發（`core.py`）**

| 改動 | 內容 |
|---|---|
| `URL_TAIL_NOT_A_FILENAME` | 新增集合，列出 `view`/`preview`/`edit`/`document` 等**唔係檔名**嘅路徑段 |
| `looks_like_opaque_id()` | 新函式，認出 Drive file id / UUID 等隨機字串（大小寫混雜＋數字，或超長 token） |
| `fallback_title_from_url()` | 由尾向前搵第一段似檔名嘅；全部唔似就回 `None`（唔再砌假標題） |
| `GENERIC_DOWNLOAD_TITLES` | 補入 `view`/`preview`/`open`/`檢視`/`預覽`/`瀏覽` |

設計取捨：搵唔到標題時**回 `None`（丟棄該筆）而唔係砌個假標題**。
假標題會污染 cache 又難察覺；丟棄至少會喺「零資料／抓錯內容」報告亮燈。

**二、清走已污染資料（`fix_hks_titles.py`）**

逐份開 24 份 PDF 攞內文標題。**唔可以信 PDF metadata** —— 好多份 metadata
都錯寫成「港島南區幼童軍支部比賽2023」（用舊檔另存為冇改）。內文第一個標題行先係真標題。

修復後例子：

| 舊 | 新 |
|---|---|
| view | 港島南區 40 周年活動 の「童」賀聖誕營火會 |
| view | 第 543 屆童軍領導才訓練班 |
| view | 幼童軍金紫荊獎章考驗營 2024（一） |
| view | 小童軍聖誕老人村派對 |

### 驗證

- 全庫 **4493 筆**用**現有真實標題**重跑新邏輯 → **0 筆被誤殺**
- 港島南區仍然 36 筆（無丟失），24 筆有真標題
- `check_stale.py` 由「可疑 3」變 **「可疑 0」**
- 新增 `test_url_title_fallback.py`（6 組、28 項檢查），測試過程中仲捉到
  一個未發現嘅漏洞：`/document/d/<id>/edit` 會退回攞到 `document`，已一併修好
