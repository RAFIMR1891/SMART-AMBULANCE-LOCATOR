"""Smart Ambulance Locator - Flask backend (routes kept in one file for readability)."""
import uuid, click
from functools import wraps
from flask import Flask, jsonify, request, session, render_template, redirect
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql, config
from database import query, transaction
from services.haversine import validate_coordinates
from services.ambulance_allocator import filter_eligible, rank, explain
from services.google_maps_service import traffic_etas
from services.gemini_service import ask_gemini

app = Flask(__name__)
app.secret_key = config.SECRET_KEY or "dev-only-change-me"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
CORS(app, origins=config.ALLOWED_ORIGINS, supports_credentials=True)

STATUSES = ["Available", "Assigned", "Dispatched", "En route", "At scene", "Transporting patient", "Out of service"]
TYPES = ["Fire accident", "Road accident", "Cardiac emergency", "Other emergency"]
STAFF = ["admin", "dispatcher"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]

def ok(data=None, code=200, **kw):  return jsonify(success=True, data=data, **kw), code
def fail(msg, code=400):            return jsonify(success=False, error=msg), code

@app.errorhandler(Exception)
def handle_error(e):
    if hasattr(e, "code") and isinstance(e.code, int):  # HTTP errors
        return fail(getattr(e, "description", "Error"), e.code)
    app.logger.exception(e)
    return fail("Internal server error", 500)  # safe message, details only in logs

