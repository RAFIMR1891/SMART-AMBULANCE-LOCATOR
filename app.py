"""Smart Ambulance Locator — Flask backend.
Includes: Rule-Based AI Dispatch, Manual Dispatch, Auto-Fail Fallback,
          Pollachi Fleet, Dispatch Mode Management, Concurrency Safety.
"""
import uuid, click
from functools import wraps
from flask import Flask, jsonify, request, session, render_template, redirect
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql, config
from database import query, transaction
from services.haversine import validate_coordinates
from services.ambulance_allocator import filter_eligible, rank, explain, explain_exclusion
from services.google_maps_service import traffic_etas
from services.gemini_service import ask_gemini

app = Flask(__name__)
# Security: require SECRET_KEY in env; no insecure fallback in production
_secret = config.SECRET_KEY
if not _secret or len(_secret) < 16:
    import os
    if os.getenv("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY must be set (>=16 chars) in production")
    _secret = _secret or "dev-only-placeholder-change-me"
app.secret_key = _secret
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
CORS(app, origins=config.ALLOWED_ORIGINS, supports_credentials=True)

STATUSES   = ["Available", "Assigned", "Dispatched", "En route", "At scene", "Transporting patient", "Out of service"]
TYPES      = ["Fire accident", "Road accident", "Cardiac emergency", "Other emergency"]
STAFF      = ["admin", "dispatcher"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]

# ── Helpers ──────────────────────────────────────────────────────────────────
def ok(data=None, code=200, **kw):  return jsonify(success=True,  data=data, **kw), code
def fail(msg, code=400):            return jsonify(success=False, error=msg), code

@app.errorhandler(Exception)
def handle_error(e):
    if hasattr(e, "code") and isinstance(e.code, int):
        return fail(getattr(e, "description", "Error"), e.code)
    app.logger.exception(e)
    return fail("Internal server error", 500)

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

def body():  return request.get_json(silent=True) or {}

def coords(d):
    try:   return validate_coordinates(d.get("latitude"), d.get("longitude"))
    except ValueError as e: raise ValueError(str(e))

# ── Pages ────────────────────────────────────────────────────────────────────
HOME = {"admin": "/dashboard", "dispatcher": "/dashboard", "user": "/user", "driver": "/driver"}

@app.route("/")
def index():
    if session.get("role") in HOME:
        return redirect(HOME[session["role"]])
    return render_template("landing.html")

@app.route("/signup")
def signup_page(): return render_template("signup.html")

@app.route("/login")
def login_page(): return render_template("login.html")

@app.route("/user")
def user_page():
    if session.get("role") != "user": return redirect("/login")
    return render_template("user.html", maps_key=config.MAPS_BROWSER_KEY,
                           user=session.get("name"), role_label="User")

@app.route("/driver")
def driver_page():
    if session.get("role") != "driver": return redirect("/login")
    return render_template("driver.html", maps_key=config.MAPS_BROWSER_KEY,
                           user=session.get("name"), role_label="Driver")

@app.route("/dashboard")
def dashboard():
    if session.get("role") not in STAFF: return redirect("/login")
    return render_template("dashboard.html", maps_key=config.MAPS_BROWSER_KEY,
                           user=session.get("name"), role=session.get("role"),
                           role_label=session.get("role", "").title())

# ── Auth ─────────────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
def login():
    d = body()
    email, pw = (d.get("email") or "").strip().lower(), d.get("password") or ""
    if not email or not pw: return fail("Email and password are required")
    u = query("SELECT * FROM users WHERE email=%s AND is_active=1", (email,), one=True)
    if not u or not check_password_hash(u["password_hash"], pw):
        return fail("Invalid credentials", 401)
    groups = {"user": {"user"}, "driver": {"driver"}, "admin": {"admin", "dispatcher"}}
    if d.get("role") and u["role"] not in groups.get(d["role"], set()):
        return fail("These credentials do not belong to the selected role", 401)
    session.clear()
    session.update(user_id=u["id"], role=u["role"], name=u["name"])
    return ok({"name": u["name"], "role": u["role"]})

@app.post("/api/auth/logout")
def logout(): session.clear(); return ok()

