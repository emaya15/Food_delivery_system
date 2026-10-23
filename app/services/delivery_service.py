"""Delivery partner operations: availability, live location, pickup, OTP delivery, earnings."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import transaction
from app.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import DeliveryPartnerProfile, User
from app.schemas.delivery import EarningsDay, EarningsOut
from app.services import assignment_service, billing
from app.services.notification_service import notify_admins
from app.services.order_service import actor, lock_order, record_status
from app.utils.constants import MAX_OTP_ATTEMPTS, PARTNER_BASE_EARNING, PARTNER_EARNING_PER_KM
from app.utils.errors import BadRequestError, ForbiddenError, NotFoundError
from app.utils.geo import haversine_km, travel_minutes
from app.utils.money import ZERO, money, to_decimal
from app.utils.timeutils import local_day_bounds_utc, local_range_bounds_utc, local_today, to_local, utcnow
from app.websockets.manager import order_channel, partner_channel, queue_event, restaurant_channel


def _profile(db: Session, partner: User, lock: bool = False) -> DeliveryPartnerProfile:
    stmt = select(DeliveryPartnerProfile).where(DeliveryPartnerProfile.user_id == partner.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    profile = db.scalar(stmt)
    if profile is None:
        raise NotFoundError("Delivery partner profile not found")
    return profile


def set_availability(db: Session, partner: User, is_online: bool) -> DeliveryPartnerProfile:
    """Go online/offline. Going online needs admin approval and a known location."""
    with transaction(db):
        profile = _profile(db, partner, lock=True)
        if is_online:
            if not partner.is_approved:
                raise ForbiddenError("Your account is pending admin approval")
            if profile.latitude is None or profile.longitude is None:
                raise BadRequestError("Update your location before going online")
            profile.last_seen_at = utcnow()
        elif assignment_service.has_active_delivery(db, partner.id):
            raise BadRequestError("Finish your active delivery before going offline")
        profile.is_online = is_online
        db.flush()
    return profile


def update_location(db: Session, partner: User, latitude: float, longitude: float) -> DeliveryPartnerProfile:
    """Store the partner's position and broadcast it to the customer of any active delivery."""
    with transaction(db):
        profile = _profile(db, partner, lock=True)
        now = utcnow()
        profile.latitude = latitude
        profile.longitude = longitude
        profile.last_location_at = now
        profile.last_seen_at = now
        db.flush()

        active = db.scalars(
            select(Order).where(
                Order.partner_id == partner.id,
                Order.status.in_(
                    [OrderStatus.ACCEPTED.value, OrderStatus.PREPARING.value, OrderStatus.READY_FOR_PICKUP.value,
                     OrderStatus.PICKED_UP.value, OrderStatus.OUT_FOR_DELIVERY.value]
                ),
            )
        ).all()
        for order in active:
            if order.status in (OrderStatus.PICKED_UP.value, OrderStatus.OUT_FOR_DELIVERY.value):
                target_lat, target_lng = order.delivery_latitude, order.delivery_longitude
            else:
                restaurant = db.get(Restaurant, order.restaurant_id)
                target_lat, target_lng = restaurant.latitude, restaurant.longitude
            remaining = haversine_km(latitude, longitude, target_lat, target_lng)
            eta = travel_minutes(remaining)
            queue_event(
                db,
                order_channel(order.id),
                {
                    "type": "partner_location",
                    "order_id": order.id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "remaining_distance_km": round(remaining, 2),
                    "estimated_arrival_minutes": eta,
                    "timestamp": now.isoformat(),
                },
            )
    return profile


