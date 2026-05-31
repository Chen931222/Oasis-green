"""
預約 API 測試：
  - 建立預約（需登入 / 時間驗證 / 衝突偵測 / 過去日期）
  - 取消預約（本人 / 他人 / 已完成的預約）
  - 場地主確認 / 拒絕預約
  - 使用者預約列表
  - 空間可用時段查詢
"""

import pytest
from datetime import date, timedelta


# ─────────────────────────────────────────────────────────────────────────────
# 輔助
# ─────────────────────────────────────────────────────────────────────────────

def future_date(days=7) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def booking_payload(space_id: int, start="10:00", end="12:00", days=7) -> dict:
    return {
        "space_id":   space_id,
        "space_name": "測試空間",
        "date":       future_date(days),
        "start_time": start,
        "end_time":   end,
        "purpose":    "pytest 測試預約",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. 建立預約
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateBooking:

    def test_requires_auth(self, client, confirmed_space_id):
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        resp = client.post("/api/bookings", json=booking_payload(confirmed_space_id))
        assert resp.json()["ok"] is False

    def test_success(self, client, user_headers, confirmed_space_id):
        """已登入使用者可成功提交預約，初始 status 為「待確認」。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        resp = client.post("/api/bookings",
                           json=booking_payload(confirmed_space_id, days=14),
                           headers=user_headers)
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "待確認"

    def test_past_date_rejected(self, client, user_headers, confirmed_space_id):
        """預約過去日期應被後端拒絕。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        past = (date.today() - timedelta(days=1)).isoformat()
        payload = booking_payload(confirmed_space_id)
        payload["date"] = past
        resp = client.post("/api/bookings", json=payload, headers=user_headers)
        assert resp.json()["ok"] is False
        assert "過去" in resp.json()["message"]

    def test_end_before_start_rejected(self, client, user_headers, confirmed_space_id):
        """結束時間早於開始時間應被拒絕。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        resp = client.post("/api/bookings",
                           json=booking_payload(confirmed_space_id, start="14:00", end="10:00", days=21),
                           headers=user_headers)
        assert resp.json()["ok"] is False

    def test_conflict_detection(self, client, user_headers, confirmed_space_id):
        """同一空間相同時段重複預約應被拒絕。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        days = 30
        # 第一筆預約
        client.post("/api/bookings",
                    json=booking_payload(confirmed_space_id, start="09:00", end="11:00", days=days),
                    headers=user_headers)
        # 第二筆重疊預約
        resp = client.post("/api/bookings",
                           json=booking_payload(confirmed_space_id, start="10:00", end="12:00", days=days),
                           headers=user_headers)
        assert resp.json()["ok"] is False
        assert "已有預約" in resp.json()["message"]

    def test_adjacent_times_allowed(self, client, user_headers, confirmed_space_id):
        """相鄰時段（不重疊）應允許預約。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        days = 45
        # 09:00–11:00
        r1 = client.post("/api/bookings",
                         json=booking_payload(confirmed_space_id, start="09:00", end="11:00", days=days),
                         headers=user_headers)
        # 11:00–13:00（緊接在後，不重疊）
        r2 = client.post("/api/bookings",
                         json=booking_payload(confirmed_space_id, start="11:00", end="13:00", days=days),
                         headers=user_headers)
        assert r1.json()["ok"] is True
        assert r2.json()["ok"] is True

    def test_purpose_too_long(self, client, user_headers, confirmed_space_id):
        """使用目的超過 500 字元應被拒絕。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        payload = booking_payload(confirmed_space_id, days=60)
        payload["purpose"] = "A" * 501
        resp = client.post("/api/bookings", json=payload, headers=user_headers)
        assert resp.json()["ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. 取消預約
# ─────────────────────────────────────────────────────────────────────────────

class TestCancelBooking:

    def _create_booking(self, client, user_headers, space_id, days=90):
        """建立測試預約並回傳 booking id。"""
        resp = client.post("/api/bookings",
                           json=booking_payload(space_id, days=days),
                           headers=user_headers)
        assert resp.json()["ok"] is True, f"booking create failed: {resp.text}"
        return resp.json()["data"]["id"]

    def test_cancel_own_pending_booking(self, client, user_headers, confirmed_space_id):
        """使用者可取消自己「待確認」狀態的預約。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        booking_id = self._create_booking(client, user_headers, confirmed_space_id, days=100)
        resp = client.post(f"/api/bookings/{booking_id}/cancel", headers=user_headers)
        assert resp.json()["ok"] is True

    def test_cannot_cancel_others_booking(self, client, user_headers, admin_headers, confirmed_space_id):
        """使用者不可取消別人的預約。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        # admin 建立一筆預約
        resp = client.post("/api/bookings",
                           json=booking_payload(confirmed_space_id, days=110),
                           headers=admin_headers)
        booking_id = resp.json()["data"]["id"]

        # user 嘗試取消 admin 的預約
        cancel = client.post(f"/api/bookings/{booking_id}/cancel", headers=user_headers)
        assert cancel.json()["ok"] is False

    def test_cancel_nonexistent_booking(self, client, user_headers):
        """取消不存在的預約應回傳 ok=False。"""
        resp = client.post("/api/bookings/999999/cancel", headers=user_headers)
        assert resp.json()["ok"] is False

    def test_unauthenticated_cancel(self, client, confirmed_space_id):
        """未登入取消預約應回傳未授權。"""
        resp = client.post("/api/bookings/1/cancel")
        assert resp.json()["ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. 預約清單
# ─────────────────────────────────────────────────────────────────────────────

class TestUserBookings:

    def test_user_bookings_requires_auth(self, client, user_and_headers):
        """未登入不可查看使用者預約清單。"""
        user, _ = user_and_headers
        resp = client.get("/api/user/bookings", params={"email": user["email"]})
        assert resp.json()["ok"] is False

    def test_cannot_view_others_bookings(self, client, user_and_headers, admin_headers):
        """使用者不可查看其他人的預約清單。"""
        user, user_headers = user_and_headers
        # 用 admin token 查詢 user 的預約（應被拒絕，因為 email 不符）
        resp = client.get("/api/user/bookings",
                          params={"email": user["email"]},
                          headers=admin_headers)
        assert resp.json()["ok"] is False

    def test_user_sees_own_bookings(self, client, user_and_headers):
        """使用者可以查看自己的預約清單。"""
        user, user_headers = user_and_headers
        resp = client.get("/api/user/bookings",
                          params={"email": user["email"]},
                          headers=user_headers)
        assert resp.json()["ok"] is True
        assert isinstance(resp.json()["data"], list)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 空間可用時段
# ─────────────────────────────────────────────────────────────────────────────

class TestAvailability:

    def test_empty_for_no_date(self, client, confirmed_space_id):
        """不傳 date 參數應回傳空陣列。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        resp = client.get(f"/api/spaces/{confirmed_space_id}/availability")
        assert resp.json() == {"ok": True, "data": []}

    def test_returns_booked_slots(self, client, user_headers, confirmed_space_id):
        """有預約的日期應回傳該時段。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        target_date = future_date(120)
        client.post("/api/bookings", json={
            "space_id":   confirmed_space_id,
            "space_name": "Test",
            "date":       target_date,
            "start_time": "13:00",
            "end_time":   "15:00",
            "purpose":    "availability test",
        }, headers=user_headers)

        resp = client.get(f"/api/spaces/{confirmed_space_id}/availability",
                          params={"date": target_date})
        slots = resp.json()["data"]
        assert any(s["start_time"] == "13:00" and s["end_time"] == "15:00" for s in slots)
