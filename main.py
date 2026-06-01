# main.py：Oasis 綠洲 FastAPI 後端，使用 SQLite 儲存空間與預約資料。
import base64
import hashlib
import json
import logging
import logging.handlers
import os
import random
import re
import secrets
import smtplib
import sqlite3
import threading
from datetime import date as dt_date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Server-side Logging：記錄重要事件與錯誤，方便除錯與稽核。────────────────────
# 日誌存放在 logs/ 資料夾，RotatingFileHandler 自動截斷，不會無限增大。
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("oasis")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _fh = logging.handlers.RotatingFileHandler(
        "logs/oasis.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _ch = logging.StreamHandler()
    _ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))
    logger.addHandler(_fh)
    logger.addHandler(_ch)
logger.info("Oasis 綠洲 server module loaded")

# ── Sentry 錯誤追蹤：設定 SENTRY_DSN 環境變數後自動啟用。──────────────────────
# 任何未捕捉的 500 錯誤都會即時回報到 Sentry Dashboard（免費方案即可）。
# 取得 DSN：https://sentry.io → 建立 Python 專案 → Project Settings → DSN
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,   # 取樣 10% 的 request 做效能追蹤
        environment=os.environ.get("SENTRY_ENV", "production"),
    )
    logger.info("[SENTRY] 錯誤追蹤已啟動")

# ── 資料庫相容層：同時支援 PostgreSQL 與 SQLite，切換只需設定環境變數。──────────
# 設定方式：set DATABASE_URL=postgresql://user:pass@localhost:5432/oasis
#   未設定 → 繼續使用 SQLite（開發 / 展示環境）
PG_URL    = os.environ.get("DATABASE_URL", "")
# SQLITE_DB：允許測試環境使用不同的 SQLite 檔案，不污染正式資料
SQLITE_DB = os.environ.get("SQLITE_DB", "oasis.db")


class _PGCursor:
    """
    包裝 psycopg2 cursor，讓現有程式碼可以直接使用 SQLite 語法（? 佔位符、
    INSERT OR REPLACE、cursor.lastrowid）而不需大量修改。
    """

    def __init__(self, cursor):
        self._c         = cursor
        self._lastrowid = None

    def execute(self, query: str, params=()):
        q = query.replace("?", "%s")
        # SQLite INSERT OR REPLACE → PostgreSQL INSERT ... ON CONFLICT DO UPDATE
        if re.search(r"\bINSERT\s+OR\s+REPLACE\b", q, re.IGNORECASE):
            q = re.sub(r"\bINSERT\s+OR\s+REPLACE\b", "INSERT", q, flags=re.IGNORECASE)
            if re.search(r"\bINTO\s+ratings\b", q, re.IGNORECASE):
                q = (q.rstrip("; \n") +
                     " ON CONFLICT (space_id, user_email)"
                     " DO UPDATE SET score = EXCLUDED.score, comment = EXCLUDED.comment")
        # 自動補 RETURNING id 讓 .lastrowid 可用
        # 例外：schema_versions 的 PK 是 version，不是 id
        if q.lstrip().upper().startswith("INSERT") and "RETURNING" not in q.upper():
            _m   = re.search(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", q, re.IGNORECASE)
            _tbl = _m.group(1).lower() if _m else ""
            if _tbl not in ("schema_versions",):
                q = q.rstrip("; \n") + " RETURNING id"
                self._c.execute(q, params)
                row = self._c.fetchone()
                self._lastrowid = row[0] if row else None
            else:
                self._c.execute(q, params)
                self._lastrowid = None
        else:
            self._c.execute(q, params)

    def executemany(self, query: str, params_list):
        self._c.executemany(query.replace("?", "%s"), params_list)

    def fetchone(self):     return self._c.fetchone()
    def fetchall(self):     return self._c.fetchall()

    @property
    def lastrowid(self):    return self._lastrowid
    @property
    def description(self):  return self._c.description


_PG_POOL = None   # ThreadedConnectionPool（每個 Gunicorn worker 進程各自獨立）


def _get_pg_pool():
    """
    Lazy-init PostgreSQL 連線池。
    重複使用同一批 TCP 連線（min=2, max=20），大幅降低每次 request 的建立開銷。
    """
    global _PG_POOL
    if _PG_POOL is None:
        import psycopg2.pool
        _PG_POOL = psycopg2.pool.ThreadedConnectionPool(2, 20, PG_URL)
        logger.info("[DB POOL] PostgreSQL 連線池已建立（min=2, max=20）")
    return _PG_POOL


class _PGConn:
    """
    包裝 psycopg2 connection（從連線池取得），使 .cursor() 回傳 _PGCursor。
    close() 不真正關閉連線，而是歸還到連線池供下一個 request 重用。
    """

    def __init__(self, url: str):
        self._conn = _get_pg_pool().getconn()

    def cursor(self):   return _PGCursor(self._conn.cursor())
    def commit(self):   self._conn.commit()
    def close(self):
        try:
            self._conn.rollback()   # 清除任何未提交的殘留事務
        except Exception:
            pass
        _get_pg_pool().putconn(self._conn)   # 歸還到池子，不關閉連線


def _get_conn():
    """取得資料庫連線（PostgreSQL 優先，否則 SQLite）。"""
    if PG_URL:
        return _PGConn(PG_URL)
    return sqlite3.connect(SQLITE_DB, check_same_thread=False)


def _get_columns(cursor, table: str) -> list:
    """取得資料表欄位名稱清單（相容 SQLite PRAGMA 與 PostgreSQL information_schema）。"""
    if PG_URL:
        raw = getattr(cursor, "_c", cursor)
        raw.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = 'public'",
            (table,),
        )
        return [row[0] for row in raw.fetchall()]
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


# ── 圖片檔案儲存：把 base64 data URL 存成實體檔案，DB 只存路徑。────────────────
# 原本每張 2MB 圖片以 base64 存進 DB（~2.67MB 字串），查詢 10 個空間 = 100 MB+
# 改成存檔後：DB 只存 "/static/uploads/abc.jpg"（幾十 bytes），圖片由瀏覽器直接向
# FastAPI Static 取得，不需透過 API 傳輸，效能大幅提升。
_UPLOAD_DIR  = os.path.join("www", "static", "uploads")
_MIME_TO_EXT = {"image/jpeg": "jpg", "image/png": "png",
                "image/gif":  "gif", "image/webp": "webp"}
os.makedirs(_UPLOAD_DIR, exist_ok=True)


def _delete_image_file(url_path: str) -> None:
    """
    刪除 /static/uploads/ 下的上傳圖片實體檔案。
    若為外部 URL（picsum、http...）或靜態資源（/static/images/）則略過，不誤刪。
    """
    if not url_path or not url_path.startswith("/static/uploads/"):
        return
    filepath = os.path.join("www", url_path.lstrip("/"))
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
            logger.info(f"[IMAGE DELETED] {filepath}")
    except Exception as exc:
        logger.error(f"[IMAGE DELETE ERROR] {filepath}: {exc}")


def _save_image(data_url: str) -> str:
    """
    將 base64 data URL 存成磁碟圖片，回傳可直接使用的 URL 路徑。
    若已是普通 URL（非 data:），直接回傳原值（向後相容舊資料）。
    """
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return data_url
    try:
        header, b64data = data_url.split(",", 1)
        mime = header.split(";")[0].split(":")[-1]
        ext  = _MIME_TO_EXT.get(mime, "jpg")
        filename = f"{secrets.token_hex(16)}.{ext}"
        filepath = os.path.join(_UPLOAD_DIR, filename)
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(b64data))
        logger.info(f"[IMAGE SAVED] {filename} ({mime})")
        return f"/static/uploads/{filename}"
    except Exception as exc:
        logger.error(f"[IMAGE SAVE ERROR] {exc}")
        return data_url   # 儲存失敗時退回原 data URL，不中斷流程


# ── Email 設定：從環境變數讀取，未設定時只印 log 不寄信。───────────────────────
# 使用方式：在終端機 set OASIS_EMAIL_USER=yourmail@gmail.com
#           set OASIS_EMAIL_PASS=xxxx xxxx xxxx xxxx  (Gmail App 密碼)
EMAIL_USER = os.environ.get("OASIS_EMAIL_USER", "")
EMAIL_PASS = os.environ.get("OASIS_EMAIL_PASS", "")
SITE_URL   = os.environ.get("OASIS_SITE_URL", "http://localhost:8000")


def _send_email_sync(to: str, subject: str, body_html: str) -> None:
    """實際的同步寄信邏輯，在背景執行緒中執行（避免 SMTP 延遲阻塞 API）。"""
    if not EMAIL_USER or not EMAIL_PASS:
        logger.info(f"[EMAIL SKIPPED] To={to} | {subject}")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Oasis 綠洲 <{EMAIL_USER}>"
        msg["To"]      = to
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.sendmail(EMAIL_USER, to, msg.as_string())
        logger.info(f"[EMAIL SENT] To={to} | {subject}")
    except Exception as exc:
        logger.error(f"[EMAIL ERROR] to={to} {exc}")


def send_email(to: str, subject: str, body_html: str) -> None:
    """
    寄送 HTML 郵件（背景執行緒，不阻塞 API response）。
    SMTP 握手最長約 3 秒；改成 daemon thread 後 API 立即回傳，信件在背景送出。
    """
    threading.Thread(
        target=_send_email_sync, args=(to, subject, body_html), daemon=True
    ).start()

# ── 圖片格式驗證：解碼 base64 後檢查魔術碼，防止上傳非圖片檔偽裝成圖片。────────
# 支援 JPEG / PNG / GIF / WebP 四種格式。
def _validate_image_format(data_url: str) -> bool:
    """回傳 True 表示為合法圖片格式（JPEG / PNG / GIF / WebP）。"""
    try:
        if not isinstance(data_url, str) or "," not in data_url:
            return False
        header, b64data = data_url.split(",", 1)
        if not header.startswith("data:image/"):
            return False
        raw = base64.b64decode(b64data, validate=False)[:15]
        if raw[:3] == b"\xff\xd8\xff":                                       return True  # JPEG
        if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":               return True  # PNG
        if len(raw) >= 6 and raw[:6] in (b"GIF87a", b"GIF89a"):              return True  # GIF
        if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":  return True  # WebP
        return False
    except Exception:
        return False


# ── 輸入驗證 ──────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def is_valid_email(email: str) -> bool:
    """基本 Email 格式檢查：有 @、@ 前後都有內容、@ 後有點。"""
    return bool(_EMAIL_RE.match(email))


# ── CAPTCHA 開關：設定 DISABLE_CAPTCHA=1 可在測試 / 開發環境略過驗證碼。─────────
DISABLE_CAPTCHA = os.environ.get("DISABLE_CAPTCHA", "") == "1"


# ── Pydantic 請求體模型：自動 JSON 解析＋型別安全，取代 body.get("field","")。─────
# 使用前：body = await request.json(); name = body.get("name", "")
# 使用後：body: RegisterRequest; name = body.name        ← 型別安全，無 KeyError
#
# hp（蜜罐欄位）：HTML 表單中隱藏不可見，真人不會填；爬蟲通常會填所有欄位 → 被拒。
# captcha_id / captcha_answer：數學驗證碼（由 GET /api/auth/challenge 產生）。

