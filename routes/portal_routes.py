"""User, Driver and staff-admin endpoints. Every route is guarded on the backend by role."""
import re, uuid
from flask import session
import pymysql
from werkzeug.security import generate_password_hash
from database import query, transaction
from services.google_maps_service import traffic_etas

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ALIASES = {"Arrived at scene": "At scene"}
# new ambulance status -> statuses it may move from
FLOW = {"Assigned": {"Dispatched"}, "En route": {"Dispatched", "Assigned"},
        "At scene": {"En route"}, "Transporting patient": {"At scene"}, "Completed": {"Transporting patient"}}

def register(app, m):
    ok, fail, guard, body, coords = m.ok, m.fail, m.login_required, m.body, m.coords
    STAFF = m.STAFF

    def make_user(d, allowed_roles, role):
        name, email, pw = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), d.get("password") or ""
        if not name or not EMAIL.match(email): return None, fail("A name and valid email are required", 422)
        if len(pw) < 8: return None, fail("Password must be at least 8 characters", 422)
        if role not in allowed_roles: return None, fail(f"role must be one of {sorted(allowed_roles)}", 422)
        try:
            with transaction() as cur:
                cur.execute("INSERT INTO users (name,email,password_hash,role,phone) VALUES (%s,%s,%s,%s,%s)",
                            (name, email, generate_password_hash(pw), role, (d.get("phone") or "")[:20] or None))
                return cur.lastrowid, None
        except pymysql.err.IntegrityError:
            return None, fail("Email already registered", 409)

    # ---------- public self-registration: ONLY the 'user' role ----------
    @app.post("/api/auth/register")
    def register_user():
        uid, err = make_user(body(), {"user"}, "user")
        return err or ok({"id": uid}, 201)

    # ---------- admin: staff/driver accounts ----------
    @app.post("/api/admin/users")
    @guard(["admin"])
    def admin_create_user():
        d = body(); uid, err = make_user(d, {"user", "driver", "dispatcher", "admin"}, d.get("role"))
        if err: return err
        if d.get("role") == "driver" and d.get("ambulance_id"):
            try: query("UPDATE ambulances SET driver_user_id=%s WHERE id=%s", (uid, int(d["ambulance_id"])))
            except (pymysql.err.IntegrityError, ValueError): return fail("User created, but ambulance link failed", 409)
        return ok({"id": uid}, 201)

    @app.patch("/api/ambulances/<int:aid>/driver")
    @guard(["admin"])
    def link_driver(aid):
        uid = body().get("driver_user_id")
        if uid is not None and not query("SELECT id FROM users WHERE id=%s AND role='driver'", (uid,), one=True):
            return fail("driver_user_id must be an existing driver", 422)
        try: query("UPDATE ambulances SET driver_user_id=%s WHERE id=%s", (uid, aid))
        except pymysql.err.IntegrityError: return fail("That driver is already linked to another ambulance", 409)
        return ok()

    @app.get("/api/admin/users")
    @guard(STAFF)
    def list_users():
        return ok(query("""SELECT u.id, u.name, u.email, u.role, u.is_active, u.created_at,
                                  a.ambulance_code, a.registration_number, a.service_area
                           FROM users u LEFT JOIN ambulances a ON a.driver_user_id=u.id ORDER BY u.id DESC"""))

    @app.get("/api/hospitals")
    @guard(STAFF)
    def hospitals(): return ok(query("SELECT * FROM hospitals ORDER BY name"))

    @app.get("/api/dispatch-history")
    @guard(STAFF)
    def history():
        return ok(query("""SELECT h.*, a.ambulance_code, i.incident_code FROM dispatch_history h JOIN dispatches d ON d.id=h.dispatch_id
                           JOIN ambulances a ON a.id=d.ambulance_id JOIN incidents i ON i.id=d.incident_id ORDER BY h.id DESC LIMIT 100"""))

    @app.post("/api/dispatches/<int:did>/cancel")
    @guard(STAFF)
    def cancel_dispatch(did):
        """Cancel frees the ambulance. To reassign: cancel, then recommend + dispatch again."""
        reason = (body().get("reason") or "").strip()
        if not reason: return fail("A reason is required", 422)
        with transaction() as cur:
            cur.execute("SELECT * FROM dispatches WHERE id=%s FOR UPDATE", (did,)); d = cur.fetchone()
            if not d: return fail("Dispatch not found", 404)
            if d["status"] != "Active": return fail("Dispatch is not active", 409)
            cur.execute("SELECT status FROM ambulances WHERE id=%s FOR UPDATE", (d["ambulance_id"],))
            prev = cur.fetchone()["status"]
            if prev == "Transporting patient" and session.get("role") != "admin":
                return fail("Only an administrator can cancel while a patient is on board", 403)
            cur.execute("UPDATE dispatches SET status='Cancelled', completed_at=NOW() WHERE id=%s", (did,))
            cur.execute("UPDATE ambulances SET status='Available', available_since=NOW() WHERE id=%s", (d["ambulance_id"],))
            cur.execute("INSERT INTO dispatch_history (dispatch_id,action,previous_status,new_status,reason) VALUES (%s,'cancelled',%s,'Available',%s)",
                        (did, prev, reason[:255]))
            cur.execute("SELECT COUNT(*) n FROM dispatches WHERE incident_id=%s AND status='Active'", (d["incident_id"],))
            if cur.fetchone()["n"] == 0:
                cur.execute("UPDATE incidents SET status='Open' WHERE id=%s AND status='In progress'", (d["incident_id"],))
        return ok()

    @app.get("/api/me")
    @guard()
    def me():
        return ok(query("SELECT name,email,phone,role,created_at FROM users WHERE id=%s", (session["user_id"],), one=True))

    # ---------- USER portal (own data only: every query filters by session user) ----------
    def own(rid): return query("SELECT * FROM incidents WHERE id=%s AND requester_user_id=%s", (rid, session["user_id"]), one=True)

    @app.post("/api/user/requests")
    @guard(["user"])
    def u_create():
        d = body()
        try: lat, lon = coords(d)
        except ValueError as e: return fail(str(e), 422)
        n, desc = d.get("estimated_patient_count", 1), (d.get("description") or "").strip()
        if not isinstance(n, int) or not 1 <= n <= 100: return fail("Number of injured people must be 1-100", 422)
        if not desc: return fail("Please describe the emergency", 422)
        if query("SELECT COUNT(*) n FROM incidents WHERE requester_user_id=%s AND status IN ('Open','In progress')", (session["user_id"],), one=True)["n"] >= 3:
            return fail("You already have 3 active requests", 429)
        typ = d.get("incident_type") if d.get("incident_type") in m.TYPES else "Other emergency"
        code = "INC-" + uuid.uuid4().hex[:8].upper()
        query("""INSERT INTO incidents (incident_code,title,description,incident_type,latitude,longitude,estimated_patient_count,priority,created_by,requester_user_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,'High',%s,%s)""", (code, f"User request: {typ}", desc[:2000], typ, lat, lon, n, session["user_id"], session["user_id"]))
        return ok({"incident_code": code}, 201)

    @app.get("/api/user/requests")
    @guard(["user"])
    def u_list():
        return ok(query("""SELECT i.id,i.incident_code,i.incident_type,i.status,i.estimated_patient_count,i.reported_at,i.latitude,i.longitude,
                      (SELECT a.ambulance_code FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id WHERE d.incident_id=i.id ORDER BY d.id DESC LIMIT 1) AS ambulance_code
                      FROM incidents i WHERE i.requester_user_id=%s ORDER BY i.id DESC""", (session["user_id"],)))

    @app.get("/api/user/requests/<int:rid>")
    @guard(["user"])
    def u_detail(rid):
        r = own(rid)
        if not r: return fail("Request not found", 404)  # same answer for other people's ids
        ds = query("""SELECT a.id aid,a.ambulance_code,a.registration_number,a.latitude,a.longitude,a.last_location_update,
                      a.status ambulance_status, d.status dispatch_status, dr.name driver_name FROM dispatches d JOIN ambulances a ON a.id=d.ambulance_id LEFT JOIN users dr ON dr.id=a.driver_user_id
                      WHERE d.incident_id=%s AND d.status='Active'""", (rid,))
        etas, err = traffic_etas([{"id": x["aid"], "latitude": x["latitude"], "longitude": x["longitude"]} for x in ds], r)
        for x in ds:
            x["eta_seconds"] = etas.get(x.pop("aid"))  # null when unavailable; never invented
        keep = {k: r[k] for k in ("incident_code", "incident_type", "description", "status", "reported_at", "latitude", "longitude", "estimated_patient_count")}
        return ok({**keep, "ambulances": ds}, eta_note=err or "ETA is traffic-aware (Google Routes). Location is last reported, not live tracking.")

    @app.post("/api/user/requests/<int:rid>/cancel")
    @guard(["user"])
    def u_cancel(rid):
        with transaction() as cur:
            cur.execute("SELECT status FROM incidents WHERE id=%s AND requester_user_id=%s FOR UPDATE", (rid, session["user_id"]))
            r = cur.fetchone()
            if not r: return fail("Request not found", 404)
            cur.execute("SELECT COUNT(*) n FROM dispatches WHERE incident_id=%s AND status='Active'", (rid,))
            if r["status"] != "Open" or cur.fetchone()["n"]:
                return fail("An ambulance is already assigned. Please contact the dispatcher to cancel.", 409)
            cur.execute("UPDATE incidents SET status='Cancelled' WHERE id=%s", (rid,))
        return ok()

    # ---------- DRIVER portal (own ambulance / own assignments only) ----------
    def my_amb(): return query("SELECT * FROM ambulances WHERE driver_user_id=%s", (session["user_id"],), one=True)

    @app.get("/api/driver/me")
    @guard(["driver"])
    def d_me():
        a = my_amb()
        if not a: return ok({"ambulance": None, "assignments": [], "history": []}, note="No ambulance is linked to your account. Ask an administrator.")
        cols = """d.id dispatch_id,d.status,d.distance_km,d.estimated_travel_seconds,d.eta_source,d.assigned_at,d.completed_at,
                  i.incident_code,i.title,i.incident_type,i.description,i.latitude,i.longitude,i.priority,i.estimated_patient_count"""
        base = f"SELECT {cols} FROM dispatches d JOIN incidents i ON i.id=d.incident_id WHERE d.ambulance_id=%s"
        cnt = {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) n FROM dispatches WHERE ambulance_id=%s GROUP BY status", (a["id"],))}
        u = query("SELECT id, name, email, phone, role FROM users WHERE id=%s", (session["user_id"],), one=True)
        amb_fields = ("id", "ambulance_code", "registration_number", "status", "latitude", "longitude",
                      "last_location_update", "service_area", "capacity", "equipment", "is_simulated")
        return ok({
            "user": u,
            "counts": cnt,
            "ambulance": {k: a.get(k) for k in amb_fields},
            "assignments": query(base + " AND d.status='Active'", (a["id"],)),
            "history": query(base + " AND d.status<>'Active' ORDER BY d.id DESC LIMIT 20", (a["id"],))
        })

    @app.patch("/api/driver/status")
    @guard(["driver"])
    def d_status():
        st = body().get("status"); st = ALIASES.get(st, st)
        if st not in FLOW: return fail(f"status must be one of {sorted(FLOW)}", 422)
        with transaction() as cur:
            cur.execute("SELECT id,status FROM ambulances WHERE driver_user_id=%s FOR UPDATE", (session["user_id"],)); a = cur.fetchone()
            if not a: return fail("No ambulance linked to your account", 404)
            cur.execute("SELECT id FROM dispatches WHERE ambulance_id=%s AND status='Active' FOR UPDATE", (a["id"],)); ds = cur.fetchone()
            if not ds: return fail("You have no active assignment", 409)
            if a["status"] not in FLOW[st]: return fail(f"Cannot change from '{a['status']}' to '{st}'", 409)
            new = "Available" if st == "Completed" else st
            if st == "Completed":
                cur.execute("UPDATE dispatches SET status='Completed', completed_at=NOW() WHERE id=%s", (ds["id"],))
            cur.execute("UPDATE ambulances SET status=%s, available_since=IF(%s='Available',NOW(),available_since) WHERE id=%s", (new, new, a["id"]))
            cur.execute("INSERT INTO dispatch_history (dispatch_id,action,previous_status,new_status,reason) VALUES (%s,'driver_status',%s,%s,%s)",
                        (ds["id"], a["status"], new, f"Driver reported: {st}"))
        return ok({"status": new})

    @app.post("/api/driver/location")
    @guard(["driver"])
    def d_location():
        try: lat, lon = coords(body())
        except ValueError as e: return fail(str(e), 422)
        a = my_amb()
        if not a: return fail("No ambulance linked to your account", 404)
        with transaction() as cur:
            cur.execute("UPDATE ambulances SET latitude=%s,longitude=%s,last_location_update=NOW() WHERE id=%s", (lat, lon, a["id"]))
            cur.execute("INSERT INTO ambulance_locations (ambulance_id,latitude,longitude) VALUES (%s,%s,%s)", (a["id"], lat, lon))
        return ok()
