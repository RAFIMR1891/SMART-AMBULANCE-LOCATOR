"""Rule-based ambulance allocation engine (no ML).
Pure functions — easy to unit test and audit.

Eligibility rules (MANDATORY — never overridden):
  1. status == 'Available'
  2. Not in active_ambulance_ids set
  3. capacity >= min_capacity
  4. Has all required equipment
  5. GPS coordinates present and recent (< max_location_age_minutes)
  6. Driver linked (if require_driver=True)

Ranking (in order):
  1. Traffic-aware ETA from Google Routes (if available for ALL candidates)
  2. Haversine straight-line distance as fallback (clearly labelled)
  3. Tie-break: available longest → lowest queue_position → ambulance code
"""
from datetime import datetime, timedelta, timezone
from services.haversine import haversine_km

# GPS reading older than this is considered stale
DEFAULT_LOCATION_AGE_MINUTES = 60


def filter_eligible(
    ambulances,
    active_ambulance_ids,
    required_equipment=None,
    min_capacity=1,
    require_driver=False,
    max_location_age_minutes=DEFAULT_LOCATION_AGE_MINUTES,
    only_real=False,     # if True: exclude simulated (is_simulated=1) ambulances
    only_simulated=False # if True: include only simulated ambulances
):
    """Return list of eligible ambulances with a rejection_reason for excluded ones."""
    need = {e.strip().lower() for e in (required_equipment or []) if e.strip()}
    eligible, excluded = [], []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_cutoff = now - timedelta(minutes=max_location_age_minutes)

    for a in ambulances:
        reason = None

        # Simulated/real filter
        sim = bool(a.get("is_simulated", 0))
        if only_real and sim:
            reason = "Simulated vehicle excluded for real-fleet dispatch"
        elif only_simulated and not sim:
            reason = "Real vehicle excluded (simulation mode)"

        elif a["status"] != "Available":
            reason = f"Status is '{a['status']}' (not Available)"
        elif a["id"] in active_ambulance_ids:
            reason = "Has an active dispatch assignment"
        elif a["capacity"] < min_capacity:
            reason = f"Capacity {a['capacity']} < required {min_capacity}"
        else:
            # Equipment check
            have = {e.strip().lower() for e in (a.get("equipment") or "").split(",") if e.strip()}
            missing = need - have
            if missing:
                reason = f"Missing equipment: {', '.join(sorted(missing))}"
            # GPS freshness
            elif a.get("latitude") is None or a.get("longitude") is None:
                reason = "No GPS coordinates recorded"
            else:
                lu = a.get("last_location_update")
                if lu and isinstance(lu, datetime) and lu < stale_cutoff:
                    age_min = int((now - lu).total_seconds() / 60)
                    reason = f"GPS is stale ({age_min} min old, max {max_location_age_minutes} min)"
                # Driver check
                elif require_driver and not a.get("driver_user_id"):
                    reason = "No driver linked to this ambulance"

        if reason:
            excluded.append({**a, "eligible": False, "rejection_reason": reason})
        else:
            eligible.append({**a, "eligible": True, "rejection_reason": None})

    return eligible, excluded


def rank(eligible, incident, etas=None):
    """Rank eligible ambulances by ETA (if available for all) else Haversine.

    Returns list with extra keys: distance_km, eta_seconds, eta_source, rank.
    Ties: available longest → lower queue_position → ambulance code.
    """
    etas = etas or {}
    use_eta = bool(eligible) and all(a["id"] in etas for a in eligible)
    rows = []
    for a in eligible:
        d = haversine_km(
            float(a["latitude"]), float(a["longitude"]),
            float(incident["latitude"]), float(incident["longitude"])
        )
        rows.append({
            **a,
            "distance_km": round(d, 3),
            "eta_seconds": etas.get(a["id"]),
            "eta_source": "google_routes_traffic" if use_eta else "haversine_distance_fallback",
        })

    far = datetime.max

    def sort_key(r):
        primary = r["eta_seconds"] if use_eta else r["distance_km"]
        # Normalize available_since — use far sentinel when None
        avail = r.get("available_since") or far
        if not isinstance(avail, datetime):
            avail = far
        return (primary, avail, r.get("queue_position", 0), r["ambulance_code"])

    rows.sort(key=sort_key)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def explain(row):
    """Human-readable dispatch decision for a ranked ambulance."""
    basis = (
        "traffic-aware ETA from Google Routes"
        if row.get("eta_source") == "google_routes_traffic"
        else "straight-line distance (Haversine) — no reliable road ETA available"
    )
    eta_text = (
        f"{round(row['eta_seconds'] / 60, 1)} min (ETA)"
        if row.get("eta_seconds") is not None
        else "ETA unavailable"
    )
    sim_note = " [SIMULATED VEHICLE]" if row.get("is_simulated") else ""
    return (
        f"{row['ambulance_code']}{sim_note} ranked #{row['rank']} on {basis}: "
        f"{row['distance_km']} km away, {eta_text}, "
        f"capacity {row.get('capacity',1)}, "
        f"equipment: {row.get('equipment') or 'none listed'}."
    )


def explain_exclusion(row):
    """Human-readable reason why an ambulance was excluded."""
    sim_note = " [SIMULATED]" if row.get("is_simulated") else ""
    return (
        f"{row['ambulance_code']}{sim_note} excluded: {row['rejection_reason']}."
    )