class RegisterRequest(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""
    hp: str = ""           # honeypot：機器人會填，真人看不到
    captcha_id: str = ""
    captcha_answer: str = ""

class LoginRequest(BaseModel):
    email: str = ""
    password: str = ""
    hp: str = ""
    captcha_id: str = ""
    captcha_answer: str = ""

class BookingRequest(BaseModel):
    space_id: Optional[int] = None
    space_name: str = ""
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    purpose: str = ""

class SpaceRequest(BaseModel):
    name: str = ""
    city: str = ""
    district: str = ""
    address: str = ""
    type: str = ""
    price_per_hour: Optional[int] = None
    capacity: Optional[int] = None
    equipment: List[str] = []
    description: str = ""
    images: List[str] = []
    image: Optional[str] = None   # 向後相容舊版單圖欄位
    lat: Optional[float] = None   # GPS 緯度（地圖模式用）
    lng: Optional[float] = None   # GPS 經度（地圖模式用）

class UpdateSpaceBody(BaseModel):
    name: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    type: Optional[str] = None
    price_per_hour: Optional[int] = None
    capacity: Optional[int] = None
    equipment: Optional[List[str]] = None
    description: Optional[str] = None
    images: Optional[List[str]] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

class SetPlanRequest(BaseModel):
    plan:   str = "free"
    months: int = 1

class CoRentalRequest(BaseModel):
    space_id: Optional[int] = None
    date: str = ""
    start_time: str = ""
    end_time: str = ""
    total_slots: int = 2
    price_per_slot: int = 0
    purpose: str = ""

class ContactRequest(BaseModel):
    name: str = ""
    email: str = ""
    message: str = ""
    hp: str = ""
    captcha_id: str = ""
    captcha_answer: str = ""

class ForgotPasswordRequest(BaseModel):
    email: str = ""
    hp: str = ""
    captcha_id: str = ""
    captcha_answer: str = ""

class ResetPasswordRequest(BaseModel):
    token: str = ""
    new_password: str = ""

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None

class RateSpaceRequest(BaseModel):
    score: Optional[int] = None
    comment: Optional[str] = None

class AnnouncementRequest(BaseModel):
    title: str = ""
    content: str = ""


# ── 速率限制參數（DB 版，跨 Worker 共用）────────────────────────────────────────
_MAX_ATTEMPTS   = 5        # 登入連續失敗幾次後鎖定
_LOCKOUT_MINS   = 15       # 鎖定幾分鐘
_CONTACT_MAX    = 5        # 聯絡表單：同 IP 每 60 秒最多 5 筆
_CONTACT_WINDOW = 60       # 秒
_FORGOT_MAX     = 5        # 忘記密碼：同 IP 每 5 分鐘最多 5 次
_FORGOT_WINDOW  = 300      # 秒


def _check_rate_limit_db(key: str, window_seconds: int, max_count: int) -> bool:
    """
    以資料庫為後端的速率限制，所有 Gunicorn Worker 進程共用計數。
    回傳 True 表示超過限制，應拒絕本次請求。
    原理：將每個 (key, 時間窗) 的計數存入 rate_limits 表；窗口過期後自動重置。
    """
    conn = _get_conn()
    cursor = conn.cursor()
    now     = datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    cursor.execute("SELECT count, window_start FROM rate_limits WHERE key = ?", (key,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO rate_limits(key, count, window_start) VALUES(?, 1, ?)",
            (key, now_iso),
        )
        conn.commit()
        conn.close()
        return False
    count, window_start_iso = row
    if (now - datetime.fromisoformat(window_start_iso)).total_seconds() > window_seconds:
        # 時間窗已過期，重置計數
        cursor.execute(
            "UPDATE rate_limits SET count = 1, window_start = ? WHERE key = ?",
            (now_iso, key),
        )
        conn.commit()
        conn.close()
        return False
    new_count = count + 1
    cursor.execute("UPDATE rate_limits SET count = ? WHERE key = ?", (new_count, key))
    conn.commit()
    conn.close()
    return new_count > max_count


def _is_login_locked_db(email: str) -> tuple[bool, str]:
    """回傳 (是否鎖定, 說明文字)；過期的鎖定自動清除。"""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT locked_until FROM rate_limits WHERE key = ?", (f"login:{email}",))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return False, ""
    locked_until = datetime.fromisoformat(row[0])
    if datetime.now() < locked_until:
        mins = max(1, int((locked_until - datetime.now()).total_seconds() / 60) + 1)
        return True, f"登入失敗次數過多，請 {mins} 分鐘後再試"
    # 鎖定已過期，清除
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rate_limits WHERE key = ?", (f"login:{email}",))
    conn.commit()
    conn.close()
    return False, ""


def _record_login_failure_db(email: str) -> int:
    """記錄一次登入失敗；回傳剩餘機會數（0 表示剛觸發鎖定）。"""
    key = f"login:{email}"
    conn = _get_conn()
    cursor = conn.cursor()
    now     = datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    cursor.execute("SELECT count, window_start FROM rate_limits WHERE key = ?", (key,))
    row = cursor.fetchone()
    if row is None:
        new_count = 1
        cursor.execute(
            "INSERT INTO rate_limits(key, count, window_start) VALUES(?, 1, ?)",
            (key, now_iso),
        )
    else:
        count, window_start_iso = row
        if (now - datetime.fromisoformat(window_start_iso)).total_seconds() > 3600:
            # 超過 1 小時視為新的嘗試期，重置
            new_count = 1
            cursor.execute(
                "UPDATE rate_limits SET count = 1, window_start = ?, locked_until = NULL WHERE key = ?",
                (now_iso, key),
            )
        else:
            new_count = count + 1
            cursor.execute("UPDATE rate_limits SET count = ? WHERE key = ?", (new_count, key))
    if new_count >= _MAX_ATTEMPTS:
        locked_until_iso = (now + timedelta(minutes=_LOCKOUT_MINS)).isoformat(timespec="seconds")
        cursor.execute(
            "UPDATE rate_limits SET locked_until = ? WHERE key = ?",
            (locked_until_iso, key),
        )
        conn.commit()
        conn.close()
        return 0
    conn.commit()
    conn.close()
    return _MAX_ATTEMPTS - new_count


def _clear_login_attempts_db(email: str) -> None:
    """登入成功後清除失敗紀錄，解除可能的鎖定。"""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rate_limits WHERE key = ?", (f"login:{email}",))
    conn.commit()
    conn.close()


# ── 管理員後台全文搜尋 helper ───────────────────────────────────────────────────
def _build_search_condition(search: str, text_cols: list) -> tuple:
    """
    為管理員後台搜尋構建 SQL WHERE 子句與對應參數清單。
    - 文字欄位：LIKE '%keyword%' 模糊比對
    - 數字提取：搜尋字串含數字時加上 id = N 精準比對（支援 B-5, S-0005 等編碼格式）
    回傳 (條件字串, 參數 list)；搜尋字串空白時回傳 ("", [])。
    """
    if not search.strip():
        return "", []
    like = f"%{search}%"
    parts:  list = [f"{col} LIKE ?" for col in text_cols]
    params: list = [like] * len(text_cols)
    id_match = re.search(r"\d+", search)
    if id_match:
        parts.append("id = ?")
        params.append(int(id_match.group()))
    return f"({' OR '.join(parts)})", params



# ── 數學驗證碼（CAPTCHA）：無需外部 API，伺服器端產生、DB 存儲、多 Worker 共用。──
# 流程：GET /api/auth/challenge → 取得 {id, question}
#       提交表單時帶 captcha_id + captcha_answer → 後端比對
# 每個 challenge 10 分鐘過期，驗證後立即刪除（一次性使用）。

def _create_challenge() -> dict:
    """產生新的數學加法挑戰，存入 DB（10 分鐘過期），回傳 {id, question}。"""
    a, b    = random.randint(1, 15), random.randint(1, 15)
    cid     = secrets.token_hex(12)
    expires = (datetime.now() + timedelta(minutes=10)).isoformat(timespec="seconds")
    conn    = _get_conn()
    cursor  = conn.cursor()
    # 順手清理已過期的挑戰，避免表格無限增長
    cursor.execute(
        "DELETE FROM challenges WHERE expires_at < ?",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    cursor.execute(
        "INSERT INTO challenges(id, answer, expires_at) VALUES(?, ?, ?)",
        (cid, str(a + b), expires),
    )
    conn.commit()
    conn.close()
    return {"id": cid, "question": f"{a} + {b} = ?"}


def _verify_challenge(cid: str, answer: str) -> bool:
    """
    驗證挑戰答案，回傳 True 表示通過。
    DISABLE_CAPTCHA=1 時直接回傳 True（測試 / 開發環境略過）。
    """
    if DISABLE_CAPTCHA:
        return True
    if not cid or not answer:
        return False
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT answer, expires_at FROM challenges WHERE id = ?", (cid,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    db_answer, expires_at_iso = row
    cursor.execute("DELETE FROM challenges WHERE id = ?", (cid,))   # 一次性：用後即刪
    conn.commit()
    conn.close()
    if datetime.now() > datetime.fromisoformat(expires_at_iso):
        return False
    return answer.strip() == db_answer


# ── 密碼雜湊：PBKDF2-SHA256 + 隨機 salt，避免明文儲存。─────────────────────────
def hash_password(plain: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 200_000)
    return f"{salt}:{key.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    if ":" not in stored:
        return plain == stored          # 相容舊版明文（一次性 migration 用）
    salt, key_hex = stored.split(":", 1)
    new_key = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt.encode(), 200_000)
    return secrets.compare_digest(new_key.hex(), key_hex)


app = FastAPI(title="Oasis 綠洲", docs_url=None, redoc_url=None)


# ── 自訂 404 頁面：打錯網址時顯示友善頁面，而非 FastAPI 預設 JSON 錯誤。────────
# 原本 FastAPI 遇到找不到路由時回傳 {"detail":"Not Found"}；
# 這裡改為回傳 www/404.html，讓使用者看到設計過的頁面。
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return FileResponse("www/404.html", status_code=404)


# ── HTTP 安全標頭：防止 Clickjacking、MIME sniffing 等常見攻擊。──────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    # Content-Security-Policy：防止 XSS 注入，限制資源來源。
    # - script-src 'self'              → 只允許自己的 JS 檔案
    # - style-src 'self' 'unsafe-inline' → 允許 HTML inline style（現有 HTML 使用）
    # - img-src 'self' data: https://picsum.photos → 允許自身、data URL（上傳預覽）、Picsum 預設圖
    # - frame-ancestors 'none'         → 禁止被任何 iframe 嵌入（取代 X-Frame-Options）
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
        "img-src 'self' data: blob: https://picsum.photos https://*.picsum.photos "
        "https://*.tile.openstreetmap.org https://unpkg.com; "
        "font-src 'self' https://unpkg.com https://cdn.jsdelivr.net; "
        "connect-src 'self' https://*.tile.openstreetmap.org; "
        "frame-ancestors 'none'"
    )
    return response


# 初始化資料庫（SQLite 或 PostgreSQL）與預設資料。
def init_db():
    conn   = _get_conn()
    cursor = conn.cursor()

    # PostgreSQL 用 BIGSERIAL，SQLite 用 INTEGER PRIMARY KEY AUTOINCREMENT
    _pk = "BIGSERIAL PRIMARY KEY" if PG_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # ── spaces ────────────────────────────────────────────────────────────────
    # 完整 schema（含所有後來 ALTER 新增的欄位），讓 PG 全新安裝不需 migrate
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS spaces (
            id {_pk},
            name TEXT, city TEXT, district TEXT, address TEXT,
            type TEXT, price_per_hour INTEGER, capacity INTEGER,
            rating REAL, image TEXT, equipment TEXT, description TEXT,
            status TEXT DEFAULT '已確認', owner_email TEXT, images TEXT,
            lat REAL, lng REAL
        )
    """)
    if not PG_URL:   # SQLite 舊版資料庫補欄位
        _sc = _get_columns(cursor, "spaces")
        if "status"      not in _sc: cursor.execute("ALTER TABLE spaces ADD COLUMN status TEXT DEFAULT '已確認'")
        if "owner_email" not in _sc: cursor.execute("ALTER TABLE spaces ADD COLUMN owner_email TEXT")
        if "images"      not in _sc: cursor.execute("ALTER TABLE spaces ADD COLUMN images TEXT")
        if "lat"         not in _sc: cursor.execute("ALTER TABLE spaces ADD COLUMN lat REAL")
        if "lng"         not in _sc: cursor.execute("ALTER TABLE spaces ADD COLUMN lng REAL")

    # ── bookings ──────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS bookings (
            id {_pk},
            space_id INTEGER, space_name TEXT,
            date TEXT, start_time TEXT, end_time TEXT,
            purpose TEXT, status TEXT DEFAULT '待確認',
            user_email TEXT
        )
    """)
    if not PG_URL:
        _bc = _get_columns(cursor, "bookings")
        if "user_email" not in _bc: cursor.execute("ALTER TABLE bookings ADD COLUMN user_email TEXT")

    # ── contacts ──────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS contacts (
            id {_pk},
            name TEXT, email TEXT, message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── ratings ───────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS ratings (
            id {_pk},
            space_id INTEGER NOT NULL, user_email TEXT NOT NULL,
            score INTEGER NOT NULL, comment TEXT,
            UNIQUE(space_id, user_email)
        )
    """)
    if not PG_URL:
        _rc = _get_columns(cursor, "ratings")
        if "comment" not in _rc: cursor.execute("ALTER TABLE ratings ADD COLUMN comment TEXT")

    # ── password_resets ───────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS password_resets (
            id {_pk},
            email TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL, used INTEGER DEFAULT 0
        )
    """)

    # ── announcements ─────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS announcements (
            id {_pk},
            title TEXT NOT NULL, content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    """)

    # ── rate_limits（跨 Worker 速率限制，替代記憶體 dict）──────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 1,
            window_start TEXT NOT NULL,
            locked_until TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_key ON rate_limits(key)")

    # ── challenges（數學驗證碼挑戰）──────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS challenges (
            id TEXT PRIMARY KEY,
            answer TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_challenges_expires ON challenges(expires_at)")

    # ── schema_versions（輕量級 DB Migration 版本追蹤）───────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── co_rentals（拼場功能：多人合租同一時段分攤費用）─────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS co_rentals (
            id {_pk},
            space_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            total_slots INTEGER NOT NULL DEFAULT 2,
            filled_slots INTEGER NOT NULL DEFAULT 1,
            price_per_slot INTEGER NOT NULL DEFAULT 0,
            purpose TEXT,
            organizer_email TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS co_rental_members (
            id {_pk},
            co_rental_id INTEGER NOT NULL,
            user_email TEXT NOT NULL,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(co_rental_id, user_email)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_co_rentals_date   ON co_rentals(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_co_rentals_status ON co_rentals(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_co_rentals_space  ON co_rentals(space_id)")

    # ── users（含所有歷史新增欄位）────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {_pk},
            name TEXT, email TEXT UNIQUE, password TEXT,
            role TEXT DEFAULT 'user',
            token TEXT, token_expires_at TEXT,
            banned INTEGER DEFAULT 0,
            email_verified INTEGER DEFAULT 1, email_verify_token TEXT,
            plan TEXT DEFAULT 'free', plan_expires_at TEXT
        )
    """)
    if not PG_URL:
        _uc = _get_columns(cursor, "users")
        if "token"              not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN token TEXT")
        if "token_expires_at"   not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN token_expires_at TEXT")
        if "banned"             not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
        if "email_verified"     not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 1")
        if "email_verify_token" not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN email_verify_token TEXT")
        if "plan"               not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
        if "plan_expires_at"    not in _uc: cursor.execute("ALTER TABLE users ADD COLUMN plan_expires_at TEXT")

    # ── 確保有 admin 帳號，密碼若是舊明文格式則自動升級 ─────────────────────────
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO users (name, email, password, role, email_verified) VALUES (?, ?, ?, ?, ?)",
            ("Oasis 管理員", "admin@oasis.com", hash_password("admin123"), "admin", 1),
        )
    else:
        cursor.execute("SELECT id, password FROM users WHERE role = 'admin'")
        for uid, pwd in cursor.fetchall():
            if ":" not in pwd:
                cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(pwd), uid))

    # ── 預設空間（首次安裝才插入）────────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM spaces")
    if cursor.fetchone()[0] == 0:
        # 不指定 id，讓資料庫自動遞增（PostgreSQL SERIAL / SQLite AUTOINCREMENT 皆適用）
        cursor.executemany(
            "INSERT INTO spaces (name, city, district, address, type, price_per_hour,"
            " capacity, rating, image, equipment, description, status, lat, lng)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("Tiny Desk Studio", "美國", "華盛頓特區", "美國華盛頓特區",
                 "工作室", 600, 18, 4.9, "/static/images/coldplay.png",
                 "音響,麥克風,燈光,桌椅",
                 "溫暖的音樂表演與錄影空間，適合小型演出、Podcast 錄製、訪談拍攝與直播活動。",
                 "已確認", 38.8951, -77.0364),
                ("小角 . 手捻咖啡", "台中市", "南屯區", "臺中市南屯區惠中里大墩十街360號",
                 "咖啡廳", 320, 24, 4.7, "/static/images/coffee.png",
                 "咖啡吧,桌椅,Wi-Fi,插座",
                 "帶有手作質感的小型咖啡空間，適合讀書會、手作課程、品牌小聚與輕型講座。",
                 "已確認", 24.1341, 120.6565),
                ("停車場預約", "台中市", "太平區", "台中市太平區",
                 "停車場", 120, 60, 4.3, "/static/images/parkinglot.png",
                 "車位,遮雨棚,監視器,照明",
                 "可預約短期使用的戶外停車空間，適合臨停、活動車輛停放與小型市集後勤使用。",
                 "已確認", 24.1287, 120.7198),
            ],
        )

    # ── 預設預約（首次安裝才插入）────────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) FROM bookings")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO bookings (space_id, space_name, date, start_time, end_time, purpose, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "Tiny Desk Studio",  "2026-05-20", "10:00", "14:00", "音樂錄影拍攝", "待確認"),
                (2, "小角 . 手捻咖啡",   "2026-05-28", "19:00", "21:00", "咖啡讀書會",   "已確認"),
                (3, "停車場預約",         "2026-04-12", "09:00", "17:00", "活動車輛停放", "已完成"),
            ],
        )

    # ── 索引（對效能至關重要；IF NOT EXISTS 確保重複執行安全）───────────────────
    # users.token：get_user_from_token 幾乎每個 request 都查這個欄位
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_token      ON users(token)")
    # spaces：探索頁常以 status / city / type / price 篩選
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spaces_status    ON spaces(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spaces_city      ON spaces(city)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spaces_type      ON spaces(type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spaces_price     ON spaces(price_per_hour)")
    # bookings：使用者中心、場地主收到的預約、衝突檢查都走 space_id / user_email / date
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_spaceid ON bookings(space_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_email   ON bookings(user_email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date    ON bookings(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status  ON bookings(status)")
    # password_resets.token：重設密碼時以 token 查詢
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pwreset_token    ON password_resets(token)")

    conn.commit()
    conn.close()
    logger.info(f"[DB INIT] 資料庫初始化完成（{'PostgreSQL' if PG_URL else 'SQLite'}）")


def run_migrations():
    """
    輕量級 DB Migration：讀取 migrations/*.sql，依版本號順序套用尚未執行的 migration。
    冪等設計：已套用的 migration 不會重複執行，可安全重複呼叫。
    新 SQL 檔只需放入 migrations/ 資料夾並按 NNN_xxx.sql 命名即可自動套用。
    """
    migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
    if not os.path.isdir(migrations_dir):
        logger.info("[MIGRATION] migrations/ 不存在，略過")
        return
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM schema_versions")
    applied = {row[0] for row in cursor.fetchall()}
    files   = sorted(f for f in os.listdir(migrations_dir) if re.match(r"^\d{3}_.*\.sql$", f))
    applied_count = 0
    for filename in files:
        version = int(filename[:3])
        if version in applied:
            continue
        filepath = os.path.join(migrations_dir, filename)
        with open(filepath, "r", encoding="utf-8") as fh:
            sql_content = fh.read()
        # PostgreSQL 語法轉換：SQLite AUTOINCREMENT → SERIAL
        if PG_URL:
            sql_content = re.sub(
                r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
                "SERIAL PRIMARY KEY",
                sql_content,
                flags=re.IGNORECASE,
            )
        try:
            for stmt in sql_content.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    cursor.execute(stmt)
            cursor.execute(
                "INSERT INTO schema_versions (version, name) VALUES (?, ?)",
                (version, filename),
            )
            conn.commit()
            logger.info(f"[MIGRATION] Applied v{version}: {filename}")
            applied_count += 1
        except Exception as exc:
            conn.close()
            logger.error(f"[MIGRATION ERROR] {filename}: {exc}")
            raise RuntimeError(f"Migration 失敗 [{filename}]: {exc}") from exc
    conn.close()
    if applied_count:
        logger.info(f"[MIGRATION] 共套用 {applied_count} 個 migration")
    else:
        logger.info("[MIGRATION] DB 已是最新版本")


init_db()
run_migrations()


# 將資料庫查詢結果轉成前端需要的空間 dict 格式。
def row_to_space(row):
    images_raw = row[14] if len(row) > 14 else None
    images = json.loads(images_raw) if images_raw else []
    if not images and row[9]:
        images = [row[9]]
    return {
        "id": row[0],
        "name": row[1],
        "city": row[2],
        "district": row[3],
        "address": row[4],
        "type": row[5],
        "price_per_hour": row[6],
        "capacity": row[7],
        "rating": row[8],
        "image": row[9],
        "equipment": row[10].split(",") if row[10] else [],
        "description": row[11],
        "status": row[12] if len(row) > 12 and row[12] else "已確認",
        "owner_email": row[13] if len(row) > 13 else None,
        "images": images,
        "lat": row[15] if len(row) > 15 else None,
        "lng": row[16] if len(row) > 16 else None,
    }


# 自動更新逾期預約狀態：
#   「已確認」但日期已過 → 「已完成」
#   「待確認」但日期已過 → 「已取消」（未及時確認視為失效）
# 在每次讀取預約列表前呼叫，確保狀態即時準確。
def auto_expire_bookings(cursor) -> None:
    today = dt_date.today().isoformat()
    cursor.execute(
        "UPDATE bookings SET status = '已完成' WHERE date < ? AND status = '已確認'",
        (today,),
    )
    cursor.execute(
        "UPDATE bookings SET status = '已取消' WHERE date < ? AND status = '待確認'",
        (today,),
    )


# 將資料庫查詢結果轉成前端需要的預約 dict 格式。
def row_to_booking(row):
    return {
        "id": row[0],
        "space_id": row[1],
        "space_name": row[2],
        "date": row[3],
        "start_time": row[4],
        "end_time": row[5],
        "purpose": row[6],
        "status": row[7],
        "user_email": row[8] if len(row) > 8 else None,
    }


# 將資料庫查詢結果轉成前端需要的聯絡訊息 dict 格式。
def row_to_contact(row):
    return {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "message": row[3],
        "created_at": row[4],
    }


# 將使用者資料轉成前端登入狀態需要的 dict 格式，不回傳密碼。
# row 欄位順序：id(0) name(1) email(2) password(3) role(4) token(5)
#              token_expires_at(6) banned(7) email_verified(8) email_verify_token(9)
#              plan(10) plan_expires_at(11)
def row_to_user(row):
    raw_plan    = row[10] if len(row) > 10 and row[10] else "free"
    plan_exp    = row[11] if len(row) > 11 else None
    # 若 Pro 方案已過期，自動降回 free
    if raw_plan == "pro" and plan_exp and plan_exp < datetime.now().isoformat():
        raw_plan = "free"
    return {
        "id":              row[0],
        "name":            row[1],
        "email":           row[2],
        "role":            row[4],
        "banned":          bool(row[7]) if len(row) > 7 else False,
        "plan":            raw_plan,
        "plan_expires_at": plan_exp,
    }


# 根據 X-Auth-Token header 查找使用者，並驗證 token 是否過期。
def get_user_from_token(token: str):
    if not token:
        return None
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    expires_at = row[6] if len(row) > 6 else None
    if expires_at and datetime.now() > datetime.fromisoformat(expires_at):
        return None  # token 已過期，視為未登入
    user = row_to_user(row)
    if user.get("banned"):
        return None  # 已停用帳號視為未登入
    return user


# 顯示首頁，提供搜尋入口與精選空間。
@app.get("/")
def index_page():
    return FileResponse("www/index.html")


# 顯示探索頁，提供關鍵字與條件篩選。
@app.get("/explore")
def explore_page():
    return FileResponse("www/explore.html")


# 顯示空間詳情頁，前端會依照網址 id 載入資料。
@app.get("/space")
def space_page():
    return FileResponse("www/space.html")


# 顯示預約申請頁，前端會依照網址 id 載入空間並送出預約。
@app.get("/booking")
def booking_page():
    return FileResponse("www/booking.html")


# 顯示會員中心，列出所有預約紀錄。
@app.get("/dashboard")
def dashboard_page():
    return FileResponse("www/dashboard.html")


# 顯示空間上架頁，保留既有前端連結可正常使用。
@app.get("/host")
def host_page():
    return FileResponse("www/host.html")


# 顯示聯絡我們頁，提供聯絡表單。
@app.get("/contact")
def contact_page():
    return FileResponse("www/contact.html")


# 顯示定價頁。
@app.get("/pricing")
def pricing_page():
    return FileResponse("www/pricing.html")


# 顯示服務條款頁。
@app.get("/terms")
def terms_page():
    return FileResponse("www/terms.html")


# 顯示隱私政策頁。
@app.get("/privacy")
def privacy_page():
    return FileResponse("www/privacy.html")


# 查詢目前登入使用者的訂閱方案。
@app.get("/api/user/plan")
def get_my_plan(request: Request):
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": False, "message": "未授權"}
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM spaces WHERE owner_email = ? AND status != '已拒絕'", (user["email"],))
    space_count = cursor.fetchone()[0]
    conn.close()
    return {
        "ok": True,
        "data": {
            "plan":            user.get("plan", "free"),
            "plan_expires_at": user.get("plan_expires_at"),
            "is_pro":          user.get("plan") == "pro",
            "space_count":     space_count,
            "space_limit":     None if user.get("plan") == "pro" else 1,
        },
    }


# 管理員手動設定使用者訂閱方案（正式上線後改由金流自動處理）。
@app.post("/api/admin/users/{email}/set-plan")
def admin_set_plan(email: str, body: SetPlanRequest, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    if body.plan not in ("free", "pro"):
        return {"ok": False, "message": "方案只能是 free 或 pro"}
    expires = None
    if body.plan == "pro":
        expires = (datetime.now() + timedelta(days=30 * max(1, body.months))).isoformat()
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if not cursor.fetchone():
        conn.close()
        return {"ok": False, "message": "找不到此使用者"}
    cursor.execute(
        "UPDATE users SET plan = ?, plan_expires_at = ? WHERE email = ?",
        (body.plan, expires, email),
    )
    conn.commit()
    conn.close()
    logger.info(f"[PLAN] admin={admin['email']} set {email} → {body.plan} expires={expires}")
    return {"ok": True, "message": f"已將 {email} 設為 {body.plan} 方案"}


# 顯示登入頁，管理員與一般使用者共用同一個入口。
@app.get("/login")
def login_page():
    return FileResponse("www/login.html")


# 顯示註冊頁，建立一般使用者帳號。
@app.get("/register")
def register_page():
    return FileResponse("www/register.html")


# 顯示使用者中心，給一般使用者登入後使用。
@app.get("/user")
def user_page():
    return FileResponse("www/user.html")


# 顯示忘記密碼頁，讓使用者輸入信箱申請重設連結。
@app.get("/forgot-password")
def forgot_password_page():
    return FileResponse("www/forgot-password.html")


# 顯示重設密碼頁，透過信中連結進入並輸入新密碼。
@app.get("/reset-password")
def reset_password_page():
    return FileResponse("www/reset-password.html")


# 顯示信箱驗證完成頁，用戶點擊驗證信中的連結後到達此頁。
@app.get("/verify-email")
def verify_email_page():
    return FileResponse("www/verify-email.html")


# 顯示智慧推薦頁，讓使用者輸入需求後自動推薦最適空間。
@app.get("/recommend")
def recommend_page():
    return FileResponse("www/recommend.html")


# 顯示拼場列表頁，列出所有開放合租的活動並支援加入。
@app.get("/co-rental")
def co_rental_page():
    return FileResponse("www/co-rental.html")


# 驗證信箱：使用者點擊驗證信連結後，前端呼叫此 API 完成驗證。
@app.get("/api/auth/verify-email")
def verify_email_token(token: str = ""):
    if not token:
        return {"ok": False, "message": "無效的驗證連結"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, email FROM users WHERE email_verify_token = ? AND email_verified = 0",
        (token,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "message": "驗證連結無效或已使用過，請重新註冊"}
    user_id, email = row
    cursor.execute(
        "UPDATE users SET email_verified = 1, email_verify_token = NULL WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()
    logger.info(f"[EMAIL VERIFIED] email={email}")
    return {"ok": True, "message": "信箱驗證成功！你現在可以登入了。"}


# 取得空間列表，可依關鍵字、城市與類型從 SQLite 過濾，支援分頁。
@app.get("/api/spaces")
def get_spaces(
    keyword: str = "",
    city: str = "",
    type: str = "",
    max_price: int = 0,   # 每小時價格上限，0 表示不限
    page: int = 1,
    per_page: int = 9,
    sort: str = "",       # "rating" 表示依評分高低排序
):
    per_page = max(1, min(per_page, 100))
    conn = _get_conn()
    cursor = conn.cursor()
    conditions = []
    params = []

    if keyword:
        conditions.append(
            "(name LIKE ? OR city LIKE ? OR district LIKE ? OR description LIKE ?)"
        )
        keyword_like = f"%{keyword}%"
        params.extend([keyword_like, keyword_like, keyword_like, keyword_like])

    if city:
        conditions.append("city = ?")
        params.append(city)

    if type:
        conditions.append("type = ?")
        params.append(type)

    if max_price > 0:
        conditions.append("price_per_hour <= ?")
        params.append(max_price)

    conditions.append("status = ?")
    params.append("已確認")

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    cursor.execute(f"SELECT COUNT(*) FROM spaces{where}", params)
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    order_by = "ORDER BY COALESCE(rating, 0) DESC" if sort == "rating" else "ORDER BY id ASC"
    cursor.execute(
        f"SELECT * FROM spaces{where} {order_by} LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page],
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "ok": True,
        "data": [row_to_space(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# 取得所有空間資料，包含待確認上架申請，給管理員中心使用，支援分頁。
@app.get("/api/admin/spaces")
def get_admin_spaces(request: Request, page: int = 1, per_page: int = 10, search: str = ""):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    per_page = max(1, min(per_page, 100))
    conn = _get_conn()
    cursor = conn.cursor()
    cond, cond_params = _build_search_condition(search, ["name", "city", "type", "owner_email"])
    where = f"WHERE {cond}" if cond else ""
    cursor.execute(f"SELECT COUNT(*) FROM spaces {where}", cond_params)
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    cursor.execute(
        f"SELECT * FROM spaces {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        cond_params + [per_page, (page - 1) * per_page],
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "ok": True,
        "data": [row_to_space(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# ── 智慧推薦：根據用途、人數、城市與預算為各空間打分，回傳最適前五名。────────────
# 路由必須定義在 /api/spaces/{space_id} 之前（同 cities 路由的理由）。
_PURPOSE_TYPE_MAP = {
    "會議": ["工作室", "教室"], "會談": ["工作室"], "訪談": ["工作室"],
    "錄音": ["工作室"], "錄影": ["工作室", "藝廊"], "拍攝": ["工作室", "藝廊"],
    "直播": ["工作室"], "表演": ["工作室", "藝廊"],
    "展覽": ["藝廊"], "展示": ["藝廊"],
    "咖啡": ["咖啡廳"], "讀書": ["咖啡廳"], "小聚": ["咖啡廳"],
    "停車": ["停車場"], "停放": ["停車場"], "車位": ["停車場"],
    "教學": ["教室"], "上課": ["教室"], "培訓": ["教室"], "講座": ["教室", "工作室"],
    "辦公": ["工作室"], "工作": ["工作室"], "開會": ["工作室", "教室"],
}

@app.get("/api/spaces/recommend")
def recommend_spaces(
    purpose: str = "",
    people: int = 0,
    city: str = "",
    budget: int = 0,
):
    """
    智慧推薦搜尋：依需求為每個公開空間打分，回傳最適合的前 5 個空間。
    評分維度：用途匹配 (30分) + 人數適配 (30分) + 預算符合 (20分)
              + 城市吻合 (15分) + 評分加成 (5分)
    """
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spaces WHERE status = '已確認'")
    rows = cursor.fetchall()
    conn.close()

    scored: list = []
    for row in rows:
        space = row_to_space(row)
        score = 0

        # ── 用途匹配（0-30 分）────────────────────────────────────────────────
        if purpose:
            for kw, types in _PURPOSE_TYPE_MAP.items():
                if kw in purpose and space["type"] in types:
                    score += 30
                    break
            # 部分匹配：空間描述中出現用途關鍵字
            if score < 30 and purpose in (space["description"] or ""):
                score += 15

        # ── 人數適配（0-30 分）────────────────────────────────────────────────
        cap = space["capacity"] or 0
        if people > 0:
            if cap < people:
                continue   # 容量不足，直接排除
            ratio = people / cap if cap > 0 else 0
            # 佔用率越高（越不浪費空間）越高分，但保底 10 分
            score += max(10, int(ratio * 30))
        else:
            score += 15   # 未指定人數給基礎分

        # ── 預算符合（0-20 分）────────────────────────────────────────────────
        price = space["price_per_hour"] or 0
        if budget > 0:
            if price > budget:
                score -= 15   # 超預算懲罰
            else:
                # 越省預算越高分
                ratio = 1 - price / budget if budget > 0 else 0
                score += int(ratio * 20)
        else:
            score += 10   # 未指定預算給基礎分

        # ── 城市吻合（0-15 分）────────────────────────────────────────────────
        if city:
            if space["city"] == city:
                score += 15
        else:
            score += 7

        # ── 評分加成（0-5 分）─────────────────────────────────────────────────
        if space["rating"]:
            score += min(5, int(space["rating"]))

        scored.append((score, space))

    scored.sort(key=lambda x: x[0], reverse=True)
    return {
        "ok": True,
        "data": [{"score": s, "space": sp} for s, sp in scored[:5]],
    }


# 取得目前已公開空間的不重複城市清單，供探索頁篩選器動態生成選項。
# 注意：此路由必須定義在 /api/spaces/{space_id} 之前，
# 否則 FastAPI 會把 "cities" 當成 space_id 整數解析而回傳 422。
@app.get("/api/spaces/cities")
def get_space_cities():
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT city FROM spaces WHERE status = '已確認' AND city IS NOT NULL ORDER BY city ASC"
    )
    rows = cursor.fetchall()
    conn.close()
    return {"ok": True, "data": [r[0] for r in rows if r[0]]}


# 取得單一空間資料，找不到時回傳錯誤訊息。
@app.get("/api/spaces/{space_id}")
def get_space(space_id: int):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spaces WHERE id = ?", (space_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"ok": False, "message": "找不到此空間"}
    return {"ok": True, "data": row_to_space(row)}


# 刪除指定空間；管理員可刪任意空間，場地主只能刪自己的。
@app.delete("/api/spaces/{space_id}")
def delete_space(space_id: int, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM spaces WHERE id = ?", (space_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "message": "找不到此空間"}

    space = row_to_space(row)
    if requester["role"] != "admin" and space.get("owner_email") != requester["email"]:
        conn.close()
        return {"ok": False, "message": "未授權"}

    cursor.execute("DELETE FROM spaces WHERE id = ?", (space_id,))
    conn.commit()
    conn.close()

    # 刪除空間時同步清理磁碟上的上傳圖片，避免 uploads/ 無限增長
    for img_url in (space.get("images") or []):
        _delete_image_file(img_url)
    _delete_image_file(space.get("image", ""))

    return {"ok": True, "message": "空間已刪除！", "data": space}


# 將指定空間更新為已確認，確認後才會出現在探索頁。
@app.post("/api/spaces/{space_id}/confirm")
def confirm_space(space_id: int, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE spaces SET status = '已確認' WHERE id = ?", (space_id,))
    conn.commit()
    cursor.execute("SELECT * FROM spaces WHERE id = ?", (space_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"ok": False, "message": "找不到此空間"}
    space = row_to_space(row)
    # 通知場地主：空間已通過審核公開上架
    if space.get("owner_email"):
        send_email(
            space["owner_email"],
            f"【Oasis】你的空間已通過審核：{space['name']}",
            f"<p>恭喜！你的空間「{space['name']}」已通過管理員審核，現在正式公開上架。</p>"
            f"<p>其他使用者可以在探索頁搜尋並預約你的空間。</p>"
            f"<p><a href='{SITE_URL}/user'>前往使用者中心查看</a></p>",
        )
    return {"ok": True, "message": "空間已確認上架！", "data": space}


# 取得所有預約紀錄資料，支援分頁。
@app.get("/api/bookings")
def get_bookings(request: Request, page: int = 1, per_page: int = 15, search: str = ""):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    per_page = max(1, min(per_page, 100))
    conn = _get_conn()
    cursor = conn.cursor()
    auto_expire_bookings(cursor)   # 自動取消逾期未確認的預約
    conn.commit()
    cond, cond_params = _build_search_condition(search, ["space_name", "user_email", "purpose"])
    where = f"WHERE {cond}" if cond else ""
    cursor.execute(f"SELECT COUNT(*) FROM bookings {where}", cond_params)
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    cursor.execute(
        f"SELECT * FROM bookings {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        cond_params + [per_page, (page - 1) * per_page],
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "ok": True,
        "data": [row_to_booking(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# 取得指定使用者自己的預約紀錄。
@app.get("/api/user/bookings")
def get_user_bookings(request: Request, email: str = ""):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester or requester["email"] != email:
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    auto_expire_bookings(cursor)   # 自動完成已確認 / 自動取消未確認的逾期預約
    conn.commit()
    cursor.execute(
        "SELECT * FROM bookings WHERE user_email = ? ORDER BY id DESC",
        (email,),
    )
    rows = cursor.fetchall()
    conn.close()

    return {"ok": True, "data": [row_to_booking(row) for row in rows]}


# 取得指定使用者自己送出的空間上架資料。
@app.get("/api/user/spaces")
def get_user_spaces(request: Request, email: str = ""):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester or requester["email"] != email:
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM spaces WHERE owner_email = ? ORDER BY id DESC",
        (email,),
    )
    rows = cursor.fetchall()
    conn.close()

    return {"ok": True, "data": [row_to_space(row) for row in rows]}


# 取得目前使用者場地上的拼場（場地主使用）。
@app.get("/api/owner/co-rentals")
def get_owner_co_rentals(request: Request):
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": False, "message": "未授權"}
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cr.id, cr.space_id, cr.date, cr.start_time, cr.end_time,
               cr.total_slots, cr.filled_slots, cr.price_per_slot,
               cr.purpose, cr.organizer_email, cr.status, cr.created_at,
               s.name, s.city, s.type, s.image
        FROM co_rentals cr
        JOIN spaces s ON cr.space_id = s.id
        WHERE s.owner_email = ? AND cr.status IN ('open', 'full')
        ORDER BY cr.date ASC, cr.created_at DESC
        """,
        (user["email"],),
    )
    rows = cursor.fetchall()
    conn.close()
    return {
        "ok": True,
        "data": [_row_to_co_rental(r, r[12] or "", r[13] or "", r[14] or "", r[15] or "") for r in rows],
    }


# 取得目前使用者自己發起的拼場列表。
@app.get("/api/user/co-rentals")
def get_user_co_rentals(request: Request):
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": False, "message": "未授權"}
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT cr.id, cr.space_id, cr.date, cr.start_time, cr.end_time,
               cr.total_slots, cr.filled_slots, cr.price_per_slot,
               cr.purpose, cr.organizer_email, cr.status, cr.created_at,
               s.name, s.city, s.type, s.image
        FROM co_rentals cr
        LEFT JOIN spaces s ON cr.space_id = s.id
        WHERE cr.organizer_email = ?
        ORDER BY cr.date DESC, cr.created_at DESC
        """,
        (user["email"],),
    )
    rows = cursor.fetchall()
    conn.close()
    return {
        "ok": True,
        "data": [_row_to_co_rental(r, r[12] or "", r[13] or "", r[14] or "", r[15] or "") for r in rows],
    }


# 取得指定場地主的空間收到的預約申請。
@app.get("/api/user/received-bookings")
def get_user_received_bookings(request: Request, email: str = ""):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester or requester["email"] != email:
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    auto_expire_bookings(cursor)   # 自動取消逾期未確認的預約
    conn.commit()
    cursor.execute(
        """
        SELECT bookings.*
        FROM bookings
        JOIN spaces ON bookings.space_id = spaces.id
        WHERE spaces.owner_email = ?
        ORDER BY bookings.id DESC
        """,
        (email,),
    )
    rows = cursor.fetchall()
    conn.close()

    return {"ok": True, "data": [row_to_booking(row) for row in rows]}


# 註冊一般使用者帳號；若已設定 Email，需完成信箱驗證才能登入。
@app.post("/api/auth/register")
async def register_user(body: RegisterRequest, request: Request):
    # 蜜罐：真人看不到這個隱藏欄位，爬蟲通常會填 → 被拒
    if body.hp:
        return {"ok": False, "message": "請求無效"}
    # CAPTCHA 驗證
    if not _verify_challenge(body.captcha_id, body.captcha_answer):
        return {"ok": False, "message": "驗證碼錯誤，請重新取得"}
    name     = body.name.strip()
    email    = body.email.strip()
    password = body.password.strip()

    if not name or not email or not password:
        return {"ok": False, "message": "請完整填寫註冊資料"}

    # 欄位長度限制：防止超長字串塞爆資料庫
    if len(name) > 100:
        return {"ok": False, "message": "姓名不能超過 100 個字元"}
    if len(email) > 200:
        return {"ok": False, "message": "Email 不能超過 200 個字元"}
    if len(password) > 256:
        return {"ok": False, "message": "密碼不能超過 256 個字元"}

    if not is_valid_email(email):
        return {"ok": False, "message": "Email 格式不正確"}
    if len(password) < 6:
        return {"ok": False, "message": "密碼至少需要 6 個字元"}

    # 已設定 Email → 啟用信箱驗證；未設定（開發模式）→ 跳過驗證自動啟用帳號
    needs_verification = bool(EMAIL_USER and EMAIL_PASS)
    verify_token       = secrets.token_urlsafe(32) if needs_verification else None

    conn = _get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO users (name, email, password, role, email_verified, email_verify_token)
            VALUES (?, ?, ?, 'user', ?, ?)
            """,
            (name, email, hash_password(password), 0 if needs_verification else 1, verify_token),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except Exception as exc:
        conn.close()
        # sqlite3 → "UNIQUE constraint failed"
        # psycopg2 → "duplicate key value violates unique constraint"
        exc_lower = str(exc).lower()
        if "unique" in exc_lower or "duplicate" in exc_lower:
            return {"ok": False, "message": "此信箱已經註冊"}
        logger.error(f"[REGISTER ERROR] {exc}")
        return {"ok": False, "message": "註冊失敗，請稍後再試"}

    logger.info(f"[REGISTER] email={email} name={name} needs_verify={needs_verification}")

    if needs_verification:
        conn.close()
        # 寄送驗證信，使用者點擊連結後才能登入
        verify_url = f"{SITE_URL}/verify-email?token={verify_token}"
        send_email(
            email,
            "【Oasis】請驗證你的信箱",
            f"<p>歡迎加入 Oasis 綠洲！請點擊下方連結完成信箱驗證：</p>"
            f"<p><a href='{verify_url}'>{verify_url}</a></p>"
            f"<p>若你沒有在 Oasis 綠洲註冊，請直接忽略此郵件。</p>",
        )
        logger.info(f"[EMAIL VERIFY SENT] email={email}")
        return {
            "ok": True,
            "message": "註冊成功！請前往信箱點擊驗證連結，完成驗證後即可登入。",
            "needs_verification": True,
        }
    else:
        # 開發模式（未設定 Email）：自動驗證，立即發放 token，維持原本的流暢體驗
        token      = secrets.token_hex(32)
        expires_at = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
        cursor.execute(
            "UPDATE users SET token = ?, token_expires_at = ? WHERE id = ?",
            (token, expires_at, user_id),
        )
        conn.commit()
        conn.close()
        return {
            "ok": True,
            "message": "註冊成功",
            "needs_verification": False,
            "user": {
                "id": user_id, "name": name, "email": email, "role": "user",
                "token": token, "token_expires_at": expires_at,
            },
        }


# 登入使用者，依照 users 表中的 role 分成 admin 與 user。
@app.post("/api/auth/login")
async def login_user(body: LoginRequest, request: Request):
    # 蜜罐 + CAPTCHA
    if body.hp:
        return {"ok": False, "message": "請求無效"}
    if not _verify_challenge(body.captcha_id, body.captcha_answer):
        return {"ok": False, "message": "驗證碼錯誤，請重新取得"}
    email    = body.email.strip()
    password = body.password.strip()

    # 暴力破解防護（DB 版，跨 Worker 共用）
    is_locked, lock_msg = _is_login_locked_db(email)
    if is_locked:
        return {"ok": False, "message": lock_msg}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()

    if row is None or not verify_password(password, row[3]):
        conn.close()
        remaining = _record_login_failure_db(email)
        if remaining == 0:
            logger.warning(f"[LOGIN LOCKED] email={email}")
            return {"ok": False, "message": f"登入失敗次數過多，請 {_LOCKOUT_MINS} 分鐘後再試"}
        logger.warning(f"[LOGIN FAIL] email={email} remaining={remaining}")
        return {"ok": False, "message": f"帳號或密碼錯誤（還剩 {remaining} 次機會）"}

    # 登入成功：清除失敗紀錄（DB 版）
    _clear_login_attempts_db(email)

    # 停用帳號無法登入
    if len(row) > 7 and row[7]:
        conn.close()
        logger.warning(f"[LOGIN BANNED] email={email}")
        return {"ok": False, "message": "此帳號已被停用，如有疑問請聯絡客服"}

    # 信箱未驗證的帳號無法登入（需先點擊驗證信中的連結）
    email_verified = row[8] if len(row) > 8 else 1
    if not email_verified:
        conn.close()
        logger.warning(f"[LOGIN UNVERIFIED] email={email}")
        return {"ok": False, "message": "請先完成信箱驗證，請查收你的信箱並點擊驗證連結"}

    token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
    cursor.execute(
        "UPDATE users SET token = ?, token_expires_at = ? WHERE id = ?",
        (token, expires_at, row[0]),
    )
    conn.commit()
    conn.close()

    user = row_to_user(row)
    user["token"] = token
    user["token_expires_at"] = expires_at
    logger.info(f"[LOGIN] email={email} role={user['role']}")
    return {"ok": True, "message": "登入成功", "user": user}


# 建立一筆預約資料並存入資料庫。
@app.post("/api/bookings")
async def create_booking(body: BookingRequest, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "請先登入"}

    space_id   = body.space_id
    date       = body.date
    start_time = body.start_time
    end_time   = body.end_time

    if not start_time or not end_time or start_time >= end_time:
        return {"ok": False, "message": "結束時間必須晚於開始時間"}

    # 後端也驗證日期不能是過去（防止繞過前端 min 限制直接打 API）
    if date and date < dt_date.today().isoformat():
        return {"ok": False, "message": "不能預約過去的日期"}

    purpose = body.purpose or ""
    if len(str(purpose)) > 500:
        return {"ok": False, "message": "使用目的不能超過 500 個字元"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id FROM bookings
        WHERE space_id = ? AND date = ?
        AND status IN ('待確認', '已確認')
        AND end_time > ? AND start_time < ?
        """,
        (space_id, date, start_time, end_time),
    )
    if cursor.fetchone():
        conn.close()
        return {"ok": False, "message": "此時段已有預約，請選擇其他時間"}

    cursor.execute(
        """
        INSERT INTO bookings (
            space_id, space_name, date, start_time, end_time, purpose, status, user_email
        )
        VALUES (?, ?, ?, ?, ?, ?, '待確認', ?)
        """,
        (
            space_id,
            body.space_name,
            date,
            start_time,
            end_time,
            body.purpose,
            requester["email"],
        ),
    )
    new_id = cursor.lastrowid
    logger.info(f"[BOOKING CREATED] id={new_id} space_id={space_id} user={requester['email']} date={date}")
    # 取得場地主 Email 以便通知。
    cursor.execute("SELECT owner_email FROM spaces WHERE id = ?", (space_id,))
    owner_row = cursor.fetchone()
    conn.commit()
    conn.close()

    space_name = body.space_name or ""
    send_email(
        requester["email"],
        f"【Oasis】預約申請已送出：{space_name}",
        f"<p>你好，你的預約申請已送出，等待場地主確認。</p>"
        f"<p>空間：{space_name}<br>日期：{date}<br>時間：{start_time} – {end_time}</p>"
        f"<p><a href='{SITE_URL}/user'>前往使用者中心</a></p>",
    )
    if owner_row and owner_row[0]:
        send_email(
            owner_row[0],
            f"【Oasis】你的空間收到新預約申請：{space_name}",
            f"<p>有人預約了你的空間「{space_name}」，請盡快確認。</p>"
            f"<p>日期：{date}<br>時間：{start_time} – {end_time}<br>預約人：{requester['email']}</p>"
            f"<p><a href='{SITE_URL}/user'>前往使用者中心確認</a></p>",
        )

    booking = {
        "id": new_id,
        "space_id": space_id,
        "space_name": space_name,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "purpose": body.purpose,
        "status": "待確認",
        "user_email": requester["email"],
    }
    return {"ok": True, "message": "預約申請已送出！", "data": booking}


# 將指定預約狀態更新為已確認，給場地主在使用者中心確認申請使用。
@app.post("/api/bookings/{booking_id}/confirm")
async def confirm_booking(booking_id: int, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT spaces.owner_email FROM bookings
        JOIN spaces ON bookings.space_id = spaces.id
        WHERE bookings.id = ?
        """,
        (booking_id,),
    )
    owner_row = cursor.fetchone()
    if not owner_row or owner_row[0] != requester["email"]:
        conn.close()
        return {"ok": False, "message": "未授權"}

    cursor.execute(
        "UPDATE bookings SET status = '已確認' WHERE id = ?",
        (booking_id,),
    )
    conn.commit()
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"ok": False, "message": "找不到此預約"}
    b = row_to_booking(row)
    send_email(
        b["user_email"],
        f"【Oasis】預約已確認：{b['space_name']}",
        f"<p>你好，你的預約已被場地主確認！</p>"
        f"<p>空間：{b['space_name']}<br>日期：{b['date']}<br>時間：{b['start_time']} – {b['end_time']}</p>"
        f"<p><a href='{SITE_URL}/user'>前往使用者中心</a></p>",
    )
    return {"ok": True, "message": "預約狀態已更新為已確認！", "data": b}


# 取消指定預約，只有「待確認」且本人的預約可以取消。
@app.post("/api/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: int, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "message": "找不到此預約"}

    booking = row_to_booking(row)
    if booking["user_email"] != requester["email"]:
        conn.close()
        return {"ok": False, "message": "未授權"}

    if booking["status"] not in ("待確認", "已確認"):
        conn.close()
        return {"ok": False, "message": "只有「待確認」或「已確認」狀態的預約才能取消"}

    # 已確認的預約需在開始時間 24 小時前才能取消。
    if booking["status"] == "已確認":
        booking_dt = datetime.fromisoformat(f"{booking['date']} {booking['start_time']}")
        if datetime.now() + timedelta(hours=24) > booking_dt:
            conn.close()
            return {"ok": False, "message": "已確認的預約須在開始時間 24 小時前取消，如需協助請聯絡我們"}

    # 取得場地主 Email，以便取消後通知
    cursor.execute("SELECT owner_email FROM spaces WHERE id = ?", (booking["space_id"],))
    owner_row = cursor.fetchone()

    cursor.execute("UPDATE bookings SET status = '已取消' WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

    # 通知場地主：有人取消了預約
    if owner_row and owner_row[0]:
        send_email(
            owner_row[0],
            f"【Oasis】預約已取消：{booking['space_name']}",
            f"<p>預約人（{booking.get('user_email', '未知')}）已取消對你的空間「{booking['space_name']}」的預約。</p>"
            f"<p>日期：{booking['date']}<br>時間：{booking['start_time']} – {booking['end_time']}</p>"
            f"<p>該時段現已重新開放，其他使用者可以再次預約。</p>"
            f"<p><a href='{SITE_URL}/user'>前往使用者中心查看</a></p>",
        )
    return {"ok": True, "message": "預約已取消"}


# 查詢指定日期的已佔用時段，供預約頁顯示可用性。
@app.get("/api/spaces/{space_id}/availability")
def get_space_availability(space_id: int, date: str = ""):
    if not date:
        return {"ok": True, "data": []}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT start_time, end_time FROM bookings
        WHERE space_id = ? AND date = ? AND status IN ('待確認', '已確認')
        ORDER BY start_time
        """,
        (space_id, date),
    )
    rows = cursor.fetchall()
    conn.close()
    return {"ok": True, "data": [{"start_time": r[0], "end_time": r[1]} for r in rows]}


# 更新使用者個人資料（名稱與密碼），需驗證 token 身份。
@app.patch("/api/user/profile")
async def update_profile(body: UpdateProfileRequest, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}

    name             = (body.name or "").strip()
    current_password = body.current_password or ""
    new_password     = (body.new_password or "").strip()

    conn = _get_conn()
    cursor = conn.cursor()
    updates, params = [], []
    refreshed_token  = None   # 密碼更換時產生新 token，讓其他裝置舊 token 失效
    refreshed_expiry = None

    if name:
        updates.append("name = ?")
        params.append(name)

    if new_password:
        if len(new_password) < 6:
            conn.close()
            return {"ok": False, "message": "新密碼至少需要 6 個字元"}
        cursor.execute("SELECT password FROM users WHERE email = ?", (requester["email"],))
        pw_row = cursor.fetchone()
        if not pw_row or not verify_password(current_password, pw_row[0]):
            conn.close()
            return {"ok": False, "message": "目前密碼錯誤"}
        # 密碼更換：同時換發新 token，其他裝置持有的舊 token 立即失效
        refreshed_token  = secrets.token_hex(32)
        refreshed_expiry = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
        updates.extend(["password = ?", "token = ?", "token_expires_at = ?"])
        params.extend([hash_password(new_password), refreshed_token, refreshed_expiry])

    if not updates:
        conn.close()
        return {"ok": False, "message": "沒有需要更新的資料"}

    params.append(requester["email"])
    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE email = ?", params)
    conn.commit()
    conn.close()

    resp: dict = {"ok": True, "message": "個人資料已更新！"}
    if refreshed_token:
        # 回傳新 token 讓當前裝置同步更新，不需要重新登入
        resp["token"]            = refreshed_token
        resp["token_expires_at"] = refreshed_expiry
    return resp


# 使用者為已完成的預約空間評分（1–5 星），自動更新空間平均評分。
@app.post("/api/spaces/{space_id}/rate")
async def rate_space(space_id: int, body: RateSpaceRequest, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}

    score = body.score
    if score is None or not (1 <= int(score) <= 5):
        return {"ok": False, "message": "評分需在 1 到 5 之間"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM bookings WHERE space_id = ? AND user_email = ? AND status = '已完成'",
        (space_id, requester["email"]),
    )
    if not cursor.fetchone():
        conn.close()
        return {"ok": False, "message": "只有完成過預約的使用者才能評分"}

    comment = (body.comment or "").strip()
    cursor.execute(
        "INSERT OR REPLACE INTO ratings (space_id, user_email, score, comment) VALUES (?, ?, ?, ?)",
        (space_id, requester["email"], int(score), comment or None),
    )
    cursor.execute("SELECT AVG(score) FROM ratings WHERE space_id = ?", (space_id,))
    avg = round(cursor.fetchone()[0], 1)
    cursor.execute("UPDATE spaces SET rating = ? WHERE id = ?", (avg, space_id))
    conn.commit()
    conn.close()
    return {"ok": True, "message": f"已評 {score} 顆星，此空間目前平均 ★ {avg}"}


# 拒絕預約，管理員或場地主皆可拒絕。
@app.post("/api/bookings/{booking_id}/reject")
async def reject_booking(booking_id: int, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}

    conn = _get_conn()
    cursor = conn.cursor()

    if requester["role"] != "admin":
        cursor.execute(
            """
            SELECT spaces.owner_email FROM bookings
            JOIN spaces ON bookings.space_id = spaces.id
            WHERE bookings.id = ?
            """,
            (booking_id,),
        )
        owner_row = cursor.fetchone()
        if not owner_row or owner_row[0] != requester["email"]:
            conn.close()
            return {"ok": False, "message": "未授權"}

    cursor.execute("UPDATE bookings SET status = '已拒絕' WHERE id = ?", (booking_id,))
    conn.commit()
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {"ok": False, "message": "找不到此預約"}
    b = row_to_booking(row)
    if b.get("user_email"):
        send_email(
            b["user_email"],
            f"【Oasis】預約申請未通過：{b['space_name']}",
            f"<p>很抱歉，你對「{b['space_name']}」的預約申請未獲場地主確認。</p>"
            f"<p>日期：{b['date']}<br>時間：{b['start_time']} – {b['end_time']}</p>"
            f"<p>歡迎繼續探索其他空間：<a href='{SITE_URL}/explore'>瀏覽空間</a></p>",
        )
    return {"ok": True, "message": "預約已拒絕", "data": b}


# 更新空間欄位；管理員可改任意空間，場地主只能改自己的。
@app.patch("/api/spaces/{space_id}")
async def update_space(space_id: int, body: UpdateSpaceBody, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "未授權"}

    conn = _get_conn()
    cursor = conn.cursor()
    if requester["role"] != "admin":
        cursor.execute("SELECT owner_email FROM spaces WHERE id = ?", (space_id,))
        owner_row = cursor.fetchone()
        if not owner_row or owner_row[0] != requester["email"]:
            conn.close()
            return {"ok": False, "message": "未授權"}

    body_dict  = body.model_dump(exclude_none=True)
    updatable  = ["name", "city", "district", "address", "type", "price_per_hour", "capacity", "description", "lat", "lng"]
    updates, params = [], []

    for field in updatable:
        if field in body_dict:
            updates.append(f"{field} = ?")
            params.append(body_dict[field])

    if body.equipment is not None:
        eq = body.equipment
        updates.append("equipment = ?")
        params.append(",".join(eq) if isinstance(eq, list) else str(eq))

    # 圖片更新：驗證、存檔、更新 image 與 images 欄位，並清理被移除的舊圖
    old_image_urls: list = []
    new_saved_imgs: list = []
    if body.images is not None:
        new_imgs_raw = body.images[:5]   # 上限 5 張
        for img in new_imgs_raw:
            if not isinstance(img, str):
                continue
            if len(img) > 2_800_000:
                conn.close()
                return {"ok": False, "message": "每張圖片大小不能超過 2MB"}
            if img.startswith("data:") and not _validate_image_format(img):
                conn.close()
                return {"ok": False, "message": "圖片格式不支援，請上傳 JPEG、PNG、GIF 或 WebP"}
        # 先取得舊圖路徑，以便更新成功後清理磁碟
        cursor.execute("SELECT image, images FROM spaces WHERE id = ?", (space_id,))
        old_row = cursor.fetchone()
        if old_row:
            old_list       = json.loads(old_row[1]) if old_row[1] else []
            old_image_urls = list({old_row[0]} | set(old_list)) if old_row[0] else old_list
        new_saved_imgs = [_save_image(img) for img in new_imgs_raw]
        first_img = new_saved_imgs[0] if new_saved_imgs else None
        if first_img:
            updates.append("image = ?")
            params.append(first_img)
        updates.append("images = ?")
        params.append(json.dumps(new_saved_imgs))

    if not updates:
        conn.close()
        return {"ok": False, "message": "沒有需要更新的欄位"}

    params.append(space_id)
    cursor.execute(f"UPDATE spaces SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    cursor.execute("SELECT * FROM spaces WHERE id = ?", (space_id,))
    row = cursor.fetchone()
    conn.close()

    # 清理被替換掉的舊圖檔（更新成功後才執行，避免失敗時誤刪）
    if new_saved_imgs:
        new_set = set(new_saved_imgs)
        for old_url in old_image_urls:
            if old_url not in new_set:
                _delete_image_file(old_url)

    if row is None:
        return {"ok": False, "message": "找不到此空間"}
    return {"ok": True, "message": "空間資料已更新！", "data": row_to_space(row)}


# 管理員查看全部拼場列表（含所有狀態）。
@app.get("/api/admin/co-rentals")
def admin_list_co_rentals(request: Request, page: int = 1, per_page: int = 15, search: str = ""):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    per_page = max(1, min(per_page, 100))
    conn   = _get_conn()
    cursor = conn.cursor()
    cond_parts: list = []
    params: list = []
    if search:
        cond_parts.append("(s.name LIKE ? OR cr.organizer_email LIKE ? OR cr.purpose LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    where = ("WHERE " + " AND ".join(cond_parts)) if cond_parts else ""
    cursor.execute(
        f"SELECT COUNT(*) FROM co_rentals cr LEFT JOIN spaces s ON cr.space_id = s.id {where}",
        params,
    )
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    cursor.execute(
        f"""
        SELECT cr.id, cr.space_id, cr.date, cr.start_time, cr.end_time,
               cr.total_slots, cr.filled_slots, cr.price_per_slot,
               cr.purpose, cr.organizer_email, cr.status, cr.created_at,
               s.name, s.city, s.type, s.image
        FROM co_rentals cr
        LEFT JOIN spaces s ON cr.space_id = s.id
        {where}
        ORDER BY cr.created_at DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, (page - 1) * per_page],
    )
    rows = cursor.fetchall()
    conn.close()
    return {
        "ok": True,
        "data": [_row_to_co_rental(r, r[12] or "", r[13] or "", r[14] or "", r[15] or "") for r in rows],
        "total": total, "page": page, "per_page": per_page, "total_pages": total_pages,
    }


# 管理員儀表板專用統計，單一 API 一次取得所有數字。
@app.get("/api/admin/stats")
def get_admin_stats(request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM spaces")
    total_spaces = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM spaces WHERE status = '待確認'")
    pending_spaces = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM spaces WHERE status = '已確認'")
    confirmed_spaces = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM bookings")
    total_bookings = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM contacts")
    total_contacts = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM co_rentals WHERE status = 'open'")
    open_co_rentals = cursor.fetchone()[0]
    conn.close()
    return {
        "ok": True,
        "total_spaces": total_spaces,
        "pending_spaces": pending_spaces,
        "confirmed_spaces": confirmed_spaces,
        "total_bookings": total_bookings,
        "total_contacts": total_contacts,
        "total_users": total_users,
        "open_co_rentals": open_co_rentals,
    }


# 取得所有會員列表，給管理員中心顯示，支援分頁。
@app.get("/api/admin/users")
def get_admin_users(request: Request, page: int = 1, per_page: int = 15, search: str = ""):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    per_page = max(1, min(per_page, 100))
    conn = _get_conn()
    cursor = conn.cursor()
    cond, cond_params = _build_search_condition(search, ["name", "email"])
    where = f"WHERE {cond}" if cond else ""
    cursor.execute(f"SELECT COUNT(*) FROM users {where}", cond_params)
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    cursor.execute(
        f"SELECT id, name, email, role, COALESCE(banned, 0), COALESCE(plan,'free'), plan_expires_at"
        f" FROM users {where} ORDER BY id ASC LIMIT ? OFFSET ?",
        cond_params + [per_page, (page - 1) * per_page],
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "ok": True,
        "data": [
            {
                "id": r[0], "name": r[1], "email": r[2],
                "role": r[3], "banned": bool(r[4]),
                "plan": r[5] or "free",
                "plan_expires_at": r[6],
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# 接收空間上架資料並存入資料庫，讓探索頁可以看到新增空間。
@app.post("/api/spaces")
async def create_space(body: SpaceRequest, request: Request):
    requester = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not requester:
        return {"ok": False, "message": "請先登入才能上架空間"}

    # ── 訂閱方案限制：免費版最多 1 個空間 ───────────────────────────────────────
    _disable_limit = os.environ.get("DISABLE_PLAN_LIMIT", "")
    if requester["role"] != "admin" and requester.get("plan", "free") == "free" and not _disable_limit:
        _cc = _get_conn()
        _cur = _cc.cursor()
        _cur.execute(
            "SELECT COUNT(*) FROM spaces WHERE owner_email = ? AND status != '已拒絕'",
            (requester["email"],),
        )
        _count = _cur.fetchone()[0]
        _cc.close()
        if _count >= 1:
            return {
                "ok": False,
                "message": "免費方案只能上架 1 個空間，升級為專業方案即可無限上架。",
                "upgrade_required": True,
            }

    # ── 欄位長度限制 ──────────────────────────────────────────────────────────
    field_limits = [
        ("name",        body.name,        100, "空間名稱不能超過 100 個字元"),
        ("city",        body.city,         50, "城市名稱不能超過 50 個字元"),
        ("district",    body.district,     50, "行政區不能超過 50 個字元"),
        ("address",     body.address,     200, "地址不能超過 200 個字元"),
        ("description", body.description, 2000, "空間介紹不能超過 2000 個字元"),
    ]
    for field, value, limit, msg in field_limits:
        if value and len(str(value)) > limit:
            logger.warning(f"[FIELD TOO LONG] field={field} len={len(str(value))} user={requester['email']}")
            return {"ok": False, "message": msg}

    equipment = body.equipment or []
    equipment_text = ",".join(equipment) if isinstance(equipment, list) else str(equipment)
    if len(equipment_text) > 500:
        return {"ok": False, "message": "設備清單太長，請精簡內容（上限 500 字元）"}

    # 數值欄位驗證
    try:
        price = int(body.price_per_hour or 0)
        if price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return {"ok": False, "message": "每小時價格必須是大於 0 的整數"}
    try:
        capacity = int(body.capacity or 0)
        if capacity <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return {"ok": False, "message": "容納人數必須是大於 0 的整數"}

    images = body.images or []
    if not images and body.image:
        images = [body.image]

    # 後端驗證圖片數量、大小與格式，防止繞過前端限制直接打 API。
    if len(images) > 5:
        return {"ok": False, "message": "最多只能上傳 5 張圖片"}
    for img in images:
        if not isinstance(img, str):
            continue
        # base64 後字串長度約為原始大小的 4/3，2MB 對應約 2,800,000 字元。
        if len(img) > 2_800_000:
            return {"ok": False, "message": "每張圖片大小不能超過 2MB"}
        # 真正驗證圖片格式（檢查魔術碼），防止上傳非圖片檔案
        if img.startswith("data:") and not _validate_image_format(img):
            logger.warning(f"[IMAGE INVALID] user={requester['email']}")
            return {"ok": False, "message": "圖片格式不支援，請上傳 JPEG、PNG、GIF 或 WebP"}
    # 將 base64 圖片解碼後存入磁碟，DB 只存 URL 路徑，大幅降低 DB 體積與查詢流量。
    images = [_save_image(img) for img in images]
    first_image = images[0] if images else f"https://picsum.photos/seed/space-{body.name or 'new'}/400/300"
    images_json = json.dumps(images)

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO spaces (
            name, city, district, address, type, price_per_hour,
            capacity, rating, image, equipment, description, status, owner_email, images,
            lat, lng
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            body.name,
            body.city,
            body.district,
            body.address or f"{body.city}{body.district}",
            body.type,
            body.price_per_hour,
            body.capacity,
            0.0,
            first_image,
            equipment_text,
            body.description,
            "待確認",
            requester["email"],   # 使用 token 驗證後的 email，防止偽造 owner_email
            images_json,
            body.lat,
            body.lng,
        ),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"[SPACE CREATED] id={new_id} name={body.name} owner={requester['email']}")

    new_space = {
        "id": new_id,
        "name": body.name,
        "city": body.city,
        "district": body.district,
        "type": body.type,
        "price_per_hour": body.price_per_hour,
        "capacity": body.capacity,
        "rating": 0.0,
        "image": first_image,
        "equipment": equipment,
        "description": body.description,
        "status": "待確認",
        "owner_email": requester["email"],
        "images": images,
    }
    return {"ok": True, "message": "空間上架申請已送出，等待管理員確認後才會公開！", "data": new_space}


# 取得所有聯絡表單訊息，給管理員中心顯示，支援分頁。
@app.get("/api/contacts")
def get_contacts(request: Request, page: int = 1, per_page: int = 15, search: str = ""):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    per_page = max(1, min(per_page, 100))
    conn = _get_conn()
    cursor = conn.cursor()
    cond, cond_params = _build_search_condition(search, ["name", "email", "message"])
    where = f"WHERE {cond}" if cond else ""
    cursor.execute(f"SELECT COUNT(*) FROM contacts {where}", cond_params)
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    cursor.execute(
        f"SELECT * FROM contacts {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        cond_params + [per_page, (page - 1) * per_page],
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "ok": True,
        "data": [row_to_contact(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


# 刪除指定聯絡訊息，給管理員中心清理留言使用。
@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        return {"ok": False, "message": "找不到此訊息"}

    cursor.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "message": "訊息已刪除！", "data": row_to_contact(row)}


# 接收聯絡表單資料，存入資料庫並回傳感謝訊息。
@app.post("/api/contact")
async def create_contact_message(body: ContactRequest, request: Request):
    # 蜜罐 + CAPTCHA
    if body.hp:
        return {"ok": False, "message": "請求無效"}
    if not _verify_challenge(body.captcha_id, body.captcha_answer):
        return {"ok": False, "message": "驗證碼錯誤，請重新取得"}
    # 速率限制（DB 版，跨 Worker 共用）
    ip = request.client.host if request.client else "unknown"
    if _check_rate_limit_db(f"contact:{ip}", _CONTACT_WINDOW, _CONTACT_MAX):
        logger.warning(f"[RATE LIMIT] ip={ip} endpoint=contact")
        return {"ok": False, "message": "發送太頻繁，請稍後再試"}

    # 欄位長度限制
    contact_name    = str(body.name or "")
    contact_email   = str(body.email or "")
    contact_message = str(body.message or "")
    if len(contact_name) > 100:
        return {"ok": False, "message": "姓名不能超過 100 個字元"}
    if len(contact_email) > 200:
        return {"ok": False, "message": "Email 不能超過 200 個字元"}
    if len(contact_message) > 2000:
        return {"ok": False, "message": "訊息不能超過 2000 個字元"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO contacts (name, email, message)
        VALUES (?, ?, ?)
        """,
        (contact_name, contact_email, contact_message),
    )
    conn.commit()
    conn.close()
    logger.info(f"[CONTACT] name={contact_name} email={contact_email} ip={ip}")

    return {"ok": True, "message": "感謝你的來信"}


# 取得目前登入使用者對指定空間的評分（用於評分表單預填）。
@app.get("/api/spaces/{space_id}/my-rating")
def get_my_rating(space_id: int, request: Request):
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": True, "data": None, "can_rate": False}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT score, comment FROM ratings WHERE space_id = ? AND user_email = ?",
        (space_id, user["email"]),
    )
    row = cursor.fetchone()
    # 只有「已完成」的預約使用者才能評分（或已經有評分紀錄的使用者可以修改）
    cursor.execute(
        "SELECT id FROM bookings WHERE space_id = ? AND user_email = ? AND status = '已完成'",
        (space_id, user["email"]),
    )
    has_completed = bool(cursor.fetchone())
    conn.close()
    return {
        "ok": True,
        "data": {"score": row[0], "comment": row[1] or ""} if row else None,
        "can_rate": has_completed or bool(row),   # 已評分過的人也可以修改
    }


# 取得空間的所有評論，公開顯示（隱去 Email 後半段保護隱私）。
@app.get("/api/spaces/{space_id}/reviews")
def get_space_reviews(space_id: int):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_email, score, comment FROM ratings WHERE space_id = ? ORDER BY id DESC",
        (space_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    def mask(email: str) -> str:
        parts = email.split("@")
        name = parts[0]
        hidden = name[:2] + "***" if len(name) > 2 else name
        return f"{hidden}@{parts[1]}" if len(parts) == 2 else email

    return {"ok": True, "data": [{"user": mask(r[0]), "score": r[1], "comment": r[2]} for r in rows]}


# 忘記密碼：產生一次性重設連結並寄送到使用者信箱。
@app.post("/api/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    # 蜜罐 + CAPTCHA
    if body.hp:
        return {"ok": False, "message": "請求無效"}
    if not _verify_challenge(body.captcha_id, body.captcha_answer):
        return {"ok": False, "message": "驗證碼錯誤，請重新取得"}
    # 速率限制（DB 版，跨 Worker 共用）
    ip = request.client.host if request.client else "unknown"
    if _check_rate_limit_db(f"forgot:{ip}", _FORGOT_WINDOW, _FORGOT_MAX):
        logger.warning(f"[RATE LIMIT] ip={ip} endpoint=forgot-password")
        return {"ok": False, "message": "申請太頻繁，請稍後再試"}

    email = body.email.strip().lower()
    if not email:
        return {"ok": False, "message": "請輸入信箱"}

    conn = _get_conn()
    cursor = conn.cursor()
    # 順手清除已過期或已使用的舊重設 token，避免 password_resets 無限增長
    cursor.execute(
        "DELETE FROM password_resets WHERE expires_at < ? OR used = 1",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if not cursor.fetchone():
        conn.commit()
        conn.close()
        # 不透露帳號是否存在，統一回成功訊息（防止帳號枚舉）。
        return {"ok": True, "message": "若此信箱已註冊，重設連結將在幾分鐘內寄出"}

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    cursor.execute(
        "INSERT INTO password_resets (email, token, expires_at) VALUES (?, ?, ?)",
        (email, token, expires_at),
    )
    conn.commit()
    conn.close()

    reset_url = f"{SITE_URL}/reset-password?token={token}"
    send_email(
        email,
        "【Oasis】密碼重設連結",
        f"<p>你好，請點擊下方連結重設密碼（連結 1 小時內有效）：</p>"
        f"<p><a href='{reset_url}'>{reset_url}</a></p>"
        f"<p>若你沒有申請重設，請忽略此郵件。</p>",
    )
    return {"ok": True, "message": "若此信箱已註冊，重設連結將在幾分鐘內寄出"}


# 重設密碼：驗證 token 後更新密碼。
@app.post("/api/auth/reset-password")
async def reset_password(body: ResetPasswordRequest, request: Request):
    token        = body.token.strip()
    new_password = body.new_password.strip()

    if not token or not new_password:
        return {"ok": False, "message": "缺少必要欄位"}
    if len(new_password) < 6:
        return {"ok": False, "message": "新密碼至少需要 6 個字元"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT email, expires_at, used FROM password_resets WHERE token = ?", (token,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"ok": False, "message": "無效的重設連結"}

    email, expires_at, used = row
    if used:
        conn.close()
        return {"ok": False, "message": "此重設連結已使用過"}
    if datetime.now() > datetime.fromisoformat(expires_at):
        conn.close()
        return {"ok": False, "message": "重設連結已過期，請重新申請"}

    cursor.execute(
        # token = NULL 同時讓所有已登入裝置的舊 token 全數失效，
        # 防止攻擊者在取得 token 後再利用密碼重設來留下持久存取權。
        "UPDATE users SET password = ?, token = NULL, token_expires_at = NULL WHERE email = ?",
        (hash_password(new_password), email),
    )
    cursor.execute(
        "UPDATE password_resets SET used = 1 WHERE token = ?", (token,)
    )
    conn.commit()
    conn.close()
    logger.info(f"[PASSWORD RESET] email={email} — all tokens invalidated")
    return {"ok": True, "message": "密碼已成功重設，請重新登入"}


# 管理員停用會員帳號（被停用者無法登入也無法呼叫需驗證的 API）
@app.post("/api/admin/users/{user_id}/ban")
async def ban_user(user_id: int, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "message": "找不到此使用者"}
    if row[1] == "admin":
        conn.close()
        return {"ok": False, "message": "不能停用管理員帳號"}
    cursor.execute("UPDATE users SET banned = 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "帳號已停用"}


# 管理員解除停用
@app.post("/api/admin/users/{user_id}/unban")
async def unban_user(user_id: int, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET banned = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "帳號已恢復"}


# 管理員強制取消任何預約（糾紛處理用），並自動寄通知給預約人
@app.post("/api/admin/bookings/{booking_id}/cancel")
async def admin_cancel_booking(booking_id: int, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "message": "找不到此預約"}
    b = row_to_booking(row)
    if b["status"] in ("已完成", "已取消", "已拒絕"):
        conn.close()
        return {"ok": False, "message": "此預約已結束，無法再取消"}
    cursor.execute("UPDATE bookings SET status = '已取消' WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    if b.get("user_email"):
        send_email(
            b["user_email"],
            f"【Oasis】預約已由管理員取消：{b['space_name']}",
            f"<p>你好，你對「{b['space_name']}」的預約已由平台管理員取消。</p>"
            f"<p>日期：{b['date']}<br>時間：{b['start_time']} – {b['end_time']}</p>"
            f"<p>如有疑問，歡迎 <a href='{SITE_URL}/contact'>聯絡我們</a>。</p>",
        )
    return {"ok": True, "message": "預約已強制取消", "data": b}


# 取得所有上架中的公告（公開，無需驗證）
@app.get("/api/announcements")
def get_announcements():
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, title, content, created_at FROM announcements WHERE is_active = 1 ORDER BY id DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return {"ok": True, "data": [{"id": r[0], "title": r[1], "content": r[2], "created_at": r[3]} for r in rows]}


# 管理員發布公告
@app.post("/api/admin/announcements")
async def create_announcement(body: AnnouncementRequest, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    title   = body.title.strip()
    content = body.content.strip()
    if not title:
        return {"ok": False, "message": "請填寫公告標題"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO announcements (title, content) VALUES (?, ?)", (title, content))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "ok": True, "message": "公告已發布",
        "data": {"id": new_id, "title": title, "content": content,
                 "created_at": datetime.now().isoformat(timespec="seconds")},
    }


# 管理員下架公告（軟刪除，is_active = 0）
@app.delete("/api/admin/announcements/{announcement_id}")
def delete_announcement(announcement_id: int, request: Request):
    admin = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not admin or admin["role"] != "admin":
        return {"ok": False, "message": "未授權"}
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE announcements SET is_active = 0 WHERE id = ?", (announcement_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "message": "公告已下架"}


# ── 拼場功能（Co-Rental）：多人合租同一時段，分攤場地費用。────────────────────────

def _row_to_co_rental(row, space_name: str = "", space_city: str = "",
                      space_type: str = "", space_image: str = "") -> dict:
    return {
        "id": row[0],
        "space_id": row[1],
        "space_name": space_name,
        "space_city": space_city,
        "space_type": space_type,
        "space_image": space_image,
        "date": row[2],
        "start_time": row[3],
        "end_time": row[4],
        "total_slots": row[5],
        "filled_slots": row[6],
        "price_per_slot": row[7],
        "purpose": row[8] or "",
        "organizer_email": row[9],
        "status": row[10],
        "created_at": row[11] if len(row) > 11 else "",
        "available_slots": row[5] - row[6],
    }


@app.get("/api/co-rentals")
def list_co_rentals(city: str = "", date: str = ""):
    """列出所有開放中的拼場活動（today 以後），可依城市/日期篩選。"""
    today = dt_date.today().isoformat()
    conn = _get_conn()
    cursor = conn.cursor()
    conditions = ["cr.status = 'open'", "cr.date >= ?"]
    params: list = [today]
    if city:
        conditions.append("s.city = ?")
        params.append(city)
    if date:
        conditions.append("cr.date = ?")
        params.append(date)
    where = " AND ".join(conditions)
    cursor.execute(
        f"""
        SELECT cr.id, cr.space_id, cr.date, cr.start_time, cr.end_time,
               cr.total_slots, cr.filled_slots, cr.price_per_slot,
               cr.purpose, cr.organizer_email, cr.status, cr.created_at,
               s.name, s.city, s.type, s.image
        FROM co_rentals cr
        LEFT JOIN spaces s ON cr.space_id = s.id
        WHERE {where}
        ORDER BY cr.date ASC, cr.created_at DESC
        """,
        params,
    )
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = {
            "id": r[0], "space_id": r[1], "date": r[2],
            "start_time": r[3], "end_time": r[4],
            "total_slots": r[5], "filled_slots": r[6],
            "price_per_slot": r[7], "purpose": r[8] or "",
            "organizer_email": r[9], "status": r[10], "created_at": r[11],
            "space_name": r[12] or "未知空間",
            "space_city": r[13] or "",
            "space_type": r[14] or "",
            "space_image": r[15] or "",
            "available_slots": r[5] - r[6],
        }
        result.append(d)
    return {"ok": True, "data": result}


@app.post("/api/co-rentals")
def create_co_rental(body: CoRentalRequest, request: Request):
    """建立拼場活動，需登入。發起人自動佔一個名額。"""
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": False, "message": "請先登入才能發起拼場"}

    if not body.space_id:
        return {"ok": False, "message": "請選擇要拼場的空間"}
    if not body.date or not body.start_time or not body.end_time:
        return {"ok": False, "message": "請填寫拼場日期與時間"}
    if body.total_slots < 2 or body.total_slots > 10:
        return {"ok": False, "message": "拼場名額須為 2~10 人"}
    if body.price_per_slot <= 0:
        return {"ok": False, "message": "每人費用必須大於 0"}

    # 確認空間存在
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM spaces WHERE id = ? AND status = '已確認'", (body.space_id,))
    if not cursor.fetchone():
        conn.close()
        return {"ok": False, "message": "找不到此空間或空間尚未公開"}

    cursor.execute(
        """
        INSERT INTO co_rentals (space_id, date, start_time, end_time,
            total_slots, filled_slots, price_per_slot, purpose, organizer_email, status)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'open')
        """,
        (body.space_id, body.date, body.start_time, body.end_time,
         body.total_slots, body.price_per_slot, body.purpose, user["email"]),
    )
    new_id = cursor.lastrowid
    # 發起人自動成為第一位成員
    cursor.execute(
        "INSERT INTO co_rental_members (co_rental_id, user_email) VALUES (?, ?)",
        (new_id, user["email"]),
    )
    conn.commit()
    conn.close()
    logger.info(f"[CO-RENTAL CREATED] id={new_id} space={body.space_id} organizer={user['email']}")
    return {"ok": True, "message": "拼場活動已建立！等待其他人加入。", "id": new_id}


@app.post("/api/co-rentals/{co_rental_id}/join")
def join_co_rental(co_rental_id: int, request: Request):
    """加入拼場活動，需登入。加入後 filled_slots +1，滿員後自動關閉。"""
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": False, "message": "請先登入才能加入拼場"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, total_slots, filled_slots, organizer_email, status FROM co_rentals WHERE id = ?",
        (co_rental_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "message": "找不到此拼場活動"}
    _, total_slots, filled_slots, organizer_email, status = row

    if status != "open":
        conn.close()
        return {"ok": False, "message": "此拼場已結束或名額已滿"}
    if filled_slots >= total_slots:
        conn.close()
        return {"ok": False, "message": "名額已滿"}

    # 檢查是否已加入
    cursor.execute(
        "SELECT id FROM co_rental_members WHERE co_rental_id = ? AND user_email = ?",
        (co_rental_id, user["email"]),
    )
    if cursor.fetchone():
        conn.close()
        return {"ok": False, "message": "你已經加入此拼場了"}

    new_filled = filled_slots + 1
    new_status = "full" if new_filled >= total_slots else "open"
    cursor.execute(
        "UPDATE co_rentals SET filled_slots = ?, status = ? WHERE id = ?",
        (new_filled, new_status, co_rental_id),
    )
    cursor.execute(
        "INSERT INTO co_rental_members (co_rental_id, user_email) VALUES (?, ?)",
        (co_rental_id, user["email"]),
    )
    conn.commit()
    conn.close()
    msg = "加入拼場成功！名額已滿，請各自完成預約。" if new_status == "full" else "加入拼場成功！等待其他人加入。"
    logger.info(f"[CO-RENTAL JOIN] id={co_rental_id} user={user['email']} filled={new_filled}/{total_slots}")
    return {"ok": True, "message": msg, "status": new_status}


@app.delete("/api/co-rentals/{co_rental_id}")
def cancel_co_rental(co_rental_id: int, request: Request):
    """取消拼場（僅發起人或管理員可操作）。"""
    user = get_user_from_token(request.headers.get("X-Auth-Token", ""))
    if not user:
        return {"ok": False, "message": "請先登入"}

    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT organizer_email, status FROM co_rentals WHERE id = ?", (co_rental_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "message": "找不到此拼場活動"}
    organizer_email, status = row
    # 允許操作：發起人、管理員、或此拼場對應空間的場地主
    is_space_owner = False
    if user["email"] != organizer_email and user["role"] != "admin":
        cursor.execute(
            "SELECT owner_email FROM spaces WHERE id = (SELECT space_id FROM co_rentals WHERE id = ?)",
            (co_rental_id,),
        )
        owner_row = cursor.fetchone()
        if owner_row and owner_row[0] == user["email"]:
            is_space_owner = True
        else:
            conn.close()
            return {"ok": False, "message": "只有發起人或場地主才能取消拼場"}

    if status == "closed":
        conn.close()
        return {"ok": False, "message": "此拼場已關閉"}

    cursor.execute("UPDATE co_rentals SET status = 'closed' WHERE id = ?", (co_rental_id,))
    conn.commit()
    conn.close()
    actor = "場地主" if is_space_owner else ("管理員" if user["role"] == "admin" else "發起人")
    logger.info(f"[CO-RENTAL CANCEL] id={co_rental_id} by={user['email']} role={actor}")
    return {"ok": True, "message": "拼場已關閉"}


# ── 健康檢查：Docker HEALTHCHECK 與 nginx upstream_check 使用。──────────────────
# 只回傳 200 + JSON，不做任何 DB 查詢，確保回應速度極快（< 5ms）。
@app.get("/api/health")
def health_check():
    return {"ok": True, "status": "healthy"}


# ── 數學驗證碼：供登入 / 註冊 / 聯絡 / 忘記密碼頁取得題目。────────────────────────
@app.get("/api/auth/challenge")
def get_challenge():
    """產生並回傳一道隨機加法驗證碼 {id, question}，10 分鐘內有效、一次性使用。"""
    return {"ok": True, "data": _create_challenge()}


# ── SEO：robots.txt 告知爬蟲爬取規則；sitemap.xml 幫助搜尋引擎索引頁面。────────────
@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    content = (
        "User-agent: *\n"
        "Disallow: /api/\n"
        "Disallow: /dashboard\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    pages = [
        ("",            "weekly",  "1.0"),
        ("explore",     "daily",   "0.9"),
        ("recommend",   "weekly",  "0.8"),
        ("co-rental",   "daily",   "0.7"),
        ("contact",     "monthly", "0.5"),
        ("login",       "monthly", "0.3"),
        ("register",    "monthly", "0.3"),
    ]
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{SITE_URL}/{path}</loc>\n"
        f"    <changefreq>{freq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        f"  </url>"
        for path, freq, priority in pages
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


app.mount("/static", StaticFiles(directory="www/static"), name="static")
