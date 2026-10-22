# Smart Ambulance Locator

One Flask + MySQL application with **three portals**: User/Patient, Ambulance Driver, Admin/Dispatcher. Dispatchers locate incidents, rank available ambulances (Haversine distance + traffic-aware ETA when Google Routes is configured), and confirm assignments. Gemini only writes summaries/reports; it never dispatches.

## Features
- **User portal** (`/user`): register/login, request an ambulance (browser GPS, click-on-map or typed coordinates), view own requests, assigned ambulance, last *reported* position and traffic-aware ETA (if configured), cancel while no ambulance is assigned.
- **Driver portal** (`/driver`): own ambulance, active assignments with route link to Google Maps, status updates (Assigned -> En route -> Arrived at scene -> Transporting patient -> Completed), GPS sharing (saved to `ambulance_locations`), previous assignments.
- **Dispatcher/Admin portal** (`/dashboard`): summary cards, map, incidents, recommendations table, multi-ambulance confirmation, cancel dispatch (reassign = cancel + dispatch again), users & drivers, hospitals, dispatch history, Gemini panel. Admins also create accounts and link drivers to ambulances.
- Not live tracking: positions are whatever the driver device/dispatcher last reported, shown with timestamps.

## Pages (match the UI mockups)
`/` landing page, `/login` (role dropdown: User / Driver / Admin-Dispatcher; credentials must belong to the selected role), `/signup` (patients only).
- `/user`: Dashboard, Request Ambulance, My Requests, Track Ambulance, Profile
- `/driver`: Dashboard, My Assignments, Update Status, Profile
- `/dashboard` (admin/dispatcher): Dashboard, Emergency Requests, Ambulances, Hospitals, Users, Reports, Gemini AI Assistant
New endpoint: `GET /api/me` (own profile). The landing-page ambulance is a simple SVG illustration, not a photo; drop your own image into `static/images/` and reference it in `templates/landing.html` if you want one.

## Permissions (enforced in the backend on every route)
| Role | Can |
|---|---|
| user | only `/api/user/*` on **own** requests (others return 404) |
| driver | only `/api/driver/*` on own ambulance/assignments |
| dispatcher | all staff APIs: incidents, patients, recommend, dispatch, cancel (not while a patient is on board) |
| admin | everything above + create accounts, link drivers, cancel any dispatch |

## Setup
```bash
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill DB_USER, DB_PASSWORD, SECRET_KEY, keys
```
Generate a secret: `python -c "import secrets; print(secrets.token_hex(32))"`.

**Database (fresh install)** - run both, in order:
```bash
mysql -u USER -p < sql/schema.sql
mysql -u USER -p smart_ambulance < sql/migration_001_portals.sql
```
**Upgrading an existing database** (rows preserved): run only `migration_001_portals.sql` once. It adds `users.phone`, roles `driver`/`user`, `ambulances.driver_user_id`, `incidents.requester_user_id` + `Cancelled` status, and the `ambulance_locations` table. `schema.sql` contains 3 clearly simulated demo ambulances (AMB101-103).

**Accounts**
```bash
flask --app app create-admin            # first admin (prompts; password hashed)
```
Users self-register on `/login`. Admins create drivers/dispatchers from the dashboard ("Users & drivers": for a driver, enter the ambulance's DB id) or `POST /api/admin/users`.

**Run**: `flask --app app run` -> open http://localhost:5000 (browser geolocation needs `localhost` or HTTPS).

## API keys
- `GOOGLE_MAPS_API_KEY` (server): enable **Routes API**; restrict by server IP. Used only in the backend.
- `GOOGLE_MAPS_BROWSER_KEY` (browser): enable **Maps JavaScript API**; restrict by HTTP referrer.
- Billing must be enabled on the Google Cloud project; check Routes API quotas/pricing there.
- `GEMINI_API_KEY`, `GEMINI_MODEL`: key from Google AI Studio; set `GEMINI_MODEL` to a currently supported model name from Google's docs.
Without keys: map shows a notice, recommendations use Haversine distance and are labelled *haversine_distance_fallback*, AI endpoints return a 503 message.

## Workflow test
1. Register a user on `/login`; sign in -> `/user`; submit a request.
2. Sign in as dispatcher/admin -> incident appears -> **Find ambulances** -> tick ambulances -> confirm.
3. Sign in as the linked driver -> `/driver` shows the assignment -> press status buttons, **Share my location**.
4. User page (auto-refresh 15 s) shows status, ambulance and last reported position.
Automated: `python -m pytest -q` (authorization/validation/allocator tests need no DB). The end-to-end test runs against a real DB if reachable:
`DB_USER=... DB_PASSWORD=... DB_HOST=127.0.0.1 python -m pytest -q`

## How it works
- **Haversine** (`services/haversine.py`): `a = sin^2(dphi/2) + cos(phi1) cos(phi2) sin^2(dlambda/2)`, `d = 2R atan2(sqrt a, sqrt(1-a))`, R = 6371 km. Straight-line only, not road distance or traffic.
- **Allocation** (`services/ambulance_allocator.py`, rule-based, no ML): drop non-Available, already-dispatched, out-of-capacity, or missing-equipment ambulances -> rank by traffic ETA (only if *every* candidate has one) else Haversine distance -> ties: available longest, then lowest `queue_position`, then ambulance code.
- **Concurrency**: dispatch locks the incident and ambulance rows (`SELECT ... FOR UPDATE`), advances `queue_position` in the same transaction, and a unique index on `dispatches.active_ambulance_id` rejects a second active dispatch of one ambulance at database level.
- **Multi-patient incidents**: one incident, many `patients`, many dispatches; ambulances are never auto-assigned all patients; triage is entered by humans only. Gemini receives counts and dispatch facts, no patient identifiers.

## Endpoints (new in this upgrade)
`POST /api/auth/register` | `POST/GET /api/user/requests`, `GET /api/user/requests/<id>`, `POST /api/user/requests/<id>/cancel` | `GET /api/driver/me`, `PATCH /api/driver/status`, `POST /api/driver/location` | `POST/GET /api/admin/users`, `PATCH /api/ambulances/<id>/driver`, `GET /api/hospitals`, `GET /api/dispatch-history`, `POST /api/dispatches/<id>/cancel`. Existing endpoints are unchanged except they now require staff roles.

## Limitations
No ambulance-edit form, no 'Remember me' / 'Forgot password' (omitted rather than faked); no address/geocoding (locations are coordinates); the track map draws markers only (no route line); patient records have no dedicated page beyond API + '+ Patients' (hospital rows must be inserted manually); no incident-status update UI (use SQL); no password reset; no rate limiting beyond 3 active requests per user; sessions use Flask cookies (set `SESSION_COOKIE_SECURE` behind HTTPS); Google/Gemini paths are untested here without real keys.
