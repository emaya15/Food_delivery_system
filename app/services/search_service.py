"""Location-based restaurant search with filtering, sorting and pagination."""
from typing import List, Optional, Tuple

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models.coupon import Coupon
from app.models.restaurant import MenuItem, Restaurant
from app.schemas.restaurant import NearbyRestaurantOut, RestaurantOut
from app.utils.errors import BadRequestError
from app.utils.geo import estimated_delivery_minutes, haversine_km
from app.utils.timeutils import local_now, utcnow

SORT_FIELDS = ("distance", "rating", "delivery_time")


def restaurants_with_active_coupons(db: Session) -> set:
    """IDs of restaurants that have at least one currently valid restaurant-specific coupon."""
    now = utcnow()
    rows = db.scalars(
        select(Coupon.restaurant_id)
        .where(
            Coupon.restaurant_id.is_not(None),
            Coupon.is_active.is_(True),
            Coupon.valid_from <= now,
            Coupon.valid_until >= now,
        )
        .distinct()
    )
    return set(rows)


def nearby_restaurants(
    db: Session,
    latitude: float,
    longitude: float,
    skip: int,
    limit: int,
    search: Optional[str] = None,
    cuisine: Optional[str] = None,
    veg_only: bool = False,
    min_rating: Optional[float] = None,
    has_coupon: bool = False,
    sort_by: str = "distance",
    order: Optional[str] = None,
) -> Tuple[int, List[NearbyRestaurantOut]]:
    """Active, open restaurants whose delivery radius covers the given point.

    Distance uses the Haversine formula; the estimated delivery time is the
    restaurant's preparation time plus travel time at 20 km/h.
    """
    if sort_by not in SORT_FIELDS:
        raise BadRequestError(f"sort_by must be one of: {', '.join(SORT_FIELDS)}")
    if order is None:
        order = "desc" if sort_by == "rating" else "asc"
    if order not in ("asc", "desc"):
        raise BadRequestError("order must be 'asc' or 'desc'")

    stmt = select(Restaurant).where(
        Restaurant.is_active.is_(True), Restaurant.is_temporarily_closed.is_(False)
    )
    if search:
        stmt = stmt.where(func.lower(Restaurant.name).contains(search.strip().lower(), autoescape=True))
    if cuisine:
        stmt = stmt.where(func.lower(Restaurant.cuisine_type) == cuisine.strip().lower())
    if min_rating is not None:
        stmt = stmt.where(Restaurant.average_rating >= min_rating)
    if veg_only:
        live = (MenuItem.restaurant_id == Restaurant.id, MenuItem.is_deleted.is_(False), MenuItem.is_available.is_(True))
        stmt = stmt.where(exists().where(*live, MenuItem.is_veg.is_(True)), ~exists().where(*live, MenuItem.is_veg.is_(False)))

    coupon_ids = restaurants_with_active_coupons(db)
    if has_coupon:
        stmt = stmt.where(Restaurant.id.in_(coupon_ids or {0}))

    now_time = local_now().time().replace(tzinfo=None)
    results: List[NearbyRestaurantOut] = []
    for restaurant in db.scalars(stmt):
        if not restaurant.is_open_at(now_time):
            continue
        distance = haversine_km(latitude, longitude, restaurant.latitude, restaurant.longitude)
        if distance > float(restaurant.delivery_radius_km):
            continue
        base = RestaurantOut.model_validate(restaurant).model_dump()
        results.append(
            NearbyRestaurantOut(
                **base,
                distance_km=round(distance, 2),
                estimated_delivery_minutes=estimated_delivery_minutes(restaurant.avg_preparation_minutes, distance),
                has_active_coupon=restaurant.id in coupon_ids,
            )
        )

    keys = {
        "distance": lambda r: (r.distance_km, r.id),
        "rating": lambda r: (float(r.average_rating), -r.id),
        "delivery_time": lambda r: (r.estimated_delivery_minutes, r.distance_km),
    }
    results.sort(key=keys[sort_by], reverse=(order == "desc"))
    total = len(results)
    return total, results[skip: skip + limit]
