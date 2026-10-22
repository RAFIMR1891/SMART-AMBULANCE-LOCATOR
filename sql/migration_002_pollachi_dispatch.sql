-- Smart Ambulance Locator — Migration 002: Pollachi Fleet + Dispatch Mode
-- MySQL 5.7/8.0 compatible (no ADD COLUMN IF NOT EXISTS)
-- Run ONCE: Get-Content sql\migration_002_pollachi_dispatch.sql | mysql -u root -pPASSWORD smart_ambulance

USE smart_ambulance;

-- ── 1. App-level settings (dispatch mode, audit) ─────────────────────────────
CREATE TABLE IF NOT EXISTS app_settings (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  setting_key VARCHAR(80)   NOT NULL UNIQUE,
  value       VARCHAR(500)  NOT NULL DEFAULT '',
  changed_by  INT           NULL,
  changed_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (changed_by) REFERENCES users(id)
);
INSERT IGNORE INTO app_settings (setting_key, value) VALUES ('dispatch_mode', 'manual');

-- ── 2. ambulances: simulated flag & service_area ─────────────────────────────
-- Only add if column doesn't exist (via stored procedure trick for 5.7 compat)
SET @col_exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ambulances' AND COLUMN_NAME='is_simulated'
);
SET @sql = IF(@col_exists=0,
  'ALTER TABLE ambulances ADD COLUMN is_simulated TINYINT(1) NOT NULL DEFAULT 0 AFTER equipment',
  'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col2_exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='ambulances' AND COLUMN_NAME='service_area'
);
SET @sql2 = IF(@col2_exists=0,
  'ALTER TABLE ambulances ADD COLUMN service_area VARCHAR(100) NULL',
  'SELECT 1');
PREPARE stmt FROM @sql2; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Index on is_simulated (safe to ignore if already exists)
ALTER TABLE ambulances ADD INDEX idx_amb_simulated (is_simulated);

-- ── 3. dispatch_history: dispatch_mode, fail_reason, dispatcher, override ────
SET @dh1 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatch_history' AND COLUMN_NAME='dispatch_mode');
SET @s1 = IF(@dh1=0,'ALTER TABLE dispatch_history ADD COLUMN dispatch_mode VARCHAR(30) NULL','SELECT 1');
PREPARE s FROM @s1; EXECUTE s; DEALLOCATE PREPARE s;

SET @dh2 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatch_history' AND COLUMN_NAME='auto_fail_reason');
SET @s2 = IF(@dh2=0,'ALTER TABLE dispatch_history ADD COLUMN auto_fail_reason VARCHAR(500) NULL','SELECT 1');
PREPARE s FROM @s2; EXECUTE s; DEALLOCATE PREPARE s;

SET @dh3 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatch_history' AND COLUMN_NAME='dispatcher_id');
SET @s3 = IF(@dh3=0,'ALTER TABLE dispatch_history ADD COLUMN dispatcher_id INT NULL','SELECT 1');
PREPARE s FROM @s3; EXECUTE s; DEALLOCATE PREPARE s;

SET @dh4 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatch_history' AND COLUMN_NAME='override_reason');
SET @s4 = IF(@dh4=0,'ALTER TABLE dispatch_history ADD COLUMN override_reason VARCHAR(500) NULL','SELECT 1');
PREPARE s FROM @s4; EXECUTE s; DEALLOCATE PREPARE s;

-- ── 4. dispatches: dispatch_mode, decision_explanation, auto_fail_reason ─────
SET @dp1 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatches' AND COLUMN_NAME='dispatch_mode');
SET @sd1 = IF(@dp1=0,'ALTER TABLE dispatches ADD COLUMN dispatch_mode VARCHAR(30) NOT NULL DEFAULT ''Manual''','SELECT 1');
PREPARE s FROM @sd1; EXECUTE s; DEALLOCATE PREPARE s;

SET @dp2 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatches' AND COLUMN_NAME='decision_explanation');
SET @sd2 = IF(@dp2=0,'ALTER TABLE dispatches ADD COLUMN decision_explanation TEXT NULL','SELECT 1');
PREPARE s FROM @sd2; EXECUTE s; DEALLOCATE PREPARE s;

SET @dp3 = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dispatches' AND COLUMN_NAME='auto_fail_reason');
SET @sd3 = IF(@dp3=0,'ALTER TABLE dispatches ADD COLUMN auto_fail_reason VARCHAR(500) NULL','SELECT 1');
PREPARE s FROM @sd3; EXECUTE s; DEALLOCATE PREPARE s;

-- ── 5. Pollachi-area hospitals ────────────────────────────────────────────────
INSERT IGNORE INTO hospitals (name, address, latitude, longitude, contact_number, services, last_verified_at) VALUES
  ('Kovai Medical Center Pollachi',  'Pollachi Main Road, Pollachi TN',      10.6515, 76.9916, '04259-234567', 'Emergency,ICU,Surgery,Cardiology', NOW()),
  ('Sri Lakshmi Hospital',           'Nehru Nagar, Pollachi TN',             10.6532, 76.9955, '04259-222111', 'Emergency,Orthopaedics,Maternity',  NOW()),
  ('Pollachi Government Hospital',   'Government Hospital Rd, Pollachi TN',  10.6551, 76.9973, '04259-222000', 'Emergency,General,Trauma',          NOW()),
  ('RVS Hospital Pollachi',          'Coimbatore Road, Pollachi TN',         10.6489, 76.9878, '04259-245000', 'Emergency,Neurology,Cardiac',       NOW()),
  ('Annai Hospital',                 'Palladam Road, near Pollachi TN',      10.6420, 77.0012, '04259-231000', 'Emergency,ICU,General',             NOW());
