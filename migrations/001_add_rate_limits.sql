-- v1: 跨 Worker 速率限制表
-- 替代各 Gunicorn Worker 進程中的記憶體 dict，讓所有 Worker 共用同一份計數器。
-- key 格式：login:{email}、contact:{ip}、forgot:{ip}
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 1,
    window_start TEXT NOT NULL,
    locked_until TEXT
);
CREATE INDEX IF NOT EXISTS idx_rate_limits_key ON rate_limits(key)
