# 圖書館 Log Book 人工覆核 — 2026-10-16

> **後續實作已完成（2026-10-16，本地分支，未部署）**：補錄 25 筆真實發出日期；7 份／9 URL 的對象與訂閱標籤補正；Story 各類優先、最多 5 張且去重。以下原報告保留為修復前快照；實作、驗證及尚待核實事項見文末「實作補記」。

## 範圍與結論

- 基準：本分支 `a0c81250f0dd966b6020575f3832bb1877697846` 的 `cache.json`、`enrich.json`、`sources.json` 及爬蟲程式；cache 更新時間 2026-10-16 05:00:07 HKT。
- 通告抽取：只篩 `captured_date` 為 **2026-10-15 / 2026-10-16**，共 **45 筆（37 + 8）**。這是入庫日，不是原文發出日。
- 已逐份讀原文核對其中 **27 筆非空 audience**；其餘 18 筆只做資料盤點，沒有把「空值」一律當成錯誤，也不宣稱完成 45 份所有欄位覆核。
- 來源：重訪 3 個 expected_empty 網站、7 個 >90 日來源，並加查觀塘區。Scout System 只核對配置，沒有假稱連到未設定的網址。
- **確定漏抓：沙田南區、璧峰區（repo 名稱「壁峰區」）。** 何文田、鯉魚門、元朗東、十八鄉的可見最新通告／附件樣本已在庫；雙魚可見內容偏舊，但有失效附件、標題不準及純 HTML 內容未完整收錄等另外問題。
- **確定多抽對象至少 6 筆**，另有一筆職務／身分範圍混淆；也發現多筆漏抽。不能只靠再加幾個支部關鍵字解決。
- 本次是研究報告：**未修改 production 程式、來源配置、cache、enrich、指紋；沒有觸發抓取／推送／補發。** 已處理的 Supabase 連接問題及已刪除的 Vercel 用量報告不列入待辦。

## 1. SKIP 是甚麼，今次是否合理？

最新 `last_run.skipped_sources` 只有以下四個；不是「四個網站網絡失敗」。

