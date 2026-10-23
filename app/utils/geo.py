"""Geographic helpers (Haversine distance, travel-time estimation)."""
import math
from typing import Union

from app.utils.constants import TRAVEL_SPEED_KMPH

Number = Union[int, float]

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: Number, lon1: Number, lat2: Number, lon2: Number) -> float:
    """Return the great-circle distance in kilometres between two coordinates.

    Args:
        lat1, lon1: Latitude and longitude of the first point in decimal degrees.
        lat2, lon2: Latitude and longitude of the second point in decimal degrees.
    """
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def travel_minutes(distance_km: Number, speed_kmph: float = TRAVEL_SPEED_KMPH) -> int:
    """Travel time in whole minutes (rounded up) for a distance at a constant speed."""
    if distance_km <= 0:
        return 0
    return int(math.ceil(float(distance_km) / speed_kmph * 60))


def estimated_delivery_minutes(preparation_minutes: int, distance_km: Number) -> int:
    """Preparation time plus travel time at 20 km/h."""
    return int(preparation_minutes) + travel_minutes(distance_km)
