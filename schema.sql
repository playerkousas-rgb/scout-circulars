-- ============================================================
-- 全港童軍通告自動化圖書館 v5.3 — Supabase 資料表 Schema
-- ============================================================
-- 使用方式:
--   1. 在 Supabase SQL Editor 中貼上執行
--   2. 已有舊表也可重跑，本腳本會盡量以 ALTER 方式升級
--
-- v5.3 關鍵修正:
--   - 舊版 pdf_url UNIQUE 會令不同區會引用同一下載連結時互相污染
--   - 新版改為 (source_site, pdf_url) 複合唯一鍵，落實來源隔離

CREATE TABLE IF NOT EXISTS scout_notices (
    id            BIGSERIAL PRIMARY KEY,
    source_site   TEXT NOT NULL,
    region        TEXT DEFAULT '',
    pdf_url       TEXT NOT NULL,
    title         TEXT DEFAULT '',
    captured_date DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 若舊表已存在，補齊欄位
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS source_site   TEXT;
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS region        TEXT DEFAULT '';
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS pdf_url       TEXT;
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS title         TEXT DEFAULT '';
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS captured_date DATE NOT NULL DEFAULT CURRENT_DATE;
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE scout_notices ADD COLUMN IF NOT EXISTS updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE scout_notices ALTER COLUMN source_site SET NOT NULL;
ALTER TABLE scout_notices ALTER COLUMN pdf_url SET NOT NULL;

-- 移除舊的單欄唯一鍵 / 舊索引（若存在）
ALTER TABLE scout_notices DROP CONSTRAINT IF EXISTS scout_notices_pdf_url_key;
DROP INDEX IF EXISTS uq_scout_notices_pdf_url;

-- 新版來源隔離唯一鍵
CREATE UNIQUE INDEX IF NOT EXISTS uq_scout_notices_source_pdf
    ON scout_notices(source_site, pdf_url);

-- 查詢索引
CREATE INDEX IF NOT EXISTS idx_captured_date ON scout_notices(captured_date DESC);
CREATE INDEX IF NOT EXISTS idx_source_site ON scout_notices(source_site);
CREATE INDEX IF NOT EXISTS idx_pdf_url ON scout_notices(pdf_url);
CREATE INDEX IF NOT EXISTS idx_region ON scout_notices(region);

-- 自動更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_updated_at ON scout_notices;
CREATE TRIGGER trg_updated_at
    BEFORE UPDATE ON scout_notices
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 啟用 RLS
ALTER TABLE scout_notices ENABLE ROW LEVEL SECURITY;

-- 清理舊 policy（避免重跑報錯）
DROP POLICY IF EXISTS "Allow public read" ON scout_notices;
DROP POLICY IF EXISTS "Allow service insert" ON scout_notices;
DROP POLICY IF EXISTS "Allow service update" ON scout_notices;

-- 公開讀取政策
CREATE POLICY "Allow public read"
    ON scout_notices FOR SELECT
    USING (true);

-- 僅 service_role 可寫
CREATE POLICY "Allow service insert"
    ON scout_notices FOR INSERT
    TO service_role
    WITH CHECK (true);

CREATE POLICY "Allow service update"
    ON scout_notices FOR UPDATE
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================
-- 常用查詢範例
-- ============================================================

-- 1. 最近 30 天新通告（前端預設視窗）
-- SELECT * FROM scout_notices
-- WHERE captured_date >= CURRENT_DATE - INTERVAL '30 days'
-- ORDER BY captured_date DESC;

-- 2. 按來源區會統計
-- SELECT source_site, COUNT(*) as cnt, MAX(captured_date) as latest
-- FROM scout_notices
-- GROUP BY source_site
-- ORDER BY latest DESC;

-- 3. 同一下載連結若被兩個區會引用，可共存
-- SELECT source_site, pdf_url, captured_date
-- FROM scout_notices
-- WHERE pdf_url = 'https://example.com/file.pdf';
