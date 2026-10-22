from datetime import datetime, timedelta
from services.ambulance_allocator import filter_eligible, rank
NOW = datetime(2026, 1, 1, 12)
INC = {"latitude": 10.0, "longitude": 76.0}
def amb(i, code, lat=10.0, lon=76.0, status="Available", cap=1, eq="ALS", since=NOW, q=0):
    return dict(id=i, ambulance_code=code, latitude=lat, longitude=lon, status=status,
                capacity=cap, equipment=eq, available_since=since, queue_position=q)

def test_filters_status_active_equipment_capacity():
    ambs = [amb(1, "A1"), amb(2, "A2", status="Out of service"), amb(3, "A3"),
            amb(4, "A4", eq="BLS"), amb(5, "A5", cap=1)]
    got = filter_eligible(ambs, active_ambulance_ids={3}, required_equipment=["ALS"], min_capacity=1)
    assert [a["id"] for a in got] == [1, 5]
    assert [a["id"] for a in filter_eligible(ambs, set(), ["ALS"], 2)] == []

def test_ranks_by_distance_fallback_and_label():
    r = rank([amb(1, "A1", lat=10.2), amb(2, "A2", lat=10.1)], INC)
    assert [x["id"] for x in r] == [2, 1]
    assert r[0]["eta_source"] == "haversine_distance_fallback"

def test_eta_used_only_when_all_have_it():
    ambs = [amb(1, "A1", lat=10.2), amb(2, "A2", lat=10.1)]
    assert rank(ambs, INC, {1: 100})[0]["id"] == 2                 # partial ETA -> ignored
    full = rank(ambs, INC, {1: 100, 2: 300})
    assert full[0]["id"] == 1 and full[0]["eta_source"] == "google_routes_traffic"

def test_tie_break_available_longer_then_queue_then_code():
    ambs = [amb(1, "A1", since=NOW), amb(2, "A2", since=NOW - timedelta(hours=1))]
    assert rank(ambs, INC)[0]["id"] == 2
    ambs = [amb(1, "A1", q=5), amb(2, "A2", q=2)]
    assert rank(ambs, INC)[0]["id"] == 2
    ambs = [amb(1, "B1"), amb(2, "A1")]
    assert rank(ambs, INC)[0]["ambulance_code"] == "A1"

def test_multiple_ambulances_for_multi_patient_incident():
    r = rank([amb(i, f"A{i}", lat=10 + i / 100) for i in range(1, 6)], INC)
    assert len(r) == 5 and [x["rank"] for x in r] == [1, 2, 3, 4, 5]
