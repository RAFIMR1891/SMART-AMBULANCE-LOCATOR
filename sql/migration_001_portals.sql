-- Upgrade for existing databases (keeps all rows). Run once: mysql -u USER -p smart_ambulance < sql/migration_001_portals.sql
ALTER TABLE users MODIFY role ENUM('admin','dispatcher','driver','user') NOT NULL DEFAULT 'user', ADD COLUMN phone VARCHAR(20) NULL;
ALTER TABLE ambulances ADD COLUMN driver_user_id INT NULL, ADD UNIQUE KEY uq_amb_driver (driver_user_id),
  ADD CONSTRAINT fk_amb_driver FOREIGN KEY (driver_user_id) REFERENCES users(id);
ALTER TABLE incidents MODIFY status ENUM('Open','In progress','Closed','Cancelled') NOT NULL DEFAULT 'Open',
  ADD COLUMN requester_user_id INT NULL, ADD INDEX idx_inc_requester (requester_user_id),
  ADD CONSTRAINT fk_inc_requester FOREIGN KEY (requester_user_id) REFERENCES users(id);
CREATE TABLE ambulance_locations (
  id BIGINT AUTO_INCREMENT PRIMARY KEY, ambulance_id INT NOT NULL,
  latitude DECIMAL(9,6) NOT NULL, longitude DECIMAL(9,6) NOT NULL,
  source ENUM('driver_device','dispatcher') NOT NULL DEFAULT 'driver_device',
  recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (ambulance_id) REFERENCES ambulances(id), INDEX idx_loc (ambulance_id, recorded_at));