def login_required(roles=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return fail("Authentication required", 401)
            if roles and session.get("role") not in roles:
                return fail("Insufficient permissions", 403)
            return f(*a, **kw)
        return wrapper
    return deco

def body():
    return request.get_json(silent=True) or {}

def coords(d):
    try: return validate_coordinates(d.get("latitude"), d.get("longitude"))
    except ValueError as e: raise ValueError(str(e))

# ---------- pages ----------
@app.route("/")
def index():
    if session.get("role") in HOME: return redirect(HOME[session["role"]])
    return render_template("landing.html")
@app.route("/signup")
def signup_page(): return render_template("signup.html")
HOME = {"admin": "/dashboard", "dispatcher": "/dashboard", "user": "/user", "driver": "/driver"}
@app.route("/login")
def login_page(): return render_template("login.html")
@app.route("/user")
def user_page():
    if session.get("role") != "user": return redirect("/login")
    return render_template("user.html", maps_key=config.MAPS_BROWSER_KEY, user=session.get("name"), role_label="User")
@app.route("/driver")
def driver_page():
    if session.get("role") != "driver": return redirect("/login")
    return render_template("driver.html", maps_key=config.MAPS_BROWSER_KEY, user=session.get("name"), role_label="Driver")
@app.route("/dashboard")
def dashboard():
    if session.get("role") not in STAFF: return redirect("/login")
    return render_template("dashboard.html", maps_key=config.MAPS_BROWSER_KEY, user=session.get("name"), role=session.get("role"), role_label=session.get("role", "").title())

# ---------- auth ----------
@app.post("/api/auth/login")
def login():
    d = body(); email, pw = (d.get("email") or "").strip().lower(), d.get("password") or ""
    if not email or not pw: return fail("Email and password are required")
    u = query("SELECT * FROM users WHERE email=%s AND is_active=1", (email,), one=True)
    if not u or not check_password_hash(u["password_hash"], pw): return fail("Invalid credentials", 401)
    groups = {"user": {"user"}, "driver": {"driver"}, "admin": {"admin", "dispatcher"}}
    if d.get("role") and u["role"] not in groups.get(d["role"], set()):
        return fail("These credentials do not belong to the selected role", 401)
    session.clear(); session.update(user_id=u["id"], role=u["role"], name=u["name"])
    return ok({"name": u["name"], "role": u["role"]})
@app.post("/api/auth/logout")
def logout(): session.clear(); return ok()

@app.cli.command("create-admin")
@click.option("--name", prompt=True)
@click.option("--email", prompt=True)
@click.password_option()
def create_admin(name, email, password):
    """First administrator: flask create-admin (password prompted, never stored in plain text)."""
    if len(password) < 8: raise click.ClickException("Password must be at least 8 characters")
    query("INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,'admin')",
          (name, email.lower(), generate_password_hash(password)))
    click.echo("Admin created.")

# ---------- dashboard ----------
@app.get("/api/dashboard/summary")
@login_required(STAFF)
def summary():
    s = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM ambulances GROUP BY status")}
    return ok({
        "total_ambulances": sum(s.values()), "available": s.get("Available", 0),
        "assigned": s.get("Assigned", 0) + s.get("Dispatched", 0),
        "en_route": s.get("En route", 0), "status_counts": s,
        "active_incidents": query("SELECT COUNT(*) n FROM incidents WHERE status<>'Closed'", one=True)["n"],
        "patients": query("SELECT COUNT(*) n FROM patients", one=True)["n"],
        "new_requests": query("SELECT COUNT(*) n FROM incidents WHERE status='Open'", one=True)["n"],
        "completed_today": query("SELECT COUNT(*) n FROM dispatches WHERE status='Completed' AND DATE(completed_at)=CURDATE()", one=True)["n"],
        "recent_incidents": query("SELECT id,incident_code,title,priority,status,reported_at FROM incidents ORDER BY id DESC LIMIT 5"),
        "recent_dispatches": query("""SELECT d.id,a.ambulance_code,i.incident_code,d.eta_source,d.assigned_at,d.status
                                      FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id
                                      JOIN incidents i ON i.id=d.incident_id ORDER BY d.id DESC LIMIT 5"""),
    }, last_updated=str(query("SELECT NOW() t", one=True)["t"]))

# ---------- ambulances ----------
@app.get("/api/ambulances")
@login_required(STAFF)
def list_ambulances():
    return ok(query("""SELECT a.*, (SELECT i.incident_code FROM dispatches d JOIN incidents i ON i.id=d.incident_id
                       WHERE d.ambulance_id=a.id AND d.status='Active' LIMIT 1) AS current_incident, (SELECT name FROM users WHERE id=a.driver_user_id) AS driver_name
                       FROM ambulances a ORDER BY ambulance_code"""))

@app.post("/api/ambulances")
@login_required(["admin", "dispatcher"])
def add_ambulance():
    d = body()
    try: lat, lon = coords(d)
    except ValueError as e: return fail(str(e), 422)
    code, reg = (d.get("ambulance_code") or "").strip().upper(), (d.get("registration_number") or "").strip()
    cap = d.get("capacity", 1)
    if not code or not reg: return fail("ambulance_code and registration_number are required", 422)
    if not isinstance(cap, int) or cap < 1: return fail("capacity must be a positive integer", 422)
    try:
        query("""INSERT INTO ambulances (ambulance_code,registration_number,latitude,longitude,capacity,equipment,last_location_update,available_since)
                 VALUES (%s,%s,%s,%s,%s,%s,NOW(),NOW())""", (code, reg, lat, lon, cap, d.get("equipment", "")))
    except pymysql.err.IntegrityError: return fail("Ambulance code or registration already exists", 409)
    return ok(code=201, data={"ambulance_code": code})

@app.patch("/api/ambulances/<int:aid>/location")
@login_required(STAFF)
def set_location(aid):
    try: lat, lon = coords(body())
    except ValueError as e: return fail(str(e), 422)
    n = _exec("UPDATE ambulances SET latitude=%s,longitude=%s,last_location_update=NOW() WHERE id=%s", (lat, lon, aid))
    return ok() if n else fail("Ambulance not found", 404)

@app.patch("/api/ambulances/<int:aid>/status")
@login_required(STAFF)
def set_status(aid):
    st = body().get("status")
    if st not in STATUSES: return fail(f"status must be one of {STATUSES}", 422)
    with transaction() as cur:
        cur.execute("SELECT status FROM ambulances WHERE id=%s FOR UPDATE", (aid,))
        row = cur.fetchone()
        if not row: return fail("Ambulance not found", 404)
        cur.execute("SELECT id FROM dispatches WHERE ambulance_id=%s AND status='Active'", (aid,))
        active = cur.fetchone()
        if st in ("Available", "Out of service") and active:
            return fail("Ambulance has an active dispatch; complete or cancel it first", 409)
        cur.execute("UPDATE ambulances SET status=%s, available_since=IF(%s='Available',NOW(),available_since) WHERE id=%s", (st, st, aid))
    return ok()

def _exec(sql, args):
    with transaction() as cur:
        cur.execute(sql, args); return cur.rowcount

# ---------- incidents & patients ----------
@app.get("/api/incidents")
@login_required(STAFF)
def list_incidents(): return ok(query("SELECT * FROM incidents ORDER BY id DESC"))

@app.post("/api/incidents")
@login_required(["admin", "dispatcher"])
def add_incident():
    d = body()
    try: lat, lon = coords(d)
    except ValueError as e: return fail(str(e), 422)
    if not (d.get("title") or "").strip(): return fail("title is required", 422)
    if d.get("incident_type") not in TYPES: return fail(f"incident_type must be one of {TYPES}", 422)
    if d.get("priority", "High") not in PRIORITIES: return fail(f"priority must be one of {PRIORITIES}", 422)
    n = d.get("estimated_patient_count", 1)
    if not isinstance(n, int) or n < 0: return fail("estimated_patient_count must be >= 0", 422)
    code = "INC-" + uuid.uuid4().hex[:8].upper()
    query("""INSERT INTO incidents (incident_code,title,description,incident_type,latitude,longitude,estimated_patient_count,priority,created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (code, d["title"].strip(), d.get("description", ""), d["incident_type"], lat, lon, n, d.get("priority", "High"), session["user_id"]))
    return ok({"incident_code": code}, 201)

def get_incident(iid): return query("SELECT * FROM incidents WHERE id=%s", (iid,), one=True)

@app.get("/api/incidents/<int:iid>")
@login_required(STAFF)
def incident_detail(iid):
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    inc["patients"] = query("SELECT case_reference,triage_category,transport_status,assigned_ambulance_id FROM patients WHERE incident_id=%s", (iid,))
    inc["dispatches"] = query("""SELECT d.id,a.ambulance_code,d.status,d.distance_km,d.estimated_travel_seconds,d.eta_source
                                 FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id WHERE d.incident_id=%s""", (iid,))
    return ok(inc)

@app.post("/api/incidents/<int:iid>/patients")
@login_required(["admin", "dispatcher"])
def add_patients(iid):
    if not get_incident(iid): return fail("Incident not found", 404)
    d = body(); count = d.get("count", 1); triage = d.get("triage_category")  # triage is entered by a human, never by AI
    if not isinstance(count, int) or not 1 <= count <= 100: return fail("count must be 1-100", 422)
    refs = []
    with transaction() as cur:
        for _ in range(count):
            ref = "CASE-" + uuid.uuid4().hex[:8].upper(); refs.append(ref)
            cur.execute("INSERT INTO patients (case_reference,incident_id,triage_category) VALUES (%s,%s,%s)", (ref, iid, triage))
    return ok({"case_references": refs}, 201)

# ---------- recommend + dispatch ----------
def _candidates(iid, inc, equipment, min_cap):
    ambs = query("SELECT * FROM ambulances")
    active = {r["ambulance_id"] for r in query("SELECT ambulance_id FROM dispatches WHERE status='Active'")}
    elig = filter_eligible(ambs, active, equipment, min_cap)
    etas, err = traffic_etas(elig, inc)
    return rank(elig, inc, etas), err

@app.post("/api/incidents/<int:iid>/recommend-ambulances")
@login_required(STAFF)
def recommend(iid):
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    d = body()
    rows, err = _candidates(iid, inc, d.get("required_equipment", []), int(d.get("min_capacity", 1)))
    out = [{"id": r["id"], "ambulance": r["ambulance_code"], "distance_km": r["distance_km"], "eta_seconds": r["eta_seconds"],
            "eta_source": r["eta_source"], "status": r["status"], "reason": explain(r)} for r in rows]
    return ok(out, maps_warning=err, note="Distance is straight-line (Haversine); ETA shown only when Google Routes returned one.")

@app.post("/api/incidents/<int:iid>/dispatch")
@login_required(["admin", "dispatcher"])
def dispatch(iid):
    """Dispatcher-confirmed. Body: {"ambulance_ids":[...]}. All-or-nothing transaction."""
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    ids = body().get("ambulance_ids")
    if not isinstance(ids, list) or not ids: return fail("ambulance_ids must be a non-empty list", 422)
    ranked, _ = _candidates(iid, inc, [], 1)
    info = {r["id"]: r for r in ranked}
    try:
        with transaction() as cur:
            cur.execute("SELECT status FROM incidents WHERE id=%s FOR UPDATE", (iid,))
            if cur.fetchone()["status"] not in ("Open", "In progress"):
                raise ValueError("Incident is closed or cancelled")
            for aid in sorted(set(ids)):  # sorted lock order avoids deadlocks
                cur.execute("SELECT status FROM ambulances WHERE id=%s FOR UPDATE", (aid,))
                row = cur.fetchone()
                if not row or row["status"] != "Available" or aid not in info:
                    raise ValueError(f"Ambulance {aid} is not available for this incident")
                r = info[aid]
                cur.execute("""INSERT INTO dispatches (incident_id,ambulance_id,assigned_by,distance_km,estimated_travel_seconds,eta_source)
                               VALUES (%s,%s,%s,%s,%s,%s)""", (iid, aid, session["user_id"], r["distance_km"], r["eta_seconds"], r["eta_source"]))
                did = cur.lastrowid
                cur.execute("SELECT COALESCE(MAX(queue_position),0)+1 p FROM ambulances FOR UPDATE")
                pos = cur.fetchone()["p"]
                cur.execute("UPDATE ambulances SET status='Dispatched', queue_position=%s WHERE id=%s", (pos, aid))
                cur.execute("""INSERT INTO dispatch_history (dispatch_id,action,previous_status,new_status,reason)
                               VALUES (%s,'dispatched','Available','Dispatched',%s)""", (did, explain(r)))
            cur.execute("UPDATE incidents SET status='In progress' WHERE id=%s AND status='Open'", (iid,))
    except ValueError as e:
        return fail(str(e), 409)
    except pymysql.err.IntegrityError:
        return fail("Duplicate active assignment prevented", 409)
    return ok({"dispatched": sorted(set(ids))}, 201)

@app.get("/api/dispatches")
@login_required(STAFF)
def dispatches():
    return ok(query("""SELECT d.*, a.ambulance_code, i.incident_code FROM dispatches d
                       JOIN ambulances a ON a.id=d.ambulance_id JOIN incidents i ON i.id=d.incident_id ORDER BY d.id DESC LIMIT 100"""))

# ---------- AI (text only; minimal, non-identifying data) ----------
def _facts(iid):
    inc = get_incident(iid)
    if not inc: return None
    cnt = query("SELECT COUNT(*) n FROM patients WHERE incident_id=%s", (iid,), one=True)["n"]
    ds = query("""SELECT a.ambulance_code,d.status,d.distance_km,d.estimated_travel_seconds,d.eta_source,h.reason FROM dispatches d
                  JOIN ambulances a ON a.id=d.ambulance_id LEFT JOIN dispatch_history h ON h.dispatch_id=d.id WHERE d.incident_id=%s""", (iid,))
    return (f"Incident {inc['incident_code']}: {inc['title']} ({inc['incident_type']}), priority {inc['priority']}, status {inc['status']}, "
            f"estimated patients {inc['estimated_patient_count']}, recorded patient cases {cnt}.\nDispatches: {ds}")  # no patient identifiers sent

def _ai(task):
    iid = body().get("incident_id")
    facts = _facts(iid) if isinstance(iid, int) else None
    if not facts: return fail("Valid incident_id required", 422)
    extra = body().get("question")
    text, err = ask_gemini(f"{task} {extra or ''}", facts)
    return fail(err, 503) if err else ok({"text": text, "draft": True})

@app.post("/api/ai/incident-summary")
@login_required(STAFF)
def ai_summary(): return _ai("Write a concise summary of this incident and the ambulance resources assigned.")
@app.post("/api/ai/explain-allocation")
@login_required(STAFF)
def ai_explain(): return _ai("Explain why the listed ambulances were selected, using only the recorded reasons.")
@app.post("/api/ai/generate-report")
@login_required(STAFF)
def ai_report(): return _ai("Draft an incident report: details, patient count, assigned ambulances, status updates, outstanding tasks. Mark it as a DRAFT for dispatcher review.")

from routes.portal_routes import register as _register_portals
_register_portals(app, __import__("sys").modules[__name__])

if __name__ == "__main__":
    import os
    app.run(debug=os.getenv("FLASK_ENV") == "development")
