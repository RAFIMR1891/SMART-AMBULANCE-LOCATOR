-- Smart Ambulance Locator — Pollachi Fleet Seed Script
-- Idempotent: safe to run multiple times (uses INSERT IGNORE)
-- Run: python seed_pollachi.py  OR  mysql -u root -p smart_ambulance < sql/seed_pollachi_fleet.sql
--
-- IMPORTANT: All records here are marked is_simulated=1
-- They MUST NOT be used for real emergency dispatches.
-- Production/real fleet has is_simulated=0 and must be managed separately.

USE smart_ambulance;

-- ── Demonstration Driver Accounts (Pollachi area staff) ────────────────────
-- Passwords are hashed by Python seeding script; stored here as placeholders
-- Run seed_pollachi.py instead of this SQL directly to get proper hashed passwords.

-- ── 15 Demonstration Ambulances around Pollachi, Tamil Nadu ────────────────
-- Coordinates distributed across Pollachi and surrounding towns
-- Registration format: TN-xx-Y-xxxx (Tamil Nadu format near Coimbatore district)

INSERT IGNORE INTO ambulances
  (ambulance_code, registration_number, latitude, longitude, status, capacity, equipment, is_simulated, service_area, last_location_update, available_since)
VALUES
-- Central Pollachi (10.6550, 76.9988)
('AMB-001', 'TN33-A-1101', 10.6550, 76.9988, 'Available', 2, 'ALS,Oxygen,Defibrillator,Stretcher',     1, 'Pollachi Central',    NOW() - INTERVAL 5  MINUTE, NOW() - INTERVAL 3  HOUR),
('AMB-002', 'TN33-A-1102', 10.6580, 77.0010, 'Available', 2, 'BLS,Oxygen,Stretcher',                   1, 'Pollachi North',      NOW() - INTERVAL 8  MINUTE, NOW() - INTERVAL 2  HOUR),
('AMB-003', 'TN33-A-1103', 10.6520, 76.9960, 'Available', 1, 'ALS,Ventilator,Oxygen,Defibrillator',    1, 'Pollachi South',      NOW() - INTERVAL 3  MINUTE, NOW() - INTERVAL 4  HOUR),
-- Anaimalai area (~10 km east)
('AMB-004', 'TN33-A-1104', 10.5923, 77.0832, 'Available', 2, 'BLS,Oxygen,First Aid Kit',               1, 'Anaimalai',           NOW() - INTERVAL 12 MINUTE, NOW() - INTERVAL 1  HOUR),
('AMB-005', 'TN33-A-1105', 10.5850, 77.0780, 'Available', 1, 'ALS,Oxygen,Defibrillator',               1, 'Anaimalai South',     NOW() - INTERVAL 6  MINUTE, NOW() - INTERVAL 5  HOUR),
-- Valparai area (~40 km south)
('AMB-006', 'TN33-A-1106', 10.3289, 76.9554, 'Available', 2, 'BLS,Oxygen,Stretcher,Trauma Kit',        1, 'Valparai',            NOW() - INTERVAL 20 MINUTE, NOW() - INTERVAL 2  HOUR),
-- Udumalaipettai area (~30 km north)
('AMB-007', 'TN33-A-1107', 10.5844, 77.2498, 'Available', 2, 'ALS,Oxygen,Defibrillator,Cardiac Monitor',1,'Udumalaipettai',     NOW() - INTERVAL 15 MINUTE, NOW() - INTERVAL 6  HOUR),
-- Palladam area (~25 km north-east)
('AMB-008', 'TN33-A-1108', 10.9933, 77.2875, 'Available', 2, 'BLS,Oxygen,Stretcher',                   1, 'Palladam',            NOW() - INTERVAL 10 MINUTE, NOW() - INTERVAL 1  HOUR),
-- Kinathukadavu area (~20 km north)
('AMB-009', 'TN33-A-1109', 10.7847, 76.9448, 'Available', 1, 'ALS,Oxygen,Ventilator,Spinal Board',     1, 'Kinathukadavu',       NOW() - INTERVAL 7  MINUTE, NOW() - INTERVAL 3  HOUR),
-- Coimbatore outskirts (~35 km north)
('AMB-010', 'TN33-A-1110', 11.0168, 76.9558, 'Available', 2, 'ALS,Oxygen,Defibrillator,ECG Machine',   1, 'Coimbatore South',    NOW() - INTERVAL 18 MINUTE, NOW() - INTERVAL 2  HOUR),
-- Ethapur area (~15 km west of Pollachi)
('AMB-011', 'TN33-A-1111', 10.6432, 76.8321, 'Available', 2, 'BLS,Oxygen,First Aid Kit,Stretcher',     1, 'Ethapur',             NOW() - INTERVAL 9  MINUTE, NOW() - INTERVAL 1  HOUR),
-- Dharapuram area (~45 km north-east)
('AMB-012', 'TN33-A-1112', 10.7326, 77.5161, 'Available', 1, 'ALS,Oxygen,Defibrillator,Maternity Kit', 1, 'Dharapuram',          NOW() - INTERVAL 25 MINUTE, NOW() - INTERVAL 4  HOUR),
-- Pollachi west outskirts
('AMB-013', 'TN33-A-1113', 10.6615, 76.9720, 'Available', 2, 'BLS,Oxygen,Stretcher,Spine Board',       1, 'Pollachi West',       NOW() - INTERVAL 4  MINUTE, NOW() - INTERVAL 2  HOUR),
-- Pollachi east outskirts
('AMB-014', 'TN33-A-1114', 10.6490, 77.0210, 'Available', 2, 'ALS,Oxygen,Defibrillator,Pediatric Kit', 1, 'Pollachi East',       NOW() - INTERVAL 11 MINUTE, NOW() - INTERVAL 3  HOUR),
-- Pollachi bypass / industrial area
('AMB-015', 'TN33-A-1115', 10.6700, 77.0050, 'Out of service', 1, 'BLS,Oxygen',                        1, 'Pollachi Bypass',     NOW() - INTERVAL 60 MINUTE, NULL);
