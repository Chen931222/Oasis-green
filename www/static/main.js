// main.js：集中管理 Oasis 前端所有 fetch 與頁面互動。
const page = document.body.dataset.page

// 登入狀態存兩個地方：勾「記得我」→ localStorage（跨瀏覽器重啟都在）；
// 沒勾 → sessionStorage（關掉瀏覽器就登出）。讀取時兩邊都找。
function readUserFrom(store) {
  const rawUser = store.getItem("oasisCurrentUser")
  if (!rawUser) return null
  const user = JSON.parse(rawUser)
  // 無 token 欄位（加入 token 機制前的舊版登入資料）→ 強制清除，視為未登入
  if (!user.token) {
    store.removeItem("oasisCurrentUser")
    return null
  }
  if (user.token_expires_at && new Date() > new Date(user.token_expires_at)) {
    store.removeItem("oasisCurrentUser")
    sessionStorage.setItem("oasisSessionExpired", "1")
    return null
  }
  return user
}

function getCurrentUser() {
  return readUserFrom(localStorage) ?? readUserFrom(sessionStorage)
}

// remember 不傳的話，維持使用者資料現在住的位置更新（例如改完個人資料回寫）；
// 只有登入頁會明確傳 true / false。都沒登入過則預設 localStorage（與註冊行為一致）。
function setCurrentUser(user, remember) {
  if (remember === undefined) {
    remember = !sessionStorage.getItem("oasisCurrentUser")
  }
  const target = remember ? localStorage : sessionStorage
  const other  = remember ? sessionStorage : localStorage
  target.setItem("oasisCurrentUser", JSON.stringify(user))
  other.removeItem("oasisCurrentUser")
}

function clearCurrentUser() {
  localStorage.removeItem("oasisCurrentUser")
  sessionStorage.removeItem("oasisCurrentUser")
}

// XSS 防護
function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;")
}

// ── 價格千分位格式：1000 → NT$ 1,000 ────────────────────────────────────────
function formatPrice(price) {
  return `NT$ ${Number(price).toLocaleString()}`
}

// ── 實體短碼：將資料庫 id 格式化為可搜尋碼，例如 B-0001 / S-0023 ────────────
function formatCode(prefix, id) {
  return `${prefix}-${String(id).padStart(4, "0")}`
}

// ── 空狀態圖示（Lucide 風格 inline SVG，不依賴外部 CDN） ────────────────────
const ICONS = {
  home:      `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>`,
  search:    `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>`,
  calendar:  `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`,
  mail:      `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
  building:  `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>`,
  users:     `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
  clipboard: `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>`,
  inbox:     `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>`,
}

// ── 空狀態元件：列表無資料時顯示圖示 + 說明 ─────────────────────────────────
function emptyState(icon, title, msg, actionHtml = "") {
  const svg = ICONS[icon] || ICONS.home
  return `
    <div class="empty-state">
      <div class="empty-state-icon">${svg}</div>
      <h3 class="empty-state-title">${title}</h3>
      <p class="empty-state-msg">${msg}</p>
      ${actionHtml}
    </div>`
}

function getAuthHeaders(withBody = false) {
  const user = getCurrentUser()
  const headers = { "X-Auth-Token": user?.token || "" }
  if (withBody) headers["Content-Type"] = "application/json"
  return headers
}

// ── 數學驗證碼 helper ──────────────────────────────────────────────────────────
// 向後端取得新的加法挑戰（如 "7 + 3 = ?"），更新題目顯示與 hidden id 欄位。
async function fetchChallenge(questionEl, idInputEl) {
  if (!questionEl || !idInputEl) return
  questionEl.textContent = "載入中…"
  try {
    const res  = await fetch("/api/auth/challenge")
    const data = await res.json()
    if (data.ok) {
      questionEl.textContent = data.data.question
      idInputEl.value        = data.data.id
    } else {
      questionEl.textContent = "無法載入驗證碼"
    }
  } catch {
    questionEl.textContent = "網路錯誤，請重新整理"
  }
}

// ── 骨架屏佔位 HTML ──────────────────────────────────────────────────────────
function skeletonCards(count = 3) {
  return Array(count).fill(`
    <div class="skeleton-card">
      <div class="skeleton" style="aspect-ratio:4/3"></div>
      <div class="card-body" style="display:grid;gap:10px">
        <div class="skeleton" style="height:13px;width:55%"></div>
        <div class="skeleton" style="height:20px;width:80%"></div>
        <div class="skeleton" style="height:13px;width:45%"></div>
        <div class="skeleton" style="height:13px;width:30%"></div>
      </div>
    </div>`).join("")
}

function skeletonBookingCards(count = 3) {
  return Array(count).fill(`
    <article class="booking-card">
      <div style="flex:1;display:grid;gap:10px">
        <div class="skeleton" style="height:24px;width:72px;border-radius:999px"></div>
        <div class="skeleton" style="height:18px;width:60%"></div>
        <div class="skeleton" style="height:13px;width:40%"></div>
      </div>
    </article>`).join("")
}

function skeletonStatCards(count = 6) {
  return Array(count).fill(`
    <article class="stat-card">
      <div class="skeleton" style="height:36px;width:50%;margin-bottom:12px"></div>
      <div class="skeleton" style="height:13px;width:65%"></div>
    </article>`).join("")
}

function skeletonAdminSpaceCards(count = 3) {
  return Array(count).fill(`
    <article class="admin-space-card">
      <div class="skeleton admin-space-image"></div>
      <div style="display:grid;gap:10px;align-content:start">
        <div class="skeleton" style="height:13px;width:40%"></div>
        <div class="skeleton" style="height:20px;width:70%"></div>
        <div class="skeleton" style="height:13px;width:50%"></div>
      </div>
      <div></div>
    </article>`).join("")
}

function skeletonSpaceDetail() {
  return `
    <div class="detail-layout">
      <div>
        <div class="skeleton" style="width:100%;aspect-ratio:16/10;border-radius:8px"></div>
        <div class="detail-section">
          <div class="skeleton" style="height:20px;width:40%;margin-bottom:14px"></div>
          <div class="skeleton" style="height:13px;width:95%;margin-bottom:7px"></div>
          <div class="skeleton" style="height:13px;width:78%"></div>
        </div>
      </div>
      <aside class="detail-side">
        <div class="skeleton" style="height:26px;width:60px;border-radius:999px;margin-bottom:10px"></div>
        <div class="skeleton" style="height:30px;width:80%;margin-bottom:10px"></div>
        <div class="skeleton" style="height:15px;width:55%;margin-bottom:7px"></div>
        <div class="skeleton" style="height:15px;width:40%;margin-bottom:20px"></div>
        <div class="skeleton" style="height:48px;width:100%;border-radius:8px"></div>
      </aside>
    </div>`
}

// ── 按鈕 loading 狀態：送出期間 disabled + 顯示「處理中…」，防止重複送出 ────
function setButtonLoading(btn, isLoading) {
  if (!btn) return
  if (isLoading) {
    btn.disabled = true
    btn.dataset.originalText = btn.textContent
    btn.textContent = "處理中…"
  } else {
    btn.disabled = false
    btn.textContent = btn.dataset.originalText || btn.textContent
  }
}

// ── Navbar：依登入狀態更新連結，並注入漢堡按鈕（手機版） ─────────────────────
function renderNavbar() {
  const navbar = document.querySelector(".navbar")
  const navLinks = document.querySelector(".nav-links")
  if (!navLinks) return

  // 注入漢堡按鈕（只注入一次）
  if (!document.querySelector(".nav-hamburger")) {
    const hamburger = document.createElement("button")
    hamburger.className = "nav-hamburger"
    hamburger.setAttribute("aria-label", "開關選單")
    hamburger.setAttribute("type", "button")
    hamburger.innerHTML = "<span></span><span></span><span></span>"
    navbar.insertBefore(hamburger, navLinks)

    hamburger.addEventListener("click", () => {
      navLinks.classList.toggle("open")
      hamburger.classList.toggle("open")
    })
    // 點選連結後自動收合
    navLinks.addEventListener("click", (e) => {
      if (e.target.tagName === "A" || e.target.classList.contains("nav-logout-button")) {
        navLinks.classList.remove("open")
        hamburger.classList.remove("open")
      }
    })
  }

  const user = getCurrentUser()
  if (!user) {
    navLinks.innerHTML = `
      <a href="/">首頁</a>
      <a href="/explore">探索空間</a>
      <a href="/recommend">智慧推薦</a>
      <a href="/co-rental">拼場</a>
      <a href="/pricing">定價</a>
      <a href="/login">登入</a>
      <a href="/register">註冊</a>
      <a href="/contact">聯絡我們</a>`
    return
  }

  if (user.role === "admin") {
    navLinks.innerHTML = `
      <a href="/">首頁</a>
      <a href="/explore">探索空間</a>
      <a href="/recommend">智慧推薦</a>
      <a href="/co-rental">拼場</a>
      <a href="/dashboard">管理員中心</a>
      <a href="/contact">聯絡我們</a>
      <button class="nav-logout-button" type="button">登出</button>`
  } else {
    navLinks.innerHTML = `
      <a href="/">首頁</a>
      <a href="/explore">探索空間</a>
      <a href="/recommend">智慧推薦</a>
      <a href="/co-rental">拼場</a>
      <a href="/pricing">定價</a>
      <a href="/host">上架空間</a>
      <a href="/user">使用者中心</a>
      <a href="/contact">聯絡我們</a>
      <button class="nav-logout-button" type="button">登出</button>`
  }

  document.querySelector(".nav-logout-button").addEventListener("click", () => {
    clearCurrentUser()
    window.location.href = "/login"
  })
}

// ── 返回頂部按鈕：滾超過 300px 後右下角浮現 ─────────────────────────────────
function initScrollToTop() {
  const btn = document.createElement("button")
  btn.id = "scroll-top-btn"
  btn.setAttribute("aria-label", "返回頂部")
  btn.setAttribute("type", "button")
  btn.innerHTML = '<i class="ri-arrow-up-line"></i>'
  document.body.appendChild(btn)

  window.addEventListener("scroll", () => {
    btn.classList.toggle("visible", window.scrollY > 300)
  }, { passive: true })

  btn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" })
  })
}

function requireRole(role) {
  const user = getCurrentUser()
  if (!user || user.role !== role) {
    const expired = sessionStorage.getItem("oasisSessionExpired")
    sessionStorage.removeItem("oasisSessionExpired")
    window.location.href = expired ? "/login?expired=1" : "/login"
    return null
  }
  return user
}

function getQueryParam(name) {
  return new URLSearchParams(window.location.search).get(name)
}

function createSpaceCard(space) {
  return `
    <a class="space-card" href="/space?id=${space.id}">
      <img src="${space.image}" alt="${escapeHtml(space.name)}">
      <div class="card-body">
        <div class="card-meta">
          <span>${escapeHtml(space.type)}</span>
          <span>★ ${space.rating}</span>
        </div>
        <h3>${escapeHtml(space.name)}</h3>
        <p>${escapeHtml(space.city)} ${escapeHtml(space.district)} · 最多 ${space.capacity} 人</p>
        <div class="card-footer"><span>${formatPrice(space.price_per_hour)} / 小時</span></div>
      </div>
    </a>`
}

// 首頁：最新拼場卡片
function createHomeCoRentalCard(cr) {
  const slotsLeft  = cr.available_slots ?? (cr.total_slots - cr.filled_slots)
  const badgeClass = slotsLeft <= 1 ? "almost" : "open"
  const badgeText  = slotsLeft <= 1 ? `<i class="ri-flashlight-line"></i> 僅剩 ${slotsLeft} 位` : `剩 ${slotsLeft} 位`
  return `
    <div class="home-cr-card">
      <div class="home-cr-space">${escapeHtml(cr.space_name)}</div>
      <div class="home-cr-meta">
        <span><i class="ri-calendar-event-line"></i> ${escapeHtml(cr.date)}</span>
        <span><i class="ri-time-line"></i> ${escapeHtml(cr.start_time)}–${escapeHtml(cr.end_time)}</span>
        <span><i class="ri-map-pin-2-line"></i> ${escapeHtml(cr.space_city || "")}</span>
      </div>
      ${cr.purpose ? `<div class="home-cr-purpose"><i class="ri-focus-3-line"></i> ${escapeHtml(cr.purpose)}</div>` : ""}
      <div class="home-cr-footer">
        <span class="home-cr-price">${formatPrice(cr.price_per_slot)} / 人</span>
        <span class="home-cr-badge ${badgeClass}">${badgeText}</span>
      </div>
    </div>`
}

// 初始化首頁
async function initIndexPage() {
  const featuredContainer  = document.querySelector("#featured-spaces")
  const coRentalContainer  = document.querySelector("#home-co-rentals")

  // ── 最新拼場（前 3 筆）────────────────────────────────────────────────────
  if (coRentalContainer) {
    coRentalContainer.innerHTML = skeletonCards(3)
    try {
      const crRes   = await fetch("/api/co-rentals")
      const crData  = await crRes.json()
      const crItems = (crData.data || []).slice(0, 3)
      if (crItems.length === 0) {
        coRentalContainer.innerHTML = `
          <div class="home-cr-empty">
            目前還沒有拼場資訊，
            <a href="/co-rental">來發起第一個吧！</a>
          </div>`
      } else {
        coRentalContainer.innerHTML = crItems.map(createHomeCoRentalCard).join("")
      }
    } catch {
      coRentalContainer.innerHTML = `<div class="home-cr-empty">載入失敗，請稍後再試。</div>`
    }
  }

  // ── 精選空間（評分最高 3 筆）─────────────────────────────────────────────
  if (featuredContainer) {
    featuredContainer.innerHTML = skeletonCards(3)
    try {
      const response = await fetch("/api/spaces?sort=rating&per_page=3")
      const result   = await response.json()
      const spaces   = result.data || []
      featuredContainer.innerHTML = spaces.map(createSpaceCard).join("") ||
        emptyState("home", "目前還沒有公開空間", "空間上架後就會出現在這裡。")
    } catch {
      featuredContainer.innerHTML = emptyState("home", "載入失敗", "請稍後重新整理。")
    }
  }
}

