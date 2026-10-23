"""Restaurant and menu management business rules."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import transaction
from app.enums import Role
from app.models.restaurant import MenuCategory, MenuItem, Restaurant
from app.models.user import User
from app.schemas.restaurant import (
    CategoryCreate,
    MenuCategoryGroup,
    MenuItemCreate,
    MenuItemOut,
    MenuItemUpdate,
    MenuOut,
    RestaurantCreate,
    RestaurantUpdate,
)
from app.utils.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.utils.timeutils import utcnow


# ---------------------------------------------------------------- restaurants
def get_restaurant_or_404(db: Session, restaurant_id: int) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    return restaurant


def get_owned_restaurant(db: Session, owner: User, restaurant_id: int) -> Restaurant:
    """Return the restaurant if it belongs to ``owner`` (404 if missing, 403 if not theirs)."""
    restaurant = get_restaurant_or_404(db, restaurant_id)
    if restaurant.owner_id != owner.id:
        raise ForbiddenError("You can only manage your own restaurants")
    return restaurant


def get_visible_restaurant(db: Session, user: User, restaurant_id: int) -> Restaurant:
    """Inactive restaurants are visible only to their owner and admins."""
    restaurant = get_restaurant_or_404(db, restaurant_id)
    if not restaurant.is_active and user.role != Role.ADMIN.value and restaurant.owner_id != user.id:
        raise NotFoundError("Restaurant not found")
    return restaurant


def create_restaurant(db: Session, owner: User, data: RestaurantCreate) -> Restaurant:
    with transaction(db):
        restaurant = Restaurant(owner_id=owner.id, **data.model_dump())
        db.add(restaurant)
        db.flush()
    return restaurant


def update_restaurant(db: Session, owner: User, restaurant_id: int, data: RestaurantUpdate) -> Restaurant:
    restaurant = get_owned_restaurant(db, owner, restaurant_id)
    changes = data.model_dump(exclude_unset=True)
    for key in ("name", "cuisine_type", "address", "latitude", "longitude", "opening_time", "closing_time",
                "delivery_radius_km", "min_order_value", "avg_preparation_minutes", "is_active"):
        if key in changes and changes[key] is None:
            raise BadRequestError(f"{key} cannot be null")
    opening = changes.get("opening_time", restaurant.opening_time)
    closing = changes.get("closing_time", restaurant.closing_time)
    if opening >= closing:
        raise BadRequestError("opening_time must be before closing_time")
    with transaction(db):
        for key, value in changes.items():
            setattr(restaurant, key, value)
        db.flush()
    return restaurant


def set_open_status(db: Session, owner: User, restaurant_id: int, is_temporarily_closed: bool) -> Restaurant:
    restaurant = get_owned_restaurant(db, owner, restaurant_id)
    with transaction(db):
        restaurant.is_temporarily_closed = is_temporarily_closed
        db.flush()
    return restaurant


def list_owner_restaurants(db: Session, owner: User) -> List[Restaurant]:
    return list(db.scalars(select(Restaurant).where(Restaurant.owner_id == owner.id).order_by(Restaurant.id)))


# --------------------------------------------------------------------- menu
def create_category(db: Session, owner: User, restaurant_id: int, data: CategoryCreate) -> MenuCategory:
    restaurant = get_owned_restaurant(db, owner, restaurant_id)
    existing = db.scalar(
        select(MenuCategory.id).where(MenuCategory.restaurant_id == restaurant.id, MenuCategory.name == data.name)
    )
    if existing:
        raise ConflictError("Category already exists for this restaurant")
    try:
        with transaction(db):
            category = MenuCategory(restaurant_id=restaurant.id, name=data.name)
            db.add(category)
            db.flush()
    except IntegrityError:
        raise ConflictError("Category already exists for this restaurant") from None
    return category


def create_menu_item(db: Session, owner: User, restaurant_id: int, data: MenuItemCreate) -> MenuItem:
    restaurant = get_owned_restaurant(db, owner, restaurant_id)
    category = db.get(MenuCategory, data.category_id)
    if category is None or category.restaurant_id != restaurant.id:
        raise BadRequestError("category_id does not belong to this restaurant")
    with transaction(db):
        item = MenuItem(restaurant_id=restaurant.id, **data.model_dump())
        db.add(item)
        db.flush()
    return item


def get_owned_item(db: Session, owner: User, item_id: int) -> MenuItem:
    item = db.get(MenuItem, item_id)
    if item is None or item.is_deleted:
        raise NotFoundError("Menu item not found")
    restaurant = db.get(Restaurant, item.restaurant_id)
    if restaurant is None or restaurant.owner_id != owner.id:
        raise ForbiddenError("You can only manage items of your own restaurants")
    return item


def update_menu_item(db: Session, owner: User, item_id: int, data: MenuItemUpdate) -> MenuItem:
    item = get_owned_item(db, owner, item_id)
    changes = data.model_dump(exclude_unset=True)
    for key in ("name", "price", "is_veg", "packaging_charge", "category_id"):
        if key in changes and changes[key] is None:
            raise BadRequestError(f"{key} cannot be null")
    if "category_id" in changes:
        category = db.get(MenuCategory, changes["category_id"])
        if category is None or category.restaurant_id != item.restaurant_id:
            raise BadRequestError("category_id does not belong to this restaurant")
    with transaction(db):
        for key, value in changes.items():
            setattr(item, key, value)
        db.flush()
    return item


def set_item_availability(db: Session, owner: User, item_id: int, is_available: bool) -> MenuItem:
    """Hide an item from ordering without deleting it."""
    item = get_owned_item(db, owner, item_id)
    with transaction(db):
        item.is_available = is_available
        db.flush()
    return item


def delete_menu_item(db: Session, owner: User, item_id: int) -> None:
    """Soft delete: the row stays so historical orders still reference it."""
    item = get_owned_item(db, owner, item_id)
    with transaction(db):
        item.is_deleted = True
        item.is_available = False
        item.deleted_at = utcnow()
        db.flush()


def build_menu(db: Session, restaurant: Restaurant) -> MenuOut:
    """Menu grouped by category; unavailable items are included and flagged."""
    categories = db.scalars(
        select(MenuCategory).where(MenuCategory.restaurant_id == restaurant.id).order_by(MenuCategory.id)
    ).all()
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant.id, MenuItem.is_deleted.is_(False))
        .order_by(MenuItem.id)
    ).all()
    by_category: dict = {c.id: [] for c in categories}
    for item in items:
        by_category.setdefault(item.category_id, []).append(MenuItemOut.model_validate(item))
    groups = [
        MenuCategoryGroup(category_id=c.id, category_name=c.name, items=by_category.get(c.id, []))
        for c in categories
    ]
    return MenuOut(
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        is_open=restaurant.is_open,
        categories=groups,
    )
