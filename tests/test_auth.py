"""
認證系統測試：
  - 註冊（成功 / 重複信箱 / 格式錯誤 / 密碼太短）
  - 登入（成功 / 密碼錯誤 / 暴力破解鎖定）
  - 個人資料更新（改名稱 / 改密碼）
  - 忘記密碼（速率限制）
"""

import secrets
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────────────────────────────────────

def unique_email():
    return f"test_{secrets.token_hex(4)}@oasis-test.com"


# ─────────────────────────────────────────────────────────────────────────────
# 1. 註冊
# ─────────────────────────────────────────────────────────────────────────────

class TestRegister:

    def test_success(self, client):
        """正常註冊應回傳 ok=True 及使用者資訊。"""
        resp = client.post("/api/auth/register", json={
            "name": "新使用者",
            "email": unique_email(),
            "password": "secure_pass_123",
        })
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert "user" in data
        assert data["user"]["role"] == "user"

    def test_duplicate_email(self, client):
        """相同信箱再次註冊應回傳錯誤。"""
        email = unique_email()
        client.post("/api/auth/register", json={"name": "A", "email": email, "password": "pass123"})
        resp = client.post("/api/auth/register", json={"name": "B", "email": email, "password": "pass456"})
        data = resp.json()
        assert resp.status_code == 200
        assert data["ok"] is False
        assert "已經註冊" in data["message"]

    def test_invalid_email_format(self, client):
        """格式錯誤的 Email 應回傳驗證錯誤。"""
        resp = client.post("/api/auth/register", json={
            "name": "User", "email": "not-an-email", "password": "pass123"
        })
        assert resp.json()["ok"] is False

    def test_short_password(self, client):
        """密碼少於 6 個字元應回傳錯誤。"""
        resp = client.post("/api/auth/register", json={
            "name": "User", "email": unique_email(), "password": "12345"
        })
        assert resp.json()["ok"] is False
        assert "6" in resp.json()["message"]

    def test_missing_fields(self, client):
        """缺少必要欄位應回傳錯誤。"""
        resp = client.post("/api/auth/register", json={"email": unique_email()})
        assert resp.json()["ok"] is False

    def test_name_too_long(self, client):
        """名稱超過 100 字元應回傳欄位長度錯誤。"""
        resp = client.post("/api/auth/register", json={
            "name": "A" * 101, "email": unique_email(), "password": "pass123"
        })
        assert resp.json()["ok"] is False

    def test_token_returned(self, client):
        """開發模式（無 SMTP）下，register 應直接回傳可用的 token。"""
        resp = client.post("/api/auth/register", json={
            "name": "User", "email": unique_email(), "password": "pass123456"
        })
        data = resp.json()
        assert data["ok"] is True
        assert "token" in data["user"]
        assert len(data["user"]["token"]) > 10


# ─────────────────────────────────────────────────────────────────────────────
# 2. 登入
# ─────────────────────────────────────────────────────────────────────────────