// 分頁按鈕
function renderPagination(containerId, currentPage, totalPages, onPageChange) {
  const container = document.querySelector(`#${containerId}`)
  if (!container) return
  if (totalPages <= 1) { container.innerHTML = ""; return }

  const buttons = []
  buttons.push(`<button class="page-btn" data-page="${currentPage - 1}" ${currentPage <= 1 ? "disabled" : ""}>‹</button>`)
  for (let p = 1; p <= totalPages; p++) {
    if (totalPages <= 7 || Math.abs(p - currentPage) <= 2 || p === 1 || p === totalPages) {
      buttons.push(`<button class="page-btn ${p === currentPage ? "active" : ""}" data-page="${p}">${p}</button>`)
    } else if (Math.abs(p - currentPage) === 3) {
      buttons.push(`<span style="align-self:center;color:var(--muted)">…</span>`)
    }
  }
  buttons.push(`<button class="page-btn" data-page="${currentPage + 1}" ${currentPage >= totalPages ? "disabled" : ""}>›</button>`)
  container.innerHTML = buttons.join("")
  container.querySelectorAll(".page-btn:not([disabled])").forEach((btn) => {
    btn.addEventListener("click", () => onPageChange(Number(btn.dataset.page)))
  })
}

// 初始化探索頁（含 地圖模式 / 列表模式 切換）
async function initExplorePage() {
  const keywordInput = document.querySelector("#explore-keyword")
  const cityFilter   = document.querySelector("#city-filter")
  const typeFilter   = document.querySelector("#type-filter")
  const priceFilter  = document.querySelector("#price-filter")
  const resultCount  = document.querySelector("#result-count")
  const spaceList    = document.querySelector("#space-list")
  const pagination   = document.querySelector("#explore-pagination")
  const mapContainer = document.querySelector("#space-map")
  const viewListBtn  = document.querySelector("#view-list-btn")
  const viewMapBtn   = document.querySelector("#view-map-btn")

  // 從 URL 還原所有篩選條件（支援分享連結與重新整理保留狀態）
  const savedCity    = getQueryParam("city") || ""
  keywordInput.value = getQueryParam("keyword") || ""
  typeFilter.value   = getQueryParam("type") || ""
  priceFilter.value  = getQueryParam("max_price") || ""
  let currentPage = 1
  let currentView = "list"   // "list" | "map"
  let mapInstance = null     // Leaflet Map 實例（懶初始化）
  let mapMarkers  = []       // 目前的 Marker 列表，切換篩選時清除重建

  // ── 將目前篩選條件同步寫入 URL（不重新載入頁面）────────────────────────────────
  function updateURL() {
    const params = new URLSearchParams()
    const kw    = keywordInput.value.trim()
    const city  = cityFilter.value
    const type  = typeFilter.value
    const price = priceFilter.value
    if (kw)    params.set("keyword",   kw)
    if (city)  params.set("city",      city)
    if (type)  params.set("type",      type)
    if (price) params.set("max_price", price)
    const qs = params.toString()
    history.replaceState(null, "", qs ? `/explore?${qs}` : "/explore")
  }

  // ── 地圖：渲染/更新 Marker（Leaflet 懶初始化）─────────────────────────────────
  function renderMapMarkers(spaces) {
    // Leaflet 未載入（CDN 不可達）時給友善提示
    if (typeof L === "undefined") {
      mapContainer.innerHTML =
        `<div style="padding:3rem;text-align:center;color:var(--muted)"><i class="ri-alert-line"></i> 地圖載入失敗，請確認網路連線後重新整理頁面。</div>`
      return
    }
    // 懶初始化 Leaflet Map（以台灣中心為初始視圖）
    if (!mapInstance) {
      mapInstance = L.map("space-map").setView([24.1477, 120.6736], 7)
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(mapInstance)
    }
    // 清除舊 Marker
    mapMarkers.forEach((m) => m.remove())
    mapMarkers = []

    // 只顯示有座標的空間
    const located = spaces.filter((s) => s.lat && s.lng)
    located.forEach((space) => {
      // 自訂 DivIcon：顯示空間類型標籤，不依賴 Leaflet 預設圖片（避免 CSP 問題）
      const icon = L.divIcon({
        className: "",
        html: `<div style="background:#1a7a52;color:#fff;padding:4px 10px;border-radius:12px;` +
              `font-size:0.78rem;font-weight:700;white-space:nowrap;` +
              `box-shadow:0 2px 8px rgba(0,0,0,0.25);cursor:pointer">` +
              `${escapeHtml(space.type)}</div>`,
        iconAnchor: [24, 14],
        popupAnchor: [0, -18],
      })
      const marker = L.marker([space.lat, space.lng], { icon })
      marker.bindPopup(
        `<div style="min-width:180px;font-family:inherit">` +
        `<img src="${escapeHtml(space.image || "")}" alt="${escapeHtml(space.name)}" ` +
        `style="width:100%;height:100px;object-fit:cover;border-radius:8px;margin-bottom:6px" ` +
        `onerror="this.style.display='none'">` +
        `<div style="font-weight:700;margin:0 0 2px;font-size:0.95rem">${escapeHtml(space.name)}</div>` +
        `<div style="font-size:0.82rem;color:#666;margin-bottom:4px">` +
        `${escapeHtml(space.city)} ${escapeHtml(space.district)} · ★ ${space.rating}</div>` +
        `<div style="font-weight:700;color:#1a7a52;margin-bottom:8px">` +
        `${formatPrice(space.price_per_hour)} / 小時 · 最多 ${space.capacity} 人</div>` +
        `<a href="/space?id=${space.id}" style="display:inline-block;padding:5px 14px;` +
        `background:#1a7a52;color:#fff;border-radius:20px;font-size:0.82rem;text-decoration:none">查看詳情</a>` +
        `</div>`,
        { maxWidth: 220 }
      )
      marker.addTo(mapInstance)
      mapMarkers.push(marker)
    })

    // 自動縮放到所有 Marker 的範圍
    if (located.length > 0) {
      const bounds = L.latLngBounds(located.map((s) => [s.lat, s.lng]))
      mapInstance.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 })
    }
    // 解決 hidden 切換後地圖大小計算錯誤
    setTimeout(() => mapInstance.invalidateSize(), 80)
  }

  // 動態載入城市清單；若 URL 有指定城市，需先等選項載入後才能還原選取值。
  const loadCitiesPromise = fetch("/api/spaces/cities")
    .then((r) => r.json())
    .then((result) => {
      const cities = result.data || []
      if (cities.length > 0) {
        cityFilter.innerHTML =
          `<option value="">全部城市</option>` +
          cities.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("")
        if (savedCity) cityFilter.value = savedCity
      }
    })
    .catch((err) => console.warn("[城市清單] 載入失敗，請確認伺服器已重啟：", err))

  if (savedCity) await loadCitiesPromise

  async function loadSpaces(page = 1) {
    currentPage = page
    updateURL()
    resultCount.textContent = ""
    const keyword  = encodeURIComponent(keywordInput.value.trim())
    const city     = encodeURIComponent(cityFilter.value)
    const type     = encodeURIComponent(typeFilter.value)
    const maxPrice = Number(priceFilter.value) || 0

    if (currentView === "map") {
      // 地圖模式：一次載入所有符合條件的空間（上限 100 筆），不分頁
      const response = await fetch(
        `/api/spaces?keyword=${keyword}&city=${city}&type=${type}&max_price=${maxPrice}&page=1&per_page=100`
      )
      const result = await response.json()
      const spaces = result.data || []
      resultCount.textContent = `共 ${result.total} 個空間（地圖模式顯示有座標的標記）`
      renderMapMarkers(spaces)
    } else {
      // 列表模式：分頁載入
      spaceList.innerHTML = skeletonCards(6)
      const response = await fetch(
        `/api/spaces?keyword=${keyword}&city=${city}&type=${type}&max_price=${maxPrice}&page=${page}&per_page=9`
      )
      const result = await response.json()
      resultCount.textContent = `共 ${result.total} 筆結果（第 ${result.page} / ${result.total_pages} 頁）`
      spaceList.innerHTML = (result.data || []).length
        ? (result.data || []).map(createSpaceCard).join("")
        : emptyState("search", "找不到符合條件的空間", "請嘗試調整關鍵字、城市或類型篩選。")
      renderPagination("explore-pagination", result.page, result.total_pages, loadSpaces)
    }
  }

  // ── 視圖切換：列表 ↔ 地圖 ────────────────────────────────────────────────────
  if (viewListBtn) {
    viewListBtn.addEventListener("click", () => {
      if (currentView === "map") {
        currentView = "list"
        viewListBtn.classList.add("active")
        viewMapBtn.classList.remove("active")
        spaceList.classList.remove("hidden")
        if (pagination) pagination.classList.remove("hidden")
        mapContainer.classList.add("hidden")
        loadSpaces(1)
      }
    })
  }
  if (viewMapBtn) {
    viewMapBtn.addEventListener("click", () => {
      if (currentView === "list") {
        currentView = "map"
        viewMapBtn.classList.add("active")
        viewListBtn.classList.remove("active")
        spaceList.classList.add("hidden")
        if (pagination) pagination.classList.add("hidden")
        mapContainer.classList.remove("hidden")
        loadSpaces(1)
      }
    })
  }

  keywordInput.addEventListener("input",  () => loadSpaces(1))
  cityFilter.addEventListener("change",   () => loadSpaces(1))
  typeFilter.addEventListener("change",   () => loadSpaces(1))
  priceFilter.addEventListener("input",   () => loadSpaces(1))
  await loadSpaces(1)
}

