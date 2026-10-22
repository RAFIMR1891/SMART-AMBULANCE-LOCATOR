#!/usr/bin/env python3
"""
Smart Ambulance Locator - Pollachi Fleet & Staff Seed Script
Creates 15 simulated ambulances + 15 demo drivers around Pollachi, Tamil Nadu.
Idempotent: safe to run multiple times (uses INSERT IGNORE / ON DUPLICATE KEY).

Usage:  python seed_pollachi.py
"""
import sys, os
# Windows UTF-8 fix
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import pymysql
from werkzeug.security import generate_password_hash
import config

# ── Pollachi demonstration fleet ───────────────────────────────────────────────
# Each entry: (code, reg, lat, lon, status, capacity, equipment, service_area)
AMBULANCES = [
    ("AMB-001", "TN33-A-1101", 10.6550, 76.9988, "Available",      2, "ALS,Oxygen,Defibrillator,Stretcher",      "Pollachi Central"),
    ("AMB-002", "TN33-A-1102", 10.6580, 77.0010, "Available",      2, "BLS,Oxygen,Stretcher",                    "Pollachi North"),
    ("AMB-003", "TN33-A-1103", 10.6520, 76.9960, "Available",      1, "ALS,Ventilator,Oxygen,Defibrillator",     "Pollachi South"),
    ("AMB-004", "TN33-A-1104", 10.5923, 77.0832, "Available",      2, "BLS,Oxygen,First Aid Kit",                "Anaimalai"),
    ("AMB-005", "TN33-A-1105", 10.5850, 77.0780, "Available",      1, "ALS,Oxygen,Defibrillator",                "Anaimalai South"),
    ("AMB-006", "TN33-A-1106", 10.3289, 76.9554, "Available",      2, "BLS,Oxygen,Stretcher,Trauma Kit",         "Valparai"),
    ("AMB-007", "TN33-A-1107", 10.5844, 77.2498, "Available",      2, "ALS,Oxygen,Defibrillator,Cardiac Monitor","Udumalaipettai"),
    ("AMB-008", "TN33-A-1108", 10.9933, 77.2875, "Available",      2, "BLS,Oxygen,Stretcher",                    "Palladam"),
    ("AMB-009", "TN33-A-1109", 10.7847, 76.9448, "Available",      1, "ALS,Oxygen,Ventilator,Spinal Board",      "Kinathukadavu"),
    ("AMB-010", "TN33-A-1110", 11.0168, 76.9558, "Available",      2, "ALS,Oxygen,Defibrillator,ECG Machine",    "Coimbatore South"),
    ("AMB-011", "TN33-A-1111", 10.6432, 76.8321, "Available",      2, "BLS,Oxygen,First Aid Kit,Stretcher",      "Ethapur"),
    ("AMB-012", "TN33-A-1112", 10.7326, 77.5161, "Available",      1, "ALS,Oxygen,Defibrillator,Maternity Kit",  "Dharapuram"),
    ("AMB-013", "TN33-A-1113", 10.6615, 76.9720, "Available",      2, "BLS,Oxygen,Stretcher,Spine Board",        "Pollachi West"),
    ("AMB-014", "TN33-A-1114", 10.6490, 77.0210, "Available",      2, "ALS,Oxygen,Defibrillator,Pediatric Kit",  "Pollachi East"),
    ("AMB-015", "TN33-A-1115", 10.6700, 77.0050, "Out of service", 1, "BLS,Oxygen",                              "Pollachi Bypass"),
]

# Matched driver per ambulance (same index order)
DRIVERS = [
    ("Murugan Selvam",   "murugan.selvam@sal.com",   "Murugan@123", "9800000101", "AMB-001"),
    ("Senthil Kumar",    "senthil.kumar@sal.com",    "Senthil@123", "9800000102", "AMB-002"),
    ("Durai Pandian",    "durai.pandian@sal.com",    "Durai@123",   "9800000103", "AMB-003"),
    ("Balamurugan A",    "balamurugan.a@sal.com",    "Bala@123",    "9800000104", "AMB-004"),
    ("Kannan Raj",       "kannan.raj@sal.com",       "Kannan@123",  "9800000105", "AMB-005"),
    ("Arunachalam V",    "arunachalam.v@sal.com",    "Arun@123",    "9800000106", "AMB-006"),
    ("Velmurugan T",     "velmurugan.t@sal.com",     "Vel@123",     "9800000107", "AMB-007"),
    ("Ganesan P",        "ganesan.p@sal.com",        "Ganesan@123", "9800000108", "AMB-008"),
    ("Thiruvenkatam S",  "thiruvenkatam.s@sal.com",  "Thiru@123",   "9800000109", "AMB-009"),
    ("Rajasekar M",      "rajasekar.m@sal.com",      "Raja@123",    "9800000110", "AMB-010"),
    ("Palanisamy K",     "palanisamy.k@sal.com",     "Palani@123",  "9800000111", "AMB-011"),
    ("Subramanian G",    "subramanian.g@sal.com",    "Subra@123",   "9800000112", "AMB-012"),
    ("Marimuthu C",      "marimuthu.c@sal.com",      "Mari@123",    "9800000113", "AMB-013"),
    ("Krishnamurthy L",  "krishnamurthy.l@sal.com",  "Krish@123",   "9800000114", "AMB-014"),
    ("Annadurai B",      "annadurai.b@sal.com",      "Anna@123",    "9800000115", "AMB-015"),
]

