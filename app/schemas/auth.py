"""Authentication / user schemas."""
import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.enums import Role
from app.schemas.common import EMAIL_PATTERN, ORMModel, validate_phone

VEHICLE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\- ]{2,18}[A-Z0-9]$")


class RegisterRequest(BaseModel):
    """Public registration payload (Admin role is never accepted)."""

    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=255)
    phone: str
    password: str = Field(min_length=8, max_length=72)
    role: Role = Role.CUSTOMER
    vehicle_number: Optional[str] = Field(default=None, max_length=20)
    vehicle_type: Optional[str] = Field(default=None, max_length=30)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("name must be at least 2 characters")
        return v

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_PATTERN.match(v):
            raise ValueError("invalid email address")
        return v

    @field_validator("phone")
    @classmethod
    def _valid_phone(cls, v: str) -> str:
        return validate_phone(v)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("password must contain at least one letter and one digit")
        return v

    @model_validator(mode="after")
    def _partner_fields(self) -> "RegisterRequest":
        if self.role == Role.DELIVERY_PARTNER:
            if not self.vehicle_number or not self.vehicle_type:
                raise ValueError("vehicle_number and vehicle_type are required for Delivery Partners")
            number = self.vehicle_number.strip().upper()
            if not VEHICLE_PATTERN.match(number):
                raise ValueError("invalid vehicle_number")
            self.vehicle_number = number
            self.vehicle_type = self.vehicle_type.strip()
        else:
            self.vehicle_number = None
            self.vehicle_type = None
        return self


class LoginRequest(BaseModel):
    """Login payload."""

    email: str
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def _norm_email(cls, v: str) -> str:
        return v.strip().lower()


class PartnerProfileOut(ORMModel):
    vehicle_number: str
    vehicle_type: str
    is_online: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    average_rating: float = 0
    rating_count: int = 0


class UserOut(ORMModel):
    """User representation (never includes the password hash)."""

    id: int
    name: str
    email: str
    phone: str
    role: str
    is_active: bool
    is_approved: bool
    created_at: datetime
    partner_profile: Optional[PartnerProfileOut] = None


class TokenResponse(BaseModel):
    """JWT login response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ApprovalRequest(BaseModel):
    """Optional body for the approval endpoint; defaults to approving."""

    approved: bool = True
