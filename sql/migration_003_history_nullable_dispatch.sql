-- Smart Ambulance Locator — Migration 003: Nullable dispatch_id and incident-level audit
-- MySQL 5.7 / 8.0 compatible
-- Fixes: Eliminates foreign key violation on dispatch_id=0 for mode changes and auto-dispatch failures.
-- Adds: incident_id to dispatch_history with ON DELETE SET NULL FK.
-- Adds: last_fail_reason to incidents table for direct incident fallback status tracking.
-- Adds: schema_migrations tracking table.

USE smart_ambulance;

-- ── 1. Migration tracking table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(100) NOT NULL PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── 2. Ensure existing dummy 0 values are cleaned up ─────────────────────────
SET FOREIGN_KEY_CHECKS = 0;
UPDATE dispatch_history SET dispatch_id = NULL WHERE dispatch_id = 0;
SET FOREIGN_KEY_CHECKS = 1;

-- ── 3. Drop existing dispatch_history_ibfk_1 foreign key if present ──────────
SET @fk_name = (
    SELECT CONSTRAINT_NAME
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'dispatch_history'
      AND COLUMN_NAME = 'dispatch_id'
      AND REFERENCED_TABLE_NAME = 'dispatches'
    LIMIT 1
);

SET @drop_fk = IF(@fk_name IS NOT NULL,
                  CONCAT('ALTER TABLE dispatch_history DROP FOREIGN KEY `', @fk_name, '`'),
                  'SELECT 1');
PREPARE stmt FROM @drop_fk;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 4. Modify dispatch_id to be nullable ─────────────────────────────────────
ALTER TABLE dispatch_history MODIFY COLUMN dispatch_id INT NULL;

-- ── 5. Re-add foreign key constraint with ON DELETE SET NULL ─────────────────
SET @fk_exists = (
    SELECT COUNT(*)
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'dispatch_history'
      AND COLUMN_NAME = 'dispatch_id'
      AND REFERENCED_TABLE_NAME = 'dispatches'
);

SET @add_fk = IF(@fk_exists = 0,
    'ALTER TABLE dispatch_history ADD CONSTRAINT fk_dh_dispatch FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @add_fk;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 6. Add incident_id column to dispatch_history if not present ─────────────
SET @col_incident = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'dispatch_history'
      AND COLUMN_NAME = 'incident_id'
);

SET @add_col_incident = IF(@col_incident = 0,
    'ALTER TABLE dispatch_history ADD COLUMN incident_id INT NULL AFTER dispatch_id',
    'SELECT 1');
PREPARE stmt FROM @add_col_incident;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 7. Add foreign key from dispatch_history(incident_id) to incidents(id) ───
SET @fk_inc_exists = (
    SELECT COUNT(*)
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'dispatch_history'
      AND COLUMN_NAME = 'incident_id'
      AND REFERENCED_TABLE_NAME = 'incidents'
);

SET @add_fk_inc = IF(@fk_inc_exists = 0,
    'ALTER TABLE dispatch_history ADD CONSTRAINT fk_dh_incident FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE SET NULL',
    'SELECT 1');
PREPARE stmt FROM @add_fk_inc;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 8. Backfill incident_id in dispatch_history from linked dispatches ────────
UPDATE dispatch_history dh
JOIN dispatches d ON d.id = dh.dispatch_id
SET dh.incident_id = d.incident_id
WHERE dh.incident_id IS NULL AND dh.dispatch_id IS NOT NULL;

-- ── 9. Add last_fail_reason column to incidents table if not present ─────────
SET @col_fail = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'incidents'
      AND COLUMN_NAME = 'last_fail_reason'
);

SET @add_col_fail = IF(@col_fail = 0,
    'ALTER TABLE incidents ADD COLUMN last_fail_reason VARCHAR(500) NULL AFTER status',
    'SELECT 1');
PREPARE stmt FROM @add_col_fail;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ── 10. Default dispatch mode to automatic if unchanged by admin ─────────────
UPDATE app_settings SET value = 'automatic' WHERE setting_key = 'dispatch_mode' AND changed_by IS NULL;
INSERT IGNORE INTO app_settings (setting_key, value) VALUES ('dispatch_mode', 'automatic');

-- ── 11. Record applied migrations ────────────────────────────────────────────
INSERT IGNORE INTO schema_migrations (version) VALUES
    ('001_portals'),
    ('002_pollachi_dispatch'),
    ('003_history_nullable_dispatch');
