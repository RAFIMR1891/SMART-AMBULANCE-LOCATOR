import pytest
from services.haversine import haversine_km

def test_known_distance():  # Kochi -> Thiruvananthapuram is roughly 173 km straight-line
    assert 170 < haversine_km(9.9312, 76.2673, 8.5241, 76.9366) < 176
def test_identical_is_zero():
    assert haversine_km(10, 76, 10, 76) == 0.0
def test_symmetric():
    assert haversine_km(10, 76, 11, 77) == haversine_km(11, 77, 10, 76)
@pytest.mark.parametrize("a", [(91, 0), (0, 181), ("x", 1), (None, 1)])
def test_invalid(a):
    with pytest.raises(ValueError):
        haversine_km(a[0], a[1], 0, 0)
