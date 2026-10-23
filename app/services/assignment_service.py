"""Delivery partner matching and offer lifecycle.

Flow: restaurant accepts -> ``start_assignment`` offers the order to the nearest
eligible partner (30 s to respond) -> on decline/expiry the next-nearest partner
is offered -> ``retry_unassigned`` (every minute) keeps trying and alerts admins
after 15 minutes without a partner.
"""
from datetime import timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import transaction
from app.enums import ACTIVE_DELIVERY_STATUSES, ASSIGNABLE_STATUSES, OfferStatus, Role
from app.models.delivery import DeliveryOffer
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import DeliveryPartnerProfile, User
from app.services import billing
from app.services.notification_service import notify_admins
from app.utils.constants import (
    OFFER_TTL_SECONDS,
    PARTNER_SEARCH_RADIUS_KM,
    UNASSIGNED_ADMIN_ALERT_MINUTES,
)
from app.utils.errors import BadRequestError, ConflictError, NotFoundError
from app.utils.geo import haversine_km
from app.utils.money import money
from app.websockets.manager import order_channel, partner_channel, queue_event, restaurant_channel
from app.utils.timeutils import ensure_aware, utcnow

_ACTIVE_VALUES = [s.value for s in ACTIVE_DELIVERY_STATUSES]
_ASSIGNABLE_VALUES = [s.value for s in ASSIGNABLE_STATUSES]


def lock_order(db: Session, order_id: int) -> Optional[Order]:
    """``SELECT ... FOR UPDATE`` on an order, refreshing any cached state."""
    return db.scalar(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    )


def has_active_delivery(db: Session, partner_id: int, exclude_order_id: Optional[int] = None) -> bool:
    """Whether the partner is currently handling an order (one active delivery at a time)."""
    stmt = select(Order.id).where(Order.partner_id == partner_id, Order.status.in_(_ACTIVE_VALUES))
    if exclude_order_id is not None:
        stmt = stmt.where(Order.id != exclude_order_id)
    return db.scalar(stmt.limit(1)) is not None


def find_eligible_partners(
    db: Session, order: Order, restaurant: Restaurant, now=None
) -> List[Tuple[User, DeliveryPartnerProfile, float]]:
    """Approved, online partners within 5 km of the restaurant with no active delivery.

    Partners who already received an offer for this order, or who currently hold
    a live offer for another order, are skipped. Result is sorted nearest-first.
    """
    now = now or utcnow()
    busy = select(Order.partner_id).where(Order.partner_id.is_not(None), Order.status.in_(_ACTIVE_VALUES))
    holding_offer = select(DeliveryOffer.partner_id).where(
        DeliveryOffer.status == OfferStatus.PENDING.value, DeliveryOffer.expires_at > now
    )
    already_offered = select(DeliveryOffer.partner_id).where(DeliveryOffer.order_id == order.id)

    stmt = (
        select(User, DeliveryPartnerProfile)
        .join(DeliveryPartnerProfile, DeliveryPartnerProfile.user_id == User.id)
        .where(
            User.role == Role.DELIVERY_PARTNER.value,
            User.is_active.is_(True),
            User.is_approved.is_(True),
            DeliveryPartnerProfile.is_online.is_(True),
            DeliveryPartnerProfile.latitude.is_not(None),
            DeliveryPartnerProfile.longitude.is_not(None),
            User.id.not_in(busy),
            User.id.not_in(holding_offer),
            User.id.not_in(already_offered),
        )
    )
    candidates: List[Tuple[User, DeliveryPartnerProfile, float]] = []
    for user, profile in db.execute(stmt).all():
        distance = haversine_km(profile.latitude, profile.longitude, restaurant.latitude, restaurant.longitude)
        if distance <= PARTNER_SEARCH_RADIUS_KM:
            candidates.append((user, profile, distance))
    candidates.sort(key=lambda c: (c[2], c[0].id))
    return candidates


