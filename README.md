# Smart Ambulance Locator

> Emergency ambulance dispatch system with rule-based AI dispatch, manual fallback, and a Pollachi, Tamil Nadu demonstration fleet.

---

## Features

- **Rule-Based AI Dispatch** — Transparent eligibility filtering + ETA ranking (no ML black box)
- **Automatic Dispatch Mode** — Persistent default (`AI AUTOMATIC DISPATCH: ON`), atomic, duplicate-safe
- **Manual Dispatcher Mode** — Find Best Ambulance → Review → Confirm
- **Auto-Fail Fallback Panel** — Prominent alert + manual takeover when auto fails
- **15 Pollachi Ambulances** — Distributed across Pollachi, Anaimalai, Valparai, Coimbatore South, Palladam, etc.
- **Role-Based Portals** — Admin/Dispatcher, Driver, Patient
- **OpenStreetMap Integration** — Leaflet.js, no API key required for maps
- **Google Routes Traffic ETA** — Optional, falls back gracefully to Haversine
- **Gemini AI Text Assistant** — In-app key configuration + incident summaries & draft reports
- **105 Automated Tests** — 100% passing suite covering database history, auto-dispatch, eligibility, ranking, modes, fallback, auth & concurrency

---

## Quick Start (Windows / VS Code)

### 1. Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.10+ |
| MySQL | 5.7+ or 8.0 |
| Node.js | Not required |

### 2. Clone and Set Up Python Environment

```powershell
cd C:\Users\Admin\Downloads\smart-ambulance-locator
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Configure Environment

```powershell
Copy-Item .env.example .env
# Edit .env with your MySQL password and API keys
notepad .env
```

**Minimum required in `.env`:**
```
DB_PASSWORD=your_mysql_root_password
DB_NAME=smart_ambulance
SECRET_KEY=change-this-to-a-random-32-char-secret
```

### 4. Create Database and Run Migrations

```powershell
# Create database
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS smart_ambulance CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Run schema (first time)
Get-Content sql\schema.sql | mysql -u root -pYOUR_PASSWORD smart_ambulance

# Run portal migration
Get-Content sql\migration_001_portals.sql | mysql -u root -pYOUR_PASSWORD smart_ambulance

# Run dispatch mode + Pollachi fleet migration
Get-Content sql\migration_002_pollachi_dispatch.sql | mysql -u root -pYOUR_PASSWORD smart_ambulance

