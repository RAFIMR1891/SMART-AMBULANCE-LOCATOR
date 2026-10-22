"""Full user -> dispatcher -> driver -> user workflow against a REAL MySQL/MariaDB.
Skipped automatically when the database is not reachable. Needs schema.sql + migration_001 applied."""
import uuid, pytest
from werkzeug.security import generate_password_hash
import app as appmod
from database import query, connect

try: connect().close(); DB_UP = True
except Exception: DB_UP = False
pytestmark = pytest.mark.skipif(not DB_UP, reason="MySQL not reachable")

def login(email, pw="password123"):
    c = appmod.app.test_client(); r = c.post("/api/auth/login", json={"email": email, "password": pw}); assert r.status_code == 200, r.get_json(); return c

def test_complete_workflow():
    tag = uuid.uuid4().hex[:6]
    query("UPDATE ambulances SET status='Available', driver_user_id=NULL")
    query("DELETE FROM dispatch_history"); query("UPDATE patients SET assigned_ambulance_id=NULL"); query("DELETE FROM dispatches")
    query("INSERT INTO users (name,email,password_hash,role) VALUES ('Adm',%s,%s,'admin')", (f"adm{tag}@t.co", generate_password_hash("password123")))
    admin = login(f"adm{tag}@t.co")
    # accounts: user self-registers, admin creates a driver linked to AMB101
    anon = appmod.app.test_client()
    for n in ("u1", "u2"): assert anon.post("/api/auth/register", json={"name": n, "email": f"{n}{tag}@t.co", "password": "password123"}).status_code == 201
    assert anon.post("/api/auth/register", json={"name": "n", "email": f"u1{tag}@t.co", "password": "password123"}).status_code == 409
    amb = {a["ambulance_code"]: a for a in admin.get("/api/ambulances").get_json()["data"]}
    r = admin.post("/api/admin/users", json={"name": "Drv", "email": f"drv{tag}@t.co", "password": "password123", "role": "driver", "ambulance_id": amb["AMB101"]["id"]})
    assert r.status_code == 201
    u1, u2, drv = login(f"u1{tag}@t.co"), login(f"u2{tag}@t.co"), login(f"drv{tag}@t.co")
    # 1-3: user request appears for dispatcher
    r = u1.post("/api/user/requests", json={"incident_type": "Fire accident", "description": "Fire, people hurt", "latitude": 10.0159, "longitude": 76.3419, "estimated_patient_count": 3})
    assert r.status_code == 201
    inc = next(i for i in admin.get("/api/incidents").get_json()["data"] if i["incident_code"] == r.get_json()["data"]["incident_code"])
    # 4-7: recommendation (Haversine fallback, labelled) and confirmed dispatch
    rec = admin.post(f"/api/incidents/{inc['id']}/recommend-ambulances", json={}).get_json()
    assert rec["data"][0]["ambulance"] == "AMB101" and rec["data"][0]["eta_source"] == "haversine_distance_fallback" and rec["maps_warning"]
    assert admin.post(f"/api/incidents/{inc['id']}/dispatch", json={"ambulance_ids": [amb["AMB101"]["id"], amb["AMB102"]["id"]]}).status_code == 201
    # duplicate active assignment prevented
    assert admin.post(f"/api/incidents/{inc['id']}/dispatch", json={"ambulance_ids": [amb["AMB101"]["id"]]}).status_code == 409
    # 9: driver sees it, only his own
    me = drv.get("/api/driver/me").get_json()["data"]
    assert len(me["assignments"]) == 1 and me["assignments"][0]["incident_code"] == inc["incident_code"]
    # 10: status flow enforced + location saved
    assert drv.patch("/api/driver/status", json={"status": "Completed"}).status_code == 409
    for s in ("En route", "Arrived at scene", "Transporting patient"): assert drv.patch("/api/driver/status", json={"status": s}).status_code == 200, s
    assert drv.post("/api/driver/location", json={"latitude": 10.02, "longitude": 76.33}).status_code == 200
    # 11: user sees ambulance + last position; another user cannot see the request
    d = u1.get(f"/api/user/requests/{inc['id']}").get_json()
    assert d["data"]["ambulances"][0]["ambulance_code"] in ("AMB101", "AMB102") and d["data"]["status"] == "In progress"
    assert u2.get(f"/api/user/requests/{inc['id']}").status_code == 404
    assert u2.post(f"/api/user/requests/{inc['id']}/cancel").status_code == 404
    assert u1.post(f"/api/user/requests/{inc['id']}/cancel").status_code == 409   # already dispatched
    # driver completes; ambulance returns to Available; history recorded (13)
    assert drv.patch("/api/driver/status", json={"status": "Completed"}).status_code == 200
    assert query("SELECT status FROM ambulances WHERE id=%s", (amb["AMB101"]["id"],), one=True)["status"] == "Available"
    assert query("SELECT COUNT(*) n FROM dispatch_history WHERE action='driver_status'", one=True)["n"] == 4
    # 12: dispatcher cancels the second (still active) dispatch -> ambulance freed
    did = next(x for x in admin.get("/api/dispatches").get_json()["data"] if x["status"] == "Active")["id"]
    assert admin.post(f"/api/dispatches/{did}/cancel", json={}).status_code == 422
    assert admin.post(f"/api/dispatches/{did}/cancel", json={"reason": "reassign"}).status_code == 200
    assert query("SELECT COUNT(*) n FROM ambulances WHERE status='Available'", one=True)["n"] == 3
    # unlinked/foreign data: user cannot cancel after incident closed to dispatch, and cannot read staff data
    assert u1.get("/api/incidents").status_code == 403
