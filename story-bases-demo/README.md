# AI 底圖試範（story-bases-demo）

呢個資料夾係**試範素材**，唔係部署檔案 —— 已經喺 `.vercelignore` 擋住，Vercel 零 byte。

| 檔案 | 係咩 |
|---|---|
| `base-green.webp` / `base-gold.webp` / `base-topo.webp` | 3 張 AI 生成「無字底圖」（1080×1920），中間留白，零文字零假資料 |
| `demo-1-green.jpg` / `demo-2-gold.jpg` / `demo-3-topo.jpg` | 用真 queue 標題疊字之後嘅完成品（測試用） |
| `demo-4-noplate.jpg` | 對照組：唔加柔邊底板，字會撞落底圖花紋 |
| `overlay-method.jpg` | 4 格並列對比（揀款用） |

## 疊字方法（實測有效）
1. 先量標題區平均亮度
2. 淺底（>135）→ 深字＋白描邊；深底 → 白字＋黑描邊
3. 中間調（120–225）→ 標題後面加一層 **Gaussian blur 52px 柔邊底板**（唔係硬方框），字唔會撞花紋

## 體積參考（重要）
- 1080×1920 WebP q80：**62–255 KB／張**（呢 3 張平均 169 KB）
- 同樣內容 JPEG q88：405–542 KB／張
- 正式 9 張放 `bases/`（`.vercelignore`）＋由 raw.githubusercontent 讀 → Vercel 零 byte

## 下一步
等確認款式之後：出齊 9 款（訓練藍／橙／綠、比賽金黑、活動軍綠、服務羊皮紙、通告瞄準鏡／絕密／故障霓虹），
搬去 `bases/`，再喺 `?batch=1` 出圖台加「AI 底圖」一組。
