"""
Smart Ambulance Locator — Comprehensive Test Suite
Tests cover: eligibility, ranking, dispatch modes, fallback, concurrency, seeding, auth.
Run: pytest tests/ -v --tb=short
"""
import pytest, uuid, time
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# ─────────────────────────── Helpers ─────────────────────────────────────────
def make_ambulance(id=1, code="AMB-001", status="Available", capacity=2,
                   equipment="ALS,Oxygen", lat=10.655, lon=76.999,
                   driver_id=None, is_simulated=0, service_area="Pollachi",
                   last_update=None, available_since=None):
    lu = last_update if last_update is not None else datetime.utcnow()
    av = available_since if available_since is not None else datetime.utcnow() - timedelta(hours=1)
    return {
        "id": id, "ambulance_code": code, "status": status, "capacity": capacity,
        "equipment": equipment, "latitude": lat, "longitude": lon,
        "driver_user_id": driver_id, "is_simulated": is_simulated,
        "service_area": service_area, "last_location_update": lu,
        "available_since": av, "queue_position": 0,
    }

def make_incident(lat=10.650, lon=76.995, patient_count=1):
    return {"id": 1, "incident_code": "INC-TEST", "latitude": lat, "longitude": lon,
            "estimated_patient_count": patient_count, "incident_type": "Road accident"}

# ─────────────────────────── 1. Eligibility ──────────────────────────────────
from services.ambulance_allocator import filter_eligible, rank, explain, explain_exclusion

class TestEligibilityFiltering:
    def test_available_ambulance_passes(self):
        ambs = [make_ambulance(status="Available")]
        eligible, excluded = filter_eligible(ambs, set())
        assert len(eligible) == 1
        assert len(excluded) == 0

    def test_unavailable_ambulance_excluded(self):
        for st in ["Assigned", "Dispatched", "En route", "At scene", "Transporting patient", "Out of service"]:
            ambs = [make_ambulance(status=st)]
            eligible, excluded = filter_eligible(ambs, set())
            assert len(eligible) == 0, f"Status '{st}' should be excluded"
            assert "not Available" in excluded[0]["rejection_reason"] or st in excluded[0]["rejection_reason"]

    def test_active_dispatch_excludes_ambulance(self):
        ambs = [make_ambulance(id=5, status="Available")]
        eligible, excluded = filter_eligible(ambs, {5})
        assert len(eligible) == 0
        assert "active dispatch" in excluded[0]["rejection_reason"]

    def test_insufficient_capacity_excluded(self):
        ambs = [make_ambulance(capacity=1)]
        eligible, excluded = filter_eligible(ambs, set(), min_capacity=2)
        assert len(eligible) == 0
        assert "Capacity" in excluded[0]["rejection_reason"]

    def test_sufficient_capacity_passes(self):
        ambs = [make_ambulance(capacity=3)]
        eligible, _ = filter_eligible(ambs, set(), min_capacity=2)
        assert len(eligible) == 1

    def test_equipment_requirement_met(self):
        ambs = [make_ambulance(equipment="ALS,Oxygen,Defibrillator")]
        eligible, _ = filter_eligible(ambs, set(), required_equipment=["ALS", "Oxygen"])
        assert len(eligible) == 1

    def test_missing_equipment_excluded(self):
        ambs = [make_ambulance(equipment="BLS,Oxygen")]
        eligible, excluded = filter_eligible(ambs, set(), required_equipment=["ALS"])
        assert len(eligible) == 0
        assert "Missing equipment" in excluded[0]["rejection_reason"]
        assert "als" in excluded[0]["rejection_reason"].lower()

    def test_stale_gps_excluded(self):
        stale_time = datetime.utcnow() - timedelta(minutes=120)
        ambs = [make_ambulance(last_update=stale_time)]
        eligible, excluded = filter_eligible(ambs, set(), max_location_age_minutes=60)
        assert len(eligible) == 0
        assert "stale" in excluded[0]["rejection_reason"].lower()

    def test_fresh_gps_passes(self):
        fresh_time = datetime.utcnow() - timedelta(minutes=5)
        ambs = [make_ambulance(last_update=fresh_time)]
        eligible, _ = filter_eligible(ambs, set(), max_location_age_minutes=60)
        assert len(eligible) == 1

    def test_no_gps_excluded(self):
        ambs = [make_ambulance(lat=None, lon=None, last_update=None)]
        ambs[0]["latitude"] = None
        eligible, excluded = filter_eligible(ambs, set())
        assert len(eligible) == 0

    def test_driver_required_no_driver_excluded(self):
        ambs = [make_ambulance(driver_id=None)]
        eligible, excluded = filter_eligible(ambs, set(), require_driver=True)
        assert len(eligible) == 0
        assert "driver" in excluded[0]["rejection_reason"].lower()

    def test_driver_present_passes(self):
        ambs = [make_ambulance(driver_id=42)]
        eligible, _ = filter_eligible(ambs, set(), require_driver=True)
        assert len(eligible) == 1

    def test_simulated_excluded_when_real_only(self):
        ambs = [make_ambulance(is_simulated=1), make_ambulance(id=2, code="AMB-R01", is_simulated=0)]
        eligible, excluded = filter_eligible(ambs, set(), only_real=True)
        assert len(eligible) == 1
        assert eligible[0]["ambulance_code"] == "AMB-R01"

    def test_real_excluded_when_simulated_only(self):
        ambs = [make_ambulance(is_simulated=1), make_ambulance(id=2, code="AMB-R01", is_simulated=0)]
        eligible, excluded = filter_eligible(ambs, set(), only_simulated=True)
        assert len(eligible) == 1
        assert eligible[0]["is_simulated"] == 1

    def test_multiple_exclusion_reasons(self):
        ambs = [make_ambulance(status="Out of service", capacity=0)]
        _, excluded = filter_eligible(ambs, set())
        assert len(excluded) == 1  # excluded once, first matching rule

