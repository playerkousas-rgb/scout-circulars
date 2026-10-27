# 日常資料保留策略（2026-10-27）

## 原則

- 程式碼永久保留正常 Git history；不改寫 main、不刪重要 JSON、不停每日更新。
- main 的 JSON 是 bootstrap／開發測試種子，不再是線上最新資料。
- `data` 是單一 **無 parent** commit 的公開完整快照。每次更新換掉 branch tip，
  不把昨天的版本接成今日的 parent；用明確 force-with-lease 防止蓋走並行更新。
- 重要 JSON 每日 Actions artifact 備份保留 30 日；本機 `logs/data-backups/` 同樣保留 30 日。
- Story 圖片不再寫入 Git，不再延續 stories history。舊 stories branch 暫不清理。
- **GitHub size 不會保證即時下降**：已不可達物件的回收由 GitHub 控制。
  單 root snapshot 限制可達歷史，不是 object storage 的硬性容量上限。

## 資料內容與公開 URL

固定 allowlist：`cache.json`、`enrich.json`、`fingerprints.json`、
`subscription_stats.json`、`appstore.json`、`story-queue.json`。
發布工具不會加入 `.env`、其他 working files、程式碼或圖片。
六份 JSON 一起驗證，再原子發布同一個 Git tree。

```
https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/data/cache.json
https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/data/enrich.json
https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/data/fingerprints.json
https://raw.githubusercontent.com/playerkousas-rgb/scout-circulars/data/subscription_stats.json
```

其他 repo 如果讀取 `main/<上述檔案>`，需要改讀 `data/<檔名>`；舊 URL 仍存在，
但之後不會每日更新。需要跨檔嚴格一致的 reader 可先取得 data SHA，再以同一 SHA 讀取全部檔案。

`index.html`、`errors.html`、`stats.html`、PDF proxy 已修改資料來源。
前端及 proxy 僅在新來源 **404** 時 fallback main 種子，保障首次 bootstrap 前仍可用；
不會把其他 HTTP 錯誤或自訂測試 URL 靜默改成 main。正式統計頁優先讀 data，
不再讓凍結的同源 JSON 蓋住最新統計。
本機預覽保留相對路徑資料讀取。

## 上線順序（尚須在 GitHub Actions 執行）

1. 將本工作分支變更經正常 PR 合併 main；不 force-push main。
   首次 snapshot 前網頁仍可用 main 的種子資料。
2. 立即執行 **Bootstrap latest-only data**。它從最新 main 取 seed；如果 data 已存在，
   會優先載入 data，不會重設成舊 seed。成功後驗證 commit 無 parent、history 數量 = 1，
   以及 public cache URL 與本次 snapshot 位元組一致。若每日 scraper 先跑，它亦可完成 bootstrap。
3. 執行 **Scout Notice Scraper**；檢查 30 日 artifact、data 發布和網頁更新時間。
   `scrape-appstore.yml` 改成手動替代流程，避免兩份相同 cron 重複全網抓取。
4. 驗證通知與 PDF 附件、errors 頁、統計頁。通知以載入的 snapshot 作 baseline，
   保留原有 captured-date catchup 及 Supabase delivery 去重，沒有用凍結 main 作永久 baseline。
5. 執行 **Clean temporary Story images**，驗證 Storage 權限；先手動 preview（不發 IG），
   確認素材正常後再測 publish 或等每日排程。IG 發布測試真的會發佈，勿反覆補跑。
6. 執行 **Repository size guard**，記錄第一次基準。API size 是 KiB，報表轉 MiB；
   本地 object 數是另一種度量，不把 shallow clone 計數當全 repo 大小。

本工作環境不能讀取 Actions secret 清單（GitHub integration 回覆 403），也不能直連
Supabase／Meta／GitHub Raw 做端到端驗證。沒有聲稱上述線上步驟已成功。

## Story 臨時素材

沿用已有 Actions secrets `SUPABASE_URL`、`SUPABASE_SERVICE_KEY`，不把值放入 Git。
首次執行會在該 Supabase project 建立專用 public bucket `scout-story-temp`，
限制 JPEG、每檔 8 MiB；只透過 service key 寫入／刪除，無需開放匿名寫入 policy。
這是新增的臨時 object storage 用量，不是資料庫表，也不會修改通知資料。

- 發佈模式只上傳 manifest 指定的 JPEG，每次 run 使用唯一目錄。
- 保留公開圖片可讀驗證、Meta container FINISHED gate、單次 media_publish，
  不因容器建立成功便立即刪圖片。
- 全批 IG 發佈回傳成功後刪該 run 圖片；部分失敗／不確定發佈結果保留到期清理，
  不因清理而重發任何 Story。
- 每小時獨立 cleanup，刪除超過 24 小時的受管理目錄；每次上傳前亦清理。
  GitHub schedule 可能延遲，所以這是「到期後下一次成功清理」，不是精確 24 小時 TTL。
  清理失敗會令新的上傳停止，避免在清理壞掉時仍無限新增。
- 手動不發布模式只輸出一天期 Actions preview artifact，不上傳公開 bucket。
- Story 失敗不阻塞獨立 scraper／notify workflows。
- App 不再請求舊 stories hero 圖；詳情正常文字顯示，原有通告、PDF、分享與手動製圖保留。
- IG 不是原圖備份；本政策明確接受不保存已發布的原圖。

## 本機抓取與救援

Windows 排程入口仍是 `run-local-scrape-logged.bat` → `run-local-scrape.bat`。
新入口呼叫 `tools/local_scrape.py`，順序：備份現有資料 → 更新 code（ff-only）→
載入 data → 全網抓取／App Store 同步／增量 enrich → 本機備份 → 發布 data。
不再自動 commit/push main，也不會替使用者推送其他程式碼。
保留來源衝突／未推送舊 commit 時安全停止，不再自動改寫本機 history。
網絡或 data lease 衝突會報錯，保留本機救援檔，不拿過時資料覆蓋線上。
失敗抓取的部分結果會備份但不自動發布。

手動讀取最新快照：`python tools/data_snapshot.py load`。
發布必須先 load，再執行資料更新，最後 `python tools/data_snapshot.py publish`。
如果有其他 writer 搶先發布，需要重新載入並重跑工作，不能盲目強推舊 snapshot。
需要回復備份時，先 load 最新 data，經人工確認後把備份 JSON 複製回 working tree，再 publish。

## 未做的事情

- 不刪 stale arena branches、不重寫 main、不清 GitHub pull refs、不改 LICENSE。
- 不改 `.vercelignore` 核心清單、requirements 或 Vercel retention/prune/bundle guard。
- data snapshot 自帶禁止 Vercel deployment 設定；不依賴 `[skip ci]` 阻止 Vercel。

## 本次觀察值（上線前）

2026-10-27 GitHub API size = 161744 KiB = **157.95 MiB**；
GitHub commits API pagination：main **616** commits、stories **22** commits；
遠端 **data branch 尚不存在**。這是遷移前數字，不是清理成果。
本地 checkout 是 shallow clone，`git rev-list origin/main` 的 1 不是實際 main commit 數。