// 初始化空間詳情頁
async function initSpacePage() {
  const id        = getQueryParam("id")
  const container = document.querySelector("#space-detail")

  if (!id) { container.innerHTML = `<div class="success-box">找不到此空間</div>`; return }

  container.innerHTML = skeletonSpaceDetail()

  const response = await fetch(`/api/spaces/${id}`)
  const result   = await response.json()

  if (!result.ok) {
    container.innerHTML = `<div class="success-box">${escapeHtml(result.message)}</div>`
    return
  }

  const space = result.data
  const images = space.images && space.images.length > 0 ? space.images : [space.image]
  const currentUser  = getCurrentUser()
  const bookingLink  = currentUser ? `/booking?id=${space.id}` : `/login?next=${encodeURIComponent(`/booking?id=${space.id}`)}`
  const bookingText  = currentUser ? "我要預約" : "登入後預約"

  container.innerHTML = `
    <div class="detail-layout">
      <div>
        <div class="image-gallery">
          <img class="gallery-main" id="gallery-main" src="${images[0]}" alt="${escapeHtml(space.name)}">
          ${images.length > 1 ? `
            <div class="gallery-thumbs">
              ${images.map((src, i) => `<img class="gallery-thumb ${i === 0 ? "active" : ""}" src="${src}" alt="${escapeHtml(space.name)} 圖片 ${i + 1}" data-index="${i}">`).join("")}
            </div>` : ""}
        </div>
        <section class="detail-section">
          <h2>詳細介紹</h2>
          <p>${escapeHtml(space.description)}</p>
        </section>
        <section class="detail-section">
          <h2>設備清單</h2>
          <div class="pill-list">${space.equipment.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}</div>
        </section>
      </div>
      <aside class="detail-side">
        <span class="pill">${escapeHtml(space.type)}</span>
        <h1>${escapeHtml(space.name)}</h1>
        <p>${escapeHtml(space.city)} ${escapeHtml(space.district)}</p>
        <p>${escapeHtml(space.address)}</p>
        <p>最多 ${space.capacity} 人</p>
        <h2>${formatPrice(space.price_per_hour)} / 小時</h2>
        <a class="book-button" href="${bookingLink}">${bookingText}</a>
        <button id="start-corent-btn" type="button" class="corent-start-btn"><i class="ri-group-line"></i> 發起拼場</button>
        <p class="corent-hint">一個人租太貴？找人一起分攤</p>
      </aside>
    </div>`

  if (images.length > 1) {
    const mainImg = container.querySelector("#gallery-main")
    container.querySelectorAll(".gallery-thumb").forEach((thumb) => {
      thumb.addEventListener("click", () => {
        mainImg.src = images[parseInt(thumb.dataset.index)]
        container.querySelectorAll(".gallery-thumb").forEach((t) => t.classList.remove("active"))
        thumb.classList.add("active")
      })
    })
  }

  // ── 發起拼場 Modal ──────────────────────────────────────────────────────────
  const today = new Date().toISOString().slice(0, 10)
  let crModal = document.getElementById("space-corent-modal")
  if (!crModal) {
    crModal = document.createElement("div")
    crModal.id = "space-corent-modal"
    crModal.className = "modal-overlay hidden"
    crModal.innerHTML = `
      <div class="modal-card">
        <div class="modal-header">
          <h2>發起拼場</h2>
          <button type="button" id="corent-modal-close" class="modal-close">✕</button>
        </div>
        <p class="corent-space-label"><i class="ri-map-pin-2-line"></i> ${escapeHtml(space.name)}</p>
        <form id="corent-form" style="display:grid;gap:14px;margin-top:16px">
          <div class="form-grid">
            <label>日期<input type="date" id="corent-date" required min="${today}" /></label>
            <label>開始時間<input type="time" id="corent-start" required /></label>
            <label>結束時間<input type="time" id="corent-end" required /></label>
            <label>人數（含自己）
              <select id="corent-slots">
                <option value="2">2 人</option>
                <option value="3">3 人</option>
                <option value="4">4 人</option>
                <option value="5">5 人</option>
                <option value="6">6 人</option>
              </select>
            </label>
            <label>每人分攤（元）<input type="number" id="corent-price" min="0" value="0" /></label>
            <label style="grid-column:1/-1">用途說明（選填）
              <input type="text" id="corent-purpose" placeholder="例如：讀書會、練團、拍攝" />
            </label>
          </div>
          <p id="corent-error" class="form-error hidden"></p>
          <button type="submit" id="corent-submit">發起拼場</button>
        </form>
      </div>`
    document.body.appendChild(crModal)

    crModal.querySelector("#corent-modal-close").addEventListener("click", () => crModal.classList.add("hidden"))
    crModal.addEventListener("click", (e) => { if (e.target === crModal) crModal.classList.add("hidden") })

    crModal.querySelector("#corent-form").addEventListener("submit", async (e) => {
      e.preventDefault()
      const errEl     = crModal.querySelector("#corent-error")
      const submitBtn = crModal.querySelector("#corent-submit")
      errEl.classList.add("hidden")
      setButtonLoading(submitBtn, true)

      const payload = {
        space_id:       Number(id),
        date:           crModal.querySelector("#corent-date").value,
        start_time:     crModal.querySelector("#corent-start").value,
        end_time:       crModal.querySelector("#corent-end").value,
        total_slots:    Number(crModal.querySelector("#corent-slots").value),
        price_per_slot: Number(crModal.querySelector("#corent-price").value),
        purpose:        crModal.querySelector("#corent-purpose").value.trim(),
      }
      const res  = await fetch("/api/co-rentals", {
        method: "POST",
        headers: getAuthHeaders(true),
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      setButtonLoading(submitBtn, false)

      if (data.ok) {
        crModal.classList.add("hidden")
        crModal.querySelector("#corent-form").reset()
        const aside   = container.querySelector(".detail-side")
        const successP = document.createElement("p")
        successP.className = "corent-success-msg"
        successP.innerHTML = '<i class="ri-checkbox-circle-line"></i> 拼場已發起！去拼場頁面找夥伴。'
        aside.appendChild(successP)
      } else {
        errEl.textContent = data.message || "發起失敗，請稍後再試"
        errEl.classList.remove("hidden")
      }
    })
  }

  const startCorentBtn = container.querySelector("#start-corent-btn")
  if (startCorentBtn) {
    startCorentBtn.addEventListener("click", () => {
      if (!currentUser) { window.location.href = "/login"; return }
      crModal.classList.remove("hidden")
    })
  }

  // ── 並行載入：評論列表 + 目前使用者的評分狀態 ──────────────────────────────
  const [reviewsResult, myRatingResult] = await Promise.all([
    fetch(`/api/spaces/${id}/reviews`).then((r) => r.json()),
    currentUser
      ? fetch(`/api/spaces/${id}/my-rating`, { headers: getAuthHeaders() }).then((r) => r.json())
      : Promise.resolve({ ok: true, data: null, can_rate: false }),
  ])
  const reviews  = reviewsResult.data  || []
  const myRating = myRatingResult.data          // null | {score, comment}
  const canRate  = myRatingResult.can_rate || false

  const mainCol = container.querySelector(".detail-layout > div")

  // ── helper：把評論陣列轉成 HTML 字串 ────────────────────────────────────
  function reviewListHTML(list) {
    if (!list.length) return `<p style="color:var(--muted)">目前還沒有評論。</p>`
    return `<div class="review-list">${list.map((r) => `
      <div class="review-card">
        <div class="review-header">
          <span class="review-stars">${"★".repeat(r.score)}${"☆".repeat(5 - r.score)}</span>
          <span class="review-user">${escapeHtml(r.user)}</span>
        </div>
        ${r.comment ? `<p class="review-comment">${escapeHtml(r.comment)}</p>` : ""}
      </div>`).join("")}</div>`
  }

  // ── 互動評分區 ──────────────────────────────────────────────────────────
  const ratingSection = document.createElement("section")
  ratingSection.className = "detail-section"

  if (!currentUser) {
    ratingSection.innerHTML = `
      <h2>給出你的評分</h2>
      <p class="rating-hint">
        <a href="/login?next=${encodeURIComponent(`/space?id=${id}`)}">登入</a>後才能評分。
      </p>`
  } else if (!canRate) {
    ratingSection.innerHTML = `
      <h2>給出你的評分</h2>
      <p class="rating-hint">完成預約後才能評分。
        <a href="${currentUser ? `/booking?id=${space.id}` : `/login`}">立即預約</a>
      </p>`
  } else {
    const existScore   = myRating?.score   || 0
    const existComment = myRating?.comment || ""
    ratingSection.innerHTML = `
      <h2>${myRating ? "修改你的評分" : "給出你的評分"}</h2>
      <div class="star-input-row" id="star-input-row">
        ${[1, 2, 3, 4, 5].map((v) =>
          `<span class="star-btn${v <= existScore ? " selected" : ""}" data-v="${v}" title="${v} 顆星">★</span>`
        ).join("")}
      </div>
      <textarea id="rating-comment" rows="3"
        placeholder="分享你的使用體驗（選填）" style="margin-top:0;width:100%">${escapeHtml(existComment)}</textarea>
      <button id="rating-submit-btn" class="btn-primary" style="margin-top:10px;width:100%">
        ${myRating ? "更新評分" : "送出評分"}
      </button>
      <p id="rating-msg" class="hidden" style="font-size:0.9rem;margin-top:8px"></p>`

    let selectedScore = existScore
    const starBtns = [...ratingSection.querySelectorAll(".star-btn")]
    const commentEl = ratingSection.querySelector("#rating-comment")
    const submitBtn = ratingSection.querySelector("#rating-submit-btn")
    const msgEl     = ratingSection.querySelector("#rating-msg")

    // 更新星星的視覺狀態
    function refreshStars(hovered = 0) {
      starBtns.forEach((s) => {
        const v = parseInt(s.dataset.v)
        s.classList.toggle("hovered",  hovered > 0 && v <= hovered)
        s.classList.toggle("selected", hovered === 0 && v <= selectedScore)
      })
    }
    refreshStars()

    starBtns.forEach((s) => {
      const v = parseInt(s.dataset.v)
      s.addEventListener("mouseenter", () => refreshStars(v))
      s.addEventListener("mouseleave", () => refreshStars(0))
      s.addEventListener("click",      () => { selectedScore = v; refreshStars(0) })
    })

    submitBtn.addEventListener("click", async () => {
      msgEl.classList.add("hidden")
      if (!selectedScore) {
        msgEl.textContent = "請先點選星等"
        msgEl.style.color = "#c62828"
        msgEl.classList.remove("hidden"); return
      }
      setButtonLoading(submitBtn, true)
      const res  = await fetch(`/api/spaces/${id}/rate`, {
        method: "POST", headers: getAuthHeaders(true),
        body: JSON.stringify({ score: selectedScore, comment: commentEl.value.trim() }),
      })
      const data = await res.json()
      setButtonLoading(submitBtn, false)
      msgEl.style.color = data.ok ? "var(--primary-dark)" : "#c62828"
      msgEl.textContent = data.message
      msgEl.classList.remove("hidden")
      if (data.ok) {
        submitBtn.textContent = "更新評分"
        ratingSection.querySelector("h2").textContent = "修改你的評分"
        // 重新整理評論列表（反映新評分）
        const newRev = await fetch(`/api/spaces/${id}/reviews`).then((r) => r.json())
        const newList = newRev.data || []
        reviewListContainer.innerHTML = reviewListHTML(newList)
        reviewHeading.textContent = `使用者評論${newList.length ? `（${newList.length} 則）` : ""}`
      }
    })
  }

  // ── 評論列表區 ──────────────────────────────────────────────────────────
  const reviewSection = document.createElement("section")
  reviewSection.className = "detail-section"
  const reviewHeading = document.createElement("h2")
  reviewHeading.textContent = `使用者評論${reviews.length ? `（${reviews.length} 則）` : ""}`
  reviewSection.appendChild(reviewHeading)
  const reviewListContainer = document.createElement("div")
  reviewListContainer.innerHTML = reviewListHTML(reviews)
  reviewSection.appendChild(reviewListContainer)

  mainCol.appendChild(ratingSection)
  mainCol.appendChild(reviewSection)
}

function timeToHour(time) {
  const parts = time.split(":").map(Number)
  return parts[0] + parts[1] / 60
}

// ── 預約確認 Modal：送出前彈出確認視窗，回傳 Promise<boolean> ────────────────
function showBookingConfirmModal({ spaceName, date, startTime, endTime, hours, price }) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div")
    overlay.className = "modal-overlay"
    overlay.innerHTML = `
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="modal-title-text">
        <h2 class="modal-title" id="modal-title-text">確認預約資訊</h2>
        <div class="modal-body">
          <div class="modal-row"><span>空間</span><strong>${escapeHtml(spaceName)}</strong></div>
          <div class="modal-row"><span>日期</span><strong>${escapeHtml(date)}</strong></div>
          <div class="modal-row"><span>時間</span><strong>${escapeHtml(startTime)} – ${escapeHtml(endTime)}</strong></div>
          <div class="modal-row modal-total">
            <span>費用</span>
            <strong>${hours} 小時 × ${formatPrice(price)} = ${formatPrice(hours * price)}</strong>
          </div>
        </div>
        <div class="modal-actions">
          <button class="modal-cancel" type="button">返回修改</button>
          <button class="modal-confirm" type="button">確認送出</button>
        </div>
      </div>`
    document.body.appendChild(overlay)

    const closeModal = (confirmed) => {
      document.removeEventListener("keydown", handleKey)
      overlay.remove()
      resolve(confirmed)
    }

    overlay.querySelector(".modal-cancel").addEventListener("click", () => closeModal(false))
    overlay.querySelector(".modal-confirm").addEventListener("click", () => closeModal(true))
    // 點擊遮罩關閉
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(false) })
    // Esc 關閉
    const handleKey = (e) => { if (e.key === "Escape") closeModal(false) }
    document.addEventListener("keydown", handleKey)
  })
}

// ── Toast 通知：右下角滑入，3.5 秒後自動消失 ─────────────────────────────────
function showToast(message, type = "success") {
  let container = document.querySelector("#toast-container")
  if (!container) {
    container = document.createElement("div")
    container.id = "toast-container"
    document.body.appendChild(container)
  }
  const toast = document.createElement("div")
  toast.className = `toast toast-${type}`
  toast.innerHTML = `<span class="toast-msg">${escapeHtml(message)}</span><button class="toast-close" type="button" aria-label="關閉">×</button>`
  container.prepend(toast)   // 最新的貼在視覺最下方（配合 flex column-reverse）
  const remove = () => {
    toast.style.animation = "toastIn 0.25s ease reverse both"
    setTimeout(() => toast.remove(), 260)
  }
  toast.querySelector(".toast-close").addEventListener("click", remove)
  setTimeout(remove, 3500)
}

// ── 確認對話框：危險操作前彈出，回傳 Promise<boolean> ────────────────────────
function showConfirmDialog(message) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div")
    overlay.className = "modal-overlay"
    overlay.innerHTML = `
      <div class="modal-card confirm-dialog" role="dialog" aria-modal="true">
        <p class="confirm-dialog-msg">${escapeHtml(message)}</p>
        <div class="modal-actions">
          <button class="modal-cancel" type="button">取消</button>
          <button class="modal-confirm confirm-danger" type="button">確認</button>
        </div>
      </div>`
    document.body.appendChild(overlay)
    const close = (result) => {
      document.removeEventListener("keydown", handleKey)
      overlay.remove()
      resolve(result)
    }
    overlay.querySelector(".modal-cancel").addEventListener("click", () => close(false))
    overlay.querySelector(".modal-confirm").addEventListener("click", () => close(true))
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(false) })
    const handleKey = (e) => { if (e.key === "Escape") close(false) }
    document.addEventListener("keydown", handleKey)
  })
}

// ── 平台公告橫幅：有上架公告時自動插入 <main> 頂部 ──────────────────────────
async function loadAnnouncementBanner() {
  const main = document.querySelector("main")
  if (!main) return
  try {
    const res    = await fetch("/api/announcements")
    const result = await res.json()
    const anns   = result.data || []
    if (!anns.length) return
    const wrap = document.createElement("div")
    wrap.className = "container"
    wrap.style.cssText = "padding-top:24px"
    wrap.innerHTML = anns.map((a) => `
      <div class="announcement-banner">
        <strong><i class="ri-megaphone-line"></i> ${escapeHtml(a.title)}</strong>
        ${a.content ? `<p>${escapeHtml(a.content)}</p>` : ""}
      </div>`).join("")
    main.insertBefore(wrap, main.firstChild)
  } catch {}
}