def _get_assigned_order(db: Session, partner: User, order_id: int) -> Order:
    order = lock_order(db, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.partner_id != partner.id:
        raise ForbiddenError("This order is not assigned to you")
    return order


def pickup(db: Session, partner: User, order_id: int) -> Order:
    """Only the assigned partner may collect, and only once the order is Ready for Pickup."""
    with transaction(db):
        order = _get_assigned_order(db, partner, order_id)
        if order.status != OrderStatus.READY_FOR_PICKUP.value:
            raise BadRequestError("Order is not ready for pickup")
        record_status(db, order, OrderStatus.PICKED_UP, actor(partner))
        order.picked_up_at = utcnow()
    return order


def out_for_delivery(db: Session, partner: User, order_id: int) -> Order:
    with transaction(db):
        order = _get_assigned_order(db, partner, order_id)
        record_status(db, order, OrderStatus.OUT_FOR_DELIVERY, actor(partner))
    return order


def deliver(db: Session, partner: User, order_id: int, otp: str) -> Order:
    """Complete delivery with the customer's 4-digit OTP.

    Wrong OTP -> HTTP 400 (attempt recorded and *persisted*). After three wrong
    attempts delivery completion is locked and admins are notified.
    """
    outcome: Optional[str] = None
    with transaction(db):
        order = _get_assigned_order(db, partner, order_id)
        if order.status != OrderStatus.OUT_FOR_DELIVERY.value:
            raise BadRequestError("Order must be 'Out for Delivery' before it can be delivered")
        if order.otp_locked:
            raise ForbiddenError("Delivery completion is locked after too many incorrect OTP attempts; contact support")
        if otp != order.delivery_otp:
            order.otp_attempts += 1
            remaining = MAX_OTP_ATTEMPTS - order.otp_attempts
            if order.otp_attempts >= MAX_OTP_ATTEMPTS:
                order.otp_locked = True
                notify_admins(
                    db,
                    "otp_locked",
                    f"Delivery OTP locked for order {order.order_number} after {MAX_OTP_ATTEMPTS} incorrect attempts",
                    order.id,
                )
                outcome = "Incorrect OTP. Delivery completion is now locked and an admin has been notified"
            else:
                outcome = f"Incorrect OTP. {remaining} attempt(s) remaining"
        else:
            now = utcnow()
            record_status(db, order, OrderStatus.DELIVERED, actor(partner))
            order.delivered_at = now
            order.partner_earning = billing.calculate_partner_earning(order.distance_km, order.tip)
            if order.payment_method == PaymentMethod.COD.value:
                order.payment_status = PaymentStatus.PAID.value
            db.flush()
    # The failed-attempt counter has been committed by the context manager above.
    if outcome is not None:
        raise BadRequestError(outcome)
    return order


# ------------------------------------------------------------------ earnings
def earnings_summary(
    db: Session, partner: User, from_date: Optional[date] = None, to_date: Optional[date] = None
) -> EarningsOut:
    """Earnings (25 base + 6/km + tip per delivery) for a date range; defaults to today."""
    from_date = from_date or local_today()
    to_date = to_date or from_date
    if to_date < from_date:
        raise BadRequestError("to_date must not be before from_date")
    start, end = local_range_bounds_utc(from_date, to_date)
    orders = db.scalars(
        select(Order).where(
            Order.partner_id == partner.id,
            Order.status == OrderStatus.DELIVERED.value,
            Order.delivered_at >= start,
            Order.delivered_at < end,
        )
    ).all()
    per_day: dict = {}
    base = distance_earn = tips = distance_total = ZERO
    for order in orders:
        day = to_local(order.delivered_at).date()
        d = per_day.setdefault(day, {"n": 0, "km": ZERO, "earn": ZERO})
        earning = order.partner_earning if order.partner_earning is not None else billing.calculate_partner_earning(
            order.distance_km, order.tip
        )
        d["n"] += 1
        d["km"] += to_decimal(order.distance_km)
        d["earn"] += to_decimal(earning)
        base += PARTNER_BASE_EARNING
        distance_earn += PARTNER_EARNING_PER_KM * to_decimal(order.distance_km)
        tips += to_decimal(order.tip)
        distance_total += to_decimal(order.distance_km)
    daily = [
        EarningsDay(date=day, deliveries=v["n"], distance_km=money(v["km"]), earnings=money(v["earn"]))
        for day, v in sorted(per_day.items())
    ]
    return EarningsOut(
        partner_id=partner.id,
        from_date=from_date,
        to_date=to_date,
        completed_deliveries=len(orders),
        total_distance_km=money(distance_total),
        base_earnings=money(base),
        distance_earnings=money(distance_earn),
        tips=money(tips),
        total_earnings=money(base + distance_earn + tips),
        daily=daily,
    )


def set_offline_if_stale(db: Session, minutes: int) -> int:
    """Scheduled job: partners with no location update for ``minutes`` go Offline (never mid-delivery)."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(minutes=minutes)
    changed = 0
    with transaction(db):
        profiles = db.scalars(
            select(DeliveryPartnerProfile)
            .where(
                DeliveryPartnerProfile.is_online.is_(True),
                (DeliveryPartnerProfile.last_location_at.is_(None) & (DeliveryPartnerProfile.last_seen_at < cutoff))
                | (DeliveryPartnerProfile.last_location_at < cutoff),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
        for profile in profiles:
            if assignment_service.has_active_delivery(db, profile.user_id):
                continue
            profile.is_online = False
            changed += 1
            queue_event(db, partner_channel(profile.user_id), {"type": "set_offline", "reason": "No location update"})
    return changed
