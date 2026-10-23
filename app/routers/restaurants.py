"""Restaurant, menu and nearby-search endpoints (Levels 3, 4, 14)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, pagination, require_approved_owner, require_owner
from app.models.user import User
from app.schemas.common import Page
from app.schemas.restaurant import (
    AvailabilityUpdate,
    CategoryCreate,
    CategoryOut,
    MenuItemCreate,
    MenuItemOut,
    MenuItemUpdate,
    MenuOut,
    NearbyRestaurantOut,
    OpenStatusUpdate,
    RestaurantCreate,
    RestaurantOut,
    RestaurantUpdate,
)
from app.services import restaurant_service, search_service
from app.utils.pagination import PageParams

router = APIRouter(tags=["Restaurants"])


@router.post("/restaurants", response_model=RestaurantOut, status_code=status.HTTP_201_CREATED)
def create_restaurant(
    data: RestaurantCreate, owner: User = Depends(require_approved_owner), db: Session = Depends(get_db)
):
    """Create a restaurant (approved Restaurant Owners only)."""
    return restaurant_service.create_restaurant(db, owner, data)


# NOTE: fixed paths must be declared before ``/restaurants/{restaurant_id}``.
@router.get("/restaurants/nearby", response_model=Page[NearbyRestaurantOut])
def nearby(
    latitude: float = Query(..., ge=-90, le=90, examples=[17.4486]),
    longitude: float = Query(..., ge=-180, le=180, examples=[78.3908]),
    search: Optional[str] = Query(None, max_length=100, description="Partial restaurant name"),
    cuisine: Optional[str] = Query(None, max_length=80),
    veg_only: bool = False,
    min_rating: Optional[float] = Query(None, ge=0, le=5),
    has_coupon: bool = Query(False, description="Only restaurants with an active coupon"),
    sort_by: str = Query("distance", pattern="^(distance|rating|delivery_time)$"),
    order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    page: PageParams = Depends(pagination),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Active, open restaurants whose delivery radius covers the location."""
    total, items = search_service.nearby_restaurants(
        db, latitude, longitude, page.skip, page.limit, search, cuisine, veg_only, min_rating, has_coupon, sort_by, order
    )
    return Page(total=total, skip=page.skip, limit=page.limit, items=items)


@router.get("/restaurants/me", response_model=List[RestaurantOut])
def my_restaurants(owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """Restaurants owned by the current owner."""
    return restaurant_service.list_owner_restaurants(db, owner)


@router.get("/restaurants/{restaurant_id}", response_model=RestaurantOut)
def get_restaurant(restaurant_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return restaurant_service.get_visible_restaurant(db, user, restaurant_id)


@router.put("/restaurants/{restaurant_id}", response_model=RestaurantOut)
def update_restaurant(
    restaurant_id: int, data: RestaurantUpdate, owner: User = Depends(require_owner), db: Session = Depends(get_db)
):
    return restaurant_service.update_restaurant(db, owner, restaurant_id, data)


@router.put("/restaurants/{restaurant_id}/open-status", response_model=RestaurantOut)
def open_status(
    restaurant_id: int, data: OpenStatusUpdate, owner: User = Depends(require_owner), db: Session = Depends(get_db)
):
    """Temporarily close / reopen a restaurant."""
    return restaurant_service.set_open_status(db, owner, restaurant_id, data.is_temporarily_closed)


@router.post("/restaurants/{restaurant_id}/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    restaurant_id: int, data: CategoryCreate, owner: User = Depends(require_owner), db: Session = Depends(get_db)
):
    return restaurant_service.create_category(db, owner, restaurant_id, data)


@router.post("/restaurants/{restaurant_id}/menu-items", response_model=MenuItemOut, status_code=status.HTTP_201_CREATED)
def create_menu_item(
    restaurant_id: int, data: MenuItemCreate, owner: User = Depends(require_owner), db: Session = Depends(get_db)
):
    return restaurant_service.create_menu_item(db, owner, restaurant_id, data)


@router.get("/restaurants/{restaurant_id}/menu", response_model=MenuOut)
def get_menu(restaurant_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Menu grouped by category; unavailable items are included and marked."""
    restaurant = restaurant_service.get_visible_restaurant(db, user, restaurant_id)
    return restaurant_service.build_menu(db, restaurant)


@router.put("/menu-items/{item_id}", response_model=MenuItemOut)
def update_menu_item(
    item_id: int, data: MenuItemUpdate, owner: User = Depends(require_owner), db: Session = Depends(get_db)
):
    return restaurant_service.update_menu_item(db, owner, item_id, data)


@router.put("/menu-items/{item_id}/availability", response_model=MenuItemOut)
def item_availability(
    item_id: int, data: AvailabilityUpdate, owner: User = Depends(require_owner), db: Session = Depends(get_db)
):
    return restaurant_service.set_item_availability(db, owner, item_id, data.is_available)


@router.delete("/menu-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_menu_item(item_id: int, owner: User = Depends(require_owner), db: Session = Depends(get_db)):
    """Soft delete - past orders keep showing the item."""
    restaurant_service.delete_menu_item(db, owner, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