class TestLogin:

    def test_admin_login_success(self, client):
        """管理員帳號可以成功登入，role 為 admin。"""
        resp = client.post("/api/auth/login", json={
            "email": "admin@oasis.com", "password": "admin123"
        })
        data = resp.json()
        assert data["ok"] is True
        assert data["user"]["role"] == "admin"
        assert "token" in data["user"]

    def test_remember_me_token_duration(self, client):
        """記得我：勾選 → token 發 30 天；取消 → 只發 1 天，關瀏覽器即失效。"""
        from datetime import datetime, timedelta

        def login_expires(remember):
            resp = client.post("/api/auth/login", json={
                "email": "admin@oasis.com", "password": "admin123", "remember": remember
            })
            data = resp.json()
            assert data["ok"] is True
            return datetime.fromisoformat(data["user"]["token_expires_at"])

        now = datetime.now()
        assert login_expires(True) > now + timedelta(days=29)
        assert login_expires(False) < now + timedelta(days=2)

    def test_wrong_password(self, client):
        """密碼錯誤應回傳失敗，並提示剩餘機會。"""
        resp = client.post("/api/auth/login", json={
            "email": "admin@oasis.com", "password": "wrongpassword"
        })
        data = resp.json()
        assert data["ok"] is False
        assert "錯誤" in data["message"] or "次機會" in data["message"]

    def test_nonexistent_user(self, client):
        """不存在的帳號應回傳失敗。"""
        resp = client.post("/api/auth/login", json={
            "email": "nobody@nowhere.com", "password": "pass123"
        })
        assert resp.json()["ok"] is False

    def test_brute_force_lockout(self, client):
        """連續 5 次密碼錯誤後帳號應被鎖定。"""
        email = unique_email()
        client.post("/api/auth/register", json={"name": "BF", "email": email, "password": "correct_pass"})

        for _ in range(5):
            client.post("/api/auth/login", json={"email": email, "password": "wrong"})

        # 第 6 次，應已被鎖定
        resp = client.post("/api/auth/login", json={"email": email, "password": "correct_pass"})
        data = resp.json()
        assert data["ok"] is False
        assert "鎖定" in data["message"] or "分鐘" in data["message"]

    def test_token_is_valid(self, client):
        """登入後取得的 token 應可用於需要認證的 API。"""
        email = unique_email()
        client.post("/api/auth/register", json={"name": "T", "email": email, "password": "pass12345"})
        login_resp = client.post("/api/auth/login", json={"email": email, "password": "pass12345"})
        token = login_resp.json()["user"]["token"]

        # 用 token 呼叫需要認證的 API
        profile_resp = client.get("/api/user/bookings", params={"email": email},
                                  headers={"X-Auth-Token": token})
        assert profile_resp.json()["ok"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. 個人資料
# ─────────────────────────────────────────────────────────────────────────────

class TestProfile:

    def test_update_name(self, client, user_headers):
        """已登入使用者可以修改顯示名稱。"""
        resp = client.patch("/api/user/profile",
                            json={"name": "新名稱"},
                            headers=user_headers)
        assert resp.json()["ok"] is True

    def test_change_password_wrong_current(self, client, user_headers):
        """提供錯誤的目前密碼時，修改密碼應失敗。"""
        resp = client.patch("/api/user/profile",
                            json={"current_password": "wrongpass", "new_password": "newpass123"},
                            headers=user_headers)
        assert resp.json()["ok"] is False
        assert "密碼" in resp.json()["message"]

    def test_change_password_new_too_short(self, client, user_headers):
        """新密碼太短應回傳錯誤。"""
        resp = client.patch("/api/user/profile",
                            json={"current_password": "testpassword123", "new_password": "abc"},
                            headers=user_headers)
        assert resp.json()["ok"] is False

    def test_unauthenticated(self, client):
        """未帶 token 存取個人資料應回傳未授權。"""
        resp = client.patch("/api/user/profile", json={"name": "X"})
        assert resp.json()["ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. 忘記 / 重設密碼
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordReset:

    def test_forgot_password_unknown_email(self, client):
        """不存在的信箱也應回傳成功訊息（防帳號枚舉）。"""
        resp = client.post("/api/auth/forgot-password", json={"email": "nobody@no.com"})
        assert resp.json()["ok"] is True

    def test_forgot_password_rate_limit(self, client):
        """同一 IP 短時間超過 5 次申請應被限制。"""
        # 先送 5 次（耗盡配額）
        for _ in range(5):
            client.post("/api/auth/forgot-password", json={"email": unique_email()})
        # 第 6 次應被拒絕
        resp = client.post("/api/auth/forgot-password", json={"email": unique_email()})
        assert resp.json()["ok"] is False
        assert "頻繁" in resp.json()["message"]

    def test_reset_invalid_token(self, client):
        """使用無效 token 重設密碼應回傳錯誤。"""
        resp = client.post("/api/auth/reset-password", json={
            "token": "invalid_token_xyz",
            "new_password": "newpassword123",
        })
        assert resp.json()["ok"] is False
