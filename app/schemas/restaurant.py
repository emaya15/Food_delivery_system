"""Restaurant, menu and address schemas."""
from datetime import datetime, time
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.schemas.common import Money, ORMModel, validate_pincode

Latitude = Field(ge=-90, le=90)
Longitude = Field(ge=-180, le=180)


class RestaurantBase(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    cuisine_type: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=3, max_length=255)
    latitude: float = Latitude
    longitude: float = Longitude
    opening_time: time
    closing_time: time
    delivery_radius_km: Decimal = Field(default=Decimal("5"), gt=0, le=50, max_digits=5, decimal_places=2)
    min_order_value: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    avg_preparation_minutes: int = Field(default=20, ge=1, le=240)

    @model_validator(mode="after")
    def _opening_before_closing(self) -> "RestaurantBase":
        if self.opening_time >= self.closing_time:
            raise ValueError("opening_time must be before closing_time")
        return self


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantUpdate(BaseModel):
    """Partial update; cross-field validation is repeated in the service on merged values."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    cuisine_type: Optional[str] = Field(default=None, min_length=2, max_length=80)
    address: Optional[str] = Field(default=None, min_length=3, max_length=255)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    opening_time: Optional[time] = None
    closing_time: Optional[time] = None
    delivery_radius_km: Optional[Decimal] = Field(default=None, gt=0, le=50, max_digits=5, decimal_places=2)
    min_order_value: Optional[Decimal] = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    avg_preparation_minutes: Optional[int] = Field(default=None, ge=1, le=240)
    is_active: Optional[bool] = None


class OpenStatusUpdate(BaseModel):
    is_temporarily_closed: bool


class RestaurantOut(ORMModel):
    id: int
    owner_id: int
    name: str
    cuisine_type: str
    address: str
    latitude: float
    longitude: float
    opening_time: time
    closing_time: time
    is_temporarily_closed: bool
    delivery_radius_km: Money
    min_order_value: Money
    avg_preparation_minutes: int
    average_rating: Money
    rating_count: int
    is_active: bool
    is_open: bool
    created_at: datetime


class NearbyRestaurantOut(RestaurantOut):
    distance_km: float
    estimated_delivery_minutes: int
    has_active_coupon: bool = False


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class CategoryOut(ORMModel):
    id: int
    restaurant_id: int
    name: str


class MenuItemBase(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_veg: bool = True
    packaging_charge: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    is_available: bool = True


class MenuItemCreate(MenuItemBase):
    category_id: int


class MenuItemUpdate(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    description: Optional[str] = Field(default=None, max_length=2000)
    price: Optional[Decimal] = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    is_veg: Optional[bool] = None
    packaging_charge: Optional[Decimal] = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class AvailabilityUpdate(BaseModel):
    is_available: bool


class MenuItemOut(ORMModel):
    id: int
    restaurant_id: int
    category_id: int
    name: str
    description: Optional[str] = None
    price: Money
    is_veg: bool
    packaging_charge: Money
    is_available: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def availability(self) -> str:
        """Human readable marker so unavailable items are clearly flagged."""
        return "Available" if self.is_available else "Unavailable"


class MenuCategoryGroup(BaseModel):
    category_id: int
    category_name: str
    items: List[MenuItemOut]


class MenuOut(BaseModel):
    restaurant_id: int
    restaurant_name: str
    is_open: bool
    categories: List[MenuCategoryGroup]


# ----------------------------------------------------------------- addresses
class AddressBase(BaseModel):
    label: Literal["Home", "Work", "Other"]
    address_line: str = Field(min_length=3, max_length=255)
    city: str = Field(min_length=2, max_length=100)
    pincode: str
    latitude: float = Latitude
    longitude: float = Longitude

    @field_validator("pincode")
    @classmethod
    def _pincode(cls, v: str) -> str:
        return validate_pincode(v)


class AddressCreate(AddressBase):
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: Optional[Literal["Home", "Work", "Other"]] = None
    address_line: Optional[str] = Field(default=None, min_length=3, max_length=255)
    city: Optional[str] = Field(default=None, min_length=2, max_length=100)
    pincode: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @field_validator("pincode")
    @classmethod
    def _pincode(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else validate_pincode(v)


class AddressOut(ORMModel):
    id: int
    customer_id: int
    label: str
    address_line: str
    city: str
    pincode: str
    latitude: float
    longitude: float
    is_default: bool
