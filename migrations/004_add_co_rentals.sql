-- 004_add_co_rentals.sql
-- 新增拼場（Co-Rental）功能所需的兩個表格

CREATE TABLE IF NOT EXISTS co_rentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
);

CREATE TABLE IF NOT EXISTS co_rental_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    co_rental_id INTEGER NOT NULL,
    user_email TEXT NOT NULL,
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(co_rental_id, user_email)
);

CREATE INDEX IF NOT EXISTS idx_co_rentals_date ON co_rentals(date);
CREATE INDEX IF NOT EXISTS idx_co_rentals_status ON co_rentals(status);
CREATE INDEX IF NOT EXISTS idx_co_rentals_space ON co_rentals(space_id)
