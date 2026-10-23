"""Coupon and coupon-usage models."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin
from app.models.types import UTCDateTime


class Coupon(TimestampMixin, Base):
    """A discount coupon. ``restaurant_id`` NULL means platform-wide.

    Codes are stored upper-case; lookups are case-insensitive.
    """

    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("discount_value > 0", name="discount_positive"),
        CheckConstraint("valid_until > valid_from", name="valid_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    restaurant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("restaurants.id"), nullable=True, index=True)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_discount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    min_order_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    usage_limit_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usage_limit_per_user: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    first_order_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class CouponUsage(TimestampMixin, Base):
    """One row per order that consumed a coupon. Released on cancel/reject."""

    __tablename__ = "coupon_usages"
    __table_args__ = (Index("ix_coupon_usages_coupon_user", "coupon_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, unique=True)
    is_released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    released_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
