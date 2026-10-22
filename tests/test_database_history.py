"""Targeted tests for Phase 1 (Database History Schema) and Phase 2 (Auto-Dispatch Workflow)."""
import uuid
import pytest
from werkzeug.security import generate_password_hash
import app as appmod
from database import query, connect, transaction

try:
    connect().close()
    DB_UP = True
except Exception:
    DB_UP = False

pytestmark = pytest.mark.skipif(not DB_UP, reason="MySQL not reachable")


def login(email, pw="password123"):
    c = appmod.app.test_client()
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.get_json()
    return c


@pytest.fixture
def test_setup():
    tag = uuid.uuid4().hex[:6]
    admin_email = f"adm_hist_{tag}@t.co"
    user_email = f"usr_hist_{tag}@t.co"
    pw = "password123"

    query("INSERT INTO users (name, email, password_hash, role) VALUES ('AdminTest', %s, %s, 'admin')",
          (admin_email, generate_password_hash(pw)))
    query("INSERT INTO users (name, email, password_hash, role) VALUES ('UserTest', %s, %s, 'user')",
          (user_email, generate_password_hash(pw)))

    admin_client = login(admin_email, pw)
    user_client = login(user_email, pw)

    return {
        "admin": admin_client,
        "user": user_client,
        "admin_email": admin_email,
        "user_email": user_email,
        "tag": tag
    }


def test_mode_change_history_nullable_dispatch(test_setup):
    """Phase 1: Mode change must record in dispatch_history with NULL dispatch_id and no FK violation."""
    admin = test_setup["admin"]

    # Switch to manual
    r1 = admin.post("/api/settings/dispatch-mode", json={"mode": "manual", "reason": "Test switch to manual"})
    assert r1.status_code == 200, r1.get_json()
    assert r1.get_json()["data"]["mode"] == "manual"

    # Switch to automatic
    r2 = admin.post("/api/settings/dispatch-mode", json={"mode": "automatic", "reason": "Test switch to automatic"})
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["data"]["mode"] == "automatic"

    # Verify database records
    rows = query("""
        SELECT * FROM dispatch_history
        WHERE action = 'mode_change'
        ORDER BY id DESC LIMIT 2
    """)
    assert len(rows) >= 1
    latest = rows[0]
    assert latest["dispatch_id"] is None
    assert latest["incident_id"] is None
    assert latest["action"] == "mode_change"
    assert "mode:automatic" in (latest["new_status"] or "")


def test_auto_dispatch_failure_nullable_dispatch(test_setup):
    """Phase 1: Auto-dispatch failure must record with NULL dispatch_id and the actual incident_id."""
    admin = test_setup["admin"]

    # Create an impossible incident (e.g. 99 patients requiring impossible capacity)
    code = f"INC-FAIL-{test_setup['tag'].upper()}"
    query("""
        INSERT INTO incidents (incident_code, title, description, incident_type, latitude, longitude, estimated_patient_count, priority, created_by)
        VALUES (%s, 'Huge Disaster Test', 'Impossible capacity', 'Road accident', 10.6550, 76.9988, 99, 'Critical', 1)
    """, (code,))
    inc = query("SELECT id FROM incidents WHERE incident_code=%s", (code,), one=True)
    iid = inc["id"]

    # Trigger auto-dispatch
    r = admin.post(f"/api/incidents/{iid}/auto-dispatch")
    assert r.status_code == 409, "Expected auto-dispatch to fail due to impossible capacity"

    # Verify history event exists with NULL dispatch_id and valid incident_id
    history_row = query("""
        SELECT * FROM dispatch_history
        WHERE incident_id = %s AND action = 'auto_dispatch_failed'
        ORDER BY id DESC LIMIT 1
    """, (iid,), one=True)
    assert history_row is not None
    assert history_row["dispatch_id"] is None
    assert history_row["incident_id"] == iid
    assert "No eligible ambulance found" in (history_row["reason"] or "")

    # Verify incident record has last_fail_reason populated
    inc_row = query("SELECT status, last_fail_reason FROM incidents WHERE id=%s", (iid,), one=True)
    assert inc_row["status"] == "Open"
    assert inc_row["last_fail_reason"] is not None
    assert "No eligible ambulance found" in inc_row["last_fail_reason"]


