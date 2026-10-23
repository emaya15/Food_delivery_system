"""Delivery partner endpoints (Level 9)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import pagination, require_approved_partner, require_partner
from app.models.delivery import DeliveryOffer
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.common import Page
from app.schemas.delivery import (
    AvailabilityRequest,
    EarningsOut,
    LocationRequest,
    OfferOut,
    PartnerStatusOut,
)
from app.schemas.order import DeliverRequest, OrderOut
from app.services import assignment_service, delivery_service, order_service
from app.utils.pagination import PageParams
from app.utils.timeutils import ensure_aware, utcnow

router = APIRouter(tags=["Delivery"])


def _status(profile) -> PartnerStatusOut:
    return PartnerStatusOut(
        user_id=profile.user_id,
        is_online=profile.is_online,
        latitude=profile.latitude,
        longitude=profile.longitude,
        last_location_at=profile.last_location_at,
    )


def _offer_out(db: Session, offer: DeliveryOffer) -> OfferOut:
    order = db.get(Order, offer.order_id)
    restaurant = db.get(Restaurant, order.restaurant_id)
    remaining = max(0, int((ensure_aware(offer.expires_at) - utcnow()).total_seconds()))
    return OfferOut(
        id=offer.id,
        order_id=order.id,
        order_number=order.order_number,
        restaurant_name=restaurant.name,
        pickup_distance_km=offer.pickup_distance_km,
        delivery_distance_km=offer.delivery_distance_km,
        expected_earning=offer.expected_earning,
        status=offer.status,
        expires_at=offer.expires_at,
        seconds_remaining=remaining if offer.status == "Pending" else 0,
    )


@router.put("/partners/me/availability", response_model=PartnerStatusOut)
def availability(data: AvailabilityRequest, partner: User = Depends(require_approved_partner), db: Session = Depends(get_db)):
    return _status(delivery_service.set_availability(db, partner, data.is_online))


@router.put("/partners/me/location", response_model=PartnerStatusOut)
def location(data: LocationRequest, partner: User = Depends(require_partner), db: Session = Depends(get_db)):
    """Update position (call every 5-10 s). Broadcasts to the customer of any active delivery."""
    return _status(delivery_service.update_location(db, partner, data.latitude, data.longitude))


@router.get("/partners/me/offers", response_model=Page[OfferOut])
def offers(
    include_all: bool = Query(False, description="Include answered/expired offers"),
    page: PageParams = Depends(pagination),
    partner: User = Depends(require_partner),
    db: Session = Depends(get_db),
):
    total, rows = assignment_service.list_partner_offers(db, partner, page.skip, page.limit, include_all)
    return Page(total=total, skip=page.skip, limit=page.limit, items=[_offer_out(db, o) for o in rows])


@router.put("/offers/{offer_id}/accept", response_model=OrderOut)
def accept_offer(offer_id: int, partner: User = Depends(require_approved_partner), db: Session = Depends(get_db)):
    order = assignment_service.accept_offer(db, partner, offer_id)
    return order_service.build_order_out(order, partner)


@router.put("/offers/{offer_id}/decline", response_model=OfferOut)
def decline_offer(offer_id: int, partner: User = Depends(require_approved_partner), db: Session = Depends(get_db)):
    return _offer_out(db, assignment_service.decline_offer(db, partner, offer_id))


@router.put("/orders/{order_id}/pickup", response_model=OrderOut)
def pickup(order_id: int, partner: User = Depends(require_approved_partner), db: Session = Depends(get_db)):
    return order_service.build_order_out(delivery_service.pickup(db, partner, order_id), partner)


@router.put("/orders/{order_id}/out-for-delivery", response_model=OrderOut)
def out_for_delivery(order_id: int, partner: User = Depends(require_approved_partner), db: Session = Depends(get_db)):
    return order_service.build_order_out(delivery_service.out_for_delivery(db, partner, order_id), partner)


@router.put("/orders/{order_id}/deliver", response_model=OrderOut)
def deliver(
    order_id: int, data: DeliverRequest, partner: User = Depends(require_approved_partner), db: Session = Depends(get_db)
):
    """Complete delivery with the customer's 4-digit OTP (400 on a wrong OTP; locked after 3 failures)."""
    return order_service.build_order_out(delivery_service.deliver(db, partner, order_id, data.otp), partner)


@router.get("/partners/me/earnings", response_model=EarningsOut)
def earnings(
    from_date: Optional[date] = Query(None, description="Defaults to today"),
    to_date: Optional[date] = Query(None, description="Defaults to from_date"),
    partner: User = Depends(require_partner),
    db: Session = Depends(get_db),
):
    """Earnings = 25 base + 6/km + tip per delivery. No dates -> today."""
    return delivery_service.earnings_summary(db, partner, from_date, to_date)