@app.cli.command("create-admin")
@click.option("--name", prompt=True)
@click.option("--email", prompt=True)
@click.password_option()
def create_admin(name, email, password):
    """First administrator — flask create-admin (password never stored in plain text)."""
    if len(password) < 8: raise click.ClickException("Password must be at least 8 characters")
    query("INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,'admin')",
          (name, email.lower(), generate_password_hash(password)))
    click.echo("Admin created.")

# ── Dispatch mode management ─────────────────────────────────────────────────
def _get_dispatch_mode():
    """Read current global dispatch mode from app_settings. Default: manual."""
    try:
        row = query("SELECT value FROM app_settings WHERE setting_key='dispatch_mode'", one=True)
        return (row["value"] if row else "manual") or "manual"
    except Exception:
        return "manual"

@app.get("/api/settings/dispatch-mode")
@login_required(STAFF)
def get_dispatch_mode():
    return ok({"mode": _get_dispatch_mode()})

@app.post("/api/settings/dispatch-mode")
@login_required(["admin"])
def set_dispatch_mode():
    """Only admins can switch mode. Records who changed it and reason."""
    d = body()
    mode = d.get("mode")
    if mode not in ("manual", "automatic"):
        return fail("mode must be 'manual' or 'automatic'", 422)
    reason = (d.get("reason") or "").strip() or f"Changed to {mode} by admin"
    current = _get_dispatch_mode()
    if current == mode:
        return ok({"mode": mode, "note": "Mode unchanged"})
    with transaction() as cur:
        cur.execute("""
            INSERT INTO app_settings (setting_key, value, changed_by)
            VALUES ('dispatch_mode', %s, %s)
            ON DUPLICATE KEY UPDATE value=%s, changed_by=%s, changed_at=NOW()
        """, (mode, session["user_id"], mode, session["user_id"]))
        cur.execute("""
            INSERT INTO dispatch_history
              (dispatch_id, action, previous_status, new_status, reason,
               dispatch_mode, dispatcher_id)
            SELECT 0, 'mode_change', %s, %s, %s, %s, %s
        """, (f"mode:{current}", f"mode:{mode}", reason, mode, session["user_id"]))
    return ok({"mode": mode, "previous": current, "reason": reason})

# ── Dashboard summary ────────────────────────────────────────────────────────
@app.get("/api/dashboard/summary")
@login_required(STAFF)
def summary():
    s = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM ambulances GROUP BY status")}
    sim_count = query("SELECT COUNT(*) n FROM ambulances WHERE is_simulated=1", one=True)["n"]
    real_count = query("SELECT COUNT(*) n FROM ambulances WHERE is_simulated=0", one=True)["n"]

    # Dispatch mode stats
    auto_dispatched = query(
        "SELECT COUNT(*) n FROM dispatches WHERE dispatch_mode='Automatic'", one=True)["n"]
    manual_fallback = query(
        "SELECT COUNT(*) n FROM dispatches WHERE dispatch_mode='Manual Fallback'", one=True)["n"]
    needs_human = query(
        "SELECT COUNT(*) n FROM incidents WHERE status='Open' AND "
        "id IN (SELECT incident_id FROM dispatches WHERE auto_fail_reason IS NOT NULL AND status='Active')",
        one=True)["n"]

    return ok({
        "total_ambulances":  sum(s.values()),
        "available":         s.get("Available", 0),
        "assigned":          s.get("Assigned", 0) + s.get("Dispatched", 0),
        "en_route":          s.get("En route", 0),
        "at_scene":          s.get("At scene", 0),
        "status_counts":     s,
        "simulated_fleet":   sim_count,
        "real_fleet":        real_count,
        "active_incidents":  query("SELECT COUNT(*) n FROM incidents WHERE status<>'Closed'", one=True)["n"],
        "patients":          query("SELECT COUNT(*) n FROM patients", one=True)["n"],
        "new_requests":      query("SELECT COUNT(*) n FROM incidents WHERE status='Open'", one=True)["n"],
        "completed_today":   query("SELECT COUNT(*) n FROM dispatches WHERE status='Completed' AND DATE(completed_at)=CURDATE()", one=True)["n"],
        "auto_dispatched":   auto_dispatched,
        "manual_fallback":   manual_fallback,
        "needs_human":       needs_human,
        "dispatch_mode":     _get_dispatch_mode(),
        "recent_incidents":  query("SELECT id,incident_code,title,priority,status,reported_at FROM incidents ORDER BY id DESC LIMIT 5"),
        "recent_dispatches": query("""SELECT d.id,a.ambulance_code,i.incident_code,d.eta_source,d.assigned_at,d.status,d.dispatch_mode
                                      FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id
                                      JOIN incidents i ON i.id=d.incident_id ORDER BY d.id DESC LIMIT 5"""),
    }, last_updated=str(query("SELECT NOW() t", one=True)["t"]))

