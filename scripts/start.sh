#!/usr/bin/env bash
# ============================================================
# Oasis 綠洲 — 正式環境啟動腳本（Gunicorn + Uvicorn workers）
# ============================================================
# 使用方式：
#   chmod +x scripts/start.sh
#   DATABASE_URL="postgresql://user:pass@localhost/oasis" \
#   EMAIL_USER="xxx@gmail.com" EMAIL_PASS="app-password" \
#   ./scripts/start.sh
# ============================================================

set -euo pipefail

# 確保 logs 與上傳目錄存在
mkdir -p logs www/static/uploads

# worker 數量 = CPU 核心數 × 2 + 1（gunicorn 官方建議公式）
WORKERS=${WORKERS:-$(( $(nproc) * 2 + 1 ))}

echo "[start.sh] Starting Gunicorn with ${WORKERS} workers …"

exec gunicorn main:app \
    --workers "${WORKERS}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 60 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile logs/access.log \
    --error-logfile  logs/error.log \
    --log-level info \
    --forwarded-allow-ips "*"
