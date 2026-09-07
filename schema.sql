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

-- ============================================================
-- v6.0 — 匿名個人化 Web Push 訂閱（支部 + 官方課程／服務／活動）
-- ============================================================
-- 前端不可直接讀取這兩張表；只有 Vercel 窄 API 及 GitHub Actions 的
-- service_role 會存取。請與上方 schema 一次在 Supabase SQL Editor 執行。
--
-- 私隱：沒有姓名、電郵、電話、帳戶、旅團或地域欄位。endpoint / p256dh /
-- auth 是瀏覽器 Web Push 協定必需的匿名收件和加密資料，使用者取消通知或
-- endpoint 失效後會移除。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_hash     TEXT NOT NULL UNIQUE,
    endpoint          TEXT NOT NULL,
    p256dh            TEXT NOT NULL,
    auth              TEXT NOT NULL,
    client_token_hash TEXT NOT NULL,
    branch_ids        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    topic_ids         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    catalog_version   TEXT NOT NULL DEFAULT '',
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT push_subscriptions_branch_count CHECK (cardinality(branch_ids) BETWEEN 1 AND 8),
    CONSTRAINT push_subscriptions_topic_count CHECK (cardinality(topic_ids) BETWEEN 1 AND 24)
);

-- 若日後在測試環境已建立過舊版表，這些 ALTER 可安全補欄位。
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS endpoint_hash     TEXT;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS endpoint          TEXT;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS p256dh            TEXT;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS auth              TEXT;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS client_token_hash TEXT;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS branch_ids        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS topic_ids         TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS catalog_version   TEXT NOT NULL DEFAULT '';
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS enabled           BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS uq_push_subscriptions_endpoint_hash
    ON push_subscriptions(endpoint_hash);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_enabled
    ON push_subscriptions(enabled) WHERE enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_branch_ids
    ON push_subscriptions USING GIN(branch_ids);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_topic_ids
    ON push_subscriptions USING GIN(topic_ids);

DROP TRIGGER IF EXISTS trg_push_subscriptions_updated_at ON push_subscriptions;
CREATE TRIGGER trg_push_subscriptions_updated_at
    BEFORE UPDATE ON push_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 一項通告即使配對多個興趣，也只會留下同一個 delivery key。通知程式會先
-- 對每位使用者合併所有新通告，然後最多送出一則 Web Push。
CREATE TABLE IF NOT EXISTS push_deliveries (
    id              BIGSERIAL PRIMARY KEY,
    subscription_id UUID NOT NULL REFERENCES push_subscriptions(id) ON DELETE CASCADE,
    notice_key      TEXT NOT NULL,
    batch_date      DATE NOT NULL,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_push_deliveries_subscription_notice UNIQUE(subscription_id, notice_key)
);

CREATE INDEX IF NOT EXISTS idx_push_deliveries_notice_key ON push_deliveries(notice_key);
CREATE INDEX IF NOT EXISTS idx_push_deliveries_batch_date ON push_deliveries(batch_date DESC);

-- 沒有 anon / authenticated policy = 瀏覽器不能直接讀取任何訂閱或發送紀錄。
ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE push_deliveries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Public push subscription access" ON push_subscriptions;
DROP POLICY IF EXISTS "Public push delivery access" ON push_deliveries;
DROP POLICY IF EXISTS "Service push subscription access" ON push_subscriptions;
DROP POLICY IF EXISTS "Service push delivery access" ON push_deliveries;

REVOKE ALL ON TABLE push_subscriptions FROM anon, authenticated;
REVOKE ALL ON TABLE push_deliveries FROM anon, authenticated;
REVOKE ALL ON SEQUENCE push_deliveries_id_seq FROM anon, authenticated;
GRANT ALL ON TABLE push_subscriptions TO service_role;
GRANT ALL ON TABLE push_deliveries TO service_role;
GRANT USAGE, SELECT ON SEQUENCE push_deliveries_id_seq TO service_role;