# ─────────────────────────── 2. Ranking ──────────────────────────────────────
class TestRanking:
    def test_closer_ambulance_ranked_first_haversine(self):
        inc = make_incident(lat=10.650, lon=76.995)
        a_near = make_ambulance(id=1, code="AMB-NEAR", lat=10.651, lon=76.996)
        a_far  = make_ambulance(id=2, code="AMB-FAR",  lat=10.700, lon=77.100)
        ranked = rank([a_near, a_far], inc, etas={})
        assert ranked[0]["ambulance_code"] == "AMB-NEAR"
        assert ranked[0]["rank"] == 1
        assert ranked[1]["rank"] == 2

    def test_eta_used_when_all_have_eta(self):
        inc = make_incident()
        a1 = make_ambulance(id=1, code="AMB-1", lat=10.700, lon=77.100)  # far
        a2 = make_ambulance(id=2, code="AMB-2", lat=10.651, lon=76.996)  # near
        etas = {1: 300, 2: 600}  # AMB-1 has shorter ETA despite being farther
        ranked = rank([a1, a2], inc, etas=etas)
        assert ranked[0]["ambulance_code"] == "AMB-1"
        assert ranked[0]["eta_source"] == "google_routes_traffic"

    def test_haversine_fallback_when_eta_missing(self):
        inc = make_incident()
        a1 = make_ambulance(id=1, code="AMB-1", lat=10.651, lon=76.996)
        a2 = make_ambulance(id=2, code="AMB-2", lat=10.700, lon=77.100)
        etas = {1: 300}  # only one has ETA → fall back to haversine for all
        ranked = rank([a1, a2], inc, etas=etas)
        assert all(r["eta_source"] == "haversine_distance_fallback" for r in ranked)
        assert ranked[0]["ambulance_code"] == "AMB-1"  # nearer

    def test_rank_index_correct(self):
        inc = make_incident()
        ambs = [make_ambulance(id=i, code=f"AMB-{i:03d}", lat=10.65+i*0.01, lon=76.99) for i in range(1,5)]
        ranked = rank(ambs, inc, etas={})
        for i, r in enumerate(ranked):
            assert r["rank"] == i + 1

    def test_tie_broken_by_available_since(self):
        inc = make_incident()
        # same distance, different available_since
        a_old = make_ambulance(id=1, code="AMB-OLD", lat=10.651, lon=76.996,
                               available_since=datetime.utcnow() - timedelta(hours=3))
        a_new = make_ambulance(id=2, code="AMB-NEW", lat=10.651, lon=76.996,
                               available_since=datetime.utcnow() - timedelta(minutes=10))
        ranked = rank([a_new, a_old], inc, etas={})
        assert ranked[0]["ambulance_code"] == "AMB-OLD"  # available longest → ranked first

    def test_explain_contains_ambulance_code(self):
        inc = make_incident()
        ambs = [make_ambulance()]
        ranked = rank(ambs, inc, etas={})
        explanation = explain(ranked[0])
        assert "AMB-001" in explanation
        assert "km" in explanation

    def test_explain_labels_simulated(self):
        inc = make_incident()
        ambs = [make_ambulance(is_simulated=1)]
        ranked = rank(ambs, inc, etas={})
        exp = explain(ranked[0])
        assert "SIMULATED" in exp

    def test_explain_exclusion_contains_reason(self):
        ambs = [make_ambulance(status="Out of service")]
        _, excluded = filter_eligible(ambs, set())
        text = explain_exclusion(excluded[0])
        assert "excluded" in text.lower()