# ── Ambulances ───────────────────────────────────────────────────────────────
@app.get("/api/ambulances")
@login_required(STAFF)
def list_ambulances():
    filter_sim = request.args.get("simulated")  # "true" | "false" | None (all)
    where = ""
    if filter_sim == "true":  where = "WHERE a.is_simulated=1"
    elif filter_sim == "false": where = "WHERE a.is_simulated=0"
    return ok(query(f"""
        SELECT a.*,
          (SELECT i.incident_code FROM dispatches d JOIN incidents i ON i.id=d.incident_id
           WHERE d.ambulance_id=a.id AND d.status='Active' LIMIT 1) AS current_incident,
          (SELECT u.name FROM users u WHERE u.id=a.driver_user_id) AS driver_name
        FROM ambulances a {where} ORDER BY a.ambulance_code
    """))

@app.post("/api/ambulances")
@login_required(["admin", "dispatcher"])
def add_ambulance():
    d = body()
    try: lat, lon = coords(d)
    except ValueError as e: return fail(str(e), 422)
    code = (d.get("ambulance_code") or "").strip().upper()
    reg  = (d.get("registration_number") or "").strip()
    cap  = d.get("capacity", 1)
    if not code or not reg: return fail("ambulance_code and registration_number are required", 422)
    if not isinstance(cap, int) or cap < 1: return fail("capacity must be a positive integer", 422)
    try:
        query("""INSERT INTO ambulances
                   (ambulance_code,registration_number,latitude,longitude,capacity,equipment,
                    is_simulated,service_area,last_location_update,available_since)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())""",
              (code, reg, lat, lon, cap, d.get("equipment",""),
               int(bool(d.get("is_simulated",0))), d.get("service_area","")))
    except pymysql.err.IntegrityError:
        return fail("Ambulance code or registration already exists", 409)
    return ok({"ambulance_code": code}, code=201)

@app.patch("/api/ambulances/<int:aid>/location")
@login_required(STAFF)
def set_location(aid):
    try: lat, lon = coords(body())
    except ValueError as e: return fail(str(e), 422)
    with transaction() as cur:
        cur.execute("UPDATE ambulances SET latitude=%s,longitude=%s,last_location_update=NOW() WHERE id=%s", (lat, lon, aid))
        n = cur.rowcount
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
        cur.execute("UPDATE ambulances SET status=%s, available_since=IF(%s='Available',NOW(),available_since) WHERE id=%s",
                    (st, st, aid))
    return ok()