def ready_for_assignment(order: Order, restaurant: Restaurant, now=None) -> bool:
    """Scheduled orders only look for a partner shortly before they are due."""
    now = now or utcnow()
    if order.scheduled_for is None:
        return True
    lead = timedelta(minutes=(order.preparation_minutes or restaurant.avg_preparation_minutes) + 30)
    return now >= ensure_aware(order.scheduled_for) - lead


def offer_to_next_partner(db: Session, order: Order) -> Optional[DeliveryOffer]:
    """Create an offer for the nearest eligible partner (no-op if a live offer exists)."""
    now = utcnow()
    if order.partner_id is not None or order.status not in _ASSIGNABLE_VALUES:
        return None
    live = db.scalar(
        select(DeliveryOffer).where(
            DeliveryOffer.order_id == order.id,
            DeliveryOffer.status == OfferStatus.PENDING.value,
            DeliveryOffer.expires_at > now,
        )
    )
    if live is not None:
        return live
    restaurant = db.get(Restaurant, order.restaurant_id)
    if restaurant is None or not ready_for_assignment(order, restaurant, now):
        return None
    candidates = find_eligible_partners(db, order, restaurant, now)
    if not candidates:
        return None
    partner, _profile, distance = candidates[0]
    earning = billing.calculate_partner_earning(order.distance_km, order.tip)
    offer = DeliveryOffer(
        order_id=order.id,
        partner_id=partner.id,
        status=OfferStatus.PENDING.value,
        pickup_distance_km=money(distance),
        delivery_distance_km=money(order.distance_km),
        expected_earning=earning,
        offered_at=now,
        expires_at=now + timedelta(seconds=OFFER_TTL_SECONDS),
    )
    db.add(offer)
    db.flush()
    queue_event(
        db,
        partner_channel(partner.id),
        {
            "type": "delivery_offer",
            "offer_id": offer.id,
            "order_id": order.id,
            "order_number": order.order_number,
            "restaurant_name": restaurant.name,
            "pickup_distance_km": float(offer.pickup_distance_km),
            "delivery_distance_km": float(offer.delivery_distance_km),
            "expected_earning": float(offer.expected_earning),
            "seconds_remaining": OFFER_TTL_SECONDS,
        },
    )
    return offer


def start_assignment(db: Session, order: Order) -> Optional[DeliveryOffer]:
    """Begin partner search right after the restaurant accepts (caller owns the transaction)."""
    return offer_to_next_partner(db, order)


def _lock_offer(db: Session, offer_id: int) -> Optional[DeliveryOffer]:
    return db.scalar(
        select(DeliveryOffer).where(DeliveryOffer.id == offer_id).with_for_update().execution_options(populate_existing=True)
    )


def accept_offer(db: Session, partner: User, offer_id: int) -> Order:
    """Accept an offer. Row locks on the offer, partner profile and order make this race-free."""
    with transaction(db):
        offer = _lock_offer(db, offer_id)
        if offer is None or offer.partner_id != partner.id:
            raise NotFoundError("Offer not found")
        db.scalar(
            select(DeliveryPartnerProfile.id)
            .where(DeliveryPartnerProfile.user_id == partner.id)
            .with_for_update()
        )
        order = lock_order(db, offer.order_id)
        now = utcnow()
        if offer.status != OfferStatus.PENDING.value:
            raise ConflictError("This offer is no longer available")
        if ensure_aware(offer.expires_at) <= now:
            raise BadRequestError("This offer has expired")
        if order is None or order.partner_id is not None:
            raise ConflictError("This order has already been assigned to another partner")
        if order.status not in _ASSIGNABLE_VALUES:
            raise ConflictError("This order is no longer available for delivery")
        if has_active_delivery(db, partner.id, exclude_order_id=order.id):
            raise ConflictError("You already have an active delivery")

        order.partner_id = partner.id
        offer.status = OfferStatus.ACCEPTED.value
        offer.responded_at = now
        others = db.scalars(
            select(DeliveryOffer).where(
                DeliveryOffer.order_id == order.id,
                DeliveryOffer.id != offer.id,
                DeliveryOffer.status == OfferStatus.PENDING.value,
            )
        ).all()
        for other in others:
            other.status = OfferStatus.EXPIRED.value
            other.responded_at = now
        db.flush()

        profile = partner.partner_profile
        payload = {
            "type": "partner_assigned",
            "order_id": order.id,
            "order_number": order.order_number,
            "partner": {
                "id": partner.id,
                "name": partner.name,
                "vehicle_number": profile.vehicle_number if profile else None,
            },
        }
        queue_event(db, order_channel(order.id), payload)
        restaurant = db.get(Restaurant, order.restaurant_id)
        if restaurant is not None:
            queue_event(db, restaurant_channel(restaurant.owner_id), payload)
    return order


