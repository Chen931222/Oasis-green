# Oasis 綠洲 — 都市閒置空間的「拼場」共租平台

[![CI](https://github.com/Chen931222/Oasis-green/actions/workflows/test.yml/badge.svg)](https://github.com/Chen931222/Oasis-green/actions/workflows/test.yml)

**想用一個空間，但一個人租太貴。** 練舞室、活動場地、錄音間這類空間，大家其實會揪人一起分攤，
卻得在 LINE 群裡手動喬人、喬時間、算錢——又麻煩又容易出錯。

**Oasis 綠洲把這段協調自動化：** 你可以上架閒置空間，也可以對想用的空間發起一場「拼場」（共租）——
設定人數與分攤方式，有人加入就成團，平台幫你把時間與費用喬好、算好。

> 大二下「網際網路系統設計」期末專題。
> 設計重點不在「找空間」（那 FB、IG 都能做），而在把「揪人 ＋ 分攤 ＋ 排程」這段協調的麻煩做掉。
> 技術面：FastAPI 後端、PostgreSQL／SQLite 雙支援、部署於 Render、GitHub Actions CI、原生 HTML/CSS/JS 前端（無框架）。

## 線上展示

- 網站：<https://oasis-green.onrender.com>
- Render 免費方案閒置會自動休眠，第一次開啟可能要等約 30 秒喚醒，屬正常現象。

## 功能總覽

| 模組 | 內容 |
| --- | --- |
| 帳號 | 註冊 / 登入、Email 驗證、忘記密碼重設、登入速率限制（challenge） |
| 角色 | 一般使用者 / 空間擁有者 / 管理員 三種權限 |
| 空間 | 上架、瀏覽、城市篩選、推薦、評分與評論、可預約時段查詢 |
| 預約 | 申請、擁有者確認 / 拒絕、使用者取消、雙方各自的預約清單 |
| 共租 | 發起共租、加入、管理（co-rental） |
| 管理後台 | 統計報表、使用者停權 / 解除、上架審核、方案調整、公告、聯絡訊息 |
| 其他 | 訂閱方案 / 定價頁、公告、聯絡表單、robots.txt / sitemap.xml、健康檢查端點 |

## 技術架構

- **後端**：FastAPI + Pydantic v2
- **資料庫**：PostgreSQL（正式環境，Neon）/ SQLite（本機開發，零設定）雙支援，
  透過 `_get_conn()` 抽象層切換；`_PGCursor` 包裝讓 PostgreSQL 相容 SQLite 的查詢寫法
- **連線池**：psycopg2 `ThreadedConnectionPool`，內建殭屍連線（zombie connection）偵測（見下方亮點）
- **前端**：原生 HTML / CSS / JavaScript 多頁式（`www/`），由 FastAPI 提供靜態頁面
- **部署**：Render（gunicorn + `uvicorn.workers.UvicornWorker`）；另附 `Dockerfile`、`docker-compose.yml` + `nginx.conf` 可自架
- **CI**：GitHub Actions 跑 pytest（57 個測試，於 SQLite 上執行）
- **維運**：Sentry 錯誤追蹤（選用）
- **資料庫遷移**：`migrations/*.sql`（速率限制、challenge、座標、共租等）

## 技術亮點：Serverless 資料庫的殭屍連線修復

Neon（Serverless PostgreSQL）在閒置一段時間後會自動休眠並從伺服器端關閉底層 TCP 連線。
連線池並不知情，仍可能把這種失效連線交給下一個請求，導致查詢一執行就丟出
`OperationalError` / `InterfaceError`，回應變成間歇性 HTTP 500。

解法：在從連線池取得連線後、交給呼叫端之前，先用一次輕量的 `SELECT 1` 做存活探測
（`_pg_conn_is_alive()`）。偵測到失效就淘汰該連線並換一條新的，呼叫端完全無感。
集中在 `_PGConn` 一處修正，所有 30+ 個 `_get_conn()` 呼叫點都自動受保護。
（程式碼見 `main.py`。）

## 本機執行

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

開啟 <http://127.0.0.1:8000> 即可。預設使用 SQLite（`oasis.db`），**不需要安裝 PostgreSQL**。

### 選用：啟用 Email 寄信

若要讓「Email 驗證 / 重設密碼」實際寄出信件，需設定下列環境變數
（未設定時，這些流程會自動略過驗證，方便本機開發）：

```bash
set OASIS_EMAIL_USER=你的Gmail@gmail.com
set OASIS_EMAIL_PASS=你的應用程式密碼      # 16 碼，需先在 Google 開啟兩步驟驗證
set OASIS_SITE_URL=http://localhost:8000   # 信中連結用的網址，正式環境改成你的網域
```

> ⚠️ 這些是機密，請放在環境變數或未被追蹤的 `.env`，**絕對不要寫進原始碼或 README**。

## 測試

```bash
pytest
```

## 測試帳號

- 管理員：`admin@oasis.com`，密碼由 `ADMIN_PASSWORD` 環境變數決定；
  沒設定時，首次啟動會產生一組隨機密碼印在啟動 log。
- 一般使用者：從 `/register` 自行註冊

> 舊版寫死的預設密碼已移除：啟動時偵測到 admin 還在用舊預設密碼會自動作廢，
> 換成 `ADMIN_PASSWORD` 的值（或隨機密碼，見 log）。

## 專案結構

```
main.py                  FastAPI 應用主程式（路由、資料庫、寄信、認證）
www/                     前端靜態頁面（HTML / CSS / JS）
tests/                   pytest 測試（auth / spaces / bookings）
migrations/              SQL 資料庫遷移
.github/workflows/       CI 測試
render.yaml              Render 部署設定
Dockerfile / docker-compose.yml / nginx.conf   自架用
```