# ── Incidents ────────────────────────────────────────────────────────────────
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
    if d.get("incident_type") not in TYPES:  return fail(f"incident_type must be one of {TYPES}", 422)
    if d.get("priority","High") not in PRIORITIES: return fail(f"priority must be one of {PRIORITIES}", 422)
    n = d.get("estimated_patient_count", 1)
    if not isinstance(n, int) or n < 0: return fail("estimated_patient_count must be >= 0", 422)
    code = "INC-" + uuid.uuid4().hex[:8].upper()
    query("""INSERT INTO incidents
               (incident_code,title,description,incident_type,latitude,longitude,
                estimated_patient_count,priority,created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (code, d["title"].strip(), d.get("description",""), d["incident_type"],
           lat, lon, n, d.get("priority","High"), session["user_id"]))

    # Auto-dispatch if mode is enabled
    if _get_dispatch_mode() == "automatic":
        inc = query("SELECT * FROM incidents WHERE incident_code=%s", (code,), one=True)
        _auto_dispatch(inc, session["user_id"])

    return ok({"incident_code": code}, 201)

def get_incident(iid):
    return query("SELECT * FROM incidents WHERE id=%s", (iid,), one=True)

@app.get("/api/incidents/<int:iid>")
@login_required(STAFF)
def incident_detail(iid):
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    inc["patients"]   = query("SELECT case_reference,triage_category,transport_status,assigned_ambulance_id FROM patients WHERE incident_id=%s", (iid,))
    inc["dispatches"] = query("""SELECT d.id,a.ambulance_code,d.status,d.distance_km,
                                         d.estimated_travel_seconds,d.eta_source,d.dispatch_mode,
                                         d.decision_explanation,d.auto_fail_reason,d.assigned_at
                                  FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id
                                  WHERE d.incident_id=%s""", (iid,))
    return ok(inc)

@app.post("/api/incidents/<int:iid>/patients")
@login_required(["admin","dispatcher"])
def add_patients(iid):
    if not get_incident(iid): return fail("Incident not found", 404)
    d = body(); count = d.get("count", 1); triage = d.get("triage_category")
    if not isinstance(count, int) or not 1 <= count <= 100: return fail("count must be 1-100", 422)
    refs = []
    with transaction() as cur:
        for _ in range(count):
            ref = "CASE-" + uuid.uuid4().hex[:8].upper(); refs.append(ref)
            cur.execute("INSERT INTO patients (case_reference,incident_id,triage_category) VALUES (%s,%s,%s)",
                        (ref, iid, triage))
    return ok({"case_references": refs}, 201)

# ── Internal: build candidate list ──────────────────────────────────────────
def _candidates(iid, inc, required_equipment, min_cap, use_real_only=False):
    """Return (ranked_eligible, excluded, etas_error).
    When use_real_only=True, simulated vehicles are excluded for real dispatch.
    """
    ambs = query("SELECT * FROM ambulances")
    active_ids = {r["ambulance_id"] for r in query("SELECT ambulance_id FROM dispatches WHERE status='Active'")}
    eligible, excluded = filter_eligible(
        ambs, active_ids, required_equipment, min_cap,
        only_real=use_real_only
    )
    etas, err = traffic_etas(eligible, inc)
    ranked = rank(eligible, inc, etas)
    return ranked, excluded, err

# ── Recommend ambulances ─────────────────────────────────────────────────────
@app.post("/api/incidents/<int:iid>/recommend-ambulances")
@login_required(STAFF)
def recommend(iid):
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    d = body()
    ranked, excluded, err = _candidates(iid, inc,
                                        d.get("required_equipment", []),
                                        int(d.get("min_capacity", 1)))
    out = [{
        "id":          r["id"],
        "ambulance":   r["ambulance_code"],
        "driver_name": r.get("driver_name"),
        "distance_km": r["distance_km"],
        "eta_seconds": r["eta_seconds"],
        "eta_source":  r["eta_source"],
        "status":      r["status"],
        "capacity":    r.get("capacity"),
        "equipment":   r.get("equipment"),
        "is_simulated":bool(r.get("is_simulated")),
        "service_area":r.get("service_area"),
        "last_location_update": str(r.get("last_location_update") or ""),
        "rank":        r["rank"],
        "reason":      explain(r),
    } for r in ranked]
    excl_out = [{
        "id":           e["id"],
        "ambulance":    e["ambulance_code"],
        "status":       e["status"],
        "is_simulated": bool(e.get("is_simulated")),
        "reason":       explain_exclusion(e),
    } for e in excluded]
    return ok({"eligible": out, "excluded": excl_out},
              maps_warning=err,
              note="ETA is traffic-aware (Google Routes) when available; else straight-line (Haversine).")

# ── Auto-dispatch (internal helper) ──────────────────────────────────────────
def _auto_dispatch(inc, dispatcher_id):
    """Attempt automatic dispatch for an incident. Returns (success, info_dict)."""
    iid = inc["id"]
    ranked, excluded, err = _candidates(iid, inc, [], inc.get("estimated_patient_count",1),
                                        use_real_only=False)
    if not ranked:
        reason = (f"No eligible ambulance found. "
                  f"Routing: {err or 'OK'}. "
                  f"Excluded {len(excluded)} candidates: "
                  + "; ".join(explain_exclusion(e) for e in excluded[:3]))
        # Record failure in dispatch_history for dispatcher visibility
        query("""INSERT INTO dispatch_history
                   (dispatch_id,action,previous_status,new_status,reason,dispatch_mode,
                    auto_fail_reason,dispatcher_id)
                 VALUES (0,'auto_dispatch_failed','Open','Open',%s,'Automatic',%s,%s)""",
              (reason[:255], reason, dispatcher_id))
        return False, {"reason": reason, "excluded": excluded}

    best = ranked[0]
    explanation = explain(best)
    try:
        with transaction() as cur:
            # Revalidate inside transaction
            cur.execute("SELECT status FROM incidents WHERE id=%s FOR UPDATE", (iid,))
            inc_row = cur.fetchone()
            if not inc_row or inc_row["status"] not in ("Open", "In progress"):
                raise ValueError("Incident is closed or cancelled")
            cur.execute("SELECT status FROM ambulances WHERE id=%s FOR UPDATE", (best["id"],))
            amb_row = cur.fetchone()
            if not amb_row or amb_row["status"] != "Available":
                raise ValueError(f"Ambulance {best['ambulance_code']} became unavailable")
            cur.execute("SELECT id FROM dispatches WHERE ambulance_id=%s AND status='Active'", (best["id"],))
            if cur.fetchone():
                raise ValueError(f"Ambulance {best['ambulance_code']} has a concurrent active dispatch")
            cur.execute("""INSERT INTO dispatches
                             (incident_id,ambulance_id,assigned_by,distance_km,estimated_travel_seconds,
                              eta_source,dispatch_mode,decision_explanation)
                           VALUES (%s,%s,%s,%s,%s,%s,'Automatic',%s)""",
                        (iid, best["id"], dispatcher_id, best["distance_km"],
                         best["eta_seconds"], best["eta_source"], explanation))
            did = cur.lastrowid
            cur.execute("SELECT COALESCE(MAX(queue_position),0)+1 p FROM ambulances FOR UPDATE")
            pos = cur.fetchone()["p"]
            cur.execute("UPDATE ambulances SET status='Dispatched',queue_position=%s WHERE id=%s",
                        (pos, best["id"]))
            cur.execute("""INSERT INTO dispatch_history
                             (dispatch_id,action,previous_status,new_status,reason,dispatch_mode,dispatcher_id)
                           VALUES (%s,'auto_dispatched','Available','Dispatched',%s,'Automatic',%s)""",
                        (did, explanation[:255], dispatcher_id))
            cur.execute("UPDATE incidents SET status='In progress' WHERE id=%s AND status='Open'", (iid,))
        return True, {"ambulance_code": best["ambulance_code"], "dispatch_id": did,
                      "explanation": explanation}
    except (ValueError, pymysql.err.IntegrityError) as e:
        fail_reason = str(e)
        query("""INSERT INTO dispatch_history
                   (dispatch_id,action,previous_status,new_status,reason,dispatch_mode,
                    auto_fail_reason,dispatcher_id)
                 VALUES (0,'auto_dispatch_failed','Open','Open',%s,'Automatic',%s,%s)""",
              (fail_reason[:255], fail_reason, dispatcher_id))
        return False, {"reason": fail_reason}

# ── Auto-dispatch API (admin triggers on demand) ─────────────────────────────
@app.post("/api/incidents/<int:iid>/auto-dispatch")
@login_required(["admin", "dispatcher"])
def auto_dispatch_now(iid):
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    if inc["status"] not in ("Open", "In progress"):
        return fail("Incident is not open or in progress", 409)
    success, info = _auto_dispatch(inc, session["user_id"])
    if success:
        return ok(info, 201)
    return fail(info.get("reason", "Auto-dispatch failed — see dispatcher fallback panel"), 409)

# ── Dispatcher fallback: incidents that need human review ────────────────────
@app.get("/api/incidents/needs-dispatch")
@login_required(STAFF)
def incidents_needing_dispatch():
    """Incidents that are Open/In-progress with no active dispatch (auto-fail fallback panel)."""
    rows = query("""
        SELECT i.*,
          (SELECT reason FROM dispatch_history
           WHERE action='auto_dispatch_failed' AND
                 (dispatch_id=0 OR dispatch_id IN (SELECT id FROM dispatches WHERE incident_id=i.id))
           ORDER BY created_at DESC LIMIT 1) AS last_fail_reason,
          (SELECT COUNT(*) FROM dispatches WHERE incident_id=i.id AND status='Active') AS active_dispatch_count
        FROM incidents i
        WHERE i.status IN ('Open','In progress')
        ORDER BY i.reported_at DESC
    """)
    return ok(rows)

# ── Manual dispatch (confirm) ─────────────────────────────────────────────────
@app.post("/api/incidents/<int:iid>/dispatch")
@login_required(["admin", "dispatcher"])
def dispatch(iid):
    """Dispatcher-confirmed manual dispatch. Body: {ambulance_ids:[...], override_reason?, dispatch_mode?}."""
    inc = get_incident(iid)
    if not inc: return fail("Incident not found", 404)
    d = body()
    ids = d.get("ambulance_ids")
    if not isinstance(ids, list) or not ids: return fail("ambulance_ids must be a non-empty list", 422)
    override_reason = (d.get("override_reason") or "").strip()
    mode_label = d.get("dispatch_mode_label", "Manual")
    if mode_label not in ("Manual", "Manual Fallback"): mode_label = "Manual"

    ranked, _, _ = _candidates(iid, inc, [], 1)
    info = {r["id"]: r for r in ranked}

    try:
        dispatched_ids = []
        with transaction() as cur:
            cur.execute("SELECT status FROM incidents WHERE id=%s FOR UPDATE", (iid,))
            inc_row = cur.fetchone()
            if not inc_row or inc_row["status"] not in ("Open", "In progress"):
                raise ValueError("Incident is closed or cancelled")

            for aid in sorted(set(ids)):
                cur.execute("SELECT status,ambulance_code FROM ambulances WHERE id=%s FOR UPDATE", (aid,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Ambulance id={aid} not found")
                if row["status"] != "Available":
                    raise ValueError(f"Ambulance {row['ambulance_code']} is not available (status: {row['status']})")
                if aid not in info:
                    raise ValueError(f"Ambulance {row['ambulance_code']} did not pass eligibility checks")
                cur.execute("SELECT id FROM dispatches WHERE ambulance_id=%s AND status='Active'", (aid,))
                if cur.fetchone():
                    raise ValueError(f"Ambulance {row['ambulance_code']} has a concurrent active dispatch")

                r = info[aid]
                explanation = explain(r) + (f" [Override by dispatcher: {override_reason}]" if override_reason else "")
                cur.execute("""INSERT INTO dispatches
                                 (incident_id,ambulance_id,assigned_by,distance_km,estimated_travel_seconds,
                                  eta_source,dispatch_mode,decision_explanation)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (iid, aid, session["user_id"], r["distance_km"], r["eta_seconds"],
                             r["eta_source"], mode_label, explanation))
                did = cur.lastrowid
                cur.execute("SELECT COALESCE(MAX(queue_position),0)+1 p FROM ambulances FOR UPDATE")
                pos = cur.fetchone()["p"]
                cur.execute("UPDATE ambulances SET status='Dispatched',queue_position=%s WHERE id=%s", (pos, aid))
                cur.execute("""INSERT INTO dispatch_history
                                 (dispatch_id,action,previous_status,new_status,reason,dispatch_mode,
                                  dispatcher_id,override_reason)
                               VALUES (%s,'dispatched','Available','Dispatched',%s,%s,%s,%s)""",
                            (did, explanation[:255], mode_label, session["user_id"],
                             override_reason[:255] if override_reason else None))
                dispatched_ids.append(aid)

            cur.execute("UPDATE incidents SET status='In progress' WHERE id=%s AND status='Open'", (iid,))
    except ValueError as e:
        return fail(str(e), 409)
    except pymysql.err.IntegrityError:
        return fail("Duplicate active assignment prevented", 409)
    return ok({"dispatched": sorted(set(dispatched_ids)), "mode": mode_label}, 201)