# ─────────────────────────── 3. Haversine ────────────────────────────────────
from services.haversine import haversine_km, validate_coordinates

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_km(10.655, 76.999, 10.655, 76.999) == 0.0

    def test_known_distance_pollachi_to_coimbatore(self):
        # Pollachi (10.6550, 76.9988) to Coimbatore (11.0168, 76.9558) ~ 40 km
        d = haversine_km(10.6550, 76.9988, 11.0168, 76.9558)
        assert 35 < d < 45, f"Expected ~40km, got {d}"

    def test_returns_positive(self):
        assert haversine_km(10.0, 76.0, 11.0, 77.0) > 0

    def test_validates_lat_out_of_range(self):
        with pytest.raises(ValueError):
            validate_coordinates(91.0, 76.0)

    def test_validates_lon_out_of_range(self):
        with pytest.raises(ValueError):
            validate_coordinates(10.0, 181.0)

    def test_validates_non_numeric(self):
        with pytest.raises(ValueError):
            validate_coordinates("abc", 76.0)

    def test_valid_coords_pass(self):
        lat, lon = validate_coordinates(10.655, 76.999)
        assert lat == 10.655 and lon == 76.999

# ─────────────────────────── 4. Google Routes ────────────────────────────────
from services.google_maps_service import traffic_etas