# Run database history nullable dispatch & incident fallback migration
Get-Content sql\migration_003_history_nullable_dispatch.sql | mysql -u root -pYOUR_PASSWORD smart_ambulance
```

### 5. Seed Pollachi Fleet (15 Ambulances + Staff)

```powershell
python seed_pollachi.py
```

This creates:
- 6 staff accounts (1 admin + 5 dispatchers)
- 15 demonstration ambulances (AMB-001 to AMB-015)
- 15 drivers (one per ambulance)
- 5 Pollachi-area hospitals

**Safe to run multiple times — fully idempotent.**

### 6. Start the Application

```powershell
flask run
# or
python app.py
```

Visit: **http://127.0.0.1:5000**

---

## Login Credentials

| Role | Email | Password | Portal |
|------|-------|----------|--------|
| Admin | admin@sal.com | Admin@123 | /dashboard |
| Dispatcher | ravi.sharma@sal.com | Ravi@123 | /dashboard |
| Dispatcher | priya.mehta@sal.com | Priya@123 | /dashboard |
| Driver | murugan.selvam@sal.com | Murugan@123 | /driver |
| Driver | senthil.kumar@sal.com | Senthil@123 | /driver |
| Patient | (register at /signup) | — | / |

See `STAFF_CREDENTIALS.txt` for all 15 driver accounts. (**Never commit this file.**)

---

## Dispatch Mode

### Automatic Mode (Default: ON)
1. Fresh installations start with **AI AUTOMATIC DISPATCH: ON**.
2. When a patient or staff registers an emergency, the rule-based allocation engine immediately identifies eligible vehicles and atomically dispatches the top-ranked candidate.
3. The setting persists in the database (`app_settings`) across application restarts.
4. If auto-dispatch cannot find an eligible vehicle, the request is safely preserved and immediately appears in the **Dispatcher Fallback** panel without turning off global automatic dispatch.

### Manual Mode
1. Log in as **Admin** (only administrators can switch global dispatch mode).
2. Click **⏸️ Turn AI Dispatch OFF** in the header banner.
3. Provide a reason and confirm. The banner updates to **🔧 MANUAL DISPATCH MODE**.
4. New emergency requests will wait for human dispatcher review and assignment.

### Manual Fallback (when auto fails)
1. Navigate to **⚠️ Dispatcher Fallback** in the sidebar (shows badge with count).
2. Click **Find Eligible Ambulances** for the unresolved incident.
3. Review ranked candidates and exclusion explanations.
4. Select an ambulance (enter optional override reason) → **Confirm Dispatch Selected**.
5. The dispatch is recorded as `Manual Fallback` while preserving global automatic mode.

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/auth/login | — | Login |
| POST | /api/auth/logout | Any | Logout |
| GET | /api/dashboard/summary | Staff | Stats + dispatch mode |
| GET | /api/ambulances | Staff | List fleet (filter: ?simulated=true/false) |
| POST | /api/ambulances | Staff | Add ambulance |
| GET | /api/incidents | Staff | List incidents |
| POST | /api/incidents | Staff | Create incident |
| POST | /api/incidents/{id}/recommend-ambulances | Staff | Get ranked recommendations |
| POST | /api/incidents/{id}/auto-dispatch | Staff | Auto-dispatch now |
| POST | /api/incidents/{id}/dispatch | Staff | Manual dispatch |
| GET | /api/incidents/needs-dispatch | Staff | Fallback panel incidents |
| GET | /api/dispatches | Staff | Dispatch log |
| GET | /api/settings/dispatch-mode | Staff | Get current mode |
| POST | /api/settings/dispatch-mode | Admin | Set mode (manual/automatic) |
| POST | /api/ai/incident-summary | Staff | Gemini summary |
| POST | /api/ai/explain-allocation | Staff | Gemini explanation |
| POST | /api/ai/generate-report | Staff | Gemini draft report |

---

## Ambulance Fleet (Pollachi Region)

| Code | Registration | Location | Area | Status |
|------|-------------|----------|------|--------|
| AMB-001 | TN33-A-1101 | 10.6550, 76.9988 | Pollachi Central | Available |
| AMB-002 | TN33-A-1102 | 10.6580, 77.0010 | Pollachi Central | Available |
| AMB-003 | TN33-A-1103 | 10.6520, 76.9960 | Pollachi Central | Available |
| AMB-004 | TN33-A-1104 | 10.5923, 77.0832 | Anaimalai | Available |
| AMB-005 | TN33-A-1105 | 10.5850, 77.0780 | Anaimalai South | Available |
| AMB-006 | TN33-A-1106 | 10.3289, 76.9554 | Valparai | Available |
| AMB-007 | TN33-A-1107 | 10.5844, 77.2498 | Udumalaipettai | Available |
| AMB-008 | TN33-A-1108 | 10.9933, 77.2875 | Palladam | Available |
| AMB-009 | TN33-A-1109 | 10.7847, 76.9448 | Kinathukadavu | Available |
| AMB-010 | TN33-A-1110 | 11.0168, 76.9558 | Coimbatore South | Available |
| AMB-011 | TN33-A-1111 | 10.6432, 76.8321 | Ethapur | Available |
| AMB-012 | TN33-A-1112 | 10.7326, 77.5161 | Dharapuram | Available |
| AMB-013 | TN33-A-1113 | 10.6615, 76.9720 | Pollachi West | Available |
| AMB-014 | TN33-A-1114 | 10.6490, 77.0210 | Pollachi East | Available |
| AMB-015 | TN33-A-1115 | 10.6700, 77.0050 | Pollachi Bypass | Out of service |

> All marked `is_simulated=1` — demonstration only. Never dispatch for real emergencies.

---

## Running Tests

```powershell
python -m pytest tests/ -v --tb=short
```

**Expected: 54 passed, 0 failed**

Test coverage:
- Eligibility filtering (stale GPS, equipment, capacity, driver, simulated/real)
- Ambulance ranking (ETA priority, Haversine fallback, tie-breaking)
- Haversine distance and coordinate validation
- Google Routes API mocking (success, failure, no key)
- Authentication and role enforcement
- Dispatch mode API (get/set, unauthorized access)
- Pollachi fleet seeding and idempotency
- No-duplicate-codes validation
- App settings table

---

## Optional API Keys

| Key | Variable | Required | Notes |
|-----|----------|----------|-------|
| Google Routes API | GOOGLE_MAPS_API_KEY | No | Traffic-aware ETA; falls back to Haversine |
| Google Maps Browser | GOOGLE_MAPS_BROWSER_KEY | No | Map tiles use OpenStreetMap by default |
| Gemini AI | GEMINI_API_KEY | No | AI summaries; app works without it |

Get Gemini API key: https://aistudio.google.com/app/apikey

---

## Architecture

```
smart-ambulance-locator/
├── app.py                         # Flask app + all routes
├── database.py                    # PyMySQL helper (transaction context manager)
├── config.py                      # Environment config loader
├── seed_pollachi.py               # Idempotent fleet & staff seed script
├── STAFF_CREDENTIALS.txt          # Staff login credentials with ambulance numbers
├── services/
│   ├── ambulance_allocator.py     # Rule-based eligibility + ranking engine
│   ├── haversine.py               # Great-circle distance + coord validation
│   ├── google_maps_service.py     # Google Routes API traffic ETA
│   └── gemini_service.py          # Gemini AI text assistant (in-app configurable)
├── routes/
│   └── portal_routes.py          # Driver, patient, admin portal routes
├── templates/
│   ├── base.html, shell.html     # Layout templates
│   ├── dashboard.html            # Admin/dispatcher portal
│   ├── driver.html               # Driver portal
│   └── user.html                 # Patient portal
├── static/
│   ├── css/style.css             # Design system
│   └── js/
│       ├── main.js               # Shared helpers (API, map, toast, nav)
│       └── admin.js              # Dashboard logic
├── sql/
│   ├── schema.sql                # Full database schema
│   ├── migration_001_portals.sql # Portal columns migration
│   ├── migration_002_pollachi_dispatch.sql  # Dispatch mode + fleet
│   └── seed_pollachi_fleet.sql   # SQL-only seed reference
└── tests/
    └── test_allocator.py         # 54-test suite