# ── Dispatches list ──────────────────────────────────────────────────────────
@app.get("/api/dispatches")
@login_required(STAFF)
def dispatches():
    return ok(query("""
        SELECT d.*, a.ambulance_code, i.incident_code, a.is_simulated,
               u.name AS dispatcher_name
        FROM dispatches d
        JOIN ambulances a ON a.id=d.ambulance_id
        JOIN incidents  i ON i.id=d.incident_id
        LEFT JOIN users u ON u.id=d.assigned_by
        ORDER BY d.id DESC LIMIT 100
    """))

# ── Gemini AI (text only) ────────────────────────────────────────────────────
def _facts(iid):
    inc = get_incident(iid)
    if not inc: return None
    cnt = query("SELECT COUNT(*) n FROM patients WHERE incident_id=%s", (iid,), one=True)["n"]
    ds  = query("""SELECT a.ambulance_code,d.status,d.distance_km,d.estimated_travel_seconds,
                          d.eta_source,d.dispatch_mode,h.reason
                   FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id
                   LEFT JOIN dispatch_history h ON h.dispatch_id=d.id
                   WHERE d.incident_id=%s""", (iid,))
    return (f"Incident {inc['incident_code']}: {inc['title']} ({inc['incident_type']}), "
            f"priority {inc['priority']}, status {inc['status']}, "
            f"estimated patients {inc['estimated_patient_count']}, recorded patient cases {cnt}.\n"
            f"Dispatches: {ds}")

