-- Smart Ambulance Locator — Complete Database Schema (v2)
-- Run: mysql -u USER -p < sql/schema.sql
-- This is safe to run on a fresh database. For upgrading existing DBs, use migration_001_portals.sql

CREATE DATABASE IF NOT EXISTS smart_ambulance CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_ambulance;

-- Users (all roles)
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100) NOT NULL,
  email         VARCHAR(150) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  phone         VARCHAR(20)  NULL,
  role          ENUM('admin','dispatcher','driver','user') NOT NULL DEFAULT 'user',
  is_active     TINYINT(1) NOT NULL DEFAULT 1,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ambulances
CREATE TABLE IF NOT EXISTS ambulances (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  ambulance_code        VARCHAR(20) NOT NULL UNIQUE,
  registration_number   VARCHAR(30) NOT NULL UNIQUE,
  driver_user_id        INT NULL,
  latitude              DECIMAL(9,6) NOT NULL,
  longitude             DECIMAL(9,6) NOT NULL,
  status                ENUM('Available','Assigned','Dispatched','En route','At scene','Transporting patient','Out of service') NOT NULL DEFAULT 'Available',
  capacity              INT NOT NULL DEFAULT 1,
  equipment             VARCHAR(255) DEFAULT '',
  is_simulated          TINYINT(1) NOT NULL DEFAULT 0,
  service_area          VARCHAR(100) NULL,
  last_location_update  DATETIME NULL,
  available_since       DATETIME NULL,
  queue_position        BIGINT NOT NULL DEFAULT 0,
  created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_amb_driver (driver_user_id),
  INDEX (status),
  CONSTRAINT fk_amb_driver FOREIGN KEY (driver_user_id) REFERENCES users(id)
);

-- Incidents / Emergency Requests
CREATE TABLE IF NOT EXISTS incidents (
  id                        INT AUTO_INCREMENT PRIMARY KEY,
  incident_code             VARCHAR(30) NOT NULL UNIQUE,
  title                     VARCHAR(150) NOT NULL,
  description               TEXT,
  incident_type             ENUM('Fire accident','Road accident','Cardiac emergency','Other emergency') NOT NULL,
  latitude                  DECIMAL(9,6) NOT NULL,
  longitude                 DECIMAL(9,6) NOT NULL,
  estimated_patient_count   INT NOT NULL DEFAULT 1,
  priority                  ENUM('Critical','High','Medium','Low') NOT NULL DEFAULT 'High',
  status                    ENUM('Open','In progress','Closed','Cancelled') NOT NULL DEFAULT 'Open',
  last_fail_reason          VARCHAR(500) NULL,
  reported_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
  created_by                INT NULL,
  requester_user_id         INT NULL,
  FOREIGN KEY (created_by) REFERENCES users(id),
  CONSTRAINT fk_inc_requester FOREIGN KEY (requester_user_id) REFERENCES users(id),
  INDEX (status),
  INDEX idx_inc_requester (requester_user_id)
);

-- Hospitals
CREATE TABLE IF NOT EXISTS hospitals (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  name             VARCHAR(150) NOT NULL,
  address          VARCHAR(255),
  latitude         DECIMAL(9,6),
  longitude        DECIMAL(9,6),
  contact_number   VARCHAR(30),
  services         VARCHAR(255),
  last_verified_at DATETIME NULL
);

-- Patients
CREATE TABLE IF NOT EXISTS patients (
  id                      INT AUTO_INCREMENT PRIMARY KEY,
  case_reference          VARCHAR(30) NOT NULL UNIQUE,
  incident_id             INT NOT NULL,
  triage_category         VARCHAR(30) NULL,
  transport_status        ENUM('Waiting','Assigned','Transporting','Delivered') NOT NULL DEFAULT 'Waiting',
  assigned_ambulance_id   INT NULL,
  destination_hospital_id INT NULL,
  created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (incident_id) REFERENCES incidents(id),
  FOREIGN KEY (assigned_ambulance_id) REFERENCES ambulances(id),
  FOREIGN KEY (destination_hospital_id) REFERENCES hospitals(id),
  INDEX (incident_id)
);