// 初始化預約頁
async function initBookingPage() {
  const currentUser = getCurrentUser()
  if (!currentUser || currentUser.role !== "user") {
    const currentPath = `${window.location.pathname}${window.location.search}`
    window.location.href = `/login?next=${encodeURIComponent(currentPath)}`
    return
  }

  const id          = getQueryParam("id")
  const summary     = document.querySelector("#booking-space-summary")
  const form        = document.querySelector("#booking-form")
  const success     = document.querySelector("#booking-success")
  const startTime   = document.querySelector("#start-time")
  const endTime     = document.querySelector("#end-time")
  const costPreview = document.querySelector("#cost-preview")

  const timeOptions = ["09:00","10:00","11:00","12:00","13:00","14:00","15:00","16:00","17:00","18:00","19:00","20:00"]
  startTime.innerHTML = timeOptions.map((t) => `<option value="${t}">${t}</option>`).join("")
  endTime.innerHTML   = timeOptions.map((t) => `<option value="${t}">${t}</option>`).join("")
  startTime.value = "10:00"
  endTime.value   = "12:00"

  // ── 日期不能選過去 ──────────────────────────────────────────────────────
  const bookingDateInput = document.querySelector("#booking-date")
  const today = new Date().toISOString().slice(0, 10)
  bookingDateInput.min = today    // HTML 原生限制，瀏覽器 date picker 會灰掉過去的日期

  summary.innerHTML = `<span class="skeleton" style="height:18px;width:220px;display:inline-block"></span>`
  const response = await fetch(`/api/spaces/${id}`)
  const result   = await response.json()
  if (!result.ok) { summary.textContent = result.message; form.classList.add("hidden"); return }

  const space = result.data
  summary.textContent = `${space.name} · ${formatPrice(space.price_per_hour)} / 小時`

  function updateCost() {
    const hours = Math.max(timeToHour(endTime.value) - timeToHour(startTime.value), 0)
    costPreview.textContent = `預估費用：${hours} 小時 × ${formatPrice(space.price_per_hour)} = ${formatPrice(hours * space.price_per_hour)}`
  }
  const bookingError    = document.querySelector("#booking-error")
  const availSection    = document.querySelector("#availability-section")
  const availGrid       = document.querySelector("#availability-grid")
  const conflictWarning = document.querySelector("#booking-conflict-warning")
  let lastBooked = []   // 快取最近一次的已訂時段，供時間選擇變動時重新渲染

  // 渲染時段格：同時標示「已佔用」、「您選取的範圍」、以及「衝突」
  function renderAvailGrid(booked) {
    const start = timeToHour(startTime.value)
    const end   = timeToHour(endTime.value)
    const hours = [9,10,11,12,13,14,15,16,17,18,19,20]
    availGrid.innerHTML = hours.map((h) => {
      const isBusy      = booked.some((slot) => timeToHour(slot.start_time) < h + 1 && timeToHour(slot.end_time) > h)
      const isInRange   = end > start && h >= start && h < end   // 在預約時段「內」（不含終點格）
      const isEndPoint  = end > start && h === end               // 結束時間格（邊界標記，此格未被佔用）
      let cls
      if      (isInRange && isBusy)   cls = "time-slot-conflict"  // 內部格 + 已佔用 → 衝突
      else if (isInRange)             cls = "time-slot-selected"  // 內部格 + 空閒 → 選取中
      else if (isEndPoint && !isBusy) cls = "time-slot-end"       // 結束點 + 空閒 → 邊界標記
      else if (isBusy)                cls = "time-slot-busy"      // 其他格 + 已佔用
      else                            cls = "time-slot-free"      // 其他格 + 空閒
      return `<span class="time-slot ${cls}">${h}:00</span>`
    }).join("")
    // 衝突警告
    const hasConflict = end > start && booked.some((slot) =>
      timeToHour(slot.start_time) < end && timeToHour(slot.end_time) > start
    )
    if (conflictWarning) {
      conflictWarning.innerHTML = hasConflict ? '<i class="ri-alert-line"></i> 您選擇的時段與現有預約重疊，請調整時間' : ""
      conflictWarning.classList.toggle("hidden", !hasConflict)
    }
  }

  // 時間選擇變動時，同步更新費用預估 + 時段格顯示
  function onTimeChange() {
    updateCost()
    if (!availSection.classList.contains("hidden")) renderAvailGrid(lastBooked)
  }
  startTime.addEventListener("change", onTimeChange)
  endTime.addEventListener("change", onTimeChange)
  updateCost()

  async function updateAvailability() {
    const date = bookingDateInput.value
    if (!date) { availSection.classList.add("hidden"); return }
    const res    = await fetch(`/api/spaces/${id}/availability?date=${date}`)
    const result = await res.json()
    lastBooked = result.data || []
    renderAvailGrid(lastBooked)
    availSection.classList.remove("hidden")
  }
  bookingDateInput.addEventListener("change", updateAvailability)

  const submitBtn = form.querySelector("button[type='submit']")
  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    bookingError.classList.add("hidden")
    if (startTime.value >= endTime.value) {
      bookingError.textContent = "結束時間必須晚於開始時間"
      bookingError.classList.remove("hidden")
      return
    }
    // 前端衝突攔截：若與現有預約時段重疊則直接阻止，不進 Modal
    if (lastBooked.length > 0) {
      const startH = timeToHour(startTime.value)
      const endH   = timeToHour(endTime.value)
      if (lastBooked.some((slot) => timeToHour(slot.start_time) < endH && timeToHour(slot.end_time) > startH)) {
        bookingError.textContent = "您選擇的時段與現有預約重疊，請調整開始或結束時間。"
        bookingError.classList.remove("hidden")
        return
      }
    }

    // ── 預約確認 Modal：讓使用者核對資訊後再送出 ──────────────────────────
    const hours = Math.max(timeToHour(endTime.value) - timeToHour(startTime.value), 0)
    const confirmed = await showBookingConfirmModal({
      spaceName: space.name,
      date: bookingDateInput.value,
      startTime: startTime.value,
      endTime: endTime.value,
      hours,
      price: space.price_per_hour,
    })
    if (!confirmed) return   // 使用者點「返回修改」，不送出

    setButtonLoading(submitBtn, true)   // 防止重複送出
    const res    = await fetch("/api/bookings", {
      method: "POST",
      headers: getAuthHeaders(true),
      body: JSON.stringify({
        space_id: space.id, space_name: space.name,
        date: bookingDateInput.value,
        start_time: startTime.value, end_time: endTime.value,
        purpose: document.querySelector("#booking-purpose").value,
        user_email: currentUser.email,
      }),
    })
    const data = await res.json()
    if (!data.ok) {
      // token 在伺服器端失效（另一裝置重新登入、DB 變動等）→ 清除並導向登入頁
      if (data.message === "請先登入" || data.message === "未授權") {
        clearCurrentUser()
        window.location.href = `/login?expired=1&next=${encodeURIComponent(window.location.pathname + window.location.search)}`
        return
      }
      bookingError.textContent = data.message
      bookingError.classList.remove("hidden")
      setButtonLoading(submitBtn, false)  // 失敗時恢復按鈕
      return
    }
    form.classList.add("hidden")
    success.classList.remove("hidden")
  })
}