def _ai(task):
    d = body(); iid = d.get("incident_id")
    facts = _facts(iid) if isinstance(iid, int) else None
    if not facts: return fail("Valid incident_id required", 422)
    extra = d.get("question")
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

# ── Gemini API key configuration endpoints ──────────────────────────────────
def _load_gemini_config():
    try:
        r_key = query("SELECT value FROM app_settings WHERE setting_key='gemini_api_key'", one=True)
        if r_key and r_key["value"]:
            config.GEMINI_API_KEY = r_key["value"]
        r_model = query("SELECT value FROM app_settings WHERE setting_key='gemini_model'", one=True)
        if r_model and r_model["value"]:
            config.GEMINI_MODEL = r_model["value"]
    except Exception:
        pass

@app.get("/api/settings/gemini")
@login_required(STAFF)
def get_gemini_status():
    _load_gemini_config()
    key = config.GEMINI_API_KEY or ""
    is_placeholder = key.startswith("AIzaSyDemoKey") or not key
    configured = bool(key and config.GEMINI_MODEL and not is_placeholder)
    masked = (key[:8] + "..." + key[-4:]) if (len(key) > 12 and not is_placeholder) else ("Demo/Unconfigured" if is_placeholder else "")
    return ok({
        "configured": configured,
        "model": config.GEMINI_MODEL or "gemini-1.5-flash-latest",
        "masked_key": masked
    })

