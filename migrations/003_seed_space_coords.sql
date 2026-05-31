-- 003_seed_space_coords.sql
-- 為三個預設示範空間補上 GPS 座標（升級現有安裝用）
-- lat/lng 欄位已由 init_db() 的 ALTER TABLE fallback 建立，此 migration 僅補資料。
UPDATE spaces SET lat = 38.8951, lng = -77.0364 WHERE name = 'Tiny Desk Studio' AND (lat IS NULL OR lat = 0);
UPDATE spaces SET lat = 24.1341, lng = 120.6565 WHERE name = '小角 . 手捻咖啡' AND (lat IS NULL OR lat = 0);
UPDATE spaces SET lat = 24.1287, lng = 120.7198 WHERE name = '停車場預約' AND (lat IS NULL OR lat = 0)
