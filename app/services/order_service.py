"""Order placement, cancellation, reorder and restaurant-side order handling."""
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import transaction
from app.enums import (
    ALLOWED_TRANSITIONS,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    Role,
)
from app.models.address import Address
from app.models.cart import CartItem
from app.models.order import Order, OrderItem, OrderSequence, OrderStatusHistory
from app.models.restaurant import MenuItem, Restaurant
from app.models.user import User
from app.schemas.cart import CartOut
from app.schemas.order import OrderCreate, OrderOut, ReorderOut, StatusHistoryOut
from app.services import assignment_service, billing, cart_service, coupon_service
from app.utils.constants import (
    AUTO_REJECT_AFTER_MINUTES,
    AUTO_REJECT_REASON,
    CART_CONFLICT_MESSAGE,
    MAX_ITEM_QUANTITY,
    MIN_SCHEDULE_LEAD_MINUTES,
)
from app.utils.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.utils.geo import haversine_km
from app.utils.money import ZERO, money
from app.utils.timeutils import ensure_aware, local_day_bounds_utc, local_today, to_local, utcnow
from app.websockets.manager import order_channel, partner_channel, queue_event, restaurant_channel


# -------------------------------------------------------------------- helpers
def actor(user: User) -> str:
    """Audit-trail label for a human actor, e.g. ``Customer:12``."""
    return f"{user.role}:{user.id}"


def lock_order(db: Session, order_id: int) -> Optional[Order]:
    return assignment_service.lock_order(db, order_id)


