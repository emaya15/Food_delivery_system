"""Order schemas."""
import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.enums import PaymentMethod
from app.schemas.cart import CartOut
from app.schemas.common import Money, ORMModel


class OrderCreate(BaseModel):
    address_id: int
    payment_method: PaymentMethod
    tip: float = Field(default=0, ge=0, le=10000)
    scheduled_for: Optional[datetime] = None


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


class AcceptRequest(BaseModel):
    preparation_minutes: int = Field(ge=1, le=240)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=255)

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("reason must be at least 3 characters")
        return v


class DeliverRequest(BaseModel):
    otp: str = Field(min_length=4, max_length=4)

    @field_validator("otp")
    @classmethod
    def _four_digits(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("otp must be exactly 4 digits")
        return v


class OrderItemOut(ORMModel):
    id: int
    menu_item_id: Optional[int] = None
    name: str
    unit_price: Money
    packaging_charge: Money
    quantity: int
    line_total: Money


class StatusHistoryOut(ORMModel):
    id: int
    from_status: Optional[str] = None
    to_status: str
    changed_by: str
    note: Optional[str] = None
    created_at: datetime


class OrderOut(ORMModel):
    id: int
    order_number: str
    customer_id: int
    restaurant_id: int
    restaurant_name: Optional[str] = None
    partner_id: Optional[int] = None
    status: str
    payment_method: str
    payment_status: str
    delivery_address_line: str
    delivery_city: str
    delivery_pincode: str
    delivery_latitude: float
    delivery_longitude: float
    distance_km: Money
    item_total: Money
    discount: Money
    packaging_charges: Money
    delivery_fee: Money
    platform_fee: Money
    gst: Money
    tip: Money
    grand_total: Money
    surge_applied: bool
    coupon_code: Optional[str] = None
    # Only populated for the order's customer.
    delivery_otp: Optional[str] = None
    otp_locked: bool = False
    preparation_minutes: Optional[int] = None
    rejection_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    placed_at: datetime
    accepted_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    items: List[OrderItemOut] = []
    status_history: List[StatusHistoryOut] = []


class ReorderOut(BaseModel):
    cart: CartOut
    added_items: List[str]
    skipped_items: List[str]
