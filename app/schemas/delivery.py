"""Delivery partner, rating and notification schemas."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import Money, ORMModel


class AvailabilityRequest(BaseModel):
    is_online: bool


class LocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class PartnerStatusOut(BaseModel):
    user_id: int
    is_online: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_location_at: Optional[datetime] = None


class OfferOut(BaseModel):
    id: int
    order_id: int
    order_number: str
    restaurant_name: str
    pickup_distance_km: Money
    delivery_distance_km: Money
    expected_earning: Money
    status: str
    expires_at: datetime
    seconds_remaining: int


class EarningsDay(BaseModel):
    date: date
    deliveries: int
    distance_km: Money
    earnings: Money


class EarningsOut(BaseModel):
    partner_id: int
    from_date: date
    to_date: date
    completed_deliveries: int
    total_distance_km: Money
    base_earnings: Money
    distance_earnings: Money
    tips: Money
    total_earnings: Money
    daily: List[EarningsDay]


class RatingCreate(BaseModel):
    restaurant_rating: int = Field(ge=1, le=5)
    partner_rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)


class RatingOut(ORMModel):
    id: int
    order_id: int
    restaurant_id: int
    partner_id: Optional[int] = None
    restaurant_rating: int
    partner_rating: Optional[int] = None
    comment: Optional[str] = None
    created_at: datetime


class RestaurantRatingsOut(BaseModel):
    restaurant_id: int
    average_rating: Money
    rating_count: int
    total: int
    skip: int
    limit: int
    items: List[RatingOut]


class NotificationOut(ORMModel):
    id: int
    type: str
    message: str
    order_id: Optional[int] = None
    is_read: bool
    created_at: datetime
