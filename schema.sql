-- ============================================================
-- 全港童軍通告自動化圖書館 v5.0 — Supabase 資料表 Schema
-- ============================================================
-- 使用方式:
--   1. 在 Supabase SQL Editor 中貼上執行
--   2. 或在 Supabase Dashboard → Table Editor 手動建立

-- 主表: 童軍通告
CREATE TABLE IF NOT EXISTS scout_notices (
    id            BIGSERIAL PRIMARY KEY,
    source_site   TEXT NOT NULL,                          -- 來源地域/區會名稱
    region        TEXT DEFAULT '',                         -- 所屬地域
    pdf_url       TEXT NOT NULL UNIQUE,                    -- PDF 絕對網址 (Unique Key)
    title         TEXT DEFAULT '',                         -- 網頁上顯示的通告標題
    captured_date DATE NOT NULL DEFAULT CURRENT_DATE,      -- 系統捕獲日期 (鐵律三: 盲信)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),      -- 記錄建立時間
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()       -- 記錄更新時間
);

-- 索引: 加速前端按日期/來源查詢
CREATE INDEX IF NOT EXISTS idx_captured_date ON scout_notices(captured_date DESC);
CREATE INDEX IF NOT EXISTS idx_source_site ON scout_notices(source_site);
CREATE INDEX IF NOT EXISTS idx_pdf_url ON scout_notices(pdf_url);
CREATE INDEX IF NOT EXISTS idx_region ON scout_notices(region);

-- 自動更新 updated_at 觸發器
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

-- 啟用 RLS (Row Level Security)
ALTER TABLE scout_notices ENABLE ROW LEVEL SECURITY;

-- 公開讀取政策 (前端匿名讀取)
CREATE POLICY "Allow public read"
    ON scout_notices FOR SELECT
    USING (true);

-- 服務端寫入政策 (僅 service_role 可寫)
CREATE POLICY "Allow service insert"
    ON scout_notices FOR INSERT
    TO service_role
    USING (true);

CREATE POLICY "Allow service update"
    ON scout_notices FOR UPDATE
    TO service_role
    USING (true);

-- ============================================================
-- 常用查詢範例
-- ============================================================

-- 1. 最近 30 天新通告 (前端預設視窗)
-- SELECT * FROM scout_notices
-- WHERE captured_date >= CURRENT_DATE - INTERVAL '30 days'
-- ORDER BY captured_date DESC;

-- 2. 按來源區會統計
-- SELECT source_site, COUNT(*) as cnt, MAX(captured_date) as latest
-- FROM scout_notices
-- GROUP BY source_site
-- ORDER BY latest DESC;

-- 3. 找特定 PDF 是否已存在
-- SELECT * FROM scout_notices WHERE pdf_url = 'https://...';
