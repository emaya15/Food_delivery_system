"""Restaurant, menu category and menu item models."""
from datetime import datetime, time
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin
from app.models.types import UTCDateTime
from app.utils.timeutils import local_now


class Restaurant(TimestampMixin, Base):
    """A restaurant owned by an approved Restaurant Owner."""

    __tablename__ = "restaurants"
    __table_args__ = (Index("ix_restaurants_lat_lng", "latitude", "longitude"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    cuisine_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    opening_time: Mapped[time] = mapped_column(Time, nullable=False)
    closing_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_temporarily_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    delivery_radius_km: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.00"), server_default="5.00"
    )
    min_order_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    avg_preparation_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    average_rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    categories: Mapped[List["MenuCategory"]] = relationship(back_populates="restaurant")
    menu_items: Mapped[List["MenuItem"]] = relationship(back_populates="restaurant")

    def is_open_at(self, local_time: time) -> bool:
        """Open only inside opening hours, while active and not temporarily closed."""
        if not self.is_active or self.is_temporarily_closed:
            return False
        return self.opening_time <= local_time <= self.closing_time

    @property
    def is_open(self) -> bool:
        """Whether the restaurant is open right now (business timezone)."""
        return self.is_open_at(local_now().time().replace(tzinfo=None))


class MenuCategory(TimestampMixin, Base):
    """A grouping of menu items (Starters, Mains, ...)."""

    __tablename__ = "menu_categories"
    __table_args__ = (UniqueConstraint("restaurant_id", "name", name="uq_menu_categories_restaurant_id_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="categories")
    items: Mapped[List["MenuItem"]] = relationship(back_populates="category")


class MenuItem(TimestampMixin, Base):
    """A dish. Deletion is soft (``is_deleted``) so historical orders remain intact."""

    __tablename__ = "menu_items"
    __table_args__ = (Index("ix_menu_items_restaurant_deleted", "restaurant_id", "is_deleted"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("menu_categories.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    packaging_charge: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="menu_items")
    category: Mapped[MenuCategory] = relationship(back_populates="items")
