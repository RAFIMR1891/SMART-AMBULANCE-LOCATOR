"""Rule-based allocation (no ML). Pure functions so they are easy to test."""
from datetime import datetime
from services.haversine import haversine_km

def filter_eligible(ambulances, active_ambulance_ids, required_equipment=None, min_capacity=1):
    need = {e.strip().lower() for e in (required_equipment or []) if e.strip()}
    out = []
    for a in ambulances:
        if a["status"] != "Available" or a["id"] in active_ambulance_ids:
            continue
        if a["capacity"] < min_capacity:
            continue
        have = {e.strip().lower() for e in (a.get("equipment") or "").split(",")}
        if not need <= have:
            continue
        out.append(a)
    return out

def rank(eligible, incident, etas=None):
    """Use ETA only if EVERY candidate has one, else Haversine fallback (labelled).
    Ties: available longest -> lower queue_position -> ambulance code."""
    etas = etas or {}
    use_eta = bool(eligible) and all(a["id"] in etas for a in eligible)
    rows = []
    for a in eligible:
        d = haversine_km(a["latitude"], a["longitude"], incident["latitude"], incident["longitude"])
        rows.append({**a, "distance_km": d, "eta_seconds": etas.get(a["id"]),
                     "eta_source": "google_routes_traffic" if use_eta else "haversine_distance_fallback"})
    far = datetime.max
    def key(r):
        primary = r["eta_seconds"] if use_eta else r["distance_km"]
        return (primary, r.get("available_since") or far, r.get("queue_position", 0), r["ambulance_code"])
    rows.sort(key=key)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows

def explain(row):
    basis = ("traffic-aware ETA from Google Routes" if row["eta_source"] == "google_routes_traffic"
             else "straight-line distance (Haversine) because no reliable ETA was available")
    return (f"{row['ambulance_code']} ranked #{row['rank']} on {basis}: {row['distance_km']} km away, "
            f"status Available, equipment: {row.get('equipment') or 'none listed'}.")