// 初始化管理員中心
async function initDashboardPage() {
  const adminUser = requireRole("admin")
  if (!adminUser) return

  const adminContent       = document.querySelector("#admin-content")
  const logoutButton       = document.querySelector("#admin-logout-button")
  const adminStats         = document.querySelector("#admin-stats")
  const bookingList        = document.querySelector("#booking-list")
  const adminSpaceList     = document.querySelector("#admin-space-list")
  const adminUserList      = document.querySelector("#admin-user-list")
  const contactMessageList = document.querySelector("#contact-message-list")

  adminContent.classList.remove("hidden")

  async function loadBookings(page = 1) {
    const q        = (document.querySelector("#booking-search")?.value || "").trim()
    bookingList.innerHTML = skeletonBookingCards(3)
    const response    = await fetch(`/api/bookings?page=${page}&per_page=15&search=${encodeURIComponent(q)}`, { headers: getAuthHeaders() })
    const result      = await response.json()
    const allBookings = result.data || []
    const statusClass = { "待確認":"status-pending","已確認":"status-confirmed","已完成":"status-done","已取消":"status-cancelled","已拒絕":"status-rejected" }

    function renderBookings(list) {
      bookingList.innerHTML = list.length
        ? list.map((b) => `
          <article class="booking-card">
            <div>
              <span class="status ${statusClass[b.status] || "status-pending"}">${escapeHtml(b.status)}</span>
              <code class="entity-code">${formatCode("B", b.id)}</code>
              <h2>${escapeHtml(b.space_name)}</h2>
              <p>${escapeHtml(b.date)} · ${escapeHtml(b.start_time)} - ${escapeHtml(b.end_time)}</p>
            </div>
            <div class="booking-actions">
              <p>${escapeHtml(b.purpose)}</p>
              <small>${escapeHtml(b.user_email || "未登入使用者")}</small>
              ${!["已完成","已取消","已拒絕"].includes(b.status)
                ? `<button class="admin-cancel-booking-btn confirm-button" data-booking-id="${b.id}" style="background:#b3261e">強制取消</button>`
                : ""}
            </div>
          </article>`).join("")
        : emptyState("clipboard", "目前沒有預約紀錄", "使用者送出的預約都會出現在這裡。")

      // 強制取消：管理員介入糾紛用，會寄通知給預約人
      document.querySelectorAll(".admin-cancel-booking-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!await showConfirmDialog("確定要強制取消這筆預約嗎？系統將自動寄通知給預約人。")) return
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/admin/bookings/${btn.dataset.bookingId}/cancel`, { method: "POST", headers: getAuthHeaders(true) })
          const data = await res.json()
          if (data.ok) { showToast("預約已強制取消"); await loadBookings(); await loadAdminStats() }
          else { showToast(data.message, "error"); setButtonLoading(btn, false) }
        })
      })
    }

    const bookingSearch = document.querySelector("#booking-search")
    bookingSearch.oninput = () => loadBookings(1)   // 觸發後端全量搜尋，不受當前頁限制
    renderBookings(allBookings)
    renderPagination("booking-pagination", result.page, result.total_pages, loadBookings)
  }

  async function loadContacts(page = 1) {
    const q        = (document.querySelector("#contact-search")?.value || "").trim()
    contactMessageList.innerHTML = skeletonBookingCards(2)
    const response    = await fetch(`/api/contacts?page=${page}&per_page=15&search=${encodeURIComponent(q)}`, { headers: getAuthHeaders() })
    const result      = await response.json()
    const allContacts = result.data || []

    function renderContacts(list) {
      contactMessageList.innerHTML = list.length
        ? list.map((m) => `
          <article class="booking-card contact-card">
            <div>
              <span class="status status-confirmed">聯絡訊息</span>
              <code class="entity-code">${formatCode("C", m.id)}</code>
              <h2>${escapeHtml(m.name)}</h2>
              <p>${escapeHtml(m.email)} · ${escapeHtml(m.created_at)}</p>
            </div>
            <p>${escapeHtml(m.message)}</p>
            <button class="delete-contact-button" data-contact-id="${m.id}">刪除</button>
          </article>`).join("")
        : emptyState("mail", "目前尚無聯絡訊息", "使用者送出的聯絡訊息會出現在這裡。")

      document.querySelectorAll(".delete-contact-button").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!await showConfirmDialog("確定要刪除這則聯絡訊息嗎？")) return
          setButtonLoading(btn, true)
          await fetch(`/api/contacts/${btn.dataset.contactId}`, { method: "DELETE", headers: getAuthHeaders() })
          await loadContacts(); await loadAdminStats()
        })
      })
    }

    const contactSearch = document.querySelector("#contact-search")
    if (contactSearch) {
      contactSearch.oninput = () => loadContacts(1)   // 觸發後端全量搜尋
    }
    renderContacts(allContacts)
    renderPagination("contact-pagination", result.page, result.total_pages, loadContacts)
  }

  async function loadSpacesForAdmin(page = 1) {
    const q        = (document.querySelector("#space-search")?.value || "").trim()
    adminSpaceList.innerHTML = skeletonAdminSpaceCards(3)
    try {
      const response = await fetch(`/api/admin/spaces?page=${page}&per_page=10&search=${encodeURIComponent(q)}`, { headers: getAuthHeaders() })
      const result   = await response.json()

      function renderSpaces(list) {
        adminSpaceList.innerHTML = list.length
          ? list.map((space) => `
            <article class="admin-space-card" data-id="${space.id}">
              <img class="admin-space-image" src="${space.image}" alt="${escapeHtml(space.name)}">
              <div class="admin-space-body">
                <div class="admin-space-meta">
                  <span class="status ${space.status === "待確認" ? "status-pending" : "status-confirmed"}">${escapeHtml(space.status)}</span>
                  <span class="space-type-label">${escapeHtml(space.type)}</span>
                  <code class="entity-code">${formatCode("S", space.id)}</code>
                </div>
                <h2>${escapeHtml(space.name)}</h2>
                <p>${escapeHtml(space.city)} ${escapeHtml(space.district)} · 最多 ${space.capacity} 人</p>
                <strong>${formatPrice(space.price_per_hour)} / 小時</strong>
              </div>
              <div class="admin-space-actions">
                ${space.status === "待確認" ? `<button class="confirm-space-button" data-space-id="${space.id}">確認上架</button>` : ""}
                <button class="delete-space-button" data-space-id="${space.id}">刪除</button>
              </div>
            </article>`).join("")
          : emptyState("building", "目前沒有任何空間資料", "上架的空間審核後會顯示在這裡。")

        document.querySelectorAll(".confirm-space-button").forEach((btn) => {
          btn.addEventListener("click", async () => {
            setButtonLoading(btn, true)
            await fetch(`/api/spaces/${btn.dataset.spaceId}/confirm`, { method: "POST", headers: getAuthHeaders(true) })
            await loadSpacesForAdmin(); await loadAdminStats()
          })
        })

        document.querySelectorAll(".delete-space-button").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const space = result.data.find((s) => String(s.id) === String(btn.dataset.spaceId))
            if (!await showConfirmDialog(`確定要刪除「${space?.name || "此空間"}」嗎？`)) return
            setButtonLoading(btn, true)
            await fetch(`/api/spaces/${btn.dataset.spaceId}`, { method: "DELETE", headers: getAuthHeaders() })
            await loadSpacesForAdmin(); await loadAdminStats()
          })
        })

        // 管理員不直接編輯空間內容（由場地主自行管理），只負責審核與下架
      }

      const spaceSearch = document.querySelector("#space-search")
      spaceSearch.oninput = () => loadSpacesForAdmin(1)   // 觸發後端全量搜尋
      renderSpaces(result.data || [])
      renderPagination("space-pagination", result.page, result.total_pages, loadSpacesForAdmin)
    } catch (err) {
      adminSpaceList.innerHTML = `<div class="success-box">空間資料載入失敗，請重新整理頁面。</div>`
    }
  }

  async function loadAdminStats() {
    adminStats.innerHTML = skeletonStatCards(6)
    const res = await fetch("/api/admin/stats", { headers: getAuthHeaders() })
    const s   = await res.json()
    if (!s.ok) return
    adminStats.innerHTML = `
      <article class="stat-card"><strong>${s.total_spaces}</strong><span>總空間數</span></article>
      <article class="stat-card"><strong>${s.pending_spaces}</strong><span>待審核空間</span></article>
      <article class="stat-card"><strong>${s.confirmed_spaces}</strong><span>已公開空間</span></article>
      <article class="stat-card"><strong>${s.total_bookings}</strong><span>預約總數</span></article>
      <article class="stat-card"><strong>${s.open_co_rentals ?? 0}</strong><span>進行中拼場</span></article>
      <article class="stat-card"><strong>${s.total_contacts}</strong><span>聯絡訊息</span></article>
      <article class="stat-card"><strong>${s.total_users}</strong><span>會員總數</span></article>`
    // 顯示最後更新時間，讓管理員知道數字是即時的
    const tsEl = document.querySelector("#stats-updated-at")
    if (tsEl) tsEl.textContent = `自動更新中 · 上次更新：${new Date().toLocaleTimeString("zh-TW")}`
  }

  async function loadAdminUsers(page = 1) {
    const q      = (document.querySelector("#user-search")?.value || "").trim()
    adminUserList.innerHTML = skeletonBookingCards(3)
    const res    = await fetch(`/api/admin/users?page=${page}&per_page=15&search=${encodeURIComponent(q)}`, { headers: getAuthHeaders() })
    const result = await res.json()
    if (!result.ok) { adminUserList.innerHTML = `<div class="success-box">${escapeHtml(result.message)}</div>`; return }
    const allUsers = result.data || []

    function renderUsers(list) {
      adminUserList.innerHTML = list.length
        ? list.map((u) => {
          const isPro     = u.plan === "pro"
          const planLabel = isPro ? "專業" : "免費"
          const planClass = isPro ? "pro" : "free"
          const expStr    = isPro && u.plan_expires_at ? `到 ${u.plan_expires_at.slice(0,10)}` : ""
          return `
          <article class="booking-card">
            <div>
              <span class="status ${u.role === "admin" ? "status-confirmed" : (u.banned ? "status-cancelled" : "status-pending")}">
                ${u.role === "admin" ? "管理員" : (u.banned ? "已停用" : "會員")}
              </span>
              <span class="plan-badge ${planClass}" style="margin-left:6px">${planLabel}${expStr ? ` · ${expStr}` : ""}</span>
              <code class="entity-code">${formatCode("U", u.id)}</code>
              <h2>${escapeHtml(u.name)}</h2>
              <p>${escapeHtml(u.email)}</p>
            </div>
            ${u.role !== "admin" ? `
            <div class="booking-actions">
              ${isPro
                ? `<button class="downgrade-user-btn" data-email="${escapeHtml(u.email)}" style="background:var(--muted);font-size:0.82rem">降回免費</button>`
                : `<button class="upgrade-user-btn" data-email="${escapeHtml(u.email)}" style="background:var(--primary);font-size:0.82rem">升級 Pro</button>`}
              ${u.banned
                ? `<button class="unban-user-btn" data-user-id="${u.id}" style="background:var(--primary)">解除停用</button>`
                : `<button class="ban-user-btn confirm-button" data-user-id="${u.id}" style="background:#b3261e">停用帳號</button>`}
            </div>` : ""}
          </article>`}).join("")
        : emptyState("users", "目前沒有任何會員", "新會員註冊後會出現在這裡。")

      document.querySelectorAll(".ban-user-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!await showConfirmDialog("確定要停用此帳號嗎？該使用者將無法登入也無法進行任何操作。")) return
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/admin/users/${btn.dataset.userId}/ban`, { method: "POST", headers: getAuthHeaders(true) })
          const data = await res.json()
          if (data.ok) { showToast("帳號已停用"); await loadAdminUsers() }
          else { showToast(data.message, "error"); setButtonLoading(btn, false) }
        })
      })
      document.querySelectorAll(".unban-user-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/admin/users/${btn.dataset.userId}/unban`, { method: "POST", headers: getAuthHeaders(true) })
          const data = await res.json()
          if (data.ok) { showToast("帳號已恢復"); await loadAdminUsers() }
          else { showToast(data.message, "error"); setButtonLoading(btn, false) }
        })
      })
      document.querySelectorAll(".upgrade-user-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const months = prompt(`升級 ${btn.dataset.email} 為專業方案，幾個月？（預設 1）`, "1")
          if (months === null) return
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/admin/users/${encodeURIComponent(btn.dataset.email)}/set-plan`, {
            method: "POST", headers: getAuthHeaders(true),
            body: JSON.stringify({ plan: "pro", months: parseInt(months) || 1 }),
          })
          const data = await res.json()
          if (data.ok) { showToast("已升級為專業方案 ✅"); await loadAdminUsers() }
          else { showToast(data.message, "error"); setButtonLoading(btn, false) }
        })
      })
      document.querySelectorAll(".downgrade-user-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!await showConfirmDialog(`確定要將 ${btn.dataset.email} 降回免費方案嗎？`)) return
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/admin/users/${encodeURIComponent(btn.dataset.email)}/set-plan`, {
            method: "POST", headers: getAuthHeaders(true),
            body: JSON.stringify({ plan: "free", months: 0 }),
          })
          const data = await res.json()
          if (data.ok) { showToast("已降回免費方案"); await loadAdminUsers() }
          else { showToast(data.message, "error"); setButtonLoading(btn, false) }
        })
      })
    }

    const userSearch = document.querySelector("#user-search")
    if (userSearch) {
      userSearch.oninput = () => loadAdminUsers(1)   // 觸發後端全量搜尋
    }
    renderUsers(allUsers)
    renderPagination("user-pagination", result.page, result.total_pages, loadAdminUsers)
  }

  logoutButton.addEventListener("click", () => { clearCurrentUser(); window.location.href = "/login" })

  // ── 公告管理：管理員可發布 / 下架平台公告，首頁與探索頁頂部顯示 ──────────────
  async function loadAnnouncements() {
    const compose = document.querySelector("#announcement-compose")
    const list    = document.querySelector("#announcement-list")
    if (!compose || !list) return

    // 撰寫表單（只注入一次）
    if (!compose.querySelector("#ann-title")) {
      compose.innerHTML = `
        <div class="announce-compose">
          <label style="color:var(--muted);font-weight:700">
            公告標題
            <input id="ann-title" type="text" placeholder="輸入公告標題…">
          </label>
          <label style="color:var(--muted);font-weight:700">
            公告內容（選填）
            <textarea id="ann-content" rows="3" placeholder="補充說明…"></textarea>
          </label>
          <div style="display:flex;align-items:center;gap:12px">
            <button id="ann-submit-btn" type="button" style="min-height:38px;padding:0 20px">發布公告</button>
            <p id="ann-error" class="form-error hidden"></p>
          </div>
        </div>`

      compose.querySelector("#ann-submit-btn").addEventListener("click", async () => {
        const btn      = compose.querySelector("#ann-submit-btn")
        const errEl    = compose.querySelector("#ann-error")
        const title    = compose.querySelector("#ann-title").value.trim()
        const content  = compose.querySelector("#ann-content").value.trim()
        if (!title) {
          errEl.textContent = "請填寫公告標題"; errEl.classList.remove("hidden"); return
        }
        errEl.classList.add("hidden")
        setButtonLoading(btn, true)
        const res  = await fetch("/api/admin/announcements", {
          method: "POST", headers: getAuthHeaders(true),
          body: JSON.stringify({ title, content }),
        })
        const data = await res.json()
        setButtonLoading(btn, false)
        if (data.ok) {
          compose.querySelector("#ann-title").value   = ""
          compose.querySelector("#ann-content").value = ""
          showToast("公告已發布")
          await loadAnnouncements()
        } else {
          errEl.textContent = data.message; errEl.classList.remove("hidden")
        }
      })
    }

    // 公告清單
    const res    = await fetch("/api/announcements")
    const result = await res.json()
    const anns   = result.data || []
    list.innerHTML = anns.length
      ? anns.map((a) => `
        <article class="booking-card">
          <div>
            <span class="status status-confirmed">上架中</span>
            <h2>${escapeHtml(a.title)}</h2>
            ${a.content ? `<p>${escapeHtml(a.content)}</p>` : ""}
            <small style="color:var(--muted)">${escapeHtml(a.created_at)}</small>
          </div>
          <div class="booking-actions">
            <button class="delete-ann-btn" data-ann-id="${a.id}" style="background:#b3261e;min-height:38px;padding:0 16px">下架</button>
          </div>
        </article>`).join("")
      : emptyState("mail", "目前沒有公告", "發布後，首頁與探索頁頂部會顯示公告橫幅。")

    list.querySelectorAll(".delete-ann-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!await showConfirmDialog("確定要下架此公告嗎？")) return
        setButtonLoading(btn, true)
        await fetch(`/api/admin/announcements/${btn.dataset.annId}`, { method: "DELETE", headers: getAuthHeaders() })
        showToast("公告已下架")
        await loadAnnouncements()
      })
    })
  }

  // ── 區塊收合：點擊右側箭頭可折疊 / 展開各區塊，節省長頁面的捲動距離 ────────
  function initCollapsible() {
    document.querySelectorAll("#admin-content .admin-heading-row.contact-heading").forEach((heading) => {
      const btn = document.createElement("button")
      btn.className = "section-toggle"
      btn.setAttribute("type", "button")
      btn.setAttribute("aria-expanded", "true")
      btn.textContent = "▲"
      heading.appendChild(btn)

      // 收集此 heading 之後、下一個 heading 之前的所有 sibling（即本區塊內容容器）
      const siblings = []
      let el = heading.nextElementSibling
      while (el && !el.classList.contains("admin-heading-row")) {
        siblings.push(el)
        el = el.nextElementSibling
      }

      let open = true
      btn.addEventListener("click", () => {
        open = !open
        siblings.forEach((s) => (s.style.display = open ? "" : "none"))
        btn.textContent = open ? "▲" : "▼"
        btn.setAttribute("aria-expanded", String(open))
      })
    })
  }

  // ── 拼場管理 ────────────────────────────────────────────────────────────────
  const adminCrList = document.querySelector("#admin-co-rental-list")
  async function loadAdminCoRentals(page = 1) {
    if (!adminCrList) return
    const q   = (document.querySelector("#co-rental-search")?.value || "").trim()
    adminCrList.innerHTML = skeletonBookingCards(3)
    const res  = await fetch(`/api/admin/co-rentals?page=${page}&per_page=15&search=${encodeURIComponent(q)}`, { headers: getAuthHeaders() })
    const data = await res.json()
    const items = data.data || []
    const statusLabel = { open: "開放中", full: "已額滿", closed: "已關閉" }
    const statusClass = { open: "status-confirmed", full: "status-pending", closed: "status-cancelled" }
    adminCrList.innerHTML = items.length
      ? items.map((cr) => `
        <article class="booking-card">
          <div>
            <span class="status ${statusClass[cr.status] || "status-pending"}">${statusLabel[cr.status] || cr.status}</span>
            <h2>${escapeHtml(cr.space_name)}</h2>
            <p>${escapeHtml(cr.date)} · ${escapeHtml(cr.start_time)}–${escapeHtml(cr.end_time)} · ${escapeHtml(cr.space_city)}</p>
            <p>發起人：${escapeHtml(cr.organizer_email)} · ${cr.filled_slots}/${cr.total_slots} 人 · ${formatPrice(cr.price_per_slot)}/人</p>
            ${cr.purpose ? `<p style="color:var(--muted);font-size:0.85rem">${escapeHtml(cr.purpose)}</p>` : ""}
          </div>
          ${cr.status === "open" ? `
          <div class="booking-actions">
            <button class="admin-cancel-cr-btn" data-id="${cr.id}" style="background:#b3261e">強制關閉</button>
          </div>` : ""}
        </article>`).join("")
      : emptyState("group", "目前沒有拼場資料", "使用者發起拼場後會出現在這裡。")

    adminCrList.querySelectorAll(".admin-cancel-cr-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!await showConfirmDialog("確定要強制關閉這個拼場嗎？")) return
        setButtonLoading(btn, true)
        const r = await fetch(`/api/co-rentals/${btn.dataset.id}`, { method: "DELETE", headers: getAuthHeaders() })
        const d = await r.json()
        if (d.ok) { showToast("拼場已關閉"); loadAdminCoRentals() }
        else { showToast(d.message || "操作失敗", "error"); setButtonLoading(btn, false) }
      })
    })

    const crSearch = document.querySelector("#co-rental-search")
    if (crSearch && !crSearch.dataset.bound) {
      crSearch.dataset.bound = "1"
      crSearch.oninput = () => loadAdminCoRentals(1)
    }
    renderPagination("co-rental-admin-pagination", data.page, data.total_pages, loadAdminCoRentals)
  }

  await loadAdminStats()
  await loadBookings()
  await loadSpacesForAdmin()
  await loadAdminCoRentals()
  await loadAdminUsers()
  await loadContacts()
  await loadAnnouncements()
  initCollapsible()   // 所有內容容器都已存在後才注入收合按鈕

  // ── 自動 polling：每 60 秒靜默更新統計數字與公告，不干擾其他列表 ──────────────
  const _autoRefreshInterval = setInterval(async () => {
    await loadAdminStats()
    await loadAnnouncements()
  }, 60_000)
  // 離頁時清除計時器，避免記憶體洩漏
  window.addEventListener("beforeunload", () => clearInterval(_autoRefreshInterval), { once: true })
}

// 初始化聯絡頁
function initContactPage() {
  const form       = document.querySelector("#contact-form")
  const success    = document.querySelector("#contact-success")
  const submitBtn  = form.querySelector("button[type='submit']")
  const questionEl = document.querySelector("#captcha-question")
  const refreshBtn = document.querySelector("#captcha-refresh")
  const idInput    = document.querySelector("#captcha-id")

  fetchChallenge(questionEl, idInput)
  refreshBtn?.addEventListener("click", () => fetchChallenge(questionEl, idInput))

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    setButtonLoading(submitBtn, true)
    const response = await fetch("/api/contact", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:           document.querySelector("#contact-name").value,
        email:          document.querySelector("#contact-email").value,
        message:        document.querySelector("#contact-message").value,
        hp:             document.querySelector("#hp").value,
        captcha_id:     idInput.value,
        captcha_answer: document.querySelector("#captcha-answer").value,
      }),
    })
    const result = await response.json()
    if (!result.ok) {
      // 驗證碼錯誤時重新取得，讓使用者可以再試
      fetchChallenge(questionEl, idInput)
      setButtonLoading(submitBtn, false)
      alert(result.message)
      return
    }
    form.classList.add("hidden")
    success.textContent = result.message
    success.classList.remove("hidden")
  })
}