@app.post("/api/settings/gemini")
@login_required(["admin"])
def update_gemini_settings():
    d = body()
    api_key = (d.get("api_key") or "").strip()
    model = (d.get("model") or "").strip() or "gemini-1.5-flash-latest"
    uid = session.get("user_id")
    if api_key:
        config.GEMINI_API_KEY = api_key
        try:
            with transaction() as cur:
                cur.execute("""
                    INSERT INTO app_settings (setting_key, value, changed_by)
                    VALUES ('gemini_api_key', %s, %s)
                    ON DUPLICATE KEY UPDATE value=%s, changed_by=%s, changed_at=NOW()
                """, (api_key, uid, api_key, uid))
        except Exception as e:
            app.logger.warning(f"Failed to persist gemini_api_key: {e}")
    if model:
        config.GEMINI_MODEL = model
        try:
            with transaction() as cur:
                cur.execute("""
                    INSERT INTO app_settings (setting_key, value, changed_by)
                    VALUES ('gemini_model', %s, %s)
                    ON DUPLICATE KEY UPDATE value=%s, changed_by=%s, changed_at=NOW()
                """, (model, uid, model, uid))
        except Exception as e:
            app.logger.warning(f"Failed to persist gemini_model: {e}")
    _load_gemini_config()
    configured = bool(config.GEMINI_API_KEY and not config.GEMINI_API_KEY.startswith("AIzaSyDemoKey"))
    return ok({"configured": configured, "model": config.GEMINI_MODEL})

# ── Register portal routes ───────────────────────────────────────────────────
from routes.portal_routes import register as _register_portals
_register_portals(app, __import__("sys").modules[__name__])

if __name__ == "__main__":
    import os
    app.run(debug=os.getenv("FLASK_ENV") == "development")