def test_history_endpoint_displays_pre_dispatch_events(test_setup):
    """Phase 1: GET /api/dispatch-history must return mode changes and failures even without dispatches."""
    admin = test_setup["admin"]

    r = admin.get("/api/dispatch-history")
    assert r.status_code == 200
    events = r.get_json()["data"]

    # Ensure mode changes are visible
    actions = [e["action"] for e in events]
    assert "mode_change" in actions, "mode_change event missing from dispatch history"

    # Validate that records with NULL dispatch_id have '-' for ambulance_code
    for e in events:
        if e["dispatch_id"] is None:
            assert e["ambulance_code"] == "-"


def test_patient_request_auto_dispatch_enabled(test_setup):
    """Phase 2: When mode is automatic, user request triggers auto-dispatch workflow."""
    admin = test_setup["admin"]
    user = test_setup["user"]

    # Ensure automatic mode is active
    admin.post("/api/settings/dispatch-mode", json={"mode": "automatic", "reason": "Test automatic"})

    # Submit emergency request
    r = user.post("/api/user/requests", json={
        "incident_type": "Road accident",
        "description": "Urgent assistance needed",
        "latitude": 10.6550,
        "longitude": 76.9988,
        "estimated_patient_count": 1
    })
    assert r.status_code == 201, r.get_json()
    resp = r.get_json()["data"]
    assert "incident_code" in resp
    assert "dispatch_status" in resp
    assert resp["dispatch_status"] in ("assigned", "needs_human_action")

    # If assigned, verify patient detail shows the assigned ambulance
    code = resp["incident_code"]
    inc = query("SELECT id FROM incidents WHERE incident_code=%s", (code,), one=True)
    iid = inc["id"]

    detail = user.get(f"/api/user/requests/{iid}").get_json()["data"]
    if resp["dispatch_status"] == "assigned":
        assert len(detail["ambulances"]) > 0
        assert detail["status"] == "In progress"
    else:
        assert detail["status"] == "Open"


def test_patient_request_manual_mode_awaits_dispatch(test_setup):
    """Phase 2: When mode is manual, user request is saved as Open awaiting dispatch."""
    admin = test_setup["admin"]
    user = test_setup["user"]

    # Ensure manual mode is active
    admin.post("/api/settings/dispatch-mode", json={"mode": "manual", "reason": "Test manual"})

    # Submit request
    r = user.post("/api/user/requests", json={
        "incident_type": "Cardiac emergency",
        "description": "Chest pain at home",
        "latitude": 10.6580,
        "longitude": 77.0010,
        "estimated_patient_count": 1
    })
    assert r.status_code == 201, r.get_json()
    resp = r.get_json()["data"]
    assert resp["dispatch_status"] == "awaiting_dispatch"
    assert resp["assigned"] is False

    # Check database status
    inc = query("SELECT status FROM incidents WHERE incident_code=%s", (resp["incident_code"],), one=True)
    assert inc["status"] == "Open"

    # Reset back to automatic default
    admin.post("/api/settings/dispatch-mode", json={"mode": "automatic", "reason": "Reset to default"})


def test_needs_dispatch_summary_and_panel(test_setup):
    """Phase 5 & 6: Incidents needing human intervention appear in needs-dispatch panel and summary."""
    admin = test_setup["admin"]

    # Get initial count
    summary = admin.get("/api/dashboard/summary").get_json()["data"]
    init_needs = summary.get("needs_human", 0)

    # Create an incident with a recorded auto-dispatch failure
    code = f"INC-NEED-{test_setup['tag'].upper()}"
    query("""
        INSERT INTO incidents (incident_code, title, description, incident_type, latitude, longitude, estimated_patient_count, priority, created_by, last_fail_reason)
        VALUES (%s, 'Needs Dispatcher Test', 'No ambulance in area', 'Fire accident', 10.6550, 76.9988, 1, 'High', 1, 'No eligible ambulance available')
    """, (code,))

    # Check panel
    panel = admin.get("/api/incidents/needs-dispatch").get_json()["data"]
    codes = [item["incident_code"] for item in panel]
    assert code in codes

    # Check summary count increased
    new_summary = admin.get("/api/dashboard/summary").get_json()["data"]
    assert new_summary["needs_human"] >= init_needs + 1