// 初始化上架頁
function initHostPage() {
  const currentUser = getCurrentUser()
  if (!currentUser || currentUser.role !== "user") { window.location.href = "/login"; return }

  const form             = document.querySelector("#host-form")
  const success          = document.querySelector("#host-success")
  const imageInput       = document.querySelector("#host-image")
  const imageError       = document.querySelector("#host-image-error")
  const previewContainer = document.querySelector("#host-image-preview")
  const submitBtn        = form.querySelector("button[type='submit']")
  const MAX_COUNT        = 5
  const MAX_SIZE         = 2 * 1024 * 1024

  // ── 圖片預覽：選完檔案後立即顯示縮圖 ──────────────────────────────────────
  imageInput.addEventListener("change", () => {
    const files = Array.from(imageInput.files)
    previewContainer.innerHTML = files.map((file) =>
      `<img class="preview-thumb" src="${URL.createObjectURL(file)}" alt="預覽">`
    ).join("")
  })

  function readImageAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload  = () => resolve(reader.result)
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    imageError.classList.add("hidden")
    const imageFiles = Array.from(imageInput.files)
    if (imageFiles.length > MAX_COUNT) {
      imageError.textContent = `最多只能上傳 ${MAX_COUNT} 張圖片，目前選了 ${imageFiles.length} 張`
      imageError.classList.remove("hidden"); return
    }
    const oversized = imageFiles.filter((f) => f.size > MAX_SIZE)
    if (oversized.length) {
      imageError.textContent = `以下圖片超過 2MB：${oversized.map((f) => f.name).join("、")}`
      imageError.classList.remove("hidden"); return
    }
    setButtonLoading(submitBtn, true)
    const images   = await Promise.all(imageFiles.map(readImageAsDataUrl))
    const latVal = parseFloat(document.querySelector("#host-lat")?.value)
    const lngVal = parseFloat(document.querySelector("#host-lng")?.value)
    const response = await fetch("/api/spaces", {
      method: "POST", headers: getAuthHeaders(true),
      body: JSON.stringify({
        name:          document.querySelector("#host-name").value,
        city:          document.querySelector("#host-city").value,
        district:      document.querySelector("#host-district").value,
        address:       document.querySelector("#host-address").value.trim(),
        type:          document.querySelector("#host-type").value,
        price_per_hour: Number(document.querySelector("#host-price").value),
        capacity:      Number(document.querySelector("#host-capacity").value),
        equipment:     document.querySelector("#host-equipment").value.split("、"),
        images,
        description:   document.querySelector("#host-description").value,
        lat:           isNaN(latVal) ? null : latVal,
        lng:           isNaN(lngVal) ? null : lngVal,
      }),
    })
    const result = await response.json()
    setButtonLoading(submitBtn, false)
    if (!result.ok) {
      if (result.upgrade_required) {
        form.classList.add("hidden")
        success.innerHTML = `
          <strong>免費方案上限</strong><br>
          免費方案只能上架 1 個空間。<br>
          <a href="/pricing" style="color:var(--primary);font-weight:700">升級專業方案 →</a>
          即可無限上架。`
        success.style.background = "#fff8e1"
        success.style.borderColor = "#f5a623"
      } else {
        success.textContent = result.message || "上架失敗，請稍後再試"
        success.style.background = "#ffebee"
        success.style.borderColor = "#c62828"
        form.classList.add("hidden")
      }
      success.classList.remove("hidden")
      return
    }
    form.classList.add("hidden")
    success.textContent = result.message
    success.classList.remove("hidden")
  })
}

// 初始化登入頁
function initLoginPage() {
  const form       = document.querySelector("#login-form")
  const error      = document.querySelector("#login-error")
  const submitBtn  = form.querySelector("button[type='submit']")
  const questionEl = document.querySelector("#captcha-question")
  const refreshBtn = document.querySelector("#captcha-refresh")
  const idInput    = document.querySelector("#captcha-id")

  fetchChallenge(questionEl, idInput)
  refreshBtn?.addEventListener("click", () => fetchChallenge(questionEl, idInput))

  if (getQueryParam("expired")) {
    error.textContent = "登入已過期，請重新登入"
    error.classList.remove("hidden")
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    error.classList.add("hidden")
    setButtonLoading(submitBtn, true)
    const remember = document.querySelector("#login-remember")?.checked ?? true
    const response = await fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email:          document.querySelector("#login-email").value,
        password:       document.querySelector("#login-password").value,
        hp:             document.querySelector("#hp").value,
        captcha_id:     idInput.value,
        captcha_answer: document.querySelector("#captcha-answer").value,
        remember,
      }),
    })
    const result = await response.json()
    if (!result.ok) {
      error.textContent = result.message
      error.classList.remove("hidden")
      setButtonLoading(submitBtn, false)
      fetchChallenge(questionEl, idInput)   // 失敗後重取驗證碼
      return
    }
    setCurrentUser(result.user, remember)
    const nextPage = getQueryParam("next")
    const safePage = nextPage && nextPage.startsWith("/") ? nextPage : "/user"
    window.location.href = result.user.role === "admin" ? "/dashboard" : safePage
  })
}

// 初始化註冊頁
function initRegisterPage() {
  const form       = document.querySelector("#register-form")
  const error      = document.querySelector("#register-error")
  const success    = document.querySelector("#register-success")
  const submitBtn  = form.querySelector("button[type='submit']")
  const questionEl = document.querySelector("#captcha-question")
  const refreshBtn = document.querySelector("#captcha-refresh")
  const idInput    = document.querySelector("#captcha-id")

  fetchChallenge(questionEl, idInput)
  refreshBtn?.addEventListener("click", () => fetchChallenge(questionEl, idInput))

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    const pw = document.querySelector("#register-password").value
    if (pw.length < 6) {
      error.textContent = "密碼至少需要 6 個字元"
      error.classList.remove("hidden"); return
    }
    error.classList.add("hidden")
    setButtonLoading(submitBtn, true)
    const response = await fetch("/api/auth/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:           document.querySelector("#register-name").value,
        email:          document.querySelector("#register-email").value,
        password:       pw,
        hp:             document.querySelector("#hp").value,
        captcha_id:     idInput.value,
        captcha_answer: document.querySelector("#captcha-answer").value,
      }),
    })
    const result = await response.json()
    if (!result.ok) {
      error.textContent = result.message
      error.classList.remove("hidden")
      setButtonLoading(submitBtn, false)
      fetchChallenge(questionEl, idInput)
      return
    }
    if (result.needs_verification) {
      form.classList.add("hidden")
      if (success) {
        success.innerHTML = '<i class="ri-award-fill"></i> ' + escapeHtml(result.message)
        success.classList.remove("hidden")
      }
    } else {
      setCurrentUser(result.user)
      window.location.href = "/user"
    }
  })
}

// 初始化信箱驗證頁
async function initVerifyEmailPage() {
  const token    = getQueryParam("token")
  const resultEl = document.querySelector("#verify-result")

  if (!token) {
    resultEl.innerHTML = `
      <div class="success-box" style="background:#fff0f0;color:#b3261e">
        <p><i class="ri-close-circle-line"></i> 無效的驗證連結，請重新申請。</p>
        <p style="margin-top:10px"><a href="/register">返回註冊頁面</a></p>
      </div>`
    return
  }

  resultEl.innerHTML = `<div class="success-box">驗證中，請稍候…</div>`

  try {
    const res  = await fetch(`/api/auth/verify-email?token=${encodeURIComponent(token)}`)
    const data = await res.json()
    if (data.ok) {
      resultEl.innerHTML = `
        <div class="success-box">
          <p>✅ ${escapeHtml(data.message)}</p>
          <p style="margin-top:10px;color:var(--muted);font-size:0.9rem">3 秒後自動前往登入頁…</p>
          <p style="margin-top:6px"><a href="/login">立即前往登入</a></p>
        </div>`
      setTimeout(() => { window.location.href = "/login" }, 3000)
    } else {
      resultEl.innerHTML = `
        <div class="success-box" style="background:#fff0f0;color:#b3261e">
          <p><i class="ri-close-circle-line"></i> ${escapeHtml(data.message)}</p>
          <p style="margin-top:10px"><a href="/register">重新註冊</a></p>
        </div>`
    }
  } catch {
    resultEl.innerHTML = `
      <div class="success-box" style="background:#fff0f0;color:#b3261e">
        驗證失敗，請稍後再試。
      </div>`
  }
}

// 月曆
function renderCalendar(container, year, month, bookings) {
  const sc = { "待確認":"status-pending","已確認":"status-confirmed","已完成":"status-done","已取消":"status-cancelled","已拒絕":"status-rejected" }
  const bookingMap = {}
  bookings.forEach((b) => { if (!bookingMap[b.date]) bookingMap[b.date] = []; bookingMap[b.date].push(b) })

  const monthNames = ["一月","二月","三月","四月","五月","六月","七月","八月","九月","十月","十一月","十二月"]
  const weekdays   = ["日","一","二","三","四","五","六"]
  const firstDay   = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const today      = new Date().toISOString().slice(0, 10)

  const cells = Array(firstDay).fill(`<div class="cal-day empty"></div>`)
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr    = `${year}-${String(month + 1).padStart(2,"0")}-${String(d).padStart(2,"0")}`
    const dayBookings = bookingMap[dateStr] || []
    const dots       = dayBookings.map((b) => `<span class="status-dot ${sc[b.status] || ""}"></span>`).join("")
    cells.push(`<div class="cal-day ${dateStr === today ? "cal-today" : ""}" data-date="${dateStr}"><span class="cal-day-num">${d}</span><div class="cal-dots">${dots}</div></div>`)
  }

  container.innerHTML = `
    <div class="cal-header">
      <button class="cal-nav" id="cal-prev">‹</button>
      <span class="cal-title">${year}年 ${monthNames[month]}</span>
      <button class="cal-nav" id="cal-next">›</button>
    </div>
    <div class="cal-grid">
      ${weekdays.map((w) => `<div class="cal-weekday">${w}</div>`).join("")}
      ${cells.join("")}
    </div>
    <div id="cal-detail" class="cal-detail hidden"></div>`

  container.querySelector("#cal-prev").addEventListener("click", () => {
    renderCalendar(container, month === 0 ? year - 1 : year, month === 0 ? 11 : month - 1, bookings)
  })
  container.querySelector("#cal-next").addEventListener("click", () => {
    renderCalendar(container, month === 11 ? year + 1 : year, month === 11 ? 0 : month + 1, bookings)
  })
  container.querySelectorAll(".cal-day:not(.empty)").forEach((day) => {
    day.addEventListener("click", () => {
      const dayBookings = bookingMap[day.dataset.date] || []
      const detail = container.querySelector("#cal-detail")
      if (!dayBookings.length) { detail.classList.add("hidden"); return }
      detail.innerHTML = `
        <p class="cal-detail-date">${day.dataset.date} 的預約</p>
        ${dayBookings.map((b) => `
          <div class="cal-detail-item">
            <span class="status ${sc[b.status] || "status-pending"}">${escapeHtml(b.status)}</span>
            <strong>${escapeHtml(b.space_name)}</strong>
            <span>${escapeHtml(b.start_time)} – ${escapeHtml(b.end_time)}</span>
          </div>`).join("")}`
      detail.classList.remove("hidden")
    })
  })
}

