# Oasis 綠洲：都市閒置空間共享平台

FastAPI 期末專題展示版，使用 Python list 假資料與純 HTML/CSS/JavaScript 製作，不使用資料庫與前端框架。

## 執行方式

```bash
uvicorn main:app --reload
```

啟動後開啟：

```text
http://127.0.0.1:8000
```
database pass : Chen0908957736
## 頁面
set OASIS_EMAIL_USER=chenchen931222@gmail.com
set OASIS_EMAIL_PASS=syae hxbj dcmu fwvn
set OASIS_SITE_URL=http://localhost:8000
uvicorn main:app --reload

- `/`：首頁
- `/explore`：空間探索
- `/space?id=1`：空間詳情
- `/booking?id=1`：預約申請
- `/login`：登入，共用入口，依角色導向管理員或一般使用者
- `/register`：註冊一般使用者
- `/user`：使用者中心，可前往上架空間
- `/dashboard`：管理員中心，管理預約、上架審核與聯絡訊息
- `/host`：上架空間
- `/contact`：聯絡我們

## API

- `GET /api/spaces`
- `GET /api/spaces/{space_id}`
- `GET /api/bookings`
- `POST /api/auth/login`
- `POST /api/auth/register`
- `POST /api/spaces`
- `POST /api/bookings`
- `POST /api/contact`

## 測試帳號

- 管理員：`admin@oasis.com` / `admin123`
- 一般使用者：可從 `/register` 自行註冊
