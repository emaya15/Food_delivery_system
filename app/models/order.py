"""Order, order items, status history and order-number sequence models."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, Numeric, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import CreatedAtMixin, TimestampMixin
from app.models.restaurant import Restaurant
from app.models.types import UTCDateTime
from app.models.user import User
from app.utils.timeutils import utcnow

_MONEY = Numeric(10, 2)


def _money_col(**kw):
    return mapped_column(_MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00", **kw)


class Order(TimestampMixin, Base):
    """A customer order with a price snapshot and a full billing breakdown."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        Index("ix_orders_restaurant_status", "restaurant_id", "status"),
        Index("ix_orders_status_placed_at", "status", "placed_at"),
        Index("ix_orders_partner_status", "partner_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    partner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    address_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )

    # Snapshot of the delivery address (the saved address may change later).
    delivery_address_line: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_city: Mapped[str] = mapped_column(String(100), nullable=False)
    delivery_pincode: Mapped[str] = mapped_column(String(6), nullable=False)
    delivery_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=Decimal("0.00"))

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Placed")
    payment_method: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(10), nullable=False, default="Pending")

    item_total: Mapped[Decimal] = _money_col()
    discount: Mapped[Decimal] = _money_col()
    packaging_charges: Mapped[Decimal] = _money_col()
    delivery_fee: Mapped[Decimal] = _money_col()
    platform_fee: Mapped[Decimal] = _money_col()
    gst: Mapped[Decimal] = _money_col()
    tip: Mapped[Decimal] = _money_col()
    grand_total: Mapped[Decimal] = _money_col()
    surge_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    coupon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("coupons.id"), nullable=True)
    coupon_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    delivery_otp: Mapped[str] = mapped_column(String(4), nullable=False)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    otp_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    preparation_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    unassigned_alert_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    partner_earning: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    placed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    ready_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    history: Mapped[List["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderStatusHistory.id"
    )
    restaurant: Mapped[Restaurant] = relationship()
    customer: Mapped[User] = relationship(foreign_keys=[customer_id])
    partner: Mapped[Optional[User]] = relationship(foreign_keys=[partner_id])


class OrderItem(TimestampMixin, Base):
    """Snapshot of an ordered item (name and price at order time)."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    menu_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("menu_items.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    packaging_charge: Mapped[Decimal] = _money_col()
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusHistory(CreatedAtMixin, Base):
    """Immutable audit trail of every status change."""

    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(60), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    order: Mapped[Order] = relationship(back_populates="history")


class OrderSequence(TimestampMixin, Base):
    """Per-day counter used to build ``ORD-YYYYMMDD-NNNN`` numbers (row-locked)."""

    __tablename__ = "order_sequences"

    seq_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