// 初始化使用者中心
function initUserPage() {
  const user = requireRole("user")
  if (!user) return

  const welcome          = document.querySelector("#user-welcome")
  const logoutButton     = document.querySelector("#user-logout-button")
  const userSpaceList    = document.querySelector("#user-space-list")
  const ownerBookingList = document.querySelector("#owner-booking-list")
  const userBookingList  = document.querySelector("#user-booking-list")
  welcome.textContent = `${user.name}，你可以在這裡管理自己的空間與預約。`
  logoutButton.addEventListener("click", () => { clearCurrentUser(); window.location.href = "/login" })

  // ── 訂閱方案資訊卡 ────────────────────────────────────────────────────────
  const planBox = document.querySelector("#user-plan-box")
  if (planBox) {
    fetch("/api/user/plan", { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) return
        const d      = data.data
        const isPro  = d.is_pro
        const label  = isPro ? "專業方案" : "免費方案"
        const expStr = isPro && d.plan_expires_at
          ? `到期日：${d.plan_expires_at.slice(0, 10)}`
          : isPro ? "" : `已上架 ${d.space_count} / ${d.space_limit} 個空間`
        planBox.innerHTML = `
          <div>
            <h3><span class="plan-badge ${isPro ? "pro" : "free"}">${label}</span></h3>
            <p>${expStr}</p>
          </div>
          ${!isPro
            ? `<a href="/pricing" class="plan-upgrade-btn"><i class="ri-rocket-line"></i> 升級專業方案</a>`
            : `<span style="font-size:0.85rem;color:var(--primary-dark);font-weight:700">✅ 已啟用</span>`
          }`
      })
      .catch(() => {})
  }

  async function loadUserSpaces() {
    userSpaceList.innerHTML = skeletonAdminSpaceCards(2)
    const response = await fetch(`/api/user/spaces?email=${encodeURIComponent(user.email)}`, { headers: getAuthHeaders() })
    const result   = await response.json()
    const spaces   = result.data || []
    userSpaceList.innerHTML = spaces.length
      ? spaces.map((space) => `
        <article class="admin-space-card" data-id="${space.id}">
          <img class="admin-space-image" src="${space.image}" alt="${escapeHtml(space.name)}">
          <div class="admin-space-body">
            <div class="admin-space-meta">
              <span class="status ${space.status === "待確認" ? "status-pending" : "status-confirmed"}">${escapeHtml(space.status)}</span>
              <span class="space-type-label">${escapeHtml(space.type)}</span>
            </div>
            <h2>${escapeHtml(space.name)}</h2>
            <p>${escapeHtml(space.city)} ${escapeHtml(space.district)} · 最多 ${space.capacity} 人</p>
            <strong>${formatPrice(space.price_per_hour)} / 小時</strong>
          </div>
          <div class="admin-space-actions">
            <button class="edit-own-space-btn confirm-space-button" data-space-id="${space.id}">編輯</button>
            <button class="delete-own-space-btn delete-space-button" data-space-id="${space.id}">刪除</button>
          </div>
        </article>`).join("")
      : emptyState("home", "還沒有上架空間", "把你的場地分享給更多人！", `<a class="book-button" href="/host" style="width:auto;padding:0 28px;margin-top:0;display:inline-flex">上架我的空間</a>`)

    document.querySelectorAll(".delete-own-space-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!await showConfirmDialog("確定要刪除這個空間嗎？")) return
        setButtonLoading(btn, true)
        const res  = await fetch(`/api/spaces/${btn.dataset.spaceId}`, { method: "DELETE", headers: getAuthHeaders() })
        const data = await res.json()
        if (data.ok) await loadUserSpaces()
        else showToast(data.message || "刪除失敗", "error")
      })
    })

    document.querySelectorAll(".edit-own-space-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const space = spaces.find((s) => String(s.id) === String(btn.dataset.spaceId))
        if (!space) return
        const article     = btn.closest("article")
        const typeOptions = ["工作室","咖啡廳","藝廊","教室","停車場"]
        article.innerHTML = `
          <div class="edit-space-form" style="grid-column:1/-1">
            <div class="form-grid">
              <label>空間名稱<input class="ef-name" value="${escapeHtml(space.name)}"></label>
              <label>類型<select class="ef-type">${typeOptions.map((t) => `<option${t === space.type ? " selected" : ""}>${escapeHtml(t)}</option>`).join("")}</select></label>
              <label>城市<input class="ef-city" value="${escapeHtml(space.city)}"></label>
              <label>行政區<input class="ef-district" value="${escapeHtml(space.district)}"></label>
              <label style="grid-column:1/-1">詳細地址<input class="ef-address" value="${escapeHtml(space.address || '')}"></label>
              <label>每小時 ($)<input class="ef-price" type="number" value="${space.price_per_hour}"></label>
              <label>容量（人）<input class="ef-capacity" type="number" value="${space.capacity}"></label>
            </div>
            <label>設備（逗號分隔）<input class="ef-equipment" value="${escapeHtml(space.equipment.join(","))}"></label>
            <label>空間介紹<textarea class="ef-description" rows="3">${escapeHtml(space.description)}</textarea></label>
            <div style="display:flex;gap:10px;margin-top:14px">
              <button class="save-own-edit-btn">儲存</button>
              <button class="cancel-own-edit-btn" style="background:var(--gray)">取消</button>
            </div>
            <p class="ef-error form-error hidden"></p>
          </div>`
        article.querySelector(".cancel-own-edit-btn").addEventListener("click", () => loadUserSpaces())
        article.querySelector(".save-own-edit-btn").addEventListener("click", async () => {
          const saveBtn   = article.querySelector(".save-own-edit-btn")
          const equipment = article.querySelector(".ef-equipment").value.split(",").map((s) => s.trim()).filter(Boolean)
          setButtonLoading(saveBtn, true)
          const res  = await fetch(`/api/spaces/${space.id}`, {
            method: "PATCH", headers: getAuthHeaders(true),
            body: JSON.stringify({
              name: article.querySelector(".ef-name").value.trim(),
              type: article.querySelector(".ef-type").value,
              city: article.querySelector(".ef-city").value.trim(),
              district: article.querySelector(".ef-district").value.trim(),
              address: article.querySelector(".ef-address").value.trim(),
              price_per_hour: Number(article.querySelector(".ef-price").value),
              capacity: Number(article.querySelector(".ef-capacity").value),
              equipment,
              description: article.querySelector(".ef-description").value.trim(),
            }),
          })
          const data = await res.json()
          if (!data.ok) {
            article.querySelector(".ef-error").textContent = data.message
            article.querySelector(".ef-error").classList.remove("hidden")
            setButtonLoading(saveBtn, false)
          } else { await loadUserSpaces() }
        })
      })
    })
  }

  async function loadOwnerBookings() {
    ownerBookingList.innerHTML = skeletonBookingCards(2)
    const response = await fetch(`/api/user/received-bookings?email=${encodeURIComponent(user.email)}`, { headers: getAuthHeaders() })
    const result   = await response.json()
    const bookings = result.data || []
    const sc = { "待確認":"status-pending","已確認":"status-confirmed","已完成":"status-done","已取消":"status-cancelled","已拒絕":"status-rejected" }
    ownerBookingList.innerHTML = bookings.length
      ? bookings.map((b) => `
        <article class="booking-card">
          <div>
            <span class="status ${sc[b.status] || "status-pending"}">${escapeHtml(b.status)}</span>
            <h2>${escapeHtml(b.space_name)}</h2>
            <p>${escapeHtml(b.date)} · ${escapeHtml(b.start_time)} - ${escapeHtml(b.end_time)}</p>
            <small>${escapeHtml(b.user_email || "未登入使用者")}</small>
          </div>
          <div class="booking-actions">
            <p>${escapeHtml(b.purpose)}</p>
            ${b.status === "待確認" ? `
              <button class="confirm-owner-booking-button" data-booking-id="${b.id}">確認預約</button>
              <button class="reject-owner-booking-button" data-booking-id="${b.id}" style="background:#b3261e">拒絕</button>` : ""}
          </div>
        </article>`).join("")
      : emptyState("inbox", "還沒有收到預約申請", "空間上架並通過審核後，使用者的預約就會出現在這裡。")

    document.querySelectorAll(".confirm-owner-booking-button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        setButtonLoading(btn, true)
        await fetch(`/api/bookings/${btn.dataset.bookingId}/confirm`, { method: "POST", headers: getAuthHeaders(true) })
        await loadOwnerBookings(); await loadUserBookings()
      })
    })

    document.querySelectorAll(".reject-owner-booking-button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!await showConfirmDialog("確定要拒絕這筆預約嗎？")) return
        setButtonLoading(btn, true)
        const res  = await fetch(`/api/bookings/${btn.dataset.bookingId}/reject`, { method: "POST", headers: getAuthHeaders(true) })
        const data = await res.json()
        if (data.ok) { await loadOwnerBookings(); await loadUserBookings() }
        else showToast(data.message || "拒絕失敗，請稍後再試", "error")
      })
    })
  }

  async function loadUserBookings() {
    userBookingList.innerHTML = skeletonBookingCards(2)
    const response = await fetch(`/api/user/bookings?email=${encodeURIComponent(user.email)}`, { headers: getAuthHeaders() })
    const result   = await response.json()
    const bookings = result.data || []
    const statusClass = { "待確認":"status-pending","已確認":"status-confirmed","已完成":"status-done","已取消":"status-cancelled","已拒絕":"status-rejected" }
    userBookingList.innerHTML = bookings.length
      ? bookings.map((b) => `
        <article class="booking-card">
          <div>
            <span class="status ${statusClass[b.status] || "status-pending"}">${escapeHtml(b.status)}</span>
            <h2>${escapeHtml(b.space_name)}</h2>
            <p>${escapeHtml(b.date)} · ${escapeHtml(b.start_time)} - ${escapeHtml(b.end_time)}</p>
          </div>
          <div class="booking-actions">
            <p>${escapeHtml(b.purpose)}</p>
            ${b.status === "待確認" ? `<button class="cancel-booking-button confirm-button" data-booking-id="${b.id}" style="background:#b3261e">取消預約</button>` : ""}
            ${b.status === "已確認" ? `
              <button class="cancel-booking-button confirm-button" data-booking-id="${b.id}" style="background:#b3261e">取消預約</button>
              <small style="color:var(--muted)">需在開始前 24 小時取消</small>` : ""}
            ${b.status === "已完成" ? `
              <div class="star-rating" data-space-id="${b.space_id}">
                <span>評分：</span>
                ${[1,2,3,4,5].map((n) => `<span class="star" data-score="${n}">★</span>`).join("")}
                <textarea class="rating-comment-input" placeholder="留下文字評論（選填）" rows="2"></textarea>
              </div>` : ""}
          </div>
        </article>`).join("")
      : emptyState("calendar", "還沒有任何預約", "探索空間，預約你喜歡的場地！", `<a class="book-button" href="/explore" style="width:auto;padding:0 28px;margin-top:0;display:inline-flex">探索空間</a>`)

    document.querySelectorAll(".cancel-booking-button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!await showConfirmDialog("確定要取消這筆預約嗎？")) return
        setButtonLoading(btn, true)
        const res  = await fetch(`/api/bookings/${btn.dataset.bookingId}/cancel`, { method: "POST", headers: getAuthHeaders(true) })
        const data = await res.json()
        if (data.ok) await loadUserBookings()
        else { showToast(data.message, "error"); setButtonLoading(btn, false) }
      })
    })

    document.querySelectorAll(".star-rating").forEach((widget) => {
      const stars = widget.querySelectorAll(".star")
      stars.forEach((star) => {
        star.addEventListener("mouseenter", () => {
          const n = parseInt(star.dataset.score)
          stars.forEach((s) => s.classList.toggle("active", parseInt(s.dataset.score) <= n))
        })
        star.addEventListener("mouseleave", () => stars.forEach((s) => s.classList.remove("active")))
        star.addEventListener("click", async () => {
          const score   = parseInt(star.dataset.score)
          const comment = widget.querySelector(".rating-comment-input")?.value.trim() || ""
          const res  = await fetch(`/api/spaces/${widget.dataset.spaceId}/rate`, {
            method: "POST", headers: getAuthHeaders(true),
            body: JSON.stringify({ score, comment }),
          })
          const data = await res.json()
          if (data.ok) {
            stars.forEach((s) => s.classList.toggle("active", parseInt(s.dataset.score) <= score))
            widget.insertAdjacentHTML("afterend", `<small class="rating-success">${data.message}</small>`)
            widget.style.pointerEvents = "none"
          } else { showToast(data.message, "error") }
        })
      })
    })
  }

  // ── 個人資料表單 ───────────────────────────────────────────────────────────
  const profileForm    = document.querySelector("#profile-form")
  const profileMessage = document.querySelector("#profile-message")
  const profileSubmit  = profileForm.querySelector("button[type='submit']")

  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault()
    const name        = document.querySelector("#profile-name").value.trim()
    const currentPw   = document.querySelector("#profile-current-password").value
    const newPw       = document.querySelector("#profile-new-password").value.trim()
    if (newPw && newPw.length < 6) {
      profileMessage.textContent = "新密碼至少需要 6 個字元"
      profileMessage.style.color = "#b3261e"
      profileMessage.classList.remove("hidden"); return
    }
    setButtonLoading(profileSubmit, true)
    const res  = await fetch("/api/user/profile", {
      method: "PATCH", headers: getAuthHeaders(true),
      body: JSON.stringify({ name, current_password: currentPw, new_password: newPw }),
    })
    const data = await res.json()
    profileMessage.textContent = data.message
    profileMessage.style.color = data.ok ? "var(--primary-dark)" : "#b3261e"
    profileMessage.classList.remove("hidden")
    setButtonLoading(profileSubmit, false)   // 個人資料儲存後恢復按鈕
    if (data.ok) {
      const patch = {}
      // 後端換發新 token（密碼有修改時）→ 同步更新本機，當前裝置不需重新登入
      if (data.token) {
        patch.token            = data.token
        patch.token_expires_at = data.token_expires_at
      }
      if (name) patch.name = name
      if (Object.keys(patch).length) setCurrentUser({ ...getCurrentUser(), ...patch })
      if (name) welcome.textContent = `${name}，你可以在這裡管理自己的空間與預約。`
    }
    document.querySelector("#profile-current-password").value = ""
    document.querySelector("#profile-new-password").value = ""
  })

  async function loadCalendar() {
    const res    = await fetch(`/api/user/bookings?email=${encodeURIComponent(user.email)}`, { headers: getAuthHeaders() })
    const result = await res.json()
    const calContainer = document.querySelector("#booking-calendar")
    if (!calContainer) return
    const now = new Date()
    renderCalendar(calContainer, now.getFullYear(), now.getMonth(), result.data || [])
  }

  // ── 我發起的拼場 ────────────────────────────────────────────────────────────
  async function loadUserCoRentals() {
    const container = document.querySelector("#user-co-rental-list")
    if (!container) return
    container.innerHTML = skeletonCards(2)
    try {
      const res   = await fetch("/api/user/co-rentals", { headers: getAuthHeaders() })
      const data  = await res.json()
      const items = data.data || []
      if (!items.length) {
        container.innerHTML = emptyState("group", "還沒有發起過拼場",
          "到拼場頁面發起，找志同道合的夥伴一起分攤費用！",
          `<a href="/co-rental" class="book-button" style="width:auto;padding:0 28px;margin-top:0;display:inline-flex">前往拼場頁</a>`)
        return
      }
      const statusLabel = { open: "開放中", full: "已額滿", closed: "已關閉" }
      const statusClass = { open: "status-confirmed", full: "status-pending", closed: "status-cancelled" }
      container.innerHTML = items.map((cr) => `
        <article class="booking-card">
          <div>
            <span class="status ${statusClass[cr.status] || "status-pending"}">${statusLabel[cr.status] || cr.status}</span>
            <h2>${escapeHtml(cr.space_name)}</h2>
            <p>${escapeHtml(cr.date)} · ${escapeHtml(cr.start_time)}–${escapeHtml(cr.end_time)}</p>
            <p>${escapeHtml(cr.space_city)} · ${cr.filled_slots} / ${cr.total_slots} 人 · ${formatPrice(cr.price_per_slot)} / 人</p>
            ${cr.purpose ? `<p style="color:var(--muted);font-size:0.88rem">${escapeHtml(cr.purpose)}</p>` : ""}
          </div>
          ${cr.status === "open" ? `
          <div class="booking-actions">
            <button class="cancel-cr-btn" data-id="${cr.id}" style="background:#b3261e">撤銷拼場</button>
          </div>` : ""}
        </article>`).join("")

      container.querySelectorAll(".cancel-cr-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!await showConfirmDialog("確定要撤銷這個拼場嗎？已加入的成員將會被通知。")) return
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/co-rentals/${btn.dataset.id}`, { method: "DELETE", headers: getAuthHeaders() })
          const d    = await res.json()
          if (d.ok) { showToast("拼場已撤銷"); loadUserCoRentals() }
          else { showToast(d.message || "撤銷失敗", "error"); setButtonLoading(btn, false) }
        })
      })
    } catch {
      container.innerHTML = emptyState("group", "載入失敗", "請重新整理頁面。")
    }
  }

  // ── 我的場地的拼場活動（場地主視角）────────────────────────────────────────
  async function loadOwnerCoRentals() {
    const container = document.querySelector("#owner-co-rental-list")
    if (!container) return
    container.innerHTML = skeletonCards(2)
    try {
      const res   = await fetch("/api/owner/co-rentals", { headers: getAuthHeaders() })
      const data  = await res.json()
      const items = data.data || []
      if (!items.length) {
        container.innerHTML = `<p style="color:var(--muted);font-size:0.9rem">目前沒有人在你的場地發起拼場。</p>`
        return
      }
      const statusLabel = { open: "開放中", full: "已額滿" }
      const statusClass = { open: "status-confirmed", full: "status-pending" }
      container.innerHTML = items.map((cr) => `
        <article class="booking-card">
          <div>
            <span class="status ${statusClass[cr.status] || "status-pending"}">${statusLabel[cr.status] || cr.status}</span>
            <h2>${escapeHtml(cr.space_name)}</h2>
            <p>${escapeHtml(cr.date)} · ${escapeHtml(cr.start_time)}–${escapeHtml(cr.end_time)}</p>
            <p>發起人：${escapeHtml(cr.organizer_email)} · ${cr.filled_slots}/${cr.total_slots} 人 · ${formatPrice(cr.price_per_slot)}/人</p>
            ${cr.purpose ? `<p style="color:var(--muted);font-size:0.88rem">${escapeHtml(cr.purpose)}</p>` : ""}
          </div>
          <div class="booking-actions">
            <button class="owner-cancel-cr-btn" data-id="${cr.id}" style="background:#b3261e">關閉拼場</button>
          </div>
        </article>`).join("")

      container.querySelectorAll(".owner-cancel-cr-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!await showConfirmDialog("確定要關閉這個拼場嗎？")) return
          setButtonLoading(btn, true)
          const res  = await fetch(`/api/co-rentals/${btn.dataset.id}`, { method: "DELETE", headers: getAuthHeaders() })
          const d    = await res.json()
          if (d.ok) { showToast("拼場已關閉"); loadOwnerCoRentals() }
          else { showToast(d.message || "操作失敗", "error"); setButtonLoading(btn, false) }
        })
      })
    } catch {
      container.innerHTML = `<p style="color:var(--muted)">載入失敗，請重新整理頁面。</p>`
    }
  }

  loadUserSpaces(); loadOwnerBookings(); loadCalendar(); loadUserBookings(); loadUserCoRentals(); loadOwnerCoRentals()
}

// 初始化忘記密碼頁
function initForgotPasswordPage() {
  const form       = document.querySelector("#forgot-form")
  const error      = document.querySelector("#forgot-error")
  const success    = document.querySelector("#forgot-success")
  const submitBtn  = form.querySelector("button[type='submit']")
  const questionEl = document.querySelector("#captcha-question")
  const refreshBtn = document.querySelector("#captcha-refresh")
  const idInput    = document.querySelector("#captcha-id")

  fetchChallenge(questionEl, idInput)
  refreshBtn?.addEventListener("click", () => fetchChallenge(questionEl, idInput))

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    error.classList.add("hidden")
    setButtonLoading(submitBtn, true)
    const res  = await fetch("/api/auth/forgot-password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email:          document.querySelector("#forgot-email").value.trim(),
        hp:             document.querySelector("#hp").value,
        captcha_id:     idInput.value,
        captcha_answer: document.querySelector("#captcha-answer").value,
      }),
    })
    const data = await res.json()
    if (data.ok) {
      form.classList.add("hidden")
      success.textContent = data.message; success.classList.remove("hidden")
    } else {
      error.textContent = data.message; error.classList.remove("hidden")
      setButtonLoading(submitBtn, false)
      fetchChallenge(questionEl, idInput)
    }
  })
}

// 初始化重設密碼頁
function initResetPasswordPage() {
  const token     = getQueryParam("token")
  const form      = document.querySelector("#reset-form")
  const error     = document.querySelector("#reset-error")
  const success   = document.querySelector("#reset-success")
  const submitBtn = form.querySelector("button[type='submit']")

  if (!token) {
    form.classList.add("hidden")
    error.textContent = "無效的重設連結，請重新申請。"
    error.classList.remove("hidden"); return
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    error.classList.add("hidden")
    const newPw     = document.querySelector("#reset-password").value
    const confirmPw = document.querySelector("#reset-password-confirm").value
    if (newPw !== confirmPw) {
      error.textContent = "兩次輸入的密碼不一致"
      error.classList.remove("hidden"); return
    }
    setButtonLoading(submitBtn, true)
    const res  = await fetch("/api/auth/reset-password", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: newPw }),
    })
    const data = await res.json()
    if (data.ok) {
      form.classList.add("hidden")
      success.textContent = data.message; success.classList.remove("hidden")
      setTimeout(() => { window.location.href = "/login" }, 2000)
    } else {
      error.textContent = data.message; error.classList.remove("hidden")
      setButtonLoading(submitBtn, false)
    }
  })
}

// ── 智慧推薦頁 ────────────────────────────────────────────────────────────────
async function initRecommendPage() {
  const form        = document.querySelector("#recommend-form")
  const loading     = document.querySelector("#recommend-loading")
  const results     = document.querySelector("#recommend-results")
  const list        = document.querySelector("#recommend-list")
  const empty       = document.querySelector("#recommend-empty")
  const recCity     = document.querySelector("#rec-city")

  // 載入城市選單
  try {
    const r = await fetch("/api/spaces/cities")
    const d = await r.json()
    if (d.data?.length) {
      recCity.innerHTML =
        `<option value="">不限城市</option>` +
        d.data.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("")
    }
  } catch (_) { /* 無法載入城市時保持空 */ }

  form.addEventListener("submit", async (e) => {
    e.preventDefault()
    loading.classList.remove("hidden")
    results.classList.add("hidden")
    empty.classList.add("hidden")

    const purpose = encodeURIComponent(document.querySelector("#rec-purpose").value.trim())
    const people  = Number(document.querySelector("#rec-people").value) || 0
    const city    = encodeURIComponent(recCity.value)
    const budget  = Number(document.querySelector("#rec-budget").value) || 0

    try {
      const res  = await fetch(`/api/spaces/recommend?purpose=${purpose}&people=${people}&city=${city}&budget=${budget}`)
      const data = await res.json()
      loading.classList.add("hidden")
      const items = data.data || []
      if (!items.length) {
        empty.classList.remove("hidden"); return
      }
      list.innerHTML = items.map((item, idx) => {
        const space = item.space
        const score = item.score
        return `
          <div class="recommend-card-wrapper">
            <span class="recommend-rank">#${idx + 1} · 匹配 ${score} 分</span>
            ${createSpaceCard(space)}
          </div>`
      }).join("")
      results.classList.remove("hidden")
    } catch (_) {
      loading.classList.add("hidden")
      empty.classList.remove("hidden")
    }
  })
}


// ── 拼場頁 ────────────────────────────────────────────────────────────────────
async function initCoRentalPage() {
  const list        = document.querySelector("#co-rental-list")
  const empty       = document.querySelector("#co-rental-empty")
  const createBtn   = document.querySelector("#create-co-rental-btn")
  const modal       = document.querySelector("#co-rental-modal")
  const modalClose  = document.querySelector("#modal-close-btn")
  const crForm      = document.querySelector("#co-rental-form")
  const crSpaceEl   = document.querySelector("#cr-space-id")
  const crError     = document.querySelector("#cr-error")
  const crSubmitBtn = document.querySelector("#cr-submit-btn")
  const cityFilter  = document.querySelector("#co-city-filter")
  const dateFilter  = document.querySelector("#co-date-filter")

  const currentUser = getCurrentUser()

  // ── 城市篩選器 ────────────────────────────────────────────────────────────
  try {
    const r = await fetch("/api/spaces/cities")
    const d = await r.json()
    if (d.data?.length) {
      cityFilter.innerHTML =
        `<option value="">全部城市</option>` +
        d.data.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("")
    }
  } catch (_) { /* 無法載入城市 */ }

  // ── 載入拼場列表 ──────────────────────────────────────────────────────────
  async function loadCoRentals() {
    const city = encodeURIComponent(cityFilter.value)
    const date = encodeURIComponent(dateFilter.value)
    list.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--muted)">載入中…</div>`
    empty.classList.add("hidden")
    try {
      const res  = await fetch(`/api/co-rentals?city=${city}&date=${date}`)
      const data = await res.json()
      const items = data.data || []
      if (!items.length) {
        list.innerHTML = ""; empty.classList.remove("hidden"); return
      }
      list.innerHTML = items.map((cr) => {
        const slotsLeft  = cr.available_slots
        const slotsClass = slotsLeft <= 1 ? "almost" : "open"
        const canJoin    = currentUser && cr.organizer_email !== currentUser.email
        return `
          <div class="co-rental-card">
            <div class="co-rental-header">
              <h3 class="co-rental-title">${escapeHtml(cr.space_name)}</h3>
              <span class="co-rental-slots ${slotsClass}">剩 ${slotsLeft} 位</span>
            </div>
            <div class="co-rental-meta">
              <span><i class="ri-calendar-event-line"></i> ${escapeHtml(cr.date)} ${escapeHtml(cr.start_time)}–${escapeHtml(cr.end_time)}</span>
              <span><i class="ri-map-pin-2-line"></i> ${escapeHtml(cr.space_city)} · ${escapeHtml(cr.space_type)}</span>
              ${cr.purpose ? `<span><i class="ri-focus-3-line"></i> ${escapeHtml(cr.purpose)}</span>` : ""}
              <span><i class="ri-group-line"></i> ${cr.filled_slots} / ${cr.total_slots} 人</span>
            </div>
            <div class="co-rental-price">${formatPrice(cr.price_per_slot)} / 人</div>
            <div class="co-rental-actions">
              <a href="/space?id=${cr.space_id}" class="btn-outline" style="text-decoration:none;font-size:0.85rem;padding:8px 16px">查看空間</a>
              ${canJoin
                ? `<button class="btn-primary join-btn" data-id="${cr.id}" style="font-size:0.85rem;padding:8px 16px">加入拼場</button>`
                : `<span style="font-size:0.8rem;color:var(--muted);align-self:center">${!currentUser ? "登入後可加入" : "你是發起人"}</span>`
              }
            </div>
          </div>`
      }).join("")

      // ── 加入拼場按鈕 ────────────────────────────────────────────────────
      list.querySelectorAll(".join-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!currentUser) { window.location.href = "/login"; return }
          btn.disabled = true; btn.textContent = "處理中…"
          const res  = await fetch(`/api/co-rentals/${btn.dataset.id}/join`, {
            method: "POST", headers: getAuthHeaders(),
          })
          const data = await res.json()
          if (data.ok) {
            btn.textContent = "✓ 已加入"
            btn.style.background = "var(--muted)"
            loadCoRentals()   // 重新整理列表
          } else {
            btn.disabled = false; btn.textContent = "加入拼場"
            alert(data.message)
          }
        })
      })
    } catch (_) {
      list.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:2rem;color:var(--muted)">載入失敗，請重新整理頁面。</div>`
    }
  }

  cityFilter.addEventListener("change", loadCoRentals)
  dateFilter.addEventListener("change",  loadCoRentals)
  await loadCoRentals()

  // ── 發起拼場 Modal ────────────────────────────────────────────────────────
  // 載入空間選單（只顯示已公開的空間）
  async function loadSpacesForSelect() {
    try {
      const res  = await fetch("/api/spaces?per_page=100")
      const data = await res.json()
      const spaces = data.data || []
      crSpaceEl.innerHTML = spaces.length
        ? `<option value="">請選擇空間</option>` +
          spaces.map((s) => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.city)})</option>`).join("")
        : `<option value="">目前沒有公開空間</option>`
    } catch (_) {
      crSpaceEl.innerHTML = `<option value="">載入失敗</option>`
    }
  }

  createBtn.addEventListener("click", () => {
    if (!currentUser) {
      showToast("請先登入才能發起拼場", "error")
      setTimeout(() => { window.location.href = "/login" }, 1200)
      return
    }
    loadSpacesForSelect()
    modal.classList.remove("hidden")
  })
  modalClose.addEventListener("click", () => modal.classList.add("hidden"))
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.add("hidden") })

  crForm.addEventListener("submit", async (e) => {
    e.preventDefault()
    crError.classList.add("hidden")
    const spaceId = Number(crSpaceEl.value)
    if (!spaceId) { crError.textContent = "請選擇空間"; crError.classList.remove("hidden"); return }
    setButtonLoading(crSubmitBtn, true)
    const res  = await fetch("/api/co-rentals", {
      method: "POST", headers: getAuthHeaders(true),
      body: JSON.stringify({
        space_id:     spaceId,
        date:         document.querySelector("#cr-date").value,
        start_time:   document.querySelector("#cr-start").value,
        end_time:     document.querySelector("#cr-end").value,
        total_slots:  Number(document.querySelector("#cr-slots").value),
        price_per_slot: Number(document.querySelector("#cr-price").value),
        purpose:      document.querySelector("#cr-purpose").value.trim(),
      }),
    })
    const data = await res.json()
    setButtonLoading(crSubmitBtn, false)
    if (data.ok) {
      modal.classList.add("hidden")
      crForm.reset()
      loadCoRentals()
    } else {
      crError.textContent = data.message
      crError.classList.remove("hidden")
    }
  })
}


if (page === "index")          initIndexPage()
renderNavbar()
initScrollToTop()
if (page === "explore")        initExplorePage()
if (page === "space")          initSpacePage()
if (page === "booking")        initBookingPage()
if (page === "dashboard")      initDashboardPage()
if (page === "host")           initHostPage()
if (page === "contact")        initContactPage()
if (page === "login")          initLoginPage()
if (page === "register")       initRegisterPage()
if (page === "user")           initUserPage()
if (page === "forgot-password") initForgotPasswordPage()
if (page === "reset-password") initResetPasswordPage()
if (page === "verify-email")   initVerifyEmailPage()
if (page === "recommend")      initRecommendPage()
if (page === "co-rental")      initCoRentalPage()
// 一般瀏覽頁面顯示公告橫幅（管理員後台、登入、註冊頁除外）
if (!["dashboard","login","register","forgot-password","reset-password","verify-email"].includes(page)) loadAnnouncementBanner()
