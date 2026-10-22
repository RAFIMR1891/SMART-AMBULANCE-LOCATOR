"""Straight-line (great-circle) distance. NOT road distance or driving time."""
from math import radians, sin, cos, sqrt, atan2
EARTH_RADIUS_KM = 6371.0

def validate_coordinates(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ValueError("Coordinates must be numbers")
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError("Latitude must be -90..90 and longitude -180..180")
    return lat, lon

def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1 = validate_coordinates(lat1, lon1)
    lat2, lon2 = validate_coordinates(lat2, lon2)
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi, dlam = p2 - p1, radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlam / 2) ** 2
    a = min(1.0, max(0.0, a))
    return round(EARTH_RADIUS_KM * 2 * atan2(sqrt(a), sqrt(1 - a)), 3)
