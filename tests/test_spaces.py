"""
空間 API 測試：
  - 列表（分頁 / 關鍵字 / 城市 / 類型 / 價格篩選）
  - 取得單一空間
  - 上架申請（需登入 / 欄位驗證 / 圖片驗證）
  - 刪除空間（僅本人或管理員）
  - 更新空間資料
  - 城市清單
"""

import pytest


class TestListSpaces:

    def test_returns_data(self, client):
        """空間列表 API 應回傳 ok=True 及資料陣列。"""
        resp = client.get("/api/spaces")
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert "total" in data
        assert "page" in data
        assert "total_pages" in data

    def test_default_shows_confirmed_only(self, client):
        """預設只顯示 status='已確認' 的空間。"""
        resp = client.get("/api/spaces")
        for space in resp.json()["data"]:
            assert space["status"] == "已確認"

    def test_pagination(self, client):
        """per_page 參數應正確分頁。"""
        resp = client.get("/api/spaces?per_page=1&page=1")
        data = resp.json()
        assert len(data["data"]) <= 1

    def test_per_page_capped_at_100(self, client):
        """per_page 不得超過 100（防止傾倒整個 DB）。"""
        resp = client.get("/api/spaces?per_page=99999")
        data = resp.json()
        # 回傳數量不能超過 100
        assert len(data["data"]) <= 100

    def test_keyword_filter(self, client):
        """關鍵字篩選應只回傳名稱 / 城市 / 描述包含該詞的結果。"""
        resp = client.get("/api/spaces?keyword=Studio")
        data = resp.json()
        # 有資料時每筆都應包含關鍵字（name/city/district/description 其一）
        for space in data["data"]:
            combined = " ".join([
                space.get("name", ""),
                space.get("city", ""),
                space.get("district", ""),
                space.get("description", ""),
            ]).lower()
            assert "studio" in combined

    def test_city_filter(self, client):
        """城市篩選應只回傳指定城市的空間。"""
        resp = client.get("/api/spaces?city=台中市")
        for space in resp.json()["data"]:
            assert space["city"] == "台中市"

    def test_max_price_filter(self, client):
        """max_price 篩選應只回傳價格不超過上限的空間。"""
        resp = client.get("/api/spaces?max_price=350")
        for space in resp.json()["data"]:
            assert space["price_per_hour"] <= 350

    def test_no_results_unknown_city(self, client):
        """查詢不存在城市應回傳空陣列，total=0。"""
        resp = client.get("/api/spaces?city=火星市")
        data = resp.json()
        assert data["total"] == 0
        assert data["data"] == []


class TestGetSingleSpace:

    def test_existing_space(self, client, confirmed_space_id):
        """取得已存在的空間應回傳完整資料。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        resp = client.get(f"/api/spaces/{confirmed_space_id}")
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["id"] == confirmed_space_id

    def test_nonexistent_space(self, client):
        """不存在的空間 id 應回傳 ok=False。"""
        resp = client.get("/api/spaces/999999")
        assert resp.json()["ok"] is False

    def test_space_has_required_fields(self, client, confirmed_space_id):
        """空間資料應包含所有前端需要的欄位。"""
        if confirmed_space_id is None:
            pytest.skip("沒有已確認空間")
        space = client.get(f"/api/spaces/{confirmed_space_id}").json()["data"]
        required = ["id", "name", "city", "type", "price_per_hour", "capacity", "rating", "images"]
        for field in required:
            assert field in space, f"缺少欄位：{field}"


class TestCities:

    def test_cities_endpoint(self, client):
        """城市清單應回傳非空的字串陣列。"""
        resp = client.get("/api/spaces/cities")
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["data"], list)

    def test_cities_no_duplicates(self, client):
        """城市清單不應有重複值。"""
        cities = client.get("/api/spaces/cities").json()["data"]
        assert len(cities) == len(set(cities))


class TestCreateSpace:

    def test_requires_auth(self, client):
        """未登入時上架空間應回傳未授權。"""
        resp = client.post("/api/spaces", json={
            "name": "Test", "city": "台北市", "type": "工作室",
            "price_per_hour": 100, "capacity": 10,
        })
        assert resp.json()["ok"] is False

    def test_success(self, client, user_headers):
        """已登入使用者可成功提交上架申請，初始 status 為「待確認」。"""
        resp = client.post("/api/spaces", json={
            "name":          "整合測試空間",
            "city":          "台北市",
            "district":      "大安區",
            "address":       "台北市大安區測試路1號",
            "type":          "工作室",
            "price_per_hour": 500,
            "capacity":      20,
            "equipment":     ["投影機", "白板"],
            "description":   "整合測試用空間",
        }, headers=user_headers)
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "待確認"

    def test_negative_price_rejected(self, client, user_headers):
        """負數價格應被拒絕。"""
        resp = client.post("/api/spaces", json={
            "name": "Test", "city": "台北市", "type": "工作室",
            "price_per_hour": -100, "capacity": 10,
        }, headers=user_headers)
        assert resp.json()["ok"] is False

    def test_zero_capacity_rejected(self, client, user_headers):
        """容量為 0 應被拒絕。"""
        resp = client.post("/api/spaces", json={
            "name": "Test", "city": "台北市", "type": "工作室",
            "price_per_hour": 100, "capacity": 0,
        }, headers=user_headers)
        assert resp.json()["ok"] is False

    def test_name_too_long(self, client, user_headers):
        """名稱超過 100 字元應被拒絕。"""
        resp = client.post("/api/spaces", json={
            "name": "A" * 101, "city": "台北市", "type": "工作室",
            "price_per_hour": 100, "capacity": 10,
        }, headers=user_headers)
        assert resp.json()["ok"] is False

    def test_too_many_images(self, client, user_headers):
        """超過 5 張圖片應被拒絕。"""
        resp = client.post("/api/spaces", json={
            "name": "T", "city": "台北市", "type": "工作室",
            "price_per_hour": 100, "capacity": 10,
            "images": ["https://example.com/img.jpg"] * 6,
        }, headers=user_headers)
        assert resp.json()["ok"] is False


class TestDeleteSpace:

    def test_delete_own_space(self, client, user_headers):
        """場地主可以刪除自己的空間。"""
        # 先建立一個空間
        create = client.post("/api/spaces", json={
            "name": "待刪除空間", "city": "台北市", "type": "工作室",
            "price_per_hour": 100, "capacity": 5,
        }, headers=user_headers)
        space_id = create.json()["data"]["id"]

        # 刪除
        resp = client.delete(f"/api/spaces/{space_id}", headers=user_headers)
        assert resp.json()["ok"] is True

        # 確認已刪除
        assert client.get(f"/api/spaces/{space_id}").json()["ok"] is False

    def test_cannot_delete_others_space(self, client, user_headers, admin_headers):
        """非擁有者不可刪除空間（admin 除外）。"""
        # admin 建立空間
        create = client.post("/api/spaces", json={
            "name": "管理員的空間", "city": "台中市", "type": "教室",
            "price_per_hour": 200, "capacity": 30,
        }, headers=admin_headers)
        space_id = create.json()["data"]["id"]

        # 一般使用者嘗試刪除
        resp = client.delete(f"/api/spaces/{space_id}", headers=user_headers)
        assert resp.json()["ok"] is False
