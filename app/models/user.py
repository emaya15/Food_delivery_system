"""User and delivery-partner profile models."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Numeric, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin
from app.models.types import UTCDateTime


class User(TimestampMixin, Base):
    """A platform account: Admin, Restaurant Owner, Delivery Partner or Customer."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(10), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    partner_profile: Mapped[Optional["DeliveryPartnerProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class DeliveryPartnerProfile(TimestampMixin, Base):
    """Vehicle, availability and live location of a delivery partner."""

    __tablename__ = "delivery_partner_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    vehicle_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_location_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    average_rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    user: Mapped[User] = relationship(back_populates="partner_profile")
