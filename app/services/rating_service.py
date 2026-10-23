"""Ratings for delivered orders; keeps restaurant / partner averages up to date."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import transaction
from app.enums import OrderStatus
from app.models.delivery import Rating
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.user import DeliveryPartnerProfile, User
from app.schemas.delivery import RatingCreate, RestaurantRatingsOut, RatingOut
from app.services.order_service import lock_order
from app.utils.errors import BadRequestError, ConflictError, NotFoundError

_TWO = Decimal("0.01")


def _avg(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_TWO, rounding=ROUND_HALF_UP)


def create_rating(db: Session, customer: User, order_id: int, data: RatingCreate) -> Rating:
    """Only the order's customer, only after delivery, once per order."""
    with transaction(db):
        order = lock_order(db, order_id)
        if order is None or order.customer_id != customer.id:
            raise NotFoundError("Order not found")
        if order.status != OrderStatus.DELIVERED.value:
            raise BadRequestError("You can rate an order only after it has been delivered")
        if db.scalar(select(Rating.id).where(Rating.order_id == order.id)):
            raise ConflictError("This order has already been rated")
        if data.partner_rating is not None and order.partner_id is None:
            raise BadRequestError("This order has no delivery partner to rate")
        rating = Rating(
            order_id=order.id,
            customer_id=customer.id,
            restaurant_id=order.restaurant_id,
            partner_id=order.partner_id if data.partner_rating is not None else None,
            restaurant_rating=data.restaurant_rating,
            partner_rating=data.partner_rating,
            comment=data.comment,
        )
        try:
            with db.begin_nested():
                db.add(rating)
                db.flush()
        except IntegrityError:
            raise ConflictError("This order has already been rated") from None

        # Recompute averages from the source rows (always consistent).
        restaurant = db.scalar(
            select(Restaurant).where(Restaurant.id == order.restaurant_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        avg, count = db.execute(
            select(func.avg(Rating.restaurant_rating), func.count(Rating.id)).where(
                Rating.restaurant_id == order.restaurant_id
            )
        ).one()
        restaurant.average_rating = _avg(avg)
        restaurant.rating_count = count or 0
        if rating.partner_id is not None:
            profile = db.scalar(
                select(DeliveryPartnerProfile)
                .where(DeliveryPartnerProfile.user_id == rating.partner_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            p_avg, p_count = db.execute(
                select(func.avg(Rating.partner_rating), func.count(Rating.partner_rating)).where(
                    Rating.partner_id == rating.partner_id, Rating.partner_rating.is_not(None)
                )
            ).one()
            if profile is not None:
                profile.average_rating = _avg(p_avg)
                profile.rating_count = p_count or 0
        db.flush()
    return rating


def list_restaurant_ratings(db: Session, restaurant_id: int, skip: int, limit: int) -> RestaurantRatingsOut:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant not found")
    total = db.scalar(select(func.count(Rating.id)).where(Rating.restaurant_id == restaurant_id)) or 0
    rows = db.scalars(
        select(Rating).where(Rating.restaurant_id == restaurant_id).order_by(Rating.id.desc()).offset(skip).limit(limit)
    ).all()
    return RestaurantRatingsOut(
        restaurant_id=restaurant_id,
        average_rating=restaurant.average_rating,
        rating_count=restaurant.rating_count,
        total=total,
        skip=skip,
        limit=limit,
        items=[RatingOut.model_validate(r) for r in rows],
    )
