-- v2: 數學驗證碼挑戰表
-- 儲存伺服器端產生的隨機加法題（題目 + 答案），供登入 / 註冊 / 聯絡表單驗證使用。
-- 每個 challenge 10 分鐘後過期；驗證後立即刪除（一次性）。
CREATE TABLE IF NOT EXISTS challenges (
    id TEXT PRIMARY KEY,
    answer TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_challenges_expires ON challenges(expires_at)
