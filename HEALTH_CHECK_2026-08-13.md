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
| 港島西區 | `wp-json` 被 Cloudflare 間歇 403/503；舊邏輯第一頁非 200 即 `return None` 整站報錯；WP 呼叫用獨立 `requests.get` 無瀏覽器標頭 | ① 第一頁 3 次重試（403/429/5xx/網路異常，backoff 遞增）② 改用 SESSION 完整瀏覽器標頭 ③ 新增 `fallback_urls`：API 徹底失敗時改抓 `circular2026/` HTML 通告頁（已驗證：server-render、11 個 PDF） |
| 慈雲山區 | 同上（同一套死法） | 同上；fallback 為主頁 `group.scout.org.hk/tws/`（已驗證有全部 post + PDF 直連）。另確認區會 2026-06-01 起已遷此網址（通告 TWS-585-26），現行 API URL 正確 |
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
- 🔧 已修復：觀塘區(http→https)、總會(分頁 29)、港島西區、慈雲山區、九龍地域、深水埗東區、油尖區
- ❌ 仍無法連接：無（全部來源本日均成功載入至少一次；九龍塘區首次抓取短暫失敗、重試即正常）

## 測試

- 模擬測試 5 場景：WP 重試成功 / API 全敗→fallback / 無 fallback 全敗→error / 九龍地域 requests 優先 / 九龍地域空白→PW(selector wait) — 全部通過
- Drive `open?id=` 正規化 + 去重模擬測試通過
- `test_enrich.py` 14/14 通過；core.py / enrich.py 編譯通過
