"""
pytest 全域設定與共用 fixtures。

重點：環境變數必須在 import main 之前設好，
因為 main.py 在模組層級就呼叫 init_db()，
若此時 SQLITE_DB 還沒設，就會寫到正式 oasis.db。
"""

import os
import sys
import secrets

# ── 測試環境設定：必須在 import main 之前 ─────────────────────────────────────
os.environ["DATABASE_URL"]      = ""                 # 強制使用 SQLite 模式
os.environ["SQLITE_DB"]         = "oasis_test.db"   # 獨立測試 DB，不污染正式資料
os.environ["OASIS_EMAIL_USER"]  = ""                 # 關閉真實寄信
os.environ["OASIS_EMAIL_PASS"]  = ""
os.environ["SENTRY_DSN"]        = ""                 # 關閉 Sentry
os.environ["DISABLE_CAPTCHA"]    = "1"               # 跳過驗證碼（測試環境不需填）
os.environ["DISABLE_PLAN_LIMIT"] = "1"               # 跳過訂閱方案限制（測試環境）
os.environ["ADMIN_PASSWORD"]     = "admin123"        # 測試 DB 專用的 admin 密碼（正式環境自行設定）

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient
import main  # 此時 init_db() 會使用 oasis_test.db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """整個 test session 共用同一個 TestClient（效能最佳）。"""
    return TestClient(main.app)


@pytest.fixture(scope="session")
def admin_headers(client):
    """取得管理員 token header，供需要管理員權限的測試使用。"""
    resp = client.post("/api/auth/login", json={
        "email": "admin@oasis.com",
        "password": "admin123",
    })
    assert resp.status_code == 200
    token = resp.json()["user"]["token"]
    return {"X-Auth-Token": token}


@pytest.fixture(scope="session")
def user_and_headers(client):
    """
    建立一個普通測試使用者並回傳 (user_info, headers)。
    scope=session：整個測試 session 只建立一次，避免重複 INSERT。
    """
    email    = f"testuser_{secrets.token_hex(4)}@oasis-test.com"
    password = "testpassword123"
    resp = client.post("/api/auth/register", json={
        "name": "測試使用者",
        "email": email,
        "password": password,
    })
    assert resp.status_code == 200, f"register failed: {resp.text}"
    data = resp.json()
    # 開發模式（無 EMAIL_USER/PASS）下，register 直接回傳 token
    user    = data["user"]
    headers = {"X-Auth-Token": user["token"]}
    return user, headers


@pytest.fixture(scope="session")
def user_headers(user_and_headers):
    """只需要 headers 的快捷 fixture。"""
    _, headers = user_and_headers
    return headers


@pytest.fixture(scope="session")
def confirmed_space_id(client, admin_headers):
    """
    建立並確認一個空間，供預約相關測試使用。
    依賴 admin_headers，確保 admin 已登入。
    """
    # 取得第一個已確認空間的 id（init_db 插入的預設資料）
    resp = client.get("/api/spaces?per_page=1")
    data = resp.json()
    if data["total"] > 0:
        return data["data"][0]["id"]
    return None


# ── 清理（session 結束後刪除測試 DB）──────────────────────────────────────────
def pytest_sessionfinish(session, exitstatus):
    db_path = "oasis_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)