-- Dispatches
CREATE TABLE IF NOT EXISTS dispatches (
  id                        INT AUTO_INCREMENT PRIMARY KEY,
  incident_id               INT NOT NULL,
  ambulance_id              INT NOT NULL,
  assigned_by               INT NULL,
  assigned_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
  status                    ENUM('Active','Completed','Cancelled') NOT NULL DEFAULT 'Active',
  distance_km               DECIMAL(8,3),
  estimated_travel_seconds  INT NULL,
  eta_source                VARCHAR(40) NOT NULL DEFAULT 'haversine_distance_fallback',
  dispatch_mode             VARCHAR(30) NOT NULL DEFAULT 'Automatic',
  decision_explanation      TEXT NULL,
  auto_fail_reason          VARCHAR(500) NULL,
  completed_at              DATETIME NULL,
  active_ambulance_id       INT GENERATED ALWAYS AS (IF(status='Active', ambulance_id, NULL)) STORED,
  UNIQUE KEY uq_one_active_per_ambulance (active_ambulance_id),
  FOREIGN KEY (incident_id) REFERENCES incidents(id),
  FOREIGN KEY (ambulance_id) REFERENCES ambulances(id),
  FOREIGN KEY (assigned_by) REFERENCES users(id)
);

-- App settings (dispatch mode, persistent configuration)
CREATE TABLE IF NOT EXISTS app_settings (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  setting_key VARCHAR(80)   NOT NULL UNIQUE,
  value       VARCHAR(500)  NOT NULL DEFAULT '',
  changed_by  INT           NULL,
  changed_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (changed_by) REFERENCES users(id)
);
INSERT IGNORE INTO app_settings (setting_key, value) VALUES ('dispatch_mode', 'automatic');

-- Dispatch history / audit log (nullable dispatch_id and incident_id)
CREATE TABLE IF NOT EXISTS dispatch_history (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  dispatch_id      INT NULL,
  incident_id      INT NULL,
  action           VARCHAR(50) NOT NULL,
  previous_status  VARCHAR(30),
  new_status       VARCHAR(30),
  reason           VARCHAR(255),
  dispatch_mode    VARCHAR(30) NULL,
  auto_fail_reason VARCHAR(500) NULL,
  dispatcher_id    INT NULL,
  override_reason  VARCHAR(500) NULL,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE SET NULL,
  FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE SET NULL,
  FOREIGN KEY (dispatcher_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Schema migration history
CREATE TABLE IF NOT EXISTS schema_migrations (
  version VARCHAR(100) NOT NULL PRIMARY KEY,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT IGNORE INTO schema_migrations (version) VALUES
  ('001_portals'),
  ('002_pollachi_dispatch'),
  ('003_history_nullable_dispatch');

-- Ambulance GPS location history
CREATE TABLE IF NOT EXISTS ambulance_locations (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  ambulance_id INT NOT NULL,
  latitude     DECIMAL(9,6) NOT NULL,
  longitude    DECIMAL(9,6) NOT NULL,
  source       ENUM('driver_device','dispatcher') NOT NULL DEFAULT 'driver_device',
  recorded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (ambulance_id) REFERENCES ambulances(id),
  INDEX idx_loc (ambulance_id, recorded_at)
);

-- Demo ambulance data (Hyderabad area)
INSERT IGNORE INTO ambulances (ambulance_code, registration_number, latitude, longitude, capacity, equipment, last_location_update, available_since) VALUES
  ('AMB-001', 'TS09-A-1001', 17.3850, 78.4867, 2, 'ALS,Oxygen,Defibrillator', NOW(), NOW() - INTERVAL 2 HOUR),
  ('AMB-002', 'TS09-A-1002', 17.4100, 78.4600, 1, 'BLS,Oxygen',               NOW(), NOW() - INTERVAL 1 HOUR),
  ('AMB-003', 'TS09-A-1003', 17.3600, 78.5100, 2, 'ALS,Ventilator,Oxygen',    NOW(), NOW());

-- Demo hospitals
INSERT IGNORE INTO hospitals (name, address, latitude, longitude, contact_number, services) VALUES
  ('Care Hospitals',       'Banjara Hills, Hyderabad',    17.4126, 78.4507, '+91-40-30417777', 'Emergency,ICU,Surgery,Cardiology'),
  ('Apollo Hospitals',     'Jubilee Hills, Hyderabad',    17.4239, 78.4099, '+91-40-23607777', 'Emergency,Trauma,Cardiac,Neurology'),
  ('Yashoda Hospitals',    'Somajiguda, Hyderabad',       17.4199, 78.4573, '+91-40-45674567', 'Emergency,ICU,Orthopaedics'),
  ('NIMS Hospital',        'Punjagutta, Hyderabad',       17.4314, 78.4568, '+91-40-23489000', 'Emergency,Trauma,Burns');
