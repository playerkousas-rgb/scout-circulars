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

## 無需修復的備註

- **壁峰區**：網站正常，但區會已把內容搬到「最新消息」Google 試算表，頁面不再有 PDF 連結，
  故一直抽不到通告。其通告現經**新界東地域** Contentful feed 發布並已被抓取
  （cache 內已有「璧峰區-原野生活知識工作坊 A-101」等紀錄），暫不改設定；
  如未來該 Google Site 重新放通告，指紋機制會自動觸發。
- **西貢區 / 離島區 / 大嶼山區**：網站正常、確實沒有通告，`expected_empty` 標記繼續有效。
- **慈雲山區**：cache 內有一筆「表格下載區」偽紀錄（WP fallback 兜底產物），屬 v5.6.17 設計行為，不影響新通告抓取。

## 工具

新增 `check_sources.py`（唯讀健康檢查，不寫 cache/fingerprints）：

```bash
python check_sources.py            # 檢查全部 49 來源
python check_sources.py 觀塘區 總會  # 只檢查指定來源
```