```

---

## Bugs Fixed in This Upgrade

1. Map default was Hyderabad — changed to Pollachi (10.6550, 76.9988)
2. AMB-001/002/003 had Hyderabad coordinates — relocated to Pollachi
3. `ADD COLUMN IF NOT EXISTS` not supported in MySQL 5.7 — rewritten with prepared statements
4. Windows PowerShell `<` redirect not supported — documented `Get-Content | mysql` pattern
5. Seed script printed Unicode emoji causing `cp1252` crash on Windows — replaced with ASCII
6. `_auto_dispatch` was not revalidating ambulance availability inside transaction — fixed with `FOR UPDATE` row lock
7. `dispatch_mode` column missing from `dispatches` and `dispatch_history` — added via migration 002
8. Map icons had no distinction between available/busy/out-of-service — added 3 distinct icon types
9. `lmap()` ignored lat/lng arguments — fixed to accept Pollachi defaults

---

## Limitations and Known Issues

- **Simulated GPS**: All 15 demonstration ambulances have fixed coordinates. In production, a real GPS tracking integration is required.
- **No WebSockets**: Dashboard auto-refreshes every 30 seconds via polling. Real-time push not implemented.
- **Gemini AI**: Requires a valid `GEMINI_API_KEY`. Without it, AI panel shows a configuration warning but all other features work.
- **Google Routes ETA**: Requires a valid `GOOGLE_MAPS_API_KEY` with Routes API enabled. Falls back to Haversine without it.
- **No email/SMS notifications**: Driver/patient notifications are dashboard-only (polling). SMS gateway not integrated.
- **CSRF protection**: Session-based CSRF not fully implemented — suitable for internal LAN use. Add Flask-WTF for production.