| 來源 | 實際配置／今次人工看到的情況 | 結論 |
|---|---|---|
| [西貢區](https://sites.google.com/hkscout-skd.org/website/首頁) | `expected_empty: true`；公開首頁主要是 2024–25 區務／執委名單，未見通告下載 | 本次所見支持繼續跳過；不代表私人群組沒有通告 |
| [離島區](https://sites.google.com/view/islands-scout/活動與訓練?authuser=0) | `expected_empty: true`；活動與訓練頁只有標題；另看首頁亦只見聯絡資料、圖片 | 本次所見支持繼續跳過 |
| [大嶼山區](https://vincentpun213.wixsite.com/lantauscout) | `expected_empty: true`；首頁是誓詞及五支部入口，未見通告下載 | 現有首頁 skip 合理；未逐頁完成全部支部／圖片／私人連結審計，不作「全站永久沒有通告」保證 |
| Scout System | `enabled: false`、`url: ""`，說明寫明正式網址待定 | 屬刻意停用，不是爬蟲漏抓；須有正式來源網址才能重啟 |

另有另一種 SKIP：`process_source()` 在主頁指紋相同時，不再解析／跟子頁。這種「主頁沒變」**不保證所有支部子頁／附件內容沒變**。目前本機 `--force` 能繞過指紋閘，但不能補救設定根本沒有覆蓋的子頁。

## 2. 七個長期未更新來源：人工對照

警報日數是「最近入庫日距今」，不是已證實網站最後更新日，也不是活動日期。

| 來源 | 庫內最近入庫／日數 | 原站證據 | 判斷 |
|---|---|---|---|
| [何文田區](https://hmt.krscout.org/活動及訓練) | 06-14／124 日 | 可見 7/30–8/4 泰北服務之旅、7/5 Pickleball、6/27 游泳考驗的 Drive ID 都已在庫；頁面實際為 Google Sites | 本次可見最新連結未見漏抓；配置仍寫 WordPress／`.entry-content`，屬脆弱舊設定，不能當它完全健康 |
| [鯉魚門區](https://www.hkscout-lym.org/活動通告) | 06-30／108 日 | 最上方填色結果、12 月「童鯉馬拉遊」、8 月消防班及其 Drive ID 已在庫；實際也是 Google Sites | 本次可見最新連結未見漏抓；「12 月活動」不等於 12 月才發布，不能拿活動月份判斷漏抓 |
| [元朗東區](https://yle.scout-ntr.org.hk/allNotice.php) | 05-23／146 日 | 原站最新上載仍是 **2026-05-08** 的露營技能考驗、地圖閱讀訓練班；兩個精確 PDF URL 在庫 | 此通告頁確實長期沒新上載，暫無理由修爬蟲 |
| [十八鄉區](https://www.sph-scout.org.hk/circular.htm) | 05-30／139 日 | 整張表最上方仍是 P&T2024/14 愛護動物、P&T2024/13 水上安全；兩個精確 URL 在庫 | 此通告頁確實偏舊，未見 2025／2026 新通告；不代表區會沒有舉辦活動 |
| [雙魚區](https://www.syd-hkscout.org/活動及通告/雙魚區通告) | 06-07／131 日 | 可見最新活動是 2025/11 工作坊；庫內已有該檔案及原野烹飪等五個檔案的 view／preview 記錄。原站部分嵌入顯示 Page Not Found | 未見 2026 新通告可證明最近漏抓；另有失效 Drive／檔名式標題／HTML 內文收錄不全問題。不能稱「完整健康」 |
| [璧峰區](https://sites.google.com/view/pikfung-district/區會通訊?authuser=0) | 06-21／117 日 | 首頁指向支部頁；[童軍頁](https://sites.google.com/view/pikfung-district/支部通訊/童軍) 有公民等五章班、第 7 屆原野烹飪技能／教導組；[深資及樂行頁](https://sites.google.com/view/pikfung-district/支部通訊/深資及樂行童軍) 有 PFD2627VS004 政制探究及民政班、A-101 工作坊，均不在此來源現有十筆記錄 | **確定覆蓋不足，不能當真實沒更新**。未取得各嵌入 PDF 的原始發出日／ID，不捏造發布日期 |
| [沙田南區](https://www.stsd-scout.org/programme/notice) | 05-30／139 日 | 原站列約 22 個不同 notice URL；例如 [175 急救證書](https://www.stsd-scout.org/programme/view_notice/175) 內文日期 **2026-09-02**，另有 174 歷史章、173 情緒日營、172 領袖會議；庫內 9 筆卻全是資源／表格，**0 個 `/programme/view_notice/` URL** | **確定嚴重漏抓、並抓到不相關內容**；網站不是停在 5 月 |

### 璧峰區的程式原因

`sources.json` 設 `follow_detail_pages: false`，也沒有 `follow_listing_pages`／支部 `listing_page_urls`。所以首頁即使成功抓到，實際通告所在支部子頁亦不會掃。

下一步應明確列出官方支部通訊入口、處理其 Drive 嵌入，並測試「主頁不變、子頁新增」也能被偵測；不能只把 `body` 換另一個 selector 就當修好。

### 沙田南區的程式原因：確定現象 + 已重現的失敗機制

`extract_detail_assets()` 對整頁所有 `a[href]` 抓可下載檔案，包括側欄／選單的資源。`allow_page_notice_fallback` **只在 `not records`** 時才收內頁通告。

因此一張內文沒有 PDF 的真通告，只要頁面附帶「船鐘報時.pdf」這類共用資源，就會把資源當成果，反而不收通告 URL。用代表性重建 HTML（非完整原站 DOM）離線重現：

- `<h2>急救證書課程</h2><p>2026年9月2日</p>` → 收 `/programme/view_notice/175`。
- 同一內文加 `<aside><a href="/media/resources/1515381485_bell_signal.pdf">船鐘報時</a></aside>` → **只收船鐘報時 PDF，不收 175**。

這個機制與目前九筆資源／表格、零通告 URL 的庫況高度吻合。完整 raw HTML 未能在本機 requests 重放，所以不聲稱已取得精確 DOM trace。修正須限制正文資產範圍，並讓已確認的 HTML 通告不會被共用資源壓掉；不要全站無條件收每個 URL。

### 加查觀塘區

[總頁](https://hkscout-ktd.org/ktdweb/index.php/event-and-program.html) 現時童軍分類顯示 (1)，其他分類 (0)；[童軍分類](https://hkscout-ktd.org/ktdweb/index.php/event-and-program/category/3-2023-12-09-06-20-36.html) 真的只有「第21屆初級航空活動章訓練班」，已在庫。

前次「2/3 垃圾標題」警報主要是**舊分類假通告仍留在 cache**；配置 8 月已改抓 file 內頁。今次沒有證據支持「目前爬蟲仍然每天新抓錯兩筆」。不應為了警報盲改現行 selector，也不直接刪歷史資料。

## 3. 對象多抽：原文證據

| 通告 | 現有 audience | 原文與判斷 |
|---|---|---|
| [森林舞蹈 KT72](https://scout.org.hk/uploads/tc/circulars/26408/KT72_26.pdf) | 童軍、領袖、會務委員 | 資格是有效領袖／教練員／會務委員委任或受薪職員；「童軍運動基本原則」是前置課程。**多抽童軍，並漏受薪職員** |
| [深資進度性獎章 KT73](https://scout.org.hk/uploads/tc/circulars/26409/KT73_26.pdf) | 童軍、領袖、會務委員 | 同上，是領袖技能班，不是讓童軍成員上這班；**多抽童軍**。不能憑標題有深資，就改加深資成員 |
| [童軍支部訓練方法 Trg20](https://www.scout.org.hk/uploads/tc/circulars/26353/Trg20_26_9thSectionalTrainingMethodsCourseM2AB.pdf) | 童軍、領袖 | 原文「童軍支部領袖委任書／非支部領袖委任書／受薪職員」；**「童軍支部領袖」被拆成童軍＋領袖** |
| [幼童軍營費資助 Sp19](https://www.scout.org.hk/uploads/tc/circulars/26376/Sp19_2026-Cuboree2026_YouthSubsidy.pdf) | 幼童軍、童軍、家長 | 資助資格明確是 8–11 歲幼童軍；「童軍成員編號」不是童軍支部，「獲得家長或監護人的同意」也不是家長可獲資助。**多抽童軍及家長** |
| [寰宇童軍章 P109](https://scout.org.hk/uploads/tc/circulars/26401/P109-26.pdf) | 童軍 | 真正參加資格是深資＋樂行。資格之前另有「服務對象必須為非童軍成員」；目前寬鬆 label 搜尋會先中「服務對象」，也不理解「非」。**抽錯整個對象，不只是漏字** |
| [寰宇探索課程指引 P110](https://scout.org.hk/uploads/tc/circulars/26402/P110-26.pdf) | 深資童軍、樂行童軍、童軍 | 學員資格只有深資＋樂行；緊接「班領導人資格」提到「寰宇童軍章導師」。**多抽童軍**；欄位越界是可重現機制，但尚未取得本次 pdfplumber 原始行序來唯一確定路徑 |

另外：[沙田東深資支部領袖會議](http://www.stescout.org/pdf/circular%202026/cir_2026_pt14.pdf) 現為「深資童軍、領袖」。原文是支部領袖／旅團負責領袖／團執行委員會主席／學校旅老師。**不能把普通深資成員全當可報名，也不能把深資完全刪掉而漏主席**；需要保留職務限定，這不是單純 regex 刪詞能完整解決的問題。

## 4. 漏抽及原文自身問題（同一批資料）

| 通告 | 現有結果 | 實際情況 |
|---|---|---|
| 有蓋訊號台工作坊 Prog59 | 領袖 | 原文另有年滿 12 歲的各支部成員；不能只顯示領袖，也不能擴成無年齡限制的全部小幼童軍 |
| 羽毛球會招會員 Prog64 | 領袖 | 原文另有年滿 18 歲的各支部成員；須保留成年條件 |
| 深圳探索之行 I_MA04 | 領袖、會務委員 | 原文「各級支部成員、領袖、會務委員及家屬」，漏成員與家屬；「家屬」不應一律硬改成「家長」 |
| 柴灣攤位設計 CHW-2627-20 | 領袖、家長 | 原文「本區各支部成員、領袖及家長」，漏各支部成員 |
| 深東防騙國安嘉年華 D/05 | 童軍 | 原文含小童軍、幼童軍、童軍、幼稚園、小學生及坊眾；實際對象比系統廣得多，需再核原始 PDF 行序／表格定位 |
| 深東四格漫畫 D/05A | 小童軍、幼童軍 | 原文另有其他組（所有人士）、幼稚園／小學／中學組；漏公眾，不能只看公函收件人 |
| 皮革藝術與生活 Prog63 | 小童軍、幼童軍、童軍、領袖、家長、會務委員 | 原文「各級童軍成員」及親友；這六種並非多抽，反而未完整表示所有支部及親友。不能機械刪除領袖或家長 |
| [九灣小漁夫 PT-15-26](https://www.hkscout-klb.org/web2017/assets/kb_documents/notice/2026/PT-15-26.pdf) | 童軍、家長 | 資格行原文真的錯寫「本區小支部童軍支部成員及其家長」；但前言、收費、報名表支部均指小童軍。**原文 typo + 系統缺乏矛盾檢查**，不能假裝該行本來就寫小童軍 |

保護案例：

- 小童軍親子原野新煮意：明確邀小童軍、家長、領袖；三者應保留。
- 紅磡小童軍快樂傘：原文明定每隊 1 名領袖＋10–12 名小童軍，領袖不是僅在同意書簽名；不能一律當多抽。
- 紅磡幼童軍主席盾：領袖僅在隨團／報到等要求，現有 audience 只列幼童軍，合理。
- 觀鳥領袖座談會：原文邀領袖及會務委員，兩者應保留。

## 5. 為甚麼會錯：程式根因

### 5.1 欄位定位不是語義定位

`enrich.py:locate_label_scope()` 用 `any(k in c for k in label_keys)`，並回第一個命中。`label_keys` 包括很闊的「對象」「資格」，所以「服務對象」「班領導人資格」也可能中。它不是優先找真正的「參加資格」。

後續固定兩行 + 有限編號清單延伸，stop_keys 未涵蓋所有欄位（例如資助金額、班領導人資格、會議形式）。PDF 換行位置一改，結果也會改。不能以網頁工具抽出的 Markdown 行序冒充 production pdfplumber 行序。

### 5.2 名詞子字串不是參加者身分

`extract_audience()` 依序找小童軍／幼童軍／深資／樂行／童軍／領袖等，再移除已中詞。它可以防止「幼童軍」內再中童軍，但不理解：

- 童軍支部領袖 → 職務，不是兩個報名對象。
- 童軍成員編號／童軍紀錄冊 → 證明文件，不自動表示童軍支部。
- 童軍運動基本原則訓練班 → 前置課程，不是參加身分。
- 非童軍 → 否定詞，不應正向變成童軍。

### 5.3 家長同意的遮罩只涵蓋少數寫法

現行 regex 只遮 `家長…同意書/同意` 等緊貼寫法，沒有覆蓋「家長或監護人的同意」。因此一個已修過的類型仍會由不同句式重現。

### 5.4 只識枚舉詞，缺少年齡、各支部、職務限定

規則找不到「各支部成員」「各級支部成員」「親友」「受薪職員」等完整語義，也不保存 12+、18+ 或主席條件。若只把「各支部」粗暴展開所有支部，會製造另一種錯推。

### 5.5 往下游擴散到訂閱標籤

`subscription_tagging.extract_branch_ids()` 優先信任非空 audience。錯了的「童軍」不只顯示錯，也會變成 `branch_tags`，可能進一步產生 `training:童軍`。不能只改畫面文案，卻保留舊訂閱標籤。

此外前置課程也出現在 KT72／KT73 的 course／wood-module 訂閱 evidence；現有 requirement-noise 過濾不足，應獨立核實，不能把所有全文提過的課程都當正在招募的班。

## 6. 離線重現方式與限制

本次以 `.venv` 安裝 BeautifulSoup／requests，直接呼叫現有純解析函數，不連資料庫、不寫入通告。

以下摘錄重排了換行，目的是**最小機制重現**，不是宣稱原始 PDF 文字 dump：

```python
from enrich import extract_audience
print(extract_audience(
    '參加資格：1. 持有有效領袖委任書、教練員／會務委員委任證或受薪職員；\n'
    '2. 完成領袖初級訓練班；或\n'
    '完成童軍運動基本原則訓練班（單元1A及單元1B）。\n費用：港幣60元'))
# 童軍、領袖、會務委員

print(extract_audience(
    '受資助資格：持有有效幼童軍紀錄冊及童軍成員編號的幼童軍'
    '（必須獲得家長或監護人的同意）；\n資助金額：每位港幣300元'))
# 幼童軍、童軍、家長

print(extract_audience('參加資格：本區各支部成員、領袖及家長\n費用：免費'))
# 領袖、家長

print(extract_audience(
    '（六）參加資格：持有有效所屬支部紀錄冊之深資童軍及樂行童軍支部成員\n'
    '（七）班領導人資格：\n班領導人必須為本會委任之寰宇童軍章導師'))
# 深資童軍、樂行童軍、童軍
```

原站核實透過網頁／PDF 讀取工具；本機 requests 到沙田南的連線因 TLS 中斷，沒有繞過網絡限制做全量爬取。網頁工具讀到的公開內容可以證明原文與庫存矛盾，但不能證明每種 IP／每次 runner 都得到相同 DOM。

## 7. 建議修復次序（尚未執行）

1. **沙田南**：正文範圍提取＋HTML 通告不被共用資源壓掉；補「帶側欄 PDF」「純 HTML 通告」「正文真附件」三組測試。
2. **璧峰**：補官方支部入口及 Drive 嵌入；測主頁不變、支部頁更新；先 dry-run 比對欠缺 URL，再決定如何補庫及標示發現日。
3. **對象**：明確欄位優先級、下一欄邊界、複合職務／文件／前置課程排除、同意句式、各支部＋年齡條件；加上述真實個案及保護案例測試。
4. **只重算本次 45 筆中的受影響通告**，同步 audience／branch／subscription metadata；不要跑全庫 `--all`，不要改 captured_date 或導致重推。
5. **診斷避免假綠燈**：目前成功取得 HTTP 頁面、有資產，不等於抓對通告。對指定 HTML 通告來源應檢查 notice URL 數量；新增子頁失敗、零正文資產等警報，不再只看 `_meta.has_errors`。
6. **舊配置維護**：何文田及鯉魚門改成符合 Google Sites 的選擇器／類型，保留目前已收 URL；觀塘先區分歷史錯記與新錯記，不盲目刪資料。

不建議為消警報而把七個 stale 全設 expected_empty、重新打今天入庫日，或把資格段提過的所有身分全收進去。

## 8. Node.js 20 警告（非本次漏抓原因）

GitHub Actions 的 `actions/checkout@v4`、`actions/setup-python@v5` 是 JavaScript Action，其內部 runtime 標記 Node.js 20。GitHub 註記已在 runner 上強制轉 Node.js 24；scrape workflow 自己也設了 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`。

這與 Python 3.11 爬蟲／Vercel 網站 runtime 是不同層。更新 Action 到支援新 runtime 的版本前，要確認 runner 相容性及實際 release，並跑 workflow 驗證。這不是現在抽錯對象的根因，沒有為了警告改 runtime 或依賴。

## 附錄：45 筆盤點

「未核空值」只表示本次沒有針對空 audience 逐份評估，不能解讀成正確或錯誤。下表是該次快照，後續庫存可能已變。

| 入庫日 | 來源 | 通告（原文） | 現有 audience | 本次判斷 |
|---|---|---|---|---|
| 10-16 | 總會 | [2026年優異旅團獎勵計劃及特別嘉許童軍旅獲獎名單(修訂)](https://scout.org.hk/uploads/tc/circulars/26107/OD_cir_02-26_R_.pdf) | — | 未核空值 |
| 10-15 | 總會 | [第8屆森林舞蹈訓練班(領袖技能訓練班) (KT/72/26)](https://scout.org.hk/uploads/tc/circulars/26408/KT72_26.pdf) | 童軍、領袖、會務委員 | 多抽童軍／漏職員 |
| 10-15 | 總會 | [第30屆深資童軍進度性獎章訓練班(領袖技能訓練班) (KT/73/26)](https://scout.org.hk/uploads/tc/circulars/26409/KT73_26.pdf) | 童軍、領袖、會務委員 | 多抽童軍／漏職員 |
| 10-15 | 總會 | [東九50樂悠遊之與你「童」行海報](https://scout.org.hk/uploads/tc/circulars/26422/東九50樂悠遊之與你「童」行Poster1.pdf) | — | 未核空值 |
| 10-15 | 總會 | [明日之道 My Future My Way(Poster)](https://scout.org.hk/uploads/tc/circulars/26405/MyFutureMyWay_Poster.pdf) | — | 未核空值 |
| 10-15 | 總會 | [寰宇童軍計劃探索課程開辦指引(P110/2026)](https://scout.org.hk/uploads/tc/circulars/26402/P110-26.pdf) | 深資童軍、樂行童軍、童軍 | 多抽童軍；原始行序待確認 |
| 10-15 | 總會 | [寰宇童軍章(P109/2026)](https://scout.org.hk/uploads/tc/circulars/26401/P109-26.pdf) | 童軍 | 錯對象：應深資＋樂行 |
| 10-15 | 總會 | [九龍地域通告【2026 年 10 月】](https://scout.org.hk/uploads/tc/circulars/26410/Summary_2026_10.pdf) | — | 未核空值 |
| 10-15 | 總會 | [「東九50時間錦囊」盲盒訂購](https://scout.org.hk/uploads/tc/circulars/26383/SP18.pdf) | — | 未核空值 |
| 10-15 | 總會 | [2025-2026年度金紫荊獎章、總領袖獎章、榮譽童軍獎章及貝登堡獎章名單 (2025年9月至2026年9月)(P111/2026)](https://scout.org.hk/uploads/tc/circulars/26404/P111-26.pdf) | — | 未核空值 |
| 10-15 | 港島地域 | [香港童軍115周年-幼童軍度假營 2026-港島地域分營-青少年成員營費資助計劃(附件一)](https://www.scout.org.hk/uploads/tc/circulars/26377/Sp19a_26_YouthSubsidy_Form_GroupAccount.pdf) | — | 未核空值 |
| 10-15 | 港島地域 | [香港童軍115周年-幼童軍度假營 2026-港島地域分營-青少年成員營費資助計劃](https://www.scout.org.hk/uploads/tc/circulars/26376/Sp19_2026-Cuboree2026_YouthSubsidy.pdf) | 幼童軍、童軍、家長 | 多抽童軍＋家長 |
| 10-15 | 港島地域 | [第9屆童軍支部訓練方法訓練班(單元2A及單元2B)](https://www.scout.org.hk/uploads/tc/circulars/26353/Trg20_26_9thSectionalTrainingMethodsCourseM2AB.pdf) | 童軍、領袖 | 多抽童軍／漏職員 |
| 10-15 | 港島地域 | [港島童軍賽船大會-童軍標準艇項目-比賽結果](https://www.scout.org.hk/uploads/tc/circulars/26355/Sec53_26_Regatta2026_Pulling_Result.pdf) | — | 未核空值 |
| 10-15 | 港島地域 | [港島童軍皮藝會-皮革藝術與生活](https://www.scout.org.hk/uploads/tc/circulars/26364/Prog63_26_LeathercraftExhibition2027.pdf) | 小童軍、幼童軍、童軍、領袖、家長、會務委員 | 漏各級成員／親友 |
| 10-15 | 港島地域 | [港島童軍生態小組-觀鳥章(興趣組)領袖座談會](https://www.scout.org.hk/uploads/tc/circulars/26363/Prog62_26_BirdwatcherSeminar.pdf) | 領袖、會務委員 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [港島童軍生態小組-觀鳥章(興趣組)專章訓練班](https://www.scout.org.hk/uploads/tc/circulars/26361/Prog61_26_BirdwatcherCourse.pdf) | 童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [港島童軍氣槍射擊會-童軍射擊(技能組)專章訓練班(1)](https://www.scout.org.hk/uploads/tc/circulars/26359/Prog60_26_Marksman1.pdf) | 童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [港島童軍先鋒工程會-有蓋訊號台工作坊](https://www.scout.org.hk/uploads/tc/circulars/26357/Prog59_26_PioneeringWorkshop4.pdf) | 領袖 | 漏12歲以上各支部成員 |
| 10-15 | 港島地域 | [港島地域通告便覽(2026年10月)](https://www.scout.org.hk/uploads/tc/circulars/26380/CircularList-2026-10.pdf) | — | 未核空值 |
| 10-15 | 港島地域 | [港島地域羽毛球會-招收2026-2027年度下半年新會員](https://www.scout.org.hk/uploads/tc/circulars/26369/Prog64_26_BadmintonClubMemberRecruit.pdf) | 領袖 | 漏18歲以上各支部成員 |
| 10-15 | 港島地域 | [港島地域羽毛球會-入會表格](https://www.scout.org.hk/uploads/tc/circulars/26370/Prog64a_26_BadmintonClubRecruitForm.pdf) | — | 未核空值 |
| 10-15 | 港島地域 | [柴灣區-深資童軍原野烹飪暨營藝考驗](https://www.scout.org.hk/uploads/tc/circulars/26368/Dist07_26_CHW_VSBC_Assessment.pdf) | 深資童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [攀樹技術證書課程](https://www.scout.org.hk/uploads/tc/circulars/26354/Trg21_26_TreeClimbTechniqueCourse.pdf) | 領袖 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [探索歷史典藏、清真文化與創新科技之行-報名表格](https://www.scout.org.hk/uploads/tc/circulars/26367/I_MA04a_26_Shenzhen_form.pdf) | — | 未核空值 |
| 10-15 | 港島地域 | [探索歷史典藏、清真文化與創新科技之行](https://www.scout.org.hk/uploads/tc/circulars/26366/I_MA04_26_Shenzhen.pdf) | 領袖、會務委員 | 漏各級支部成員／家屬 |
| 10-15 | 港島地域 | [小童軍親子原野新煮意同樂日](https://www.scout.org.hk/uploads/tc/circulars/26373/Sec54_26_GSBackwoods.pdf) | 小童軍、領袖、家長 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [大潭童軍中心攻堅場工作坊](https://www.scout.org.hk/uploads/tc/circulars/26374/TTM04_26_Challenge_Course_Workshop.pdf) | 領袖 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 港島地域 | [呈交童軍旅賬目資料](https://www.scout.org.hk/uploads/tc/circulars/26352/Adm23_26_FinancialReport.pdf) | — | 未核空值 |
| 10-16 | 柴灣區 | [香港童軍115周年認可活動Operation115:「童」守護 ‧ 安心社區嘉年華-社區應急先鋒訓練班](https://chaiwanscout.org.hk/v3/wp-content/uploads/2026/10/CHW-2627-18_香港童軍115周年認可活動-「童」守護-‧-安心社區嘉年華-社區應急先鋒.pdf) | 深資童軍、樂行童軍、童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-16 | 柴灣區 | [香港童軍115周年認可活動Operation115:「童」守護 ‧ 安心社區嘉年華-攤位設計比賽](https://chaiwanscout.org.hk/v3/wp-content/uploads/2026/10/CHW-2627-20_香港童軍115周年認可活動-「童」守護-‧-安心社區嘉年華-攤位設計比賽.pdf) | 領袖、家長 | 漏各支部成員 |
| 10-16 | 柴灣區 | [香港童軍115周年認可活動Operation115:「童」守護 ‧ 安心社區嘉年華-幼童軍及童軍支部急救問題比賽](https://chaiwanscout.org.hk/v3/wp-content/uploads/2026/10/CHW-2627-19_香港童軍115周年認可活動-「童」守護-‧-安心社區嘉年華-急救問題比賽.pdf) | 幼童軍、童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 柴灣區 | [幼童軍體適能章考驗日](https://chaiwanscout.org.hk/v3/wp-content/uploads/2026/10/CHW-2627-21_幼童軍體適能章.pdf) | — | 未核空值 |
| 10-16 | 紅磡區 | [小童軍支部快樂傘(總監盃)錦標賽 活動通告:GS-26-03](https://drive.google.com/file/d/1tIVc08p8QNqAe8GtEmbqKkwouzniWkdG/view) | 小童軍、領袖 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-16 | 紅磡區 | [幼童軍支部(主席盾)錦標賽 活動通告:CS-26-02](https://drive.google.com/file/d/14ltLg_aGYuidEZdXI1gXt0PeeREd-Zss/view) | 幼童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 深水埗東區 | [香港童軍115周年暨深水埗東區35周年 防騙國安嘉年華 D/05/2026](https://drive.google.com/file/d/1MuTrFguv3ZDqO9c4_rHSbVN5XaZZz3PR/view) | 童軍 | 漏小幼／學生／坊眾 |
| 10-15 | 深水埗東區 | [深東防騙嘉年華 - 4格漫畫創作比賽 D/05A/2026](https://drive.google.com/file/d/10_hUL1ALrE_4UdrPHkn69kuiAF4KwfhR/view) | 小童軍、幼童軍 | 漏公眾／學生組 |
| 10-15 | 東九龍地域 | [東九50樂悠遊之與你「童」行海報](https://hkscout-ekr.org/circulars/download/?wpdmdl=5660) | — | 未核空值 |
| 10-15 | 九龍灣區 | [陶瓷工作坊](https://www.hkscout-klb.org/web2017/assets/kb_documents/notice/2026/PT-18-26.pdf) | — | 未核空值 |
| 10-15 | 九龍灣區 | [藝術-陶瓷工作坊](https://www.hkscout-klb.org/web2017/assets/kb_documents/notice/2026/PT-19-26.pdf) | 童軍 | 本次未見多抽（不代表完整保存年齡／資格） |
| 10-15 | 九龍灣區 | [九灣小漁夫出海記-水上文化親子大冒險](https://www.hkscout-klb.org/web2017/assets/kb_documents/notice/2026/PT-15-26.pdf) | 童軍、家長 | 原文資格行 typo：跨段證據指小童軍 |
| 10-15 | 九龍灣區 | [丁未年新春團聚活動](https://www.hkscout-klb.org/web2017/assets/kb_documents/notice/2026/PT-17-26.pdf) | — | 未核空值 |
| 10-16 | 將軍澳區 | [10-2026 童軍支部急救章訓練班 (截止: 2026-12-02)](https://hkscout-tko.org/notice/?nid=208) | — | 未核空值 |
| 10-16 | 新界東地域 | [2026年優異旅團獎勵計劃及特別嘉許童軍旅獲獎名單(修訂)](https://assets.ctfassets.net/g8bhf0l3d7iq/6IL9HoDK9eP4bn12AiTbih/e65b8f60d128900d3f7b5c3431270c28/OD_cir_02-26_R_.pdf) | — | 未核空值 |
| 10-15 | 沙田東區 | [2026-2027 年度 第一次全區深資童軍支部領袖會議](http://www.stescout.org/pdf/circular%202026/cir_2026_pt14.pdf) | 深資童軍、領袖 | 職務限定遺失；不可全當普通深資成員 |


## 實作補記 — 2026-10-16

### 已執行

- `fix_logbook_2026_10_16.py` 離線補錄 **25 筆**（沙田南 22、璧峰 3）。`date`／`captured_date` 按原文發出日期歸檔，另存 `published_date` 明確標示；不是按活動日或今日補戳。既有所有記錄及其日期逐筆比對保持原樣，`last_updated`、`_meta`／last_run 和指紋不改。
- 新補錄列帶 `backfilled_at` 及 `suppress_notifications: true`，推送新發現／同日 catch-up／摘要和 Story queue 均排除。即使其中一份璧峰公文真的於今日發出，也不借補錄觸發發佈。cache 重建及 remote refresh 均保留明確審核的離線補錄與抑制標記；沒有變更資料庫 schema 或執行 DB 寫入。
- KT72、KT73、Trg20、Sp19、P109、P110、沙田東支部領袖會議共 **7 份／9 個 URL（含既有 www 鏡像）**補正 audience、branch_tags、subscription_tags 及 evidence。保留此前核准的 categories、deadline、fee；不對整個歷史庫跑 `--all`。資格證據是人工核對節錄，不宣稱 raw pdfplumber dump。
- `enrich.py` 版本 3.7：真正參加／資助／入會資格欄優先，停在下一欄；複合職務不拆成青少年支部；前置課程、成員編號、否定及家長同意語句不當參加者。年齡限制的「各支部成員」不粗暴展開所有兒童支部。保留真正的親子、領袖及委員參加者。訂閱規則亦排除前置木章課程／括號內單元別名。
- 沙田南配置直接取官方 `/programme/view_notice/數字`，用同一列第一欄的標題；不再讓共用資源 PDF 搶走通告身分。enrich 認可官方端點形狀，但下載仍必須通過 `%PDF` bytes，HTML／登入頁不冒充 PDF。
- 璧峰增四個實際支部列表（小童軍、幼童軍、童軍、深資及樂行）；主頁指紋不變仍巡查子頁。解析 Drive iframe／lazy iframe，配鄰近標題；子頁失敗或官方 notice 列表零結果不假報成功。這是離線 layout fixture 回歸，尚未在真實 Actions runner 做端到端抓取驗證。
- Story：**訓練、活動、服務、比賽各先一張**，再用其他不重複通告補至最多 **5 張**；仍只收今日、齊料者。不足五份就少出，不用佔位資料湊數。同一通告按附件 URL、Drive 別名、www 鏡像、正規化標題去重。`--limit 0`／過大數值不能解除上限。queue 與 renderer 都限五；publisher 在任何 API 呼叫前拒絕超額／重複 manifest。沒有重試補發、延至翌日或實際發佈。

### 補錄日期清單（均已讀原文發出日期）

| 來源 | 發出日期 | 通告原文 |
|---|---|---|
| 沙田南 | 2026-09-02 | [急救證書課程](https://www.stsd-scout.org/programme/view_notice/175) |
| 沙田南 | 2026-09-01 | [幼童軍歷史章訓練班](https://www.stsd-scout.org/programme/view_notice/174) |
| 沙田南 | 2026-07-02 | [「豐盛生命」正向情緒日營](https://www.stsd-scout.org/programme/view_notice/173) |
| 沙田南 | 2026-06-24 | [2026-2027年度第一次幼童軍支部領袖會議](https://www.stsd-scout.org/programme/view_notice/172) |
| 沙田南 | 2026-05-15 | [港鐵安全體驗天地同樂日](https://www.stsd-scout.org/programme/view_notice/170) |
| 沙田南 | 2026-05-09 | [龍舟章訓練班](https://www.stsd-scout.org/programme/view_notice/169) |
| 沙田南 | 2026-04-23 | [招募龍舟隊成員2026](https://www.stsd-scout.org/programme/view_notice/168) |
| 沙田南 | 2026-03-30 | [【取錄通知書】第70屆步操基本訓練班](https://www.stsd-scout.org/programme/view_notice/167) |
| 沙田南 | 2026-03-30 | [【取錄通知書】第21屆童軍步操基本訓練班](https://www.stsd-scout.org/programme/view_notice/166) |
| 沙田南 | 2026-03-15 | [小童軍Boxing體驗日](https://www.stsd-scout.org/programme/view_notice/165) |
| 沙田南 | 2026-03-06 | [沙田區童軍運動五十周年紀念晚宴](https://www.stsd-scout.org/programme/view_notice/164) |
| 沙田南 | 2026-02-15 | [深資樂行童軍聯團活動—霓虹燈製作工作坊](https://www.stsd-scout.org/programme/view_notice/163) |
| 沙田南 | 2026-02-01 | [第21屆童軍步操基本訓練班](https://www.stsd-scout.org/programme/view_notice/162) |
| 沙田南 | 2026-02-01 | [第70屆步操基本訓練班](https://www.stsd-scout.org/programme/view_notice/161) |
| 沙田南 | 2026-01-15 | [童軍原野烹飪章（教導組）訓練班](https://www.stsd-scout.org/programme/view_notice/160) |
| 沙田南 | 2026-01-15 | [童軍原野烹飪章（技能組）訓練班](https://www.stsd-scout.org/programme/view_notice/159) |
| 沙田南 | 2025-12-15 | [2025-2026年度第二次小童軍支部領袖會議](https://www.stsd-scout.org/programme/view_notice/158) |
| 沙田南 | 2025-11-05 | [童軍支部技能錦標賽2025（顏明秀副會長盾）](https://www.stsd-scout.org/programme/view_notice/157) |
| 沙田南 | 2025-10-01 | [童軍專章考驗日2025](https://www.stsd-scout.org/programme/view_notice/156) |
| 沙田南 | 2025-10-01 | [幼童軍技能比賽2025 李美琪副主席（銀碟賽）](https://www.stsd-scout.org/programme/view_notice/155) |
| 沙田南 | 2025-10-01 | [小童軍支部比賽2025 蕭麗馨副主席（主席盃）](https://www.stsd-scout.org/programme/view_notice/154) |
| 沙田南 | 2025-07-08 | [沙田南旅團支援計劃（2025-26年度）](https://www.stsd-scout.org/programme/view_notice/148) |
| 璧峰 | 2026-10-16 | [公民章、精神健康章、社區參與章、積極公民—國家安全大使及議會探索章訓練班](https://drive.google.com/file/d/1XdP3YhKUPcS8p19F0YG-knAelOjhx4Nn/view) |
| 璧峰 | 2026-08-15 | [第7屆原野烹飪訓練班—技能組](https://drive.google.com/file/d/1lRpizyjj4c4RQ8CTSYOCwYhAv9fptWY3/view) |
| 璧峰 | 2026-08-15 | [第7屆原野烹飪訓練班—教導組](https://drive.google.com/file/d/1uNeOTX4XTfcvebSu8vSuZa3d3qzX9p2U/view) |

取錄通知 166／167 不借用課程報名 deadline／fee／audience，並以公布歸檔；旅團支援計劃 148 不把資助額當收費。原文有年份／星期／地點矛盾時不自行改成推算日期，例如璧峰公民等章訓練班部分課節同時出現 2027 年 1 月和 2026 年 2 月；補錄日期只取文件上方發出日期 2026-10-16。

### 尚待核實，沒有估日期入庫

璧峰已確認欠缺但仍只有檔名、未讀到可核日期的原件：

1. [政制探究及民政訓練班](https://sites.google.com/view/pikfung-district/支部通訊/深資及樂行童軍)（`PFD2627VS004_政制探究及民政訓練班.pdf`）。
2. 同頁原野生活知識工作坊 A-101（`PF_原野生活知識工作坊 A-101 .pdf`）。
3. [小童軍親子活動—懷舊食物工作坊](https://sites.google.com/view/pikfung-district/支部通訊/小童軍)（最後核對其餘支部頁時另見）。
4. [2026 童軍先修章訓練班](https://sites.google.com/view/pikfung-district/支部通訊/幼童軍)（`PFD2627CST002童軍先修章.pdf`，同樣是最後覆核另見）。

### 驗證

- 24 個 `test_*.py` 測試檔逐個以獨立 Python process 執行，全數 exit 0（避免舊式自測檔在 import 時 `sys.exit(0)`，被 unittest discover 誤列錯誤）。
- `test_enrich.py`：156/156；新增 `test_logbook_2026_10_16.py`：27 個 unittest；Story queue、publisher、notify 及 renderer 防線有離線覆蓋。
- 補錄執行一次後，再 dry-run：`backfilled=0, audiences_corrected=0`，可重跑且不反覆改資料。
- 真實 cache 離線比較：舊 `data`／`notices` 每筆不變；新增 25 筆；只有補錄造成的 `find_new_notices` 候選為 0。
- 真實 2026-10-16 Story queue dry-run：8 個今日候選，只選 5 個不重複通告；補錄不進清單。
- `git diff --check` 通過。沒有執行抓全站、推送、Instagram 發佈、提交／push、PR 或部署。Supabase／Vercel 已解決項目不重開。
