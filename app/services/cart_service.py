"""Cart management (one cart per customer, single restaurant)."""
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import transaction
from app.models.cart import Cart, CartItem
from app.models.coupon import Coupon
from app.models.restaurant import MenuItem, Restaurant
from app.models.user import User
from app.schemas.cart import ApplyCouponRequest, CartItemAdd, CartItemOut, CartItemUpdate, CartOut
from app.services import coupon_service
from app.utils.constants import CART_CONFLICT_MESSAGE, MAX_ITEM_QUANTITY
from app.utils.errors import BadRequestError, ConflictError, NotFoundError
from app.utils.money import ZERO, money


def get_cart(db: Session, customer: User, for_update: bool = False) -> Optional[Cart]:
    stmt = select(Cart).where(Cart.customer_id == customer.id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.scalar(stmt)


def get_or_create_cart(db: Session, customer: User, for_update: bool = False) -> Cart:
    """Return the customer's cart, creating it on first use (flush only, no commit)."""
    cart = get_cart(db, customer, for_update)
    if cart is None:
        cart = Cart(customer_id=customer.id)
        db.add(cart)
        db.flush()
    return cart


def cart_item_total(cart: Optional[Cart]) -> Decimal:
    """Sum of unit price x quantity for every line."""
    if cart is None:
        return ZERO
    return money(sum((money(ci.menu_item.price) * ci.quantity for ci in cart.items), Decimal("0")))


def build_cart_out(db: Session, customer: User, cart: Cart) -> CartOut:
    """Serialise a cart with line totals, discount and the total after discount."""
    items = []
    for ci in cart.items:
        mi = ci.menu_item
        items.append(
            CartItemOut(
                id=ci.id,
                menu_item_id=mi.id,
                name=mi.name,
                unit_price=mi.price,
                packaging_charge=mi.packaging_charge,
                quantity=ci.quantity,
                line_total=money(mi.price * ci.quantity),
                is_available=bool(mi.is_available and not mi.is_deleted),
            )
        )
    item_total = cart_item_total(cart)
    discount, message, code = ZERO, None, None
    if cart.coupon_id is not None:
        coupon = db.get(Coupon, cart.coupon_id)
        if coupon is not None:
            code = coupon.code
            try:
                discount = coupon_service.evaluate_coupon(db, coupon, customer, cart.restaurant_id, item_total)
            except BadRequestError as exc:
                message = f"Coupon currently not applicable: {exc.message}"
    restaurant_name = None
    if cart.restaurant_id is not None:
        restaurant = db.get(Restaurant, cart.restaurant_id)
        restaurant_name = restaurant.name if restaurant else None
    return CartOut(
        id=cart.id,
        restaurant_id=cart.restaurant_id,
        restaurant_name=restaurant_name,
        items=items,
        item_total=item_total,
        discount=discount,
        total_after_discount=money(item_total - discount),
        coupon_code=code,
        coupon_message=message,
    )


def view_cart(db: Session, customer: User) -> CartOut:
    with transaction(db):
        cart = get_or_create_cart(db, customer)
    return build_cart_out(db, customer, cart)


def _reset_if_empty(cart: Cart) -> None:
    if not cart.items:
        cart.restaurant_id = None
        cart.coupon_id = None


def add_item(db: Session, customer: User, data: CartItemAdd) -> CartOut:
    with transaction(db):
        cart = get_or_create_cart(db, customer, for_update=True)
        item = db.get(MenuItem, data.menu_item_id)
        if item is None or item.is_deleted:
            raise NotFoundError("Menu item not found")
        restaurant = db.get(Restaurant, item.restaurant_id)
        if restaurant is None or not restaurant.is_active:
            raise BadRequestError("Restaurant is not available")
        if not item.is_available:
            raise BadRequestError("This menu item is currently unavailable")
        if cart.items and cart.restaurant_id is not None and cart.restaurant_id != item.restaurant_id:
            raise ConflictError(CART_CONFLICT_MESSAGE)

        existing = next((ci for ci in cart.items if ci.menu_item_id == item.id), None)
        if existing is not None:
            new_quantity = existing.quantity + data.quantity
            if new_quantity > MAX_ITEM_QUANTITY:
                raise BadRequestError(f"Maximum quantity per item is {MAX_ITEM_QUANTITY}")
            existing.quantity = new_quantity
        else:
            cart.items.append(CartItem(menu_item_id=item.id, quantity=data.quantity))
        cart.restaurant_id = item.restaurant_id
        db.flush()
    return build_cart_out(db, customer, cart)


def _get_own_cart_item(db: Session, customer: User, item_id: int) -> "tuple[Cart, CartItem]":
    cart = get_or_create_cart(db, customer, for_update=True)
    cart_item = next((ci for ci in cart.items if ci.id == item_id), None)
    if cart_item is None:
        raise NotFoundError("Cart item not found")
    return cart, cart_item


def update_item(db: Session, customer: User, item_id: int, data: CartItemUpdate) -> CartOut:
    with transaction(db):
        cart, cart_item = _get_own_cart_item(db, customer, item_id)
        mi = cart_item.menu_item
        if mi.is_deleted or not mi.is_available:
            raise BadRequestError("This menu item is currently unavailable")
        cart_item.quantity = data.quantity
        db.flush()
    return build_cart_out(db, customer, cart)


def remove_item(db: Session, customer: User, item_id: int) -> CartOut:
    with transaction(db):
        cart, cart_item = _get_own_cart_item(db, customer, item_id)
        cart.items.remove(cart_item)
        db.flush()
        _reset_if_empty(cart)
        db.flush()
    return build_cart_out(db, customer, cart)


def clear_cart(db: Session, customer: User) -> CartOut:
    """Remove all items and the applied coupon."""
    with transaction(db):
        cart = get_or_create_cart(db, customer, for_update=True)
        cart.items.clear()
        cart.restaurant_id = None
        cart.coupon_id = None
        db.flush()
    return build_cart_out(db, customer, cart)


def apply_coupon(db: Session, customer: User, data: ApplyCouponRequest) -> CartOut:
    with transaction(db):
        cart = get_or_create_cart(db, customer, for_update=True)
        if not cart.items:
            raise BadRequestError("Your cart is empty")
        coupon = coupon_service.get_coupon_by_code(db, data.code)
        if coupon is None:
            raise BadRequestError("Invalid coupon code")
        coupon_service.evaluate_coupon(db, coupon, customer, cart.restaurant_id, cart_item_total(cart))
        cart.coupon_id = coupon.id
        db.flush()
    return build_cart_out(db, customer, cart)


def remove_coupon(db: Session, customer: User) -> CartOut:
    with transaction(db):
        cart = get_or_create_cart(db, customer, for_update=True)
        cart.coupon_id = None
        db.flush()
    return build_cart_out(db, customer, cart)
