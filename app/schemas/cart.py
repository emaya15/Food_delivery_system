"""Cart and coupon schemas."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.enums import DiscountType
from app.schemas.common import Money, ORMModel
from app.utils.constants import MAX_ITEM_QUANTITY, MIN_ITEM_QUANTITY


class CartItemAdd(BaseModel):
    menu_item_id: int
    quantity: int = Field(default=1, ge=MIN_ITEM_QUANTITY, le=MAX_ITEM_QUANTITY)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=MIN_ITEM_QUANTITY, le=MAX_ITEM_QUANTITY)


class ApplyCouponRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)

    @field_validator("code")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().upper()


class CartItemOut(BaseModel):
    id: int
    menu_item_id: int
    name: str
    unit_price: Money
    packaging_charge: Money
    quantity: int
    line_total: Money
    is_available: bool


class CartOut(BaseModel):
    id: int
    restaurant_id: Optional[int] = None
    restaurant_name: Optional[str] = None
    items: List[CartItemOut]
    item_total: Money
    discount: Money
    total_after_discount: Money
    coupon_code: Optional[str] = None
    coupon_message: Optional[str] = None


# ------------------------------------------------------------------- coupons
class CouponBase(BaseModel):
    description: Optional[str] = Field(default=None, max_length=255)
    discount_type: DiscountType
    discount_value: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    max_discount: Optional[Decimal] = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    min_order_value: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    valid_from: datetime
    valid_until: datetime
    usage_limit_total: Optional[int] = Field(default=None, ge=1)
    usage_limit_per_user: Optional[int] = Field(default=None, ge=1)
    first_order_only: bool = False

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        """Naive datetimes are interpreted as UTC."""
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v

    @model_validator(mode="after")
    def _validate_rules(self) -> "CouponBase":
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.discount_type == DiscountType.PERCENTAGE and not (1 <= self.discount_value <= 100):
            raise ValueError("percentage discount_value must be between 1 and 100")
        return self


class CouponCreate(CouponBase):
    code: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_\-]+$")
    restaurant_id: Optional[int] = None

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class CouponUpdate(BaseModel):
    """Partial update (the code itself is immutable)."""

    description: Optional[str] = Field(default=None, max_length=255)
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    max_discount: Optional[Decimal] = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    min_order_value: Optional[Decimal] = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    usage_limit_total: Optional[int] = Field(default=None, ge=1)
    usage_limit_per_user: Optional[int] = Field(default=None, ge=1)
    first_order_only: Optional[bool] = None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _aware(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


class CouponOut(ORMModel):
    id: int
    code: str
    description: Optional[str] = None
    restaurant_id: Optional[int] = None
    discount_type: str
    discount_value: Money
    max_discount: Optional[Money] = None
    min_order_value: Money
    valid_from: datetime
    valid_until: datetime
    usage_limit_total: Optional[int] = None
    usage_limit_per_user: Optional[int] = None
    used_count: int
    first_order_only: bool
    is_active: bool


class CouponPreviewOut(CouponOut):
    """Coupon with an eligibility preview for the customer's current cart."""

    eligible: bool
    discount: Money
    reason: Optional[str] = None
