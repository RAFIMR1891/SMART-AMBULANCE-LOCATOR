import requests, config
URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

def traffic_etas(ambulances, incident):
    """Return ({ambulance_id: seconds}, error_or_None). Never invents values."""
    if not config.MAPS_SERVER_KEY:
        return {}, "GOOGLE_MAPS_API_KEY not configured"
    if not ambulances:
        return {}, None
    def wp(lat, lng):
        return {"waypoint": {"location": {"latLng": {"latitude": float(lat), "longitude": float(lng)}}}}
    body = {"origins": [wp(a["latitude"], a["longitude"]) for a in ambulances],
            "destinations": [wp(incident["latitude"], incident["longitude"])],
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE"}
    try:
        r = requests.post(URL, json=body, timeout=10, headers={
            "X-Goog-Api-Key": config.MAPS_SERVER_KEY,
            "X-Goog-FieldMask": "originIndex,duration,condition"})
        r.raise_for_status()
        etas = {}
        for el in r.json():
            if el.get("condition") == "ROUTE_EXISTS" and "duration" in el:
                etas[ambulances[el["originIndex"]]["id"]] = int(float(el["duration"].rstrip("s")))
        return etas, None
    except (requests.RequestException, ValueError, KeyError) as e:
        return {}, f"Routes API unavailable: {type(e).__name__}"
