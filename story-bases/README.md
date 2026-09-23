# story-bases — 9 張 AI 無字底圖（1080×1920）

出 Story 草稿用嘅底圖。**全部零文字、零假資料**（冇 "TEMPLATE 2"、冇假 QR、冇假日期），
標題、分類、截止日、地點、費用、區徽全部由程式後期疊上去。

| 檔名 | 款 | 配咩分類 | 中間留白 |
|---|---|---|---|
| `train_blue.webp` | 白紙 × 藍色筆觸 | 訓練 training | 中段大片白 |
| `train_orange.webp` | 米白 × 橙色筆觸 | 訓練 training | 中段大片白 |
| `train_green.webp` | 白紙 × 螢光綠 grunge | 訓練 training | 中上大白 |
| `competition_gold_black.webp` | 黑 × 金黃筆觸 | 比賽 competition | 中段漆黑 |
| `activity_army.webp` | 軍綠地形圖 | 活動 activity | 中段深綠 |
| `service_wanted.webp` | 舊羊皮紙 | 服務 service | 中央米黃 |
| `unc_scope.webp` | 黑 × 紅瞄準環 | 通告 other | 中央漆黑 |
| `unc_topsecret.webp` | 深底 × 牛皮紙 | 通告 other | 紙面淺色 |
| `unc_glitch.webp` | 黑 × 青洋紅故障 | 通告 other | 中央漆黑 |

體積：9 張合共約 **1.05 MB**（WebP q82）。喺 `.vercelignore` 擋住 → **Vercel 零 byte**，
由 raw.githubusercontent 或本機 runner 直接讀。

## 疊字方法（自動，唔使人手逐款調）

`tools/render_story_bases_demo.py` 會為每張底圖計「標題區平均亮度 + 標準差」再決定：

| 情況 | 處理 |
|---|---|
| 亮度 > 150、雜亂 < 32 | 跟款嘅原設定色（乾淨底，唔加底板，保留質感） |
| 亮度 > 150、雜亂 ≥ 38 | **深字 + 半透明柔邊底板**（花紋撞字，例如 train_green） |
| 亮度 < 95 | 白字 + 黑描邊 |
| 中間調 | 亮度 > 122 用深字，否則白字（加底板） |

羊皮紙（`service_wanted`）同牛皮紙（`unc_topsecret`）會自動改用深啡字 ＋ 米色描邊。

## 出試樣

```bash
pip install pillow
python3 tools/render_story_bases_demo.py          # 9 款 × 真 cache.json 通告 → story-bases/demo/
python3 tools/render_story_bases_demo.py --stub   # 冇 cache.json 時用示範資料
python3 tools/bases_webp_to_png.py --out templates/clean_no_text   # 轉 PNG 畀自己嘅腳本
```

試樣成品（3 張樣本，全部真通告 + 真區徽）：`demo/` 資料夾；9 款並列：`demo/_sheet.jpg`