def decline_offer(db: Session, partner: User, offer_id: int) -> DeliveryOffer:
    """Decline an offer and immediately offer the order to the next partner."""
    with transaction(db):
        offer = _lock_offer(db, offer_id)
        if offer is None or offer.partner_id != partner.id:
            raise NotFoundError("Offer not found")
        if offer.status != OfferStatus.PENDING.value:
            raise ConflictError("This offer is no longer pending")
        offer.status = OfferStatus.DECLINED.value
        offer.responded_at = utcnow()
        db.flush()
        order = lock_order(db, offer.order_id)
        if order is not None:
            offer_to_next_partner(db, order)
    return offer


def expire_offers(db: Session) -> int:
    """Scheduled job: expire offers past their 30 s window and offer to the next partner."""
    now = utcnow()
    with transaction(db):
        expired = db.scalars(
            select(DeliveryOffer)
            .where(DeliveryOffer.status == OfferStatus.PENDING.value, DeliveryOffer.expires_at <= now)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
        order_ids = []
        for offer in expired:
            offer.status = OfferStatus.EXPIRED.value
            offer.responded_at = now
            queue_event(db, partner_channel(offer.partner_id), {"type": "offer_expired", "offer_id": offer.id})
            if offer.order_id not in order_ids:
                order_ids.append(offer.order_id)
        db.flush()
        for order_id in order_ids:
            order = lock_order(db, order_id)
            if order is not None and order.partner_id is None:
                offer_to_next_partner(db, order)
    return len(expired)


def retry_unassigned(db: Session) -> int:
    """Scheduled job (every minute): keep offering unassigned orders; alert admins after 15 minutes.

    Returns the number of admin alerts raised.
    """
    now = utcnow()
    alerts = 0
    with transaction(db):
        orders = db.scalars(
            select(Order)
            .where(Order.status.in_(_ASSIGNABLE_VALUES), Order.partner_id.is_(None))
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
        for order in orders:
            restaurant = db.get(Restaurant, order.restaurant_id)
            if restaurant is None or not ready_for_assignment(order, restaurant, now):
                continue
            offer_to_next_partner(db, order)
            reference = ensure_aware(order.accepted_at or order.placed_at)
            if order.scheduled_for is not None:
                lead = timedelta(minutes=(order.preparation_minutes or restaurant.avg_preparation_minutes) + 30)
                reference = max(reference, ensure_aware(order.scheduled_for) - lead)
            if (
                not order.unassigned_alert_sent
                and now - reference >= timedelta(minutes=UNASSIGNED_ADMIN_ALERT_MINUTES)
            ):
                order.unassigned_alert_sent = True
                notify_admins(
                    db,
                    "order_unassigned",
                    f"Order {order.order_number} has had no delivery partner for "
                    f"{UNASSIGNED_ADMIN_ALERT_MINUTES}+ minutes",
                    order.id,
                )
                alerts += 1
    return alerts


def list_partner_offers(db: Session, partner: User, skip: int, limit: int, include_all: bool = False):
    """Offers addressed to the partner (live pending offers by default)."""
    from sqlalchemy import func

    now = utcnow()
    stmt = select(DeliveryOffer).where(DeliveryOffer.partner_id == partner.id)
    if not include_all:
        stmt = stmt.where(DeliveryOffer.status == OfferStatus.PENDING.value, DeliveryOffer.expires_at > now)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(DeliveryOffer.id.desc()).offset(skip).limit(limit)))
    return total, rows
