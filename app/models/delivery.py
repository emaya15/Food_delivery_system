"""Delivery offers, ratings and admin notifications."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin
from app.models.order import Order
from app.models.types import UTCDateTime


class DeliveryOffer(TimestampMixin, Base):
    """A time-limited offer of an order to one delivery partner."""

    __tablename__ = "delivery_offers"
    __table_args__ = (
        UniqueConstraint("order_id", "partner_id", name="uq_delivery_offers_order_id_partner_id"),
        Index("ix_delivery_offers_status_expires", "status", "expires_at"),
        Index("ix_delivery_offers_partner_status", "partner_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Pending")
    pickup_distance_km: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    delivery_distance_km: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    expected_earning: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    offered_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    responded_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    order: Mapped[Order] = relationship()


class Rating(TimestampMixin, Base):
    """Customer rating of the restaurant (and optionally the delivery partner)."""

    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint("restaurant_rating BETWEEN 1 AND 5", name="restaurant_rating_range"),
        CheckConstraint("partner_rating IS NULL OR partner_rating BETWEEN 1 AND 5", name="partner_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False, index=True)
    partner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    restaurant_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    partner_rating: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class AdminNotification(TimestampMixin, Base):
    """Persistent notification for administrators (unassigned order, OTP lock, ...)."""

    __tablename__ = "admin_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
