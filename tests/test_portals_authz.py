"""Role isolation tests. They need no MySQL: the role guard rejects before any DB call."""
import app as appmod
import pytest

def as_role(role):
    c = appmod.app.test_client()
    with c.session_transaction() as s: s.update(user_id=7, role=role, name="t")
    return c

STAFF_ONLY = [("get", "/api/ambulances"), ("get", "/api/incidents"), ("get", "/api/dashboard/summary"), ("get", "/api/dispatches"),
              ("get", "/api/admin/users"), ("get", "/api/hospitals"), ("get", "/api/dispatch-history"),
              ("post", "/api/incidents/1/dispatch"), ("post", "/api/incidents/1/recommend-ambulances"), ("post", "/api/dispatches/1/cancel")]

@pytest.mark.parametrize("role", ["user", "driver"])
@pytest.mark.parametrize("method,url", STAFF_ONLY)
def test_user_and_driver_blocked_from_staff_api(role, method, url):
    assert getattr(as_role(role), method)(url, json={}).status_code == 403

@pytest.mark.parametrize("method,url", [("GET", "/api/driver/me"), ("POST", "/api/driver/location"), ("PATCH", "/api/driver/status")])
def test_only_drivers_use_driver_api(method, url):
    for role in ("user", "dispatcher", "admin"):
        assert as_role(role).open(url, method=method, json={}).status_code == 403

def test_only_users_use_user_api():
    for role in ("driver", "dispatcher", "admin"):
        assert as_role(role).post("/api/user/requests", json={}).status_code == 403
        assert as_role(role).get("/api/user/requests").status_code == 403

def test_dispatcher_cannot_create_accounts_or_link_drivers():
    assert as_role("dispatcher").post("/api/admin/users", json={}).status_code == 403
    assert as_role("dispatcher").patch("/api/ambulances/1/driver", json={}).status_code == 403

def test_anonymous_blocked():
    c = appmod.app.test_client()
    for u in ("/api/user/requests", "/api/driver/me", "/api/ambulances"):
        assert c.get(u).status_code == 401

def test_pages_redirect_wrong_roles():
    assert as_role("user").get("/dashboard").status_code == 302
    assert as_role("driver").get("/user").status_code == 302
    assert as_role("user").get("/driver").status_code == 302
    assert as_role("driver").get("/driver").status_code == 200

def test_registration_validation_and_no_role_escalation():
    c = appmod.app.test_client()
    assert c.post("/api/auth/register", json={"name": "a", "email": "bad", "password": "longenough"}).status_code == 422
    assert c.post("/api/auth/register", json={"name": "a", "email": "a@b.co", "password": "short"}).status_code == 422

def test_user_request_validation():
    c = as_role("user")
    assert c.post("/api/user/requests", json={"latitude": 99, "longitude": 0, "description": "x"}).status_code == 422
    assert c.post("/api/user/requests", json={"latitude": 10, "longitude": 76, "description": ""}).status_code == 422
    assert c.post("/api/user/requests", json={"latitude": 10, "longitude": 76, "description": "x", "estimated_patient_count": 0}).status_code == 422

def test_driver_input_validation():
    c = as_role("driver")
    assert c.patch("/api/driver/status", json={"status": "Teleported"}).status_code == 422
    assert c.post("/api/driver/location", json={"latitude": "x", "longitude": 1}).status_code == 422

def test_public_pages_render():
    c = appmod.app.test_client()
    for u in ("/", "/login", "/signup"): assert c.get(u).status_code == 200

def test_portal_pages_render_for_their_role():
    for role, url in (("user", "/user"), ("driver", "/driver"), ("admin", "/dashboard"), ("dispatcher", "/dashboard")):
        r = as_role(role).get(url); assert r.status_code == 200 and b"Smart" in r.data
