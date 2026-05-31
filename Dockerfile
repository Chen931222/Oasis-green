# ============================================================
# Oasis 綠洲 — Dockerfile
# ============================================================
# 建置：docker build -t oasis .
# 執行：docker run -p 8000:8000 \
#         -e DATABASE_URL="postgresql://..." \
#         -e EMAIL_USER="..." -e EMAIL_PASS="..." \
#         -v oasis-uploads:/app/www/static/uploads \
#         -v oasis-logs:/app/logs \
#         oasis
# ============================================================

FROM python:3.12-slim

# 系統相依（psycopg2 需要 libpq）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先複製 requirements 以利用 Docker layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式原始碼
COPY . .

# 建立必要目錄
RUN mkdir -p logs www/static/uploads

# 非 root 使用者（最小權限原則）
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 啟動 Gunicorn（worker 數量可透過環境變數 WORKERS 覆寫）
CMD ["sh", "scripts/start.sh"]