# Staff (Admin + Dispatcher) near Pollachi
STAFF = [
    # (name, email, password, role, phone)
    ("Admin Rafi",         "admin@sal.com",            "Admin@123",    "admin",      "9700000001"),
    ("Ravi Sharma",        "ravi.sharma@sal.com",      "Ravi@123",     "dispatcher", "9700000002"),
    ("Priya Mehta",        "priya.mehta@sal.com",      "Priya@123",    "dispatcher", "9700000003"),
    ("Arjun Nair",         "arjun.nair@sal.com",       "Arjun@123",    "dispatcher", "9700000004"),
    ("Sneha Reddy",        "sneha.reddy@sal.com",      "Sneha@123",    "dispatcher", "9700000005"),
    ("Vikram Iyer",        "vikram.iyer@sal.com",      "Vikram@123",   "dispatcher", "9700000006"),
]

HOSPITALS = [
    ("Kovai Medical Center",         "Pollachi Main Road, Pollachi",         10.6515, 76.9916, "04259-234567", "Emergency,ICU,Surgery,Cardiology"),
    ("Sri Lakshmi Hospital",         "Nehru Nagar, Pollachi",                10.6532, 76.9955, "04259-222111", "Emergency,Orthopaedics,Maternity"),
    ("Pollachi Government Hospital", "Government Hospital Road, Pollachi",   10.6551, 76.9973, "04259-222000", "Emergency,General,Trauma"),
    ("RVS Hospital",                 "Coimbatore Road, Pollachi",            10.6489, 76.9878, "04259-245000", "Emergency,Neurology,Cardiac"),
    ("Annai Hospital",               "Palladam Road, near Pollachi",         10.6420, 77.0012, "04259-231000", "Emergency,ICU,General"),
]


def run():
    print("Connecting to database …")
    conn = pymysql.connect(
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        **config.DB
    )
    cur = conn.cursor()

    try:
        print("--- Seeding staff accounts ...")
        for name, email, password, role, phone in STAFF:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                print(f"  SKIP  {email} (already exists)")
                continue
            cur.execute(
                "INSERT INTO users (name,email,password_hash,role,phone,is_active) VALUES (%s,%s,%s,%s,%s,1)",
                (name, email, generate_password_hash(password), role, phone)
            )
            print(f"  ADDED {role:12} {email}")

        print("--- Seeding Pollachi ambulances ...")
        for code, reg, lat, lon, status, cap, equip, area in AMBULANCES:
            cur.execute("SELECT id FROM ambulances WHERE ambulance_code=%s", (code,))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE ambulances
                    SET latitude=%s, longitude=%s, service_area=%s, is_simulated=1,
                        capacity=%s, equipment=%s, registration_number=%s
                    WHERE id=%s
                """, (lat, lon, area, cap, equip, reg, row["id"]))
                print(f"  SYNC  {code}  {area:<20}")
                continue
            cur.execute("""
                INSERT INTO ambulances
                  (ambulance_code, registration_number, latitude, longitude,
                   status, capacity, equipment, is_simulated, service_area,
                   last_location_update, available_since)
                VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,NOW()-INTERVAL 10 MINUTE,
                        IF(%s='Available', NOW()-INTERVAL 2 HOUR, NULL))
            """, (code, reg, lat, lon, status, cap, equip, area, status))
            print(f"  ADDED {code}  {area:<20}  {status}")

        print("--- Seeding Pollachi drivers and linking to ambulances ...")
        for name, email, password, phone, amb_code in DRIVERS:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            row = cur.fetchone()
            if row:
                driver_id = row["id"]
                print(f"  SKIP  {email} (already exists, id={driver_id})")
            else:
                cur.execute(
                    "INSERT INTO users (name,email,password_hash,role,phone,is_active) VALUES (%s,%s,%s,'driver',%s,1)",
                    (name, email, generate_password_hash(password), phone)
                )
                driver_id = cur.lastrowid
                print(f"  ADDED driver  {email}")

            # Link driver to ambulance
            cur.execute("SELECT id, driver_user_id FROM ambulances WHERE ambulance_code=%s", (amb_code,))
            amb = cur.fetchone()
            if amb:
                cur.execute(
                    "UPDATE ambulances SET driver_user_id=%s WHERE id=%s",
                    (driver_id, amb["id"])
                )
                print(f"          -> Linked {name} to {amb_code}")

        print("--- Seeding Pollachi hospitals ...")
        for name, addr, lat, lon, phone, services in HOSPITALS:
            cur.execute("SELECT id FROM hospitals WHERE name=%s", (name,))
            if cur.fetchone():
                print(f"  SKIP  {name}")
                continue
            cur.execute("""
                INSERT INTO hospitals (name, address, latitude, longitude, contact_number, services, last_verified_at)
                VALUES (%s,%s,%s,%s,%s,%s,NOW())
            """, (name, addr, lat, lon, phone, services))
            print(f"  ADDED hospital  {name}")

        # Ensure dispatch_mode default in app_settings
        cur.execute("SELECT id FROM app_settings WHERE setting_key='dispatch_mode'")
        if not cur.fetchone():
            cur.execute("INSERT INTO app_settings (setting_key, value) VALUES ('dispatch_mode','manual')")
            print("  ADDED app_settings: dispatch_mode=manual")

        conn.commit()
        print("\n[OK] Seed complete! Pollachi fleet is ready.")
        print("\n--- Staff login credentials ---")
        print(f"  Admin      : admin@sal.com / Admin@123  -> http://127.0.0.1:5000/dashboard")
        for _, email, pw, role, _ in STAFF[1:]:
            print(f"  {role:<12}: {email:<30} / {pw}")
        print("\n--- Drivers (login at /driver) ---")
        for name, email, pw, phone, amb in DRIVERS:
            print(f"  {name:<20} {email:<35} / {pw:<12}  [{amb}]")

    except Exception as e:
        conn.rollback()
        print(f"\n[FAIL] Seed FAILED and rolled back: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