def next_order_number(db: Session) -> str:
    """Unique ``ORD-YYYYMMDD-NNNN`` number from a per-day, row-locked counter."""
    key = local_today().strftime("%Y%m%d")
    stmt = (
        select(OrderSequence)
        .where(OrderSequence.seq_date == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sequence = db.scalar(stmt)
    if sequence is None:
        try:
            with db.begin_nested():
                db.add(OrderSequence(seq_date=key, last_value=0))
                db.flush()
        except IntegrityError:
            pass  # another transaction created it first
        sequence = db.scalar(stmt)
    sequence.last_value += 1
    db.flush()
    return f"ORD-{key}-{sequence.last_value:04d}"


def generate_otp() -> str:
    """Cryptographically random four-digit delivery OTP (leading zeros allowed)."""
    return f"{secrets.randbelow(10000):04d}"


def record_status(
    db: Session, order: Order, new_status: OrderStatus, changed_by: str, note: Optional[str] = None
) -> None:
    """Validate a transition, append it to the history and push it to WebSocket subscribers."""
    current = OrderStatus(order.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        raise BadRequestError(f"Invalid status transition: {current.value} -> {new_status.value}")
    order.history.append(
        OrderStatusHistory(from_status=current.value, to_status=new_status.value, changed_by=changed_by, note=note)
    )
    order.status = new_status.value
    db.flush()
    publish_status(db, order, current.value, changed_by, note)


def publish_status(db: Session, order: Order, previous: Optional[str], changed_by: str, note: Optional[str]) -> None:
    payload = {
        "type": "order_status",
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "previous_status": previous,
        "changed_by": changed_by,
        "note": note,
        "timestamp": utcnow().isoformat(),
    }
    queue_event(db, order_channel(order.id), payload)
    restaurant = db.get(Restaurant, order.restaurant_id)
    if restaurant is not None:
        queue_event(db, restaurant_channel(restaurant.owner_id), payload)
    if order.partner_id is not None:
        queue_event(db, partner_channel(order.partner_id), payload)


def refund_and_release(db: Session, order: Order) -> None:
    """Refund paid online orders and give back the coupon use (cancel / reject / auto-reject)."""
    if order.payment_method == PaymentMethod.ONLINE.value and order.payment_status == PaymentStatus.PAID.value:
        order.payment_status = PaymentStatus.REFUNDED.value
    coupon_service.release_usage(db, order)
    db.flush()


def can_access_order(db: Session, user: User, order: Order) -> bool:
    """Customer, owning restaurant owner, assigned partner and admins may see an order."""
    if user.role == Role.ADMIN.value:
        return True
    if user.role == Role.CUSTOMER.value:
        return order.customer_id == user.id
    if user.role == Role.RESTAURANT_OWNER.value:
        restaurant = db.get(Restaurant, order.restaurant_id)
        return restaurant is not None and restaurant.owner_id == user.id
    if user.role == Role.DELIVERY_PARTNER.value:
        return order.partner_id == user.id
    return False


def get_order_for_user(db: Session, user: User, order_id: int) -> Order:
    """Fetch an order the user may see (404 otherwise, so other users' orders are never revealed)."""
    order = db.get(Order, order_id)
    if order is None or not can_access_order(db, user, order):
        raise NotFoundError("Order not found")
    return order


def build_order_out(order: Order, viewer: User) -> OrderOut:
    """Serialise an order. The delivery OTP is only shown to the order's customer."""
    out = OrderOut.model_validate(order)
    out.restaurant_name = order.restaurant.name if order.restaurant else None
    out.status_history = [StatusHistoryOut.model_validate(h) for h in order.history]
    if viewer.id != order.customer_id or viewer.role != Role.CUSTOMER.value:
        out.delivery_otp = None
    return out


# ------------------------------------------------------------------ placement
def place_order(db: Session, customer: User, data: OrderCreate) -> Order:
    """Create an order from the customer's cart in a single atomic transaction.

    Everything - validation, coupon consumption, order number, items, status
    history and clearing the cart - commits together or not at all.
    """
    with transaction(db):
        cart = cart_service.get_or_create_cart(db, customer, for_update=True)
        if not cart.items:
            raise BadRequestError("Your cart is empty")
        restaurant = db.get(Restaurant, cart.restaurant_id) if cart.restaurant_id else None
        if restaurant is None or not restaurant.is_active:
            raise BadRequestError("Restaurant is not available")

        now = utcnow()
        scheduled_for: Optional[datetime] = None
        if data.scheduled_for is not None:
            scheduled_for = ensure_aware(data.scheduled_for)
            if scheduled_for - now < timedelta(minutes=MIN_SCHEDULE_LEAD_MINUTES):
                raise BadRequestError(f"Scheduled time must be at least {MIN_SCHEDULE_LEAD_MINUTES} minutes from now")
            if to_local(scheduled_for).date() != to_local(now).date():
                raise BadRequestError("Scheduled orders must be for later today")
            if restaurant.is_temporarily_closed:
                raise BadRequestError("Restaurant is temporarily closed")
            if not restaurant.is_open_at(to_local(scheduled_for).time().replace(tzinfo=None)):
                raise BadRequestError("Restaurant will be closed at the scheduled time")
        elif not restaurant.is_open:
            raise BadRequestError("Restaurant is currently closed")

        address = db.get(Address, data.address_id)
        if address is None or address.customer_id != customer.id:
            raise NotFoundError("Address not found")
        distance = haversine_km(restaurant.latitude, restaurant.longitude, address.latitude, address.longitude)
        if distance > float(restaurant.delivery_radius_km):
            raise BadRequestError("Delivery address is outside this restaurant's delivery radius")
        distance_dec = money(distance)

        unavailable = [
            ci.menu_item.name for ci in cart.items if ci.menu_item.is_deleted or not ci.menu_item.is_available
        ]
        if unavailable:
            raise BadRequestError("Some items are unavailable: " + ", ".join(unavailable))

        item_total = cart_service.cart_item_total(cart)
        if item_total < money(restaurant.min_order_value):
            raise BadRequestError(f"Minimum order value for this restaurant is {money(restaurant.min_order_value)}")

        coupon = None
        discount = ZERO
        if cart.coupon_id is not None:
            # Row lock: concurrent orders queue here, so usage limits cannot be exceeded.
            coupon = coupon_service.lock_coupon(db, cart.coupon_id)
            discount = coupon_service.evaluate_coupon(db, coupon, customer, restaurant.id, item_total, now)

        lines = [
            billing.BillLine(ci.menu_item.price, ci.menu_item.packaging_charge, ci.quantity) for ci in cart.items
        ]
        bill = billing.calculate_bill(
            lines, discount, distance_dec, tip=data.tip, when_local=to_local(scheduled_for or now)
        )

        method = data.payment_method
        order = Order(
            order_number=next_order_number(db),
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            address_id=address.id,
            delivery_address_line=address.address_line,
            delivery_city=address.city,
            delivery_pincode=address.pincode,
            delivery_latitude=address.latitude,
            delivery_longitude=address.longitude,
            distance_km=distance_dec,
            status=OrderStatus.PLACED.value,
            payment_method=method.value,
            payment_status=PaymentStatus.PAID.value if method == PaymentMethod.ONLINE else PaymentStatus.PENDING.value,
            item_total=bill.item_total,
            discount=bill.discount,
            packaging_charges=bill.packaging_charges,
            delivery_fee=bill.delivery_fee,
            platform_fee=bill.platform_fee,
            gst=bill.gst,
            tip=bill.tip,
            grand_total=bill.grand_total,
            surge_applied=bill.surge_applied,
            delivery_otp=generate_otp(),
            scheduled_for=scheduled_for,
            placed_at=now,
        )
        for ci in cart.items:
            mi = ci.menu_item
            order.items.append(
                OrderItem(
                    menu_item_id=mi.id,
                    name=mi.name,
                    unit_price=money(mi.price),
                    packaging_charge=money(mi.packaging_charge),
                    quantity=ci.quantity,
                    line_total=money(mi.price * ci.quantity),
                )
            )
        order.history.append(
            OrderStatusHistory(from_status=None, to_status=OrderStatus.PLACED.value, changed_by=actor(customer))
        )
        db.add(order)
        db.flush()

        if coupon is not None:
            coupon_service.record_usage(db, coupon, customer, order)
            order.coupon_id = coupon.id
            order.coupon_code = coupon.code

        # Empty the cart (items, restaurant and coupon) as part of the same transaction.
        cart.items.clear()
        cart.restaurant_id = None
        cart.coupon_id = None
        db.flush()

        queue_event(
            db,
            restaurant_channel(restaurant.owner_id),
            {
                "type": "new_order",
                "order_id": order.id,
                "order_number": order.order_number,
                "item_count": sum(i.quantity for i in order.items),
                "grand_total": float(order.grand_total),
                "payment_method": order.payment_method,
                "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            },
        )
    return order


# ------------------------------------------------------------------- queries
def list_orders(
    db: Session,
    user: User,
    skip: int,
    limit: int,
    status: Optional[OrderStatus] = None,
    restaurant_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Tuple[int, List[Order]]:
    """Orders visible to ``user`` (scoped by role) with status / restaurant / date filters."""
    stmt = select(Order)
    if user.role == Role.CUSTOMER.value:
        stmt = stmt.where(Order.customer_id == user.id)
    elif user.role == Role.RESTAURANT_OWNER.value:
        stmt = stmt.where(Order.restaurant_id.in_(select(Restaurant.id).where(Restaurant.owner_id == user.id)))
    elif user.role == Role.DELIVERY_PARTNER.value:
        stmt = stmt.where(Order.partner_id == user.id)
    if status is not None:
        stmt = stmt.where(Order.status == status.value)
    if restaurant_id is not None:
        stmt = stmt.where(Order.restaurant_id == restaurant_id)
    if from_date is not None:
        stmt = stmt.where(Order.placed_at >= local_day_bounds_utc(from_date)[0])
    if to_date is not None:
        stmt = stmt.where(Order.placed_at < local_day_bounds_utc(to_date)[1])
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(Order.id.desc()).offset(skip).limit(limit)))
    return total, rows


# ------------------------------------------------------- customer cancellation
def cancel_order(db: Session, customer: User, order_id: int, reason: Optional[str]) -> Order:
    """Free cancellation, allowed only while the order is still ``Placed``."""
    with transaction(db):
        order = lock_order(db, order_id)
        if order is None or order.customer_id != customer.id:
            raise NotFoundError("Order not found")
        if order.status != OrderStatus.PLACED.value:
            raise BadRequestError("Orders can only be cancelled while they are in 'Placed' status")
        record_status(db, order, OrderStatus.CANCELLED, actor(customer), reason)
        order.cancellation_reason = reason
        order.cancelled_at = utcnow()
        refund_and_release(db, order)
    return order


def reorder(db: Session, customer: User, order_id: int) -> ReorderOut:
    """Copy the still-available items of a past order into the cart (no coupon re-applied)."""
    order = db.get(Order, order_id)
    if order is None or order.customer_id != customer.id:
        raise NotFoundError("Order not found")
    added: List[str] = []
    skipped: List[str] = []
    with transaction(db):
        cart = cart_service.get_or_create_cart(db, customer, for_update=True)
        if cart.items and cart.restaurant_id != order.restaurant_id:
            raise ConflictError(CART_CONFLICT_MESSAGE)
        restaurant = db.get(Restaurant, order.restaurant_id)
        if restaurant is None or not restaurant.is_active:
            raise BadRequestError("Restaurant is not available")
        for oi in order.items:
            mi = db.get(MenuItem, oi.menu_item_id) if oi.menu_item_id else None
            if mi is None or mi.is_deleted or not mi.is_available:
                skipped.append(oi.name)
                continue
            existing = next((ci for ci in cart.items if ci.menu_item_id == mi.id), None)
            if existing is not None:
                existing.quantity = min(MAX_ITEM_QUANTITY, existing.quantity + oi.quantity)
            else:
                cart.items.append(CartItem(menu_item_id=mi.id, quantity=min(MAX_ITEM_QUANTITY, oi.quantity)))
            added.append(oi.name)
        if not added:
            raise BadRequestError("None of the items from this order are currently available")
        cart.restaurant_id = order.restaurant_id
        db.flush()
    cart_out: CartOut = cart_service.build_cart_out(db, customer, cart)
    return ReorderOut(cart=cart_out, added_items=added, skipped_items=skipped)


# ------------------------------------------------------------ restaurant side
def get_owned_order(db: Session, owner: User, order_id: int, lock: bool = True) -> Order:
    """Order belonging to one of the owner's restaurants (403 if it belongs to someone else)."""
    order = lock_order(db, order_id) if lock else db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    restaurant = db.get(Restaurant, order.restaurant_id)
    if restaurant is None or restaurant.owner_id != owner.id:
        raise ForbiddenError("This order does not belong to your restaurant")
    return order


def accept_order(db: Session, owner: User, order_id: int, preparation_minutes: int) -> Order:
    """Accept a placed order, set the preparation time and start delivery-partner assignment."""
    with transaction(db):
        order = get_owned_order(db, owner, order_id)
        record_status(db, order, OrderStatus.ACCEPTED, actor(owner), f"Preparation time {preparation_minutes} min")
        order.preparation_minutes = preparation_minutes
        order.accepted_at = utcnow()
        db.flush()
        assignment_service.start_assignment(db, order)
    return order


def reject_order(db: Session, owner: User, order_id: int, reason: str) -> Order:
    with transaction(db):
        order = get_owned_order(db, owner, order_id)
        record_status(db, order, OrderStatus.REJECTED, actor(owner), reason)
        order.rejection_reason = reason
        refund_and_release(db, order)
    return order


def mark_preparing(db: Session, owner: User, order_id: int) -> Order:
    with transaction(db):
        order = get_owned_order(db, owner, order_id)
        record_status(db, order, OrderStatus.PREPARING, actor(owner))
    return order


def mark_ready(db: Session, owner: User, order_id: int) -> Order:
    with transaction(db):
        order = get_owned_order(db, owner, order_id)
        record_status(db, order, OrderStatus.READY_FOR_PICKUP, actor(owner))
        order.ready_at = utcnow()
        if order.partner_id is not None:
            queue_event(
                db,
                partner_channel(order.partner_id),
                {"type": "order_ready", "order_id": order.id, "order_number": order.order_number},
            )
    return order


# -------------------------------------------------------------- scheduled job
def auto_reject_stale_orders(db: Session) -> int:
    """Reject orders still ``Placed`` after 5 minutes (restaurant did not respond)."""
    cutoff = utcnow() - timedelta(minutes=AUTO_REJECT_AFTER_MINUTES)
    with transaction(db):
        orders = db.scalars(
            select(Order)
            .where(Order.status == OrderStatus.PLACED.value, Order.placed_at < cutoff)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
        for order in orders:
            record_status(db, order, OrderStatus.REJECTED, "System", AUTO_REJECT_REASON)
            order.rejection_reason = AUTO_REJECT_REASON
            refund_and_release(db, order)
            queue_event(
                db,
                order_channel(order.id),
                {
                    "type": "order_auto_rejected",
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "reason": AUTO_REJECT_REASON,
                    "refunded": order.payment_status == PaymentStatus.REFUNDED.value,
                },
            )
    return len(orders)
