"""Coupon rules: validation, discount calculation, usage tracking and management."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import transaction
from app.enums import DiscountType, OrderStatus, Role
from app.models.cart import Cart
from app.models.coupon import Coupon, CouponUsage
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.cart import CouponCreate, CouponPreviewOut, CouponUpdate
from app.utils.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.utils.money import ZERO, money, to_decimal
from app.utils.timeutils import utcnow


# ------------------------------------------------------------ rule evaluation
def normalize_code(code: str) -> str:
    """Coupon codes are case-insensitive: always compare upper-cased."""
    return code.strip().upper()


def get_coupon_by_code(db: Session, code: str, for_update: bool = False) -> Optional[Coupon]:
    stmt = select(Coupon).where(Coupon.code == normalize_code(code))
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def lock_coupon(db: Session, coupon_id: int) -> Coupon:
    """Row-lock a coupon (``SELECT ... FOR UPDATE``) and refresh its counters.

    Holding this lock while counting usages and incrementing ``used_count``
    serialises concurrent orders so usage limits can never be exceeded.
    """
    coupon = db.scalar(
        select(Coupon).where(Coupon.id == coupon_id).with_for_update().execution_options(populate_existing=True)
    )
    if coupon is None:
        raise BadRequestError("Invalid coupon")
    return coupon


def compute_discount(coupon: Coupon, item_total: Decimal) -> Decimal:
    """Discount amount for ``item_total`` (percentage w/ cap, or flat; never above the total)."""
    item_total = to_decimal(item_total)
    if coupon.discount_type == DiscountType.PERCENTAGE.value:
        discount = money(item_total * to_decimal(coupon.discount_value) / Decimal("100"))
        if coupon.max_discount is not None:
            discount = min(discount, money(coupon.max_discount))
    else:
        discount = money(coupon.discount_value)
    return max(ZERO, min(discount, money(item_total)))


def has_previous_orders(db: Session, user_id: int) -> bool:
    """True if the user has any order that was not cancelled/rejected."""
    count = db.scalar(
        select(func.count(Order.id)).where(
            Order.customer_id == user_id,
            Order.status.notin_([OrderStatus.CANCELLED.value, OrderStatus.REJECTED.value]),
        )
    )
    return bool(count)


def evaluate_coupon(
    db: Session,
    coupon: Coupon,
    user: User,
    restaurant_id: Optional[int],
    item_total: Decimal,
    now: Optional[datetime] = None,
) -> Decimal:
    """Validate ``coupon`` for this user/cart and return the discount.

    Raises ``BadRequestError`` (HTTP 400) with a clear message when invalid.
    """
    now = now or utcnow()
    item_total = money(item_total)
    if not coupon.is_active:
        raise BadRequestError("This coupon is no longer active")
    if now < coupon.valid_from:
        raise BadRequestError("This coupon is not valid yet")
    if now > coupon.valid_until:
        raise BadRequestError("This coupon has expired")
    if coupon.restaurant_id is not None and coupon.restaurant_id != restaurant_id:
        raise BadRequestError("This coupon is not applicable to the restaurant in your cart")
    if item_total < money(coupon.min_order_value):
        raise BadRequestError(f"A minimum order value of {money(coupon.min_order_value)} is required for this coupon")
    if coupon.usage_limit_total is not None and coupon.used_count >= coupon.usage_limit_total:
        raise BadRequestError("This coupon has reached its maximum number of uses")
    if coupon.usage_limit_per_user is not None:
        used = db.scalar(
            select(func.count(CouponUsage.id)).where(
                CouponUsage.coupon_id == coupon.id,
                CouponUsage.user_id == user.id,
                CouponUsage.is_released.is_(False),
            )
        ) or 0
        if used >= coupon.usage_limit_per_user:
            raise BadRequestError("You have already used this coupon the maximum number of times")
    if coupon.first_order_only and has_previous_orders(db, user.id):
        raise BadRequestError("This coupon is valid only on your first order")
    return compute_discount(coupon, item_total)


def record_usage(db: Session, coupon: Coupon, user: User, order: Order) -> CouponUsage:
    """Count a coupon use (only called when an order is actually placed)."""
    coupon.used_count = (coupon.used_count or 0) + 1
    usage = CouponUsage(coupon_id=coupon.id, user_id=user.id, order_id=order.id)
    db.add(usage)
    db.flush()
    return usage


def release_usage(db: Session, order: Order) -> bool:
    """Give back a coupon use when the order is cancelled or rejected. Idempotent."""
    usage = db.scalar(
        select(CouponUsage).where(CouponUsage.order_id == order.id, CouponUsage.is_released.is_(False))
    )
    if usage is None:
        return False
    coupon = lock_coupon(db, usage.coupon_id)
    coupon.used_count = max(0, (coupon.used_count or 0) - 1)
    usage.is_released = True
    usage.released_at = utcnow()
    db.flush()
    return True


# ----------------------------------------------------------------- management
def _assert_can_use_restaurant(db: Session, user: User, restaurant_id: Optional[int]) -> None:
    if user.role == Role.ADMIN.value:
        if restaurant_id is not None and db.get(Restaurant, restaurant_id) is None:
            raise NotFoundError("Restaurant not found")
        return
    # Restaurant owners: only coupons for their own restaurants
    if restaurant_id is None:
        raise ForbiddenError("Only admins can create platform-wide coupons")
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    if restaurant.owner_id != user.id:
        raise ForbiddenError("You can only manage coupons for your own restaurants")


def _validate_merged(coupon: Coupon) -> None:
    if coupon.valid_until <= coupon.valid_from:
        raise BadRequestError("valid_until must be after valid_from")
    value = to_decimal(coupon.discount_value)
    if value <= 0:
        raise BadRequestError("discount_value must be positive")
    if coupon.discount_type == DiscountType.PERCENTAGE.value and not (1 <= value <= 100):
        raise BadRequestError("percentage discount_value must be between 1 and 100")


def create_coupon(db: Session, user: User, data: CouponCreate) -> Coupon:
    _assert_can_use_restaurant(db, user, data.restaurant_id)
    if get_coupon_by_code(db, data.code):
        raise ConflictError("Coupon code already exists")
    try:
        with transaction(db):
            coupon = Coupon(
                **data.model_dump(exclude={"discount_type"}),
                discount_type=data.discount_type.value,
                created_by=user.id,
                is_active=True,
                used_count=0,
            )
            db.add(coupon)
            db.flush()
    except IntegrityError:
        raise ConflictError("Coupon code already exists") from None
    return coupon


def get_manageable_coupon(db: Session, user: User, coupon_id: int) -> Coupon:
    coupon = db.get(Coupon, coupon_id)
    if coupon is None:
        raise NotFoundError("Coupon not found")
    if user.role == Role.ADMIN.value:
        return coupon
    restaurant = db.get(Restaurant, coupon.restaurant_id) if coupon.restaurant_id else None
    if restaurant is None or restaurant.owner_id != user.id:
        raise ForbiddenError("You can only manage coupons for your own restaurants")
    return coupon


def update_coupon(db: Session, user: User, coupon_id: int, data: CouponUpdate) -> Coupon:
    coupon = get_manageable_coupon(db, user, coupon_id)
    changes = data.model_dump(exclude_unset=True)
    for key in ("discount_type", "discount_value", "min_order_value", "valid_from", "valid_until", "first_order_only"):
        if key in changes and changes[key] is None:
            raise BadRequestError(f"{key} cannot be null")
    if "discount_type" in changes:
        changes["discount_type"] = changes["discount_type"].value
    with transaction(db):
        for key, value in changes.items():
            setattr(coupon, key, value)
        _validate_merged(coupon)
        db.flush()
    return coupon


def deactivate_coupon(db: Session, user: User, coupon_id: int) -> Coupon:
    coupon = get_manageable_coupon(db, user, coupon_id)
    with transaction(db):
        coupon.is_active = False
        db.flush()
    return coupon


def list_coupons(
    db: Session,
    user: User,
    skip: int,
    limit: int,
    restaurant_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    discount_type: Optional[DiscountType] = None,
) -> Tuple[int, List[Coupon]]:
    stmt = select(Coupon)
    if user.role != Role.ADMIN.value:
        owned = select(Restaurant.id).where(Restaurant.owner_id == user.id)
        stmt = stmt.where(Coupon.restaurant_id.in_(owned))
    if restaurant_id is not None:
        stmt = stmt.where(Coupon.restaurant_id == restaurant_id)
    if is_active is not None:
        stmt = stmt.where(Coupon.is_active.is_(is_active))
    if discount_type is not None:
        stmt = stmt.where(Coupon.discount_type == discount_type.value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(Coupon.id.desc()).offset(skip).limit(limit)))
    return total, rows


def available_coupons(
    db: Session, user: User, skip: int, limit: int, restaurant_id: Optional[int] = None
) -> Tuple[int, List[CouponPreviewOut]]:
    """Coupons the customer could use, each with an eligibility preview for the current cart."""
    cart = db.scalar(select(Cart).where(Cart.customer_id == user.id))
    cart_restaurant = cart.restaurant_id if cart and cart.items else None
    target_restaurant = restaurant_id if restaurant_id is not None else cart_restaurant
    now = utcnow()

    stmt = select(Coupon).where(
        Coupon.is_active.is_(True), Coupon.valid_from <= now, Coupon.valid_until >= now
    )
    if target_restaurant is not None:
        stmt = stmt.where((Coupon.restaurant_id.is_(None)) | (Coupon.restaurant_id == target_restaurant))
    else:
        stmt = stmt.where(Coupon.restaurant_id.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    coupons = list(db.scalars(stmt.order_by(Coupon.id).offset(skip).limit(limit)))

    from app.services.cart_service import cart_item_total  # local import avoids a cycle

    item_total = cart_item_total(cart) if (cart and cart.items and cart_restaurant == target_restaurant) else None
    previews: List[CouponPreviewOut] = []
    for coupon in coupons:
        eligible, discount, reason = False, ZERO, None
        if item_total is None:
            reason = "Add items from this restaurant to your cart to check eligibility"
        else:
            try:
                discount = evaluate_coupon(db, coupon, user, target_restaurant, item_total, now)
                eligible = True
            except BadRequestError as exc:
                reason = exc.message
        data = {c: getattr(coupon, c) for c in (
            "id", "code", "description", "restaurant_id", "discount_type", "discount_value", "max_discount",
            "min_order_value", "valid_from", "valid_until", "usage_limit_total", "usage_limit_per_user",
            "used_count", "first_order_only", "is_active")}
        previews.append(CouponPreviewOut(**data, eligible=eligible, discount=discount, reason=reason))
    return total, previews


def deactivate_expired(db: Session) -> int:
    """Daily job: deactivate coupons whose validity window has ended."""
    with transaction(db):
        result = db.execute(
            update(Coupon).where(Coupon.is_active.is_(True), Coupon.valid_until < utcnow()).values(is_active=False)
        )
    return result.rowcount or 0