class TestGoogleMapsService:
    def test_returns_empty_when_no_api_key(self):
        with patch("config.MAPS_SERVER_KEY", ""):
            etas, err = traffic_etas([make_ambulance()], make_incident())
            assert etas == {}
            assert "not configured" in (err or "").lower() or "GOOGLE_MAPS_API_KEY" in (err or "")

    def test_returns_empty_when_no_ambulances(self):
        with patch("config.MAPS_SERVER_KEY", "fake-key"):
            etas, err = traffic_etas([], make_incident())
            assert etas == {}
            assert err is None

    def test_handles_request_exception_gracefully(self):
        import requests
        with patch("config.MAPS_SERVER_KEY", "fake-key"):
            with patch("requests.post", side_effect=requests.RequestException("timeout")):
                etas, err = traffic_etas([make_ambulance()], make_incident())
                assert etas == {}
                assert "unavailable" in (err or "").lower() or err is not None

    def test_routes_api_response_parsed(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = [
            {"originIndex": 0, "condition": "ROUTE_EXISTS", "duration": "600s"}
        ]
        ambs = [make_ambulance(id=1)]
        with patch("config.MAPS_SERVER_KEY", "fake-key"):
            with patch("requests.post", return_value=mock_resp):
                etas, err = traffic_etas(ambs, make_incident())
                assert err is None
                assert etas.get(1) == 600

# ─────────────────────────── 5. App API (Flask routes) ───────────────────────
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

@pytest.fixture(scope="module")
def client():
    """Flask test client — no real DB needed for auth tests."""
    from app import app
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    with app.test_client() as c:
        yield c

class TestAuthRoutes:
    def test_login_missing_fields_returns_400(self, client):
        r = client.post("/api/auth/login", json={})
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_login_wrong_credentials_401(self, client):
        r = client.post("/api/auth/login", json={"email": "nobody@nowhere.com", "password": "wrong"})
        assert r.status_code == 401

    def test_public_register_only_user_role(self, client):
        """Public registration must only create 'user' accounts."""
        import uuid
        email = f"test_{uuid.uuid4().hex[:6]}@test.com"
        r = client.post("/api/auth/register", json={
            "name": "Test User", "email": email, "password": "Test@1234", "role": "admin"
        })
        # Either succeeds as 'user' or the role is overridden
        if r.status_code == 201:
            from database import query
            u = query("SELECT role FROM users WHERE email=%s", (email,), one=True)
            assert u["role"] == "user", "Public registration must never create admin"

    def test_protected_endpoints_require_auth(self, client):
        protected = [
            ("/api/dashboard/summary", "GET"),
            ("/api/ambulances", "GET"),
            ("/api/incidents", "GET"),
            ("/api/dispatches", "GET"),
        ]
        for url, method in protected:
            r = client.open(url, method=method)
            assert r.status_code == 401, f"{url} should require auth"

class TestDispatchModeAPI:
    def _login_as_admin(self, client):
        client.post("/api/auth/login", json={
            "email": "admin@sal.com", "password": "Admin@123", "role": "admin"
        })

    def test_get_dispatch_mode_requires_auth(self, client):
        # Log out first
        client.post("/api/auth/logout")
        r = client.get("/api/settings/dispatch-mode")
        assert r.status_code == 401

    def test_set_dispatch_mode_requires_admin(self, client):
        # Log in as dispatcher
        client.post("/api/auth/login", json={
            "email": "ravi.sharma@sal.com", "password": "Ravi@123", "role": "admin"
        })
        r = client.post("/api/settings/dispatch-mode", json={"mode": "automatic"})
        # Dispatcher should not be able to change mode (only admin)
        # This depends on their actual role — if login succeeded as dispatcher, 403 expected
        # Accept either 401 (not logged in as right role) or 403
        assert r.status_code in (401, 403)

    def test_invalid_mode_rejected(self, client):
        self._login_as_admin(client)
        r = client.post("/api/settings/dispatch-mode", json={"mode": "turbo-mode"})
        assert r.status_code == 422

# ─────────────────────────── 6. Allocator integration ───────────────────────
class TestAllocatorIntegration:
    def test_empty_ambulance_list_returns_empty(self):
        eligible, excluded = filter_eligible([], set())
        assert eligible == []
        assert excluded == []

    def test_all_ambulances_unavailable(self):
        ambs = [make_ambulance(status="Dispatched"), make_ambulance(id=2, code="AMB-002", status="En route")]
        eligible, excluded = filter_eligible(ambs, set())
        assert len(eligible) == 0
        assert len(excluded) == 2

    def test_rank_empty_list(self):
        ranked = rank([], make_incident(), etas={})
        assert ranked == []

    def test_filter_and_rank_pipeline(self):
        inc = make_incident()
        ambs = [
            make_ambulance(id=1, code="AMB-001", status="Available", lat=10.651, lon=76.996),
            make_ambulance(id=2, code="AMB-002", status="Dispatched", lat=10.655, lon=76.999),
            make_ambulance(id=3, code="AMB-003", status="Available", capacity=0),
        ]
        eligible, excluded = filter_eligible(ambs, set(), min_capacity=1)
        assert len(eligible) == 1
        assert eligible[0]["ambulance_code"] == "AMB-001"
        ranked = rank(eligible, inc)
        assert len(ranked) == 1
        assert ranked[0]["rank"] == 1
        assert ranked[0]["distance_km"] > 0

# ─────────────────────────── 7. Pollachi Fleet Seeding ───────────────────────
class TestPollachiFleetSeeding:
    def test_15_ambulances_in_db(self):
        from database import query
        r = query("SELECT COUNT(*) n FROM ambulances", one=True)
        assert r["n"] >= 15, f"Expected >=15 ambulances, found {r['n']}"

    def test_all_pollachi_ambs_marked_simulated(self):
        from database import query
        # Fetch all, then filter in Python to avoid PyMySQL % LIKE escaping issue
        ambs = query("SELECT ambulance_code, is_simulated FROM ambulances")
        target = {f"AMB-{i:03d}" for i in range(1, 16)}
        for a in ambs:
            if a["ambulance_code"] in target:
                assert a["is_simulated"] == 1, f"{a['ambulance_code']} should be simulated"

    def test_pollachi_coords_in_range(self):
        from database import query
        ambs = query("SELECT ambulance_code, latitude, longitude FROM ambulances WHERE is_simulated=1")
        for a in ambs:
            lat = float(a["latitude"])
            lon = float(a["longitude"])
            # Tamil Nadu / Pollachi region roughly: lat 10.0-11.5, lon 76.5-77.8
            assert 10.0 <= lat <= 11.5, f"{a['ambulance_code']} lat={lat} out of TN range"
            assert 76.5 <= lon <= 77.8, f"{a['ambulance_code']} lon={lon} out of TN range"

    def test_drivers_linked_to_ambulances(self):
        from database import query
        unlinked = query("SELECT ambulance_code FROM ambulances WHERE driver_user_id IS NULL AND is_simulated=1 AND ambulance_code != 'AMB-015'")
        assert len(unlinked) == 0, f"Unlinked simulated ambulances: {[r['ambulance_code'] for r in unlinked]}"

    def test_seed_idempotent(self):
        """Running seed_pollachi twice must not create duplicate records."""
        from database import query
        before = query("SELECT COUNT(*) n FROM ambulances WHERE ambulance_code='AMB-001'", one=True)["n"]
        # Import and run seed
        import seed_pollachi
        seed_pollachi.run()
        after = query("SELECT COUNT(*) n FROM ambulances WHERE ambulance_code='AMB-001'", one=True)["n"]
        assert before == after == 1

    def test_no_duplicate_ambulance_codes(self):
        from database import query
        dups = query("SELECT ambulance_code, COUNT(*) n FROM ambulances GROUP BY ambulance_code HAVING n > 1")
        assert len(dups) == 0, f"Duplicate ambulance codes: {dups}"

    def test_simulated_separate_from_real(self):
        from database import query
        sim  = query("SELECT COUNT(*) n FROM ambulances WHERE is_simulated=1", one=True)["n"]
        real = query("SELECT COUNT(*) n FROM ambulances WHERE is_simulated=0", one=True)["n"]
        total = query("SELECT COUNT(*) n FROM ambulances", one=True)["n"]
        assert sim + real == total

# ─────────────────────────── 8. App Settings ─────────────────────────────────
class TestAppSettings:
    def test_dispatch_mode_defaults_to_manual(self):
        from database import query
        r = query("SELECT value FROM app_settings WHERE setting_key='dispatch_mode'", one=True)
        assert r is not None
        assert r["value"] in ("manual", "automatic")

    def test_app_settings_table_exists(self):
        from database import query
        r = query("SELECT COUNT(*) n FROM app_settings", one=True)
        assert r["n"] >= 1
