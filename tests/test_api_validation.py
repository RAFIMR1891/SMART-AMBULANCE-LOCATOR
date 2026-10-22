"""Endpoint tests that need no MySQL: auth guard + validation fire before any DB call."""
import app as appmod

def client(): return appmod.app.test_client()

def test_requires_login():
    assert client().get("/api/ambulances").status_code == 401

def test_login_validation():
    r = client().post("/api/auth/login", json={})
    assert r.status_code == 400 and r.get_json()["success"] is False

def test_dispatcher_cannot_hit_admin_only_when_wrong_role():
    c = client()
    with c.session_transaction() as s: s.update(user_id=1, role="viewer")
    assert c.post("/api/ambulances", json={}).status_code == 403

def test_invalid_coordinates_rejected():
    c = client()
    with c.session_transaction() as s: s.update(user_id=1, role="dispatcher")
    r = c.post("/api/ambulances", json={"ambulance_code": "X", "registration_number": "Y", "latitude": 95, "longitude": 0})
    assert r.status_code == 422

def test_gemini_and_maps_failures_are_graceful(monkeypatch):
    from services import gemini_service, google_maps_service
    monkeypatch.setattr(gemini_service.config, "GEMINI_API_KEY", "")
    assert gemini_service.ask_gemini("t", "f")[1] is not None
    monkeypatch.setattr(google_maps_service.config, "MAPS_SERVER_KEY", "k")
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    etas, err = google_maps_service.traffic_etas([{"id": 1, "latitude": 1, "longitude": 1}], {"latitude": 2, "longitude": 2})
    assert etas == {} and "unavailable" in err
